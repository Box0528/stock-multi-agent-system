import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json
import asyncio
import logging
import threading
import re
import pandas as pd
from datetime import datetime

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from core.event_bus import EventBus, AgentEvent
from core.cost_tracker import CostTracker

logger = logging.getLogger(__name__)

app = FastAPI(title="股票研究 Multi-Agent")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

BASE_DIR  = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
META_FILE = os.path.join(BASE_DIR, "meta", "stock_meta.csv")


class ResearchRequest(BaseModel):
    stock_code: str


def lookup_by_code(stock_code: str) -> dict:
    code_6 = stock_code.strip().replace("sh.","").replace("sz.","").replace("sh","").replace("sz","")
    code_6 = code_6.zfill(6)[-6:]
    try:
        meta_df = pd.read_csv(META_FILE)
        meta_df["_code6"] = meta_df["code"].str.replace(r"[a-zA-Z.]", "", regex=True).str.zfill(6).str[-6:]
        match = meta_df[meta_df["_code6"] == code_6]
        if not match.empty:
            row = match.iloc[0]
            return {"found": True, "name": row["name"], "raw_code": row["code"], "industry": row["industry_name"]}
    except Exception as e:
        logger.error("meta 查询失败：%s", e)
    return {"found": False, "name": "", "raw_code": "", "industry": ""}


def make_sse(event_type: str, data: dict) -> str:
    return f"event: {event_type}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _event_to_sse(event: AgentEvent) -> str:
    """将 AgentEvent 转为前端期望的 SSE 格式。"""
    return make_sse(event.event_type, {
        "agent": event.agent,
        "status": event.status,
        "message": event.message,
        **event.metadata,
    })


async def research_stream(stock_code: str, stock_info: dict):
    queue: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_event_loop()

    bus = EventBus(queue, loop)
    tracker = CostTracker()

    def run_sync():
        try:
            from langchain_core.messages import HumanMessage
            from graph.workflow import workflow

            stock_name    = stock_info["name"]
            real_industry = stock_info["industry"]

            initial_state = {
                "messages":         [HumanMessage(content=f"请分析【{stock_name}】({stock_code})")],
                "stock_name":       stock_name,
                "stock_code":       stock_code,
                "industry":         "",
                "real_industry":    real_industry,
                "task_plan":        "",
                "technical_report": "",
                "news_report":      "",
                "sector_report":    "",
                "risk_report":      "",
                "final_report":     "",
                "current_step":     "start",
                "memory_context":   "",
                "has_history":      False,
                "last_advice":      "",
            }

            config = {"configurable": {"event_bus": bus, "cost_tracker": tracker}}
            result = workflow.invoke(initial_state, config=config)

            # 推送报告数据
            loop.call_soon_threadsafe(queue.put_nowait, AgentEvent(
                event_type="report_meta", agent="system", status="done",
                message="", metadata={"stock_name": stock_name, "stock_code": stock_code},
            ))
            for key in ["final_report", "technical_report", "news_report", "sector_report", "risk_report", "task_plan"]:
                loop.call_soon_threadsafe(queue.put_nowait, AgentEvent(
                    event_type=f"report_{key}", agent="system", status="done",
                    message="", metadata={"content": result.get(key, "")},
                ))
            loop.call_soon_threadsafe(queue.put_nowait, AgentEvent(
                event_type="report_done", agent="system", status="done", message="",
            ))

            # 后台异步跑 Reflection
            _run_reflection_async(
                result=result,
                stock_name=stock_name,
                queue=queue,
                loop=loop,
                tracker=tracker,
            )

        except Exception as e:
            import traceback
            traceback.print_exc()
            loop.call_soon_threadsafe(queue.put_nowait, AgentEvent(
                event_type="error", agent="system", status="error", message=str(e),
            ))

    t = threading.Thread(target=run_sync, daemon=True)
    t.start()

    yield make_sse("ping", {"message": "连接成功，开始分析..."})
    yield make_sse("stock_info", {
        "stock_name": stock_info["name"],
        "stock_code": stock_code,
        "industry":   stock_info["industry"],
    })

    while True:
        try:
            event: AgentEvent = await asyncio.wait_for(queue.get(), timeout=300)
        except asyncio.TimeoutError:
            yield make_sse("error", {"message": "分析超时，请重试"})
            break

        yield _event_to_sse(event)

        if event.event_type in ("done", "error"):
            break


def _run_reflection_async(result: dict, stock_name: str,
                           queue: asyncio.Queue, loop: asyncio.AbstractEventLoop,
                           tracker: CostTracker):

    def _push(event: AgentEvent):
        loop.call_soon_threadsafe(queue.put_nowait, event)

    def reflection_thread():
        try:
            _push(AgentEvent(
                event_type="progress", agent="risk", status="running",
                message="🔍 复盘引擎正在后台分析...",
            ))

            has_history = result.get("has_history", False)
            last_advice = result.get("last_advice", "")

            if not has_history or not last_advice:
                _push(AgentEvent(
                    event_type="progress", agent="risk", status="done",
                    message="⏭️ 首次分析，跳过复盘",
                ))
                # 推送成本统计
                _push(AgentEvent(
                    event_type="cost_summary", agent="system", status="done",
                    message="", metadata=tracker.snapshot().to_dict(),
                ))
                _push(AgentEvent(
                    event_type="done", agent="system", status="done", message="",
                ))
                return

            from tools.price_api import get_realtime_price
            from agents.reflection import run_reflection, save_reflection_to_memory
            from memory.vector_store import get_prediction_history

            current_price = get_realtime_price(stock_name)
            history       = get_prediction_history(stock_name, top_k=5)
            last_record   = history[0] if history else {}

            reflection_text = run_reflection(
                stock_name      = stock_name,
                last_advice     = last_advice,
                last_date       = last_record.get("date", ""),
                last_price_info = last_record.get("price_info", ""),
                current_price   = current_price,
                current_report  = result.get("final_report", ""),
                history_records = history,
                tracker         = tracker,
            )

            was_correct = False
            if current_price["source"] != "unavailable" and last_record.get("price_info"):
                m = re.search(r'([\d.]+)\s*元', last_record.get("price_info", ""))
                if m:
                    last_p = float(m.group(1))
                    curr_p = current_price["price"]
                    chg    = (curr_p - last_p) / last_p * 100 if last_p > 0 else 0
                    advice = last_advice
                    was_correct = (
                        (advice == "买入" and chg > 3) or
                        (advice == "回避" and chg < -3) or
                        (advice == "观望" and abs(chg) < 5)
                    )

            if reflection_text:
                save_reflection_to_memory(stock_name, reflection_text, was_correct)
                _push(AgentEvent(
                    event_type="progress", agent="risk", status="done",
                    message=f"✅ 复盘完成 — 预测{'正确 ✓' if was_correct else '存在偏差，已记录'}",
                ))
                _push(AgentEvent(
                    event_type="reflection", agent="system", status="done",
                    message="", metadata={"content": reflection_text, "was_correct": was_correct},
                ))

        except Exception as e:
            logger.error("复盘出错：%s", e)
        finally:
            _push(AgentEvent(
                event_type="cost_summary", agent="system", status="done",
                message="", metadata=tracker.snapshot().to_dict(),
            ))
            _push(AgentEvent(
                event_type="done", agent="system", status="done", message="",
            ))

    t = threading.Thread(target=reflection_thread, daemon=True)
    t.start()


@app.post("/api/research")
async def research(req: ResearchRequest):
    stock_info = lookup_by_code(req.stock_code)
    if not stock_info["found"]:
        raise HTTPException(status_code=404, detail=f"未找到股票代码 {req.stock_code}")
    return StreamingResponse(
        research_stream(req.stock_code, stock_info),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/lookup/{stock_code}")
async def lookup(stock_code: str):
    return lookup_by_code(stock_code)


@app.get("/api/health")
async def health():
    return {"status": "ok", "time": datetime.now().isoformat()}


frontend_dir = os.path.join(BASE_DIR, "frontend")
if os.path.exists(frontend_dir):
    app.mount("/static", StaticFiles(directory=frontend_dir), name="static")

@app.get("/")
async def index():
    return FileResponse(os.path.join(frontend_dir, "index.html"))

if __name__ == "__main__":
    import uvicorn
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
    print("\n🚀 股票研究 Multi-Agent 服务启动")
    print("📡 访问地址：http://localhost:8000\n")
    uvicorn.run("api.server:app", host="0.0.0.0", port=8000, reload=False)
