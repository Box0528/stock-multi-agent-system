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

def _keep_last_float(old: float, new: float) -> float:
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
    # 认知内核新增字段
    agent_lessons:     str                                    # JSON 或纯文本，各agent教训
    technical_confidence: Annotated[float, _keep_last_float]
    news_confidence:      Annotated[float, _keep_last_float]
    sector_confidence:    Annotated[float, _keep_last_float]
    reasoning_traces:     str                                 # 所有推理链拼接
    search_keywords:      str                                 # Planner 生成的搜索关键词 JSON


# ── 节点-1：数据刷新（分析前自动更新行情）──────────────────────
def data_refresh_node(state: ResearchState, config: RunnableConfig) -> dict:
    bus = get_event_bus(config)
    stock_code = state.get("stock_code") or ""
    stock_name = state["stock_name"]

    if not stock_code:
        # CLI 模式可能没有 stock_code，尝试从 meta 查
        try:
            meta_df = pd.read_csv(os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "meta", "stock_meta.csv"))
            match = meta_df[meta_df["name"] == stock_name]
            if not match.empty:
                stock_code = match.iloc[0]["code"]
        except Exception:
            pass

    if not stock_code:
        bus.emit_progress("system", "running", "📡 未找到股票代码，跳过数据更新")
        return {"current_step": "data_refreshed"}

    try:
        from tools.data_pipeline import refresh_single_stock, refresh_industry_stocks
        # 1. 更新目标股票
        result = refresh_single_stock(stock_code, bus=bus)
        if not result["ok"]:
            bus.emit_progress("system", "running", f"📡 目标股票更新失败：{result['message']}，使用本地缓存")

        # 2. 更新目标行业所有股票（板块分析需要）
        real_industry = state.get("real_industry") or state.get("industry") or ""
        if real_industry:
            refresh_industry_stocks(real_industry, bus=bus)

    except Exception as e:
        logger.warning("数据刷新异常（不影响分析）：%s", e)
        bus.emit_progress("system", "running", "📡 数据更新异常，使用本地缓存继续")

    return {"current_step": "data_refreshed"}


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

        import json
        lessons_dict = mem.get("agent_lessons", {})
        lessons_str = json.dumps(lessons_dict, ensure_ascii=False) if lessons_dict else ""

        return {
            "memory_context": context,
            "has_history":    mem["has_history"],
            "last_advice":    mem["last_advice"],
            "agent_lessons":  lessons_str,
            "current_step":   "memory_loaded",
        }
    except Exception as e:
        logger.error("Memory 加载失败：%s", e)
        bus.emit_progress("planner", "running", "🧠 记忆加载失败，继续分析")
        return {"memory_context": "", "has_history": False, "last_advice": "",
                "agent_lessons": "", "current_step": "memory_loaded"}


# ── 节点1：Planner ────────────────────────────────────────────
def planner_node(state: ResearchState, config: RunnableConfig) -> dict:
    bus = get_event_bus(config)
    tracker = get_cost_tracker(config)
    stock_name = state["stock_name"]

    bus.emit_progress("planner", "running", "📋 Planner 正在规划分析任务...")

    # 注入真实行业和概念信息
    real_industry = state.get("real_industry") or state.get("industry") or ""
    from tools.stock_data import lookup_stock_concepts
    concepts = lookup_stock_concepts(stock_name)
    concept_hint = f"，所属概念板块：{', '.join(concepts[:10])}" if concepts else ""

    from agents.planner import run_planner
    plan = run_planner(
        stock_name,
        real_industry,
        tracker=tracker,
        concept_info=concept_hint,
    )

    # 从 plan 中提取搜索关键词（Planner 输出中的 JSON 数组）
    import json as _json
    keywords_str = ""
    try:
        import re
        m = re.search(r'必搜关键词[：:]\s*(\[.+?\])', plan, re.DOTALL)
        if m:
            keywords_str = m.group(1)
            _json.loads(keywords_str)  # 验证是合法 JSON
    except Exception:
        keywords_str = ""

    bus.emit_progress("planner", "done", "✅ 任务规划完成")
    return {
        "task_plan":       plan,
        "search_keywords": keywords_str,
        "current_step":    "planner_done",
        "messages":        [AIMessage(content="任务规划完成")]
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

    # 解析 agent lessons
    import json
    try:
        lessons_dict = json.loads(state.get("agent_lessons", "{}")) if state.get("agent_lessons") else {}
    except Exception:
        lessons_dict = {}

    stock_code = state.get("stock_code") or ""

    # 获取概念信息
    from tools.stock_data import lookup_stock_concepts
    concepts = lookup_stock_concepts(stock_name)
    concept_context = f"\n📌 所属概念板块：{', '.join(concepts[:10])}\n" if concepts else ""

    # 获取最新价格作为公共上下文（三个分析师共享）
    price_context = ""
    try:
        from tools.stock_data import get_stock_detail
        if stock_code:
            price_data = get_stock_detail.invoke({"stock_code": stock_code})
            price_context = f"\n## 最新行情数据（公共上下文）\n{price_data}\n"
            if tracker:
                tracker.record_tool_call()
    except Exception as e:
        logger.warning("获取公共价格上下文失败：%s", e)

    def run_technical():
        bus.emit_progress("technical", "running", "📊 技术分析师正在分析...")
        from agents.technical_analyst import run_technical_analyst
        code_hint = f"（代码：{stock_code}）" if stock_code else ""
        query = (
            f"请分析股票【{stock_name}】{code_hint}的技术面。"
            f"必须使用代码 {stock_code} 调用工具，不要猜测其他代码。\n"
            f"任务计划：{task_plan[:200]}"
        )
        output = run_technical_analyst(
            query, bus=bus, tracker=tracker,
            lessons=lessons_dict.get("technical", ""),
            stock_name=stock_name,
        )
        bus.emit_progress("technical", "done", f"✅ 技术分析完成（置信度 {output.confidence:.0%}）")
        return "technical", output

    # 解析搜索关键词
    try:
        search_kws = json.loads(state.get("search_keywords", "[]")) if state.get("search_keywords") else []
    except Exception:
        search_kws = []

    def run_news():
        bus.emit_progress("news", "running", "📰 新闻分析师正在搜索舆情...")
        from agents.news_analyst import run_news_analyst
        output = run_news_analyst(
            stock_name, industry, bus=bus, tracker=tracker,
            lessons=lessons_dict.get("news", ""),
            search_keywords=search_kws if search_kws else None,
            price_context=price_context + concept_context,
        )
        bus.emit_progress("news", "done", f"✅ 新闻分析完成（置信度 {output.confidence:.0%}）")
        return "news", output

    def run_sector():
        bus.emit_progress("sector", "running", "🏭 板块分析师正在分析...")
        from agents.sector_analyst import run_sector_analyst
        output = run_sector_analyst(
            sector_industry, stock_name, bus=bus, tracker=tracker,
            lessons=lessons_dict.get("sector", ""),
        )
        bus.emit_progress("sector", "done", f"✅ 板块分析完成（置信度 {output.confidence:.0%}）")
        return "sector", output

    from core.cognitive import AgentOutput
    reports: dict[str, AgentOutput] = {}
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {
            executor.submit(run_technical): "technical",
            executor.submit(run_news):      "news",
            executor.submit(run_sector):    "sector",
        }
        for future in as_completed(futures):
            try:
                key, output = future.result()
                reports[key] = output
            except Exception as e:
                key = futures[future]
                logger.error("[%s] 分析出错：%s", key, e)
                bus.emit_progress(key, "done", f"⚠️ {key} 分析出错：{e}")
                reports[key] = AgentOutput(report=f"分析出错：{e}", confidence=0.1)

    # 收集推理链
    traces = []
    for name in ["technical", "news", "sector"]:
        if reports[name].reasoning_trace:
            traces.append(f"## {name} 推理\n{reports[name].reasoning_trace}")

    return {
        "technical_report":     reports["technical"].report,
        "news_report":          reports["news"].report,
        "sector_report":        reports["sector"].report,
        "technical_confidence": reports["technical"].confidence,
        "news_confidence":      reports["news"].confidence,
        "sector_confidence":    reports["sector"].confidence,
        "reasoning_traces":     "\n\n".join(traces),
        "current_step":         "analysts_done",
        "messages":             [AIMessage(content="三位分析师并行分析完成")]
    }


# ── 节点3：Supervisor ─────────────────────────────────────────
def supervisor_node(state: ResearchState, config: RunnableConfig) -> dict:
    bus = get_event_bus(config)
    tracker = get_cost_tracker(config)

    import json
    try:
        lessons_dict = json.loads(state.get("agent_lessons", "{}")) if state.get("agent_lessons") else {}
    except Exception:
        lessons_dict = {}

    bus.emit_progress("supervisor", "running", "🎯 基金经理正在汇总三份报告...")

    from agents.supervisor import run_supervisor
    output = run_supervisor(
        stock_name=state["stock_name"],
        technical_report=state["technical_report"],
        news_report=state["news_report"],
        sector_report=state["sector_report"],
        memory_context=state.get("memory_context", ""),
        last_advice=state.get("last_advice", ""),
        tracker=tracker,
        technical_confidence=state.get("technical_confidence", 0.7),
        news_confidence=state.get("news_confidence", 0.7),
        sector_confidence=state.get("sector_confidence", 0.7),
        lessons=lessons_dict.get("supervisor", ""),
        bus=bus,
    )

    bus.emit_progress("supervisor", "done", f"✅ 综合报告汇总完成（置信度 {output.confidence:.0%}）")
    return {
        "final_report": output.report,
        "current_step": "supervisor_done",
        "messages":     [AIMessage(content="综合报告汇总完成")]
    }


# ── 节点4：Risk Manager ───────────────────────────────────────
def risk_node(state: ResearchState, config: RunnableConfig) -> dict:
    bus = get_event_bus(config)
    tracker = get_cost_tracker(config)

    import json
    try:
        lessons_dict = json.loads(state.get("agent_lessons", "{}")) if state.get("agent_lessons") else {}
    except Exception:
        lessons_dict = {}

    bus.emit_progress("risk", "running", "🛡️ 风控经理正在进行风险评估...")

    from agents.risk_manager import run_risk_manager
    output = run_risk_manager(
        stock_name=state["stock_name"],
        supervisor_summary=state["final_report"],
        technical_report=state["technical_report"],
        risk_history=state.get("memory_context", ""),
        tracker=tracker,
        lessons=lessons_dict.get("risk", ""),
        bus=bus,
    )
    final = f"{state['final_report']}\n\n---\n\n{output.report}"

    bus.emit_progress("risk", "done", f"✅ 风控评估完成（置信度 {output.confidence:.0%}）")
    return {
        "risk_report":  output.report,
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

    g.add_node("data_refresh", data_refresh_node)
    g.add_node("memory_load",  memory_load_node)
    g.add_node("planner",      planner_node)
    g.add_node("analysts",     parallel_analysts_node)
    g.add_node("supervisor",   supervisor_node)
    g.add_node("risk",         risk_node)
    g.add_node("memory_save",  memory_save_node)

    g.set_entry_point("data_refresh")
    g.add_edge("data_refresh", "memory_load")
    g.add_edge("memory_load",  "planner")
    g.add_edge("planner",      "analysts")
    g.add_edge("analysts",     "supervisor")
    g.add_edge("supervisor",   "risk")
    g.add_edge("risk",         "memory_save")
    g.add_edge("memory_save",  END)

    return g.compile()


workflow = build_workflow()
