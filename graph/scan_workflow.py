"""
模式一：主动扫描 workflow

全市场扫描 → 量化选股 → LLM 精选 Top N → 对每只跑完整多智能体分析 → 综合排名

流程：
  data_refresh_all → screener → planner_select → deep_analysis(复用模式二) → final_ranking
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json
import logging
from typing import TypedDict, Annotated, List
from langgraph.graph import StateGraph, END
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph.message import add_messages

from core.event_bus import get_event_bus
from core.cost_tracker import get_cost_tracker

logger = logging.getLogger(__name__)


def _keep_last(old: str, new: str) -> str:
    return new


class ScanState(TypedDict):
    messages:          Annotated[List[BaseMessage], add_messages]
    screener_results:  str
    selected_stocks:   str   # JSON list of {code, name, industry, reason}
    analysis_reports:  str   # JSON list of per-stock reports
    market_overview:   str
    current_step:      Annotated[str, _keep_last]


# ── 节点1：全量数据刷新 ──────────────────────────────────────
def scan_data_refresh_node(state: ScanState, config: RunnableConfig) -> dict:
    bus = get_event_bus(config)
    bus.emit_progress("system", "running", "📡 正在更新全市场行情数据...")

    try:
        from tools.data_pipeline import refresh_all_stocks
        result = refresh_all_stocks(bus=bus)
        if result["ok"]:
            bus.emit_progress("system", "done",
                f"📡 数据更新完成：更新{result['updated']} 跳过{result['skipped']} 失败{result['failed']}")
        else:
            bus.emit_progress("system", "running", f"📡 数据更新部分失败，继续扫描：{result['message']}")
    except Exception as e:
        logger.warning("全量数据刷新失败：%s", e)
        bus.emit_progress("system", "running", "📡 数据更新失败，使用本地缓存继续扫描")

    return {"current_step": "data_refreshed"}


# ── 节点2：量化选股（纯本地，零成本）─────────────────────────
def screener_node(state: ScanState, config: RunnableConfig) -> dict:
    bus = get_event_bus(config)
    tracker = get_cost_tracker(config)

    bus.emit_progress("planner", "running", "🔍 正在运行量化选股模型...")

    from tools.stock_data import run_stock_screener
    result = run_stock_screener.invoke({"top_n_industries": 10})
    tracker.record_tool_call()

    stock_count = result.count("(") if result else 0
    bus.emit_progress("planner", "done", f"🔍 选股完成，筛出约 {stock_count} 只候选股")

    return {
        "screener_results": result,
        "current_step": "screened",
        "messages": [AIMessage(content="量化选股完成")],
    }


# ── 节点3：LLM 精选 Top N（1次LLM调用）─────────────────────
def planner_select_node(state: ScanState, config: RunnableConfig) -> dict:
    bus = get_event_bus(config)
    tracker = get_cost_tracker(config)

    bus.emit_progress("planner", "running", "🎯 正在从候选池精选重点标的...")

    from config import get_llm
    from langchain_core.messages import SystemMessage

    llm = get_llm(temperature=0.1)

    prompt = f"""你是一位资深投研总监。以下是今日量化选股模型筛出的候选股票池：

{state['screener_results'][:3000]}

请从中精选出**最值得深入研究的 3-5 只**股票，标准：
1. 技术信号最强（均线多头 + 换手率适中 + 放量）
2. 所在行业有资金共振（同行业多只入选）
3. 成交额充足（流动性好）

输出严格 JSON 格式（不要其他文字）：
[
  {{"code": "sh.600xxx", "name": "xxx", "industry": "xxx", "reason": "一句话理由"}},
  ...
]
"""
    response = llm.invoke([
        SystemMessage(content="你是投研总监，严格输出 JSON，不要多余文字。"),
        HumanMessage(content=prompt),
    ])

    usage = getattr(response, "usage_metadata", None) or {}
    tracker.record_llm_call(usage.get("input_tokens", 0), usage.get("output_tokens", 0))

    # 解析 JSON
    raw = response.content.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    try:
        selected = json.loads(raw)
        bus.emit_progress("planner", "done", f"🎯 精选出 {len(selected)} 只重点标的")
    except json.JSONDecodeError:
        logger.error("精选结果 JSON 解析失败：%s", raw[:200])
        bus.emit_progress("planner", "done", "🎯 精选完成（JSON解析异常，使用原始结果）")
        selected = []

    return {
        "selected_stocks": json.dumps(selected, ensure_ascii=False),
        "current_step": "selected",
        "messages": [AIMessage(content=f"精选出 {len(selected)} 只标的")],
    }


# ── 节点4：对每只精选股跑完整多智能体分析 ────────────────────
def deep_analysis_node(state: ScanState, config: RunnableConfig) -> dict:
    bus = get_event_bus(config)
    tracker = get_cost_tracker(config)

    try:
        selected = json.loads(state["selected_stocks"])
    except Exception:
        selected = []

    if not selected:
        bus.emit_progress("supervisor", "done", "⚠️ 无候选股票，跳过深度分析")
        return {"analysis_reports": "[]", "current_step": "analyzed"}

    bus.emit_progress("supervisor", "running",
        f"📊 开始对 {len(selected)} 只精选股进行多智能体深度分析...")

    from graph.workflow import workflow
    from core.event_bus import EventBus, ConsoleEventBus
    import asyncio

    reports = []
    for i, stock in enumerate(selected):
        code = stock.get("code", "")
        name = stock.get("name", "")
        industry = stock.get("industry", "")

        bus.emit_progress("supervisor", "running",
            f"📊 [{i+1}/{len(selected)}] 正在分析 {name}({code})...")

        try:
            initial_state = {
                "messages":         [HumanMessage(content=f"请分析【{name}】({code})")],
                "stock_name":       name,
                "stock_code":       code,
                "industry":         "",
                "real_industry":    industry,
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
                "agent_lessons":    "",
                "technical_confidence": 0.7,
                "news_confidence":      0.7,
                "sector_confidence":    0.7,
                "reasoning_traces":     "",
            }

            # 复用模式二 workflow，但用同一个 tracker 累计成本
            sub_bus = ConsoleEventBus()
            sub_config = {"configurable": {"event_bus": sub_bus, "cost_tracker": tracker}}
            result = workflow.invoke(initial_state, config=sub_config)

            reports.append({
                "code": code,
                "name": name,
                "industry": industry,
                "reason": stock.get("reason", ""),
                "final_report": result.get("final_report", ""),
                "technical_report": result.get("technical_report", ""),
                "news_report": result.get("news_report", ""),
                "sector_report": result.get("sector_report", ""),
                "risk_report": result.get("risk_report", ""),
            })

            bus.emit_progress("supervisor", "running",
                f"📊 [{i+1}/{len(selected)}] {name} 分析完成 ✓")

        except Exception as e:
            logger.error("深度分析失败 %s：%s", name, e)
            reports.append({
                "code": code, "name": name, "industry": industry,
                "reason": stock.get("reason", ""),
                "final_report": f"分析失败：{e}",
                "risk_report": "",
            })

    bus.emit_progress("supervisor", "done", f"📊 {len(selected)} 只股票深度分析全部完成")

    return {
        "analysis_reports": json.dumps(reports, ensure_ascii=False),
        "current_step": "analyzed",
    }


# ── 节点5：综合排名输出 ──────────────────────────────────────
def final_ranking_node(state: ScanState, config: RunnableConfig) -> dict:
    bus = get_event_bus(config)
    tracker = get_cost_tracker(config)

    try:
        reports = json.loads(state["analysis_reports"])
    except Exception:
        reports = []

    if not reports:
        return {"market_overview": "今日无推荐标的", "current_step": "done"}

    bus.emit_progress("risk", "running", "🏆 正在生成今日投研排名...")

    from config import get_llm
    from langchain_core.messages import SystemMessage

    llm = get_llm(temperature=0.2)

    reports_text = ""
    for r in reports:
        reports_text += f"\n### {r['name']}({r['code']}) — {r['industry']}\n"
        reports_text += f"精选理由：{r['reason']}\n"
        reports_text += f"{r['final_report'][:800]}\n---\n"

    prompt = f"""你是投研总监，请根据以下多只股票的完整分析报告，输出今日投研总结。

{reports_text}

输出格式：

## 📊 今日主动扫描报告

### 市场概览
（一段话总结今日市场整体特征）

### 今日推荐排名
| 排名 | 股票 | 行业 | 操作建议 | 核心理由 |
|------|------|------|---------|---------|
（按推荐程度排序，每只一行）

### 重点关注
（最值得关注的1-2只，详细说明理由）

### 风险提示
（整体市场风险和个股风险提醒）
"""

    response = llm.invoke([
        SystemMessage(content="你是资深投研总监，输出今日投研排名报告。"),
        HumanMessage(content=prompt),
    ])

    usage = getattr(response, "usage_metadata", None) or {}
    tracker.record_llm_call(usage.get("input_tokens", 0), usage.get("output_tokens", 0))

    bus.emit_progress("risk", "done", "🏆 今日投研排名生成完成")

    return {
        "market_overview": response.content,
        "current_step": "done",
    }


# ── 构建 Graph ────────────────────────────────────────────────
def build_scan_workflow():
    g = StateGraph(ScanState)

    g.add_node("data_refresh",    scan_data_refresh_node)
    g.add_node("screener",        screener_node)
    g.add_node("planner_select",  planner_select_node)
    g.add_node("deep_analysis",   deep_analysis_node)
    g.add_node("final_ranking",   final_ranking_node)

    g.set_entry_point("data_refresh")
    g.add_edge("data_refresh",   "screener")
    g.add_edge("screener",       "planner_select")
    g.add_edge("planner_select", "deep_analysis")
    g.add_edge("deep_analysis",  "final_ranking")
    g.add_edge("final_ranking",  END)

    return g.compile()


scan_workflow = build_scan_workflow()
