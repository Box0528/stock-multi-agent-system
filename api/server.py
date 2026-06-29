import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json
import asyncio
import threading
import builtins
import pandas as pd
from datetime import datetime

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

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
        print(f"[Server] meta 查询失败：{e}")
    return {"found": False, "name": "", "raw_code": "", "industry": ""}


def make_sse(event_type: str, data: dict) -> str:
    return f"event: {event_type}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def parse_print_msg(msg: str, queue: asyncio.Queue, loop: asyncio.AbstractEventLoop):
    def put(evt, data):
        loop.call_soon_threadsafe(queue.put_nowait, (evt, data))

    if "[Memory]" in msg:
        if "加载" in msg:
            put("progress", {"agent": "planner", "status": "running", "message": "🧠 加载历史记忆..."})
        elif "找到" in msg:
            put("progress", {"agent": "planner", "status": "running", "message": f"🧠 {msg.strip()}"})
        elif "首次" in msg:
            put("progress", {"agent": "planner", "status": "running", "message": "🧠 首次分析，无历史记忆"})
    elif "[Planner]" in msg:
        if "开始" in msg:
            put("progress", {"agent": "planner", "status": "running", "message": "📋 Planner 正在规划分析任务..."})
        elif "完成" in msg:
            put("progress", {"agent": "planner", "status": "done", "message": "✅ 任务规划完成"})
    elif "[Technical Analyst]" in msg:
        if "开始" in msg:
            put("progress", {"agent": "technical", "status": "running", "message": "📊 技术分析师正在分析..."})
        elif "调用工具" in msg or "调用（" in msg:
            put("tool_call", {"agent": "technical", "message": f"🔧 {msg.strip()}"})
        elif "分析完成" in msg:
            put("progress", {"agent": "technical", "status": "done", "message": "✅ 技术分析完成"})
    elif "[News Analyst]" in msg:
        if "开始" in msg:
            put("progress", {"agent": "news", "status": "running", "message": "📰 新闻分析师正在搜索舆情..."})
        elif "搜索" in msg:
            put("tool_call", {"agent": "news", "message": f"🔍 {msg.strip()}"})
        elif "分析完成" in msg:
            put("progress", {"agent": "news", "status": "done", "message": "✅ 新闻分析完成"})
    elif "[Sector Analyst]" in msg:
        if "开始" in msg:
            put("progress", {"agent": "sector", "status": "running", "message": "🏭 板块分析师正在分析..."})
        elif "调用" in msg:
            put("tool_call", {"agent": "sector", "message": f"🔧 {msg.strip()}"})
        elif "分析完成" in msg:
            put("progress", {"agent": "sector", "status": "done", "message": "✅ 板块分析完成"})
    elif "[Supervisor]" in msg:
        if "汇总三位" in msg:
            put("progress", {"agent": "supervisor", "status": "running", "message": "🎯 基金经理正在汇总三份报告..."})
        elif "汇总完成" in msg:
            put("progress", {"agent": "supervisor", "status": "done", "message": "✅ 综合报告汇总完成"})
    elif "[Risk Manager]" in msg:
        if "开始" in msg:
            put("progress", {"agent": "risk", "status": "running", "message": "🛡️ 风控经理正在进行风险评估..."})
        elif "风控评估完成" in msg:
            put("progress", {"agent": "risk", "status": "done", "message": "✅ 风控评估完成"})
    elif "[Reflection]" in msg:
        if "启动" in msg:
            put("progress", {"agent": "risk", "status": "running", "message": "🔍 复盘引擎正在后台分析..."})
        elif "跳过" in msg:
            put("progress", {"agent": "risk", "status": "done", "message": "⏭️ 首次分析，跳过复盘"})
        elif "复盘完成" in msg:
            correct = "✓" in msg
            put("progress", {"agent": "risk", "status": "done",
                "message": "✅ 复盘完成 — 预测" + ("正确 ✓" if correct else "存在偏差，已记录")})
    elif "所有 Agent 执行完毕" in msg:
        put("progress", {"agent": "system", "status": "done", "message": "🎉 所有 Agent 执行完毕"})


async def research_stream(stock_code: str, stock_info: dict):
    queue: asyncio.Queue = asyncio.Queue()
    loop  = asyncio.get_event_loop()
    original_print = builtins.print

    def patched_print(*args, **kwargs):
        msg = " ".join(str(a) for a in args)
        original_print(*args, **kwargs)
        parse_print_msg(msg, queue, loop)

    def run_sync():
        builtins.print = patched_print
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
            result = workflow.invoke(initial_state)

            # ── 第一步：先把主报告推给前端，让用户立即看到 ──────
            loop.call_soon_threadsafe(queue.put_nowait, ("report_meta", {
                "stock_name": stock_name, "stock_code": stock_code,
            }))
            for key in ["final_report","technical_report","news_report","sector_report","risk_report","task_plan"]:
                loop.call_soon_threadsafe(queue.put_nowait, (f"report_{key}", {
                    "content": result.get(key, "")
                }))
            loop.call_soon_threadsafe(queue.put_nowait, ("report_done", {}))

            # ── 第二步：后台异步跑 Reflection，跑完追加 ────────
            _run_reflection_async(
                result=result,
                stock_name=stock_name,
                queue=queue,
                loop=loop,
            )

        except Exception as e:
            import traceback
            traceback.print_exc()
            loop.call_soon_threadsafe(queue.put_nowait, ("error", {"message": str(e)}))
        finally:
            builtins.print = original_print

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
            event_type, data = await asyncio.wait_for(queue.get(), timeout=300)
        except asyncio.TimeoutError:
            yield make_sse("error", {"message": "分析超时，请重试"})
            break
        yield make_sse(event_type, data)
        if event_type in ("done", "error"):
            break


def _run_reflection_async(result: dict, stock_name: str,
                           queue: asyncio.Queue, loop: asyncio.AbstractEventLoop):
    """在独立线程里跑 Reflection，跑完把复盘报告推给前端"""

    def reflection_thread():
        try:
            print(f"\n[Reflection] 启动复盘分析...")
            has_history = result.get("has_history", False)
            last_advice = result.get("last_advice", "")

            if not has_history or not last_advice:
                print(f"[Reflection] 首次分析，跳过复盘")
                loop.call_soon_threadsafe(queue.put_nowait, ("done", {}))
                return

            import re
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
            )

            # 判断预测准确性
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
                print(f"[Reflection] 复盘完成，预测{'正确 ✓' if was_correct else '存在偏差 ✗'}")

                # 把复盘报告作为独立事件推给前端，追加到综合报告
                loop.call_soon_threadsafe(queue.put_nowait, ("reflection", {
                    "content":     reflection_text,
                    "was_correct": was_correct,
                }))

        except Exception as e:
            print(f"[Reflection] 复盘出错（不影响主报告）：{e}")
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, ("done", {}))

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
    print("\n🚀 股票研究 Multi-Agent 服务启动")
    print("📡 访问地址：http://localhost:8000\n")
    uvicorn.run("api.server:app", host="0.0.0.0", port=8000, reload=False)