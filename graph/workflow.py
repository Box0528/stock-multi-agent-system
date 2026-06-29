import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import re
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import TypedDict, Annotated, List
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage

def _keep_last(old: str, new: str) -> str:
    return new

class ResearchState(TypedDict):
    messages:          Annotated[List[BaseMessage], add_messages]
    stock_name:        str
    industry:          str
    real_industry:     str
    stock_code:        str   # 精确股票代码，如 600226
    task_plan:         str
    technical_report:  str
    news_report:       str
    sector_report:     str
    risk_report:       str
    final_report:      str
    current_step:      Annotated[str, _keep_last]
    memory_context:    str
    has_history:       bool
    last_advice:       str


def _lookup_industry(stock_name: str) -> str:
    try:
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        meta_file = os.path.join(base_dir, "meta", "stock_meta.csv")
        meta_df = pd.read_csv(meta_file)
        match = meta_df[meta_df["name"] == stock_name]
        if not match.empty:
            return match.iloc[0]["industry_name"]
    except Exception as e:
        print(f"[Workflow] 行业查询失败：{e}")
    return ""


# ── 节点0：Memory 加载 ────────────────────────────────────────
def memory_load_node(state: ResearchState) -> dict:
    print(f"\n[Memory] 加载历史记忆：{state['stock_name']}")
    try:
        from memory.vector_store import load_all_memory
        real_industry = state.get("real_industry") or state["industry"]
        mem = load_all_memory(state["stock_name"], real_industry)
        if mem["has_history"]:
            print(f"[Memory] 找到 {mem['pred_count']} 条历史记录，上次建议：{mem['last_advice']} ({mem['last_date']})")
            context = "\n\n".join(filter(None, [
                mem["prediction_text"],
                mem["sector_trend_text"],
                mem["risk_history_text"],
            ]))
        else:
            print(f"[Memory] 暂无历史记录，首次分析")
            context = ""
        return {
            "memory_context": context,
            "has_history":    mem["has_history"],
            "last_advice":    mem["last_advice"],
            "current_step":   "memory_loaded",
        }
    except Exception as e:
        print(f"[Memory] 加载失败（不影响分析）：{e}")
        return {"memory_context": "", "has_history": False, "last_advice": "", "current_step": "memory_loaded"}


# ── 节点1：Planner ────────────────────────────────────────────
def planner_node(state: ResearchState) -> dict:
    print(f"\n{'='*50}")
    print(f"[Planner] 开始规划分析任务：{state['stock_name']}")
    from agents.planner import run_planner
    plan = run_planner(state["stock_name"], state["industry"])
    print(f"[Planner] 任务规划完成")
    return {
        "task_plan":    plan,
        "current_step": "planner_done",
        "messages":     [AIMessage(content="任务规划完成")]
    }


# ── 节点2：三个分析师真并行 ───────────────────────────────────
def parallel_analysts_node(state: ResearchState) -> dict:
    stock_name      = state["stock_name"]
    industry        = state["industry"]
    real_industry   = state.get("real_industry") or ""
    task_plan       = state["task_plan"]
    sector_industry = real_industry if real_industry else industry

    def run_technical():
        print(f"\n[Technical Analyst] 开始技术面分析...")
        from agents.technical_analyst import run_technical_analyst
        query = f"请分析股票【{stock_name}】的技术面，结合任务计划：{task_plan[:200]}"
        result = run_technical_analyst(query)
        print(f"[Technical Analyst] 分析完成")
        return "technical", result

    def run_news():
        print(f"\n[News Analyst] 开始新闻舆情分析...")
        from agents.news_analyst import run_news_analyst
        result = run_news_analyst(stock_name, industry)
        print(f"[News Analyst] 分析完成")
        return "news", result

    def run_sector():
        print(f"\n[Sector Analyst] 开始板块分析...")
        from agents.sector_analyst import run_sector_analyst
        result = run_sector_analyst(sector_industry, stock_name)
        print(f"[Sector Analyst] 分析完成")
        return "sector", result

    reports = {"technical": "", "news": "", "sector": ""}
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {
            executor.submit(run_technical): "technical",
            executor.submit(run_news):      "news",
            executor.submit(run_sector):    "sector",
        }
        for future in as_completed(futures):
            try:
                key, result = future.result()
                reports[key] = result
            except Exception as e:
                key = futures[future]
                print(f"[{key}] 分析出错：{e}")
                reports[key] = f"分析出错：{e}"

    return {
        "technical_report": reports["technical"],
        "news_report":      reports["news"],
        "sector_report":    reports["sector"],
        "current_step":     "analysts_done",
        "messages":         [AIMessage(content="三位分析师并行分析完成")]
    }


# ── 节点3：Supervisor ─────────────────────────────────────────
def supervisor_node(state: ResearchState) -> dict:
    print(f"\n[Supervisor] 汇总三位分析师报告...")
    from agents.supervisor import run_supervisor
    summary = run_supervisor(
        stock_name=state["stock_name"],
        technical_report=state["technical_report"],
        news_report=state["news_report"],
        sector_report=state["sector_report"],
        memory_context=state.get("memory_context", ""),
        last_advice=state.get("last_advice", ""),
    )
    print(f"[Supervisor] 汇总完成")
    return {
        "final_report": summary,
        "current_step": "supervisor_done",
        "messages":     [AIMessage(content="综合报告汇总完成")]
    }


# ── 节点4：Risk Manager ───────────────────────────────────────
def risk_node(state: ResearchState) -> dict:
    print(f"\n[Risk Manager] 开始风控评估...")
    from agents.risk_manager import run_risk_manager
    risk_report = run_risk_manager(
        stock_name=state["stock_name"],
        supervisor_summary=state["final_report"],
        technical_report=state["technical_report"],
        risk_history=state.get("memory_context", ""),
    )
    final = f"{state['final_report']}\n\n---\n\n{risk_report}"
    print(f"[Risk Manager] 风控评估完成")
    return {
        "risk_report":  risk_report,
        "final_report": final,
        "current_step": "risk_done",
        "messages":     [AIMessage(content="风控评估完成")]
    }


# ── 节点5：Memory 保存 ────────────────────────────────────────
def memory_save_node(state: ResearchState) -> dict:
    print(f"\n[Memory] 保存本次分析结果...")
    try:
        from memory.vector_store import save_all_memory
        save_all_memory(
            stock_name    = state["stock_name"],
            industry      = state["industry"],
            real_industry = state.get("real_industry", ""),
            final_report  = state["final_report"],
            risk_report   = state["risk_report"],
            sector_report = state["sector_report"],
        )
    except Exception as e:
        print(f"[Memory] 保存失败（不影响报告）：{e}")
    return {"current_step": "memory_saved"}


# ── 节点6：Reflection Engine ──────────────────────────────────
def reflection_node(state: ResearchState) -> dict:
    print(f"\n[Reflection] 启动复盘分析...")

    if not state.get("has_history") or not state.get("last_advice"):
        print(f"[Reflection] 首次分析，跳过复盘")
        print(f"\n{'='*50}")
        print(f"  所有 Agent 执行完毕")
        print(f"{'='*50}")
        return {"current_step": "all_done"}

    try:
        from tools.price_api import get_realtime_price, format_price_info
        from agents.reflection import run_reflection, save_reflection_to_memory
        from memory.vector_store import get_prediction_history

        current_price = get_realtime_price(state["stock_name"])
        history       = get_prediction_history(state["stock_name"], top_k=5)
        last_record   = history[0] if history else {}

        reflection_text = run_reflection(
            stock_name      = state["stock_name"],
            last_advice     = state.get("last_advice", ""),
            last_date       = last_record.get("date", ""),
            last_price_info = last_record.get("price_info", ""),
            current_price   = current_price,
            current_report  = state["final_report"],
            history_records = history,
        )

        # 判断预测是否正确
        was_correct = False
        if current_price["source"] != "unavailable" and last_record.get("price_info"):
            m = re.search(r'([\d.]+)\s*元', last_record.get("price_info", ""))
            if m:
                last_p  = float(m.group(1))
                curr_p  = current_price["price"]
                chg     = (curr_p - last_p) / last_p * 100 if last_p > 0 else 0
                advice  = state.get("last_advice", "")
                was_correct = (
                    (advice == "买入" and chg > 3) or
                    (advice == "回避" and chg < -3) or
                    (advice == "观望" and abs(chg) < 5)
                )

        if reflection_text:
            save_reflection_to_memory(state["stock_name"], reflection_text, was_correct)
            final = state["final_report"] + f"\n\n---\n\n{reflection_text}"
            print(f"[Reflection] 复盘完成，预测{'正确 ✓' if was_correct else '存在偏差 ✗'}")
            print(f"\n{'='*50}")
            print(f"  所有 Agent 执行完毕")
            print(f"{'='*50}")
            return {
                "final_report": final,
                "current_step": "all_done",
            }

    except Exception as e:
        print(f"[Reflection] 复盘出错（不影响报告）：{e}")

    print(f"\n{'='*50}")
    print(f"  所有 Agent 执行完毕")
    print(f"{'='*50}")
    return {"current_step": "all_done"}


# ── 构建 Graph ────────────────────────────────────────────────
def build_workflow():
    g = StateGraph(ResearchState)

    g.add_node("memory_load",  memory_load_node)
    g.add_node("planner",      planner_node)
    g.add_node("analysts",     parallel_analysts_node)
    g.add_node("supervisor",   supervisor_node)
    g.add_node("risk",         risk_node)
    g.add_node("memory_save",  memory_save_node)
    # reflection 已移至 server.py 异步执行

    g.set_entry_point("memory_load")
    g.add_edge("memory_load",  "planner")
    g.add_edge("planner",      "analysts")
    g.add_edge("analysts",     "supervisor")
    g.add_edge("supervisor",   "risk")
    g.add_edge("risk",         "memory_save")
    g.add_edge("memory_save",  END)

    return g.compile()


workflow = build_workflow()