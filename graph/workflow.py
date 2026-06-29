import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import re
import logging
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import TypedDict, Annotated, List
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage
from langchain_core.runnables import RunnableConfig

from core.event_bus import get_event_bus
from core.cost_tracker import get_cost_tracker

logger = logging.getLogger(__name__)

def _keep_last(old: str, new: str) -> str:
    return new

class ResearchState(TypedDict):
    messages:          Annotated[List[BaseMessage], add_messages]
    stock_name:        str
    industry:          str
    real_industry:     str
    stock_code:        str
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
        logger.warning("行业查询失败：%s", e)
    return ""


# ── 节点0：Memory 加载 ────────────────────────────────────────
def memory_load_node(state: ResearchState, config: RunnableConfig) -> dict:
    bus = get_event_bus(config)
    stock_name = state["stock_name"]
    bus.emit_progress("planner", "running", f"🧠 加载历史记忆：{stock_name}")

    try:
        from memory.vector_store import load_all_memory
        real_industry = state.get("real_industry") or state["industry"]
        mem = load_all_memory(stock_name, real_industry)
        if mem["has_history"]:
            bus.emit_progress("planner", "running",
                f"🧠 找到 {mem['pred_count']} 条历史记录，上次建议：{mem['last_advice']} ({mem['last_date']})")
            context = "\n\n".join(filter(None, [
                mem["prediction_text"],
                mem["sector_trend_text"],
                mem["risk_history_text"],
            ]))
        else:
            bus.emit_progress("planner", "running", "🧠 首次分析，无历史记忆")
            context = ""
        return {
            "memory_context": context,
            "has_history":    mem["has_history"],
            "last_advice":    mem["last_advice"],
            "current_step":   "memory_loaded",
        }
    except Exception as e:
        logger.error("Memory 加载失败：%s", e)
        bus.emit_progress("planner", "running", "🧠 记忆加载失败，继续分析")
        return {"memory_context": "", "has_history": False, "last_advice": "", "current_step": "memory_loaded"}


# ── 节点1：Planner ────────────────────────────────────────────
def planner_node(state: ResearchState, config: RunnableConfig) -> dict:
    bus = get_event_bus(config)
    tracker = get_cost_tracker(config)
    stock_name = state["stock_name"]

    bus.emit_progress("planner", "running", "📋 Planner 正在规划分析任务...")

    from agents.planner import run_planner
    plan = run_planner(stock_name, state["industry"], tracker=tracker)

    bus.emit_progress("planner", "done", "✅ 任务规划完成")
    return {
        "task_plan":    plan,
        "current_step": "planner_done",
        "messages":     [AIMessage(content="任务规划完成")]
    }


# ── 节点2：三个分析师真并行 ───────────────────────────────────
def parallel_analysts_node(state: ResearchState, config: RunnableConfig) -> dict:
    bus = get_event_bus(config)
    tracker = get_cost_tracker(config)

    stock_name      = state["stock_name"]
    industry        = state["industry"]
    real_industry   = state.get("real_industry") or ""
    task_plan       = state["task_plan"]
    sector_industry = real_industry if real_industry else industry

    def run_technical():
        bus.emit_progress("technical", "running", "📊 技术分析师正在分析...")
        from agents.technical_analyst import run_technical_analyst
        query = f"请分析股票【{stock_name}】的技术面，结合任务计划：{task_plan[:200]}"
        result = run_technical_analyst(query, bus=bus, tracker=tracker)
        bus.emit_progress("technical", "done", "✅ 技术分析完成")
        return "technical", result

    def run_news():
        bus.emit_progress("news", "running", "📰 新闻分析师正在搜索舆情...")
        from agents.news_analyst import run_news_analyst
        result = run_news_analyst(stock_name, industry, bus=bus, tracker=tracker)
        bus.emit_progress("news", "done", "✅ 新闻分析完成")
        return "news", result

    def run_sector():
        bus.emit_progress("sector", "running", "🏭 板块分析师正在分析...")
        from agents.sector_analyst import run_sector_analyst
        result = run_sector_analyst(sector_industry, stock_name, bus=bus, tracker=tracker)
        bus.emit_progress("sector", "done", "✅ 板块分析完成")
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
                logger.error("[%s] 分析出错：%s", key, e)
                bus.emit_progress(key, "done", f"⚠️ {key} 分析出错：{e}")
                reports[key] = f"分析出错：{e}"

    return {
        "technical_report": reports["technical"],
        "news_report":      reports["news"],
        "sector_report":    reports["sector"],
        "current_step":     "analysts_done",
        "messages":         [AIMessage(content="三位分析师并行分析完成")]
    }


# ── 节点3：Supervisor ─────────────────────────────────────────
def supervisor_node(state: ResearchState, config: RunnableConfig) -> dict:
    bus = get_event_bus(config)
    tracker = get_cost_tracker(config)

    bus.emit_progress("supervisor", "running", "🎯 基金经理正在汇总三份报告...")

    from agents.supervisor import run_supervisor
    summary = run_supervisor(
        stock_name=state["stock_name"],
        technical_report=state["technical_report"],
        news_report=state["news_report"],
        sector_report=state["sector_report"],
        memory_context=state.get("memory_context", ""),
        last_advice=state.get("last_advice", ""),
        tracker=tracker,
    )

    bus.emit_progress("supervisor", "done", "✅ 综合报告汇总完成")
    return {
        "final_report": summary,
        "current_step": "supervisor_done",
        "messages":     [AIMessage(content="综合报告汇总完成")]
    }


# ── 节点4：Risk Manager ───────────────────────────────────────
def risk_node(state: ResearchState, config: RunnableConfig) -> dict:
    bus = get_event_bus(config)
    tracker = get_cost_tracker(config)

    bus.emit_progress("risk", "running", "🛡️ 风控经理正在进行风险评估...")

    from agents.risk_manager import run_risk_manager
    risk_report = run_risk_manager(
        stock_name=state["stock_name"],
        supervisor_summary=state["final_report"],
        technical_report=state["technical_report"],
        risk_history=state.get("memory_context", ""),
        tracker=tracker,
    )
    final = f"{state['final_report']}\n\n---\n\n{risk_report}"

    bus.emit_progress("risk", "done", "✅ 风控评估完成")
    return {
        "risk_report":  risk_report,
        "final_report": final,
        "current_step": "risk_done",
        "messages":     [AIMessage(content="风控评估完成")]
    }


# ── 节点5：Memory 保存 ────────────────────────────────────────
def memory_save_node(state: ResearchState, config: RunnableConfig) -> dict:
    bus = get_event_bus(config)
    bus.emit_progress("system", "running", "💾 保存本次分析结果...")

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
        logger.error("Memory 保存失败：%s", e)

    bus.emit_progress("system", "done", "🎉 所有 Agent 执行完毕")
    return {"current_step": "memory_saved"}


# ── 构建 Graph ────────────────────────────────────────────────
def build_workflow():
    g = StateGraph(ResearchState)

    g.add_node("memory_load",  memory_load_node)
    g.add_node("planner",      planner_node)
    g.add_node("analysts",     parallel_analysts_node)
    g.add_node("supervisor",   supervisor_node)
    g.add_node("risk",         risk_node)
    g.add_node("memory_save",  memory_save_node)

    g.set_entry_point("memory_load")
    g.add_edge("memory_load",  "planner")
    g.add_edge("planner",      "analysts")
    g.add_edge("analysts",     "supervisor")
    g.add_edge("supervisor",   "risk")
    g.add_edge("risk",         "memory_save")
    g.add_edge("memory_save",  END)

    return g.compile()


workflow = build_workflow()
