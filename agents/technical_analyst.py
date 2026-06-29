import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from config import get_llm
from tools.stock_data import run_stock_screener, get_stock_detail
from core.event_bus import ConsoleEventBus
from core.cost_tracker import CostTracker
from core.cognitive import run_reasoning, parse_self_evaluation, strip_self_evaluation, SELF_EVAL_SUFFIX, AgentOutput

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """你是一位专业的股票技术分析师。
你有以下工具可以使用：
- run_stock_screener：运行量化选股模型，筛选出符合技术条件的股票池
- get_stock_detail：获取单只股票的详细技术指标

你的职责：
1. 调用选股工具获取今日股票池
2. 分析股票的技术面状况（均线、换手率、成交量）
3. 从技术角度给出买入建议和关注重点

输出格式要求：
- 用中文回答
- 先给出整体市场技术面判断
- 再列出重点关注股票（不超过5只）
- 每只股票给出技术面理由
""" + SELF_EVAL_SUFFIX

TOOL_MAP = {
    "run_stock_screener": run_stock_screener,
    "get_stock_detail": get_stock_detail,
}


def run_technical_analyst(
    user_query: str,
    bus=None,
    tracker: CostTracker = None,
    lessons: str = "",
    stock_name: str = "",
) -> AgentOutput:
    if bus is None:
        bus = ConsoleEventBus()

    llm = get_llm(temperature=0.1)

    # ── 推理阶段 ──
    reasoning = ""
    if stock_name:
        reasoning = run_reasoning(
            llm=get_llm(temperature=0.05),
            agent_name="technical",
            stock_name=stock_name,
            context=user_query,
            lessons=lessons,
            bus=bus,
            tracker=tracker,
        )

    # ── 行动阶段 ──
    system_content = SYSTEM_PROMPT
    if lessons:
        system_content += f"\n\n## 历史教训（必须参考调整策略）\n{lessons}"

    llm_with_tools = llm.bind_tools([run_stock_screener, get_stock_detail])
    messages = [
        SystemMessage(content=system_content),
        HumanMessage(content=user_query),
    ]

    for _ in range(5):
        response = llm_with_tools.invoke(messages)
        messages.append(response)

        if tracker:
            usage = getattr(response, "usage_metadata", None) or {}
            tracker.record_llm_call(
                input_tokens=usage.get("input_tokens", 0),
                output_tokens=usage.get("output_tokens", 0),
            )

        if not response.tool_calls:
            raw_report = response.content
            confidence, details = parse_self_evaluation(raw_report)
            clean_report = strip_self_evaluation(raw_report)
            return AgentOutput(
                report=clean_report,
                reasoning_trace=reasoning,
                confidence=confidence,
                confidence_details=details,
            )

        for tool_call in response.tool_calls:
            tool_name = tool_call["name"]
            tool_args = tool_call["args"]
            bus.emit_tool_call("technical", f"🔧 调用工具: {tool_name}，参数: {tool_args}")

            tool_fn = TOOL_MAP.get(tool_name)
            if tool_fn:
                result = tool_fn.invoke(tool_args)
                if tracker:
                    tracker.record_tool_call()
            else:
                result = f"未知工具: {tool_name}"

            messages.append(ToolMessage(
                content=str(result),
                tool_call_id=tool_call["id"]
            ))

    return AgentOutput(report="分析超过最大轮次，请重试。", reasoning_trace=reasoning, confidence=0.1)
