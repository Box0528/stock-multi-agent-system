import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging
from datetime import datetime
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from config import get_llm
from tools.stock_data import analyze_sector
from tools.search import search_stock_news
from core.event_bus import ConsoleEventBus
from core.cost_tracker import CostTracker
from core.cognitive import run_reasoning, parse_self_evaluation, strip_self_evaluation, SELF_EVAL_SUFFIX, AgentOutput

logger = logging.getLogger(__name__)

TOOL_MAP = {
    "analyze_sector": analyze_sector,
    "search_stock_news": search_stock_news,
}


def get_system_prompt() -> str:
    today = datetime.now().strftime("%Y年%m月%d日")
    year = datetime.now().strftime("%Y")

    return f"""你是一位专业的板块分析师。今天是{today}。

你有两个工具：
- analyze_sector：计算指定行业板块的统计数据（上涨比例、资金流向、强度评分等）
- search_stock_news：搜索板块相关政策、热点新闻

分析一个板块时，必须按以下顺序完成3步：
1. 用analyze_sector获取板块统计数据
2. 用search_stock_news搜索"{{行业名称}} 政策 {year}"
3. 用search_stock_news搜索"{{行业名称}} 资金 龙头 {today[:7]}"

完成后输出以下格式报告：

## 板块分析报告（{today}）

### 板块强度评分：X / 100
（强：80+，中：50-80，弱：50以下）

### 量化统计
（上涨比例、平均涨幅、资金流向、均线多头占比）

### 板块龙头
（涨幅前3只，简要说明）

### 政策与热点
（近期政策催化、市场热点）

### 综合判断
- 板块当前强度：强 / 中 / 弱
- 资金参与度：高 / 中 / 低
- 操作建议：积极关注 / 观望 / 回避
- 判断依据：（2句话）
""" + SELF_EVAL_SUFFIX


def run_sector_analyst(
    industry_name: str,
    stock_name: str = "",
    bus=None,
    tracker: CostTracker = None,
    lessons: str = "",
) -> AgentOutput:
    if bus is None:
        bus = ConsoleEventBus()

    llm = get_llm(temperature=0.1)

    # ── 推理阶段 ──
    context = f"分析【{industry_name}】板块的整体强弱和资金流向"
    if stock_name:
        context += f"，重点关注{stock_name}"
    reasoning = run_reasoning(
        llm=get_llm(temperature=0.05),
        agent_name="sector",
        stock_name=stock_name or industry_name,
        context=context,
        lessons=lessons,
        bus=bus,
        tracker=tracker,
    )

    # ── 行动阶段 ──
    query = f"请分析【{industry_name}】板块的整体强弱和资金流向"
    if stock_name:
        query += f"，重点关注{stock_name}所在板块的机会"

    system_content = get_system_prompt()
    if lessons:
        system_content += f"\n\n## 历史教训（必须参考调整策略）\n{lessons}"

    llm_with_tools = llm.bind_tools([analyze_sector, search_stock_news])
    messages = [
        SystemMessage(content=system_content),
        HumanMessage(content=query),
    ]

    for _ in range(8):
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
            bus.emit_tool_call("sector", f"🔧 调用（{tool_name}）：{tool_args}")

            tool_fn = TOOL_MAP.get(tool_name)
            if tool_fn:
                result = tool_fn.invoke(tool_args)
                if tracker:
                    tracker.record_tool_call()
                    if tool_name == "search_stock_news":
                        tracker.record_search_call()
            else:
                result = f"未知工具: {tool_name}"

            messages.append(ToolMessage(
                content=str(result),
                tool_call_id=tool_call["id"]
            ))

    return AgentOutput(report="分析超过最大轮次，请重试。", reasoning_trace=reasoning, confidence=0.1)
