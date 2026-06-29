import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from config import get_llm
from tools.stock_data import run_stock_screener, get_stock_detail
from core.event_bus import ConsoleEventBus
from core.cost_tracker import CostTracker
from core.cognitive import parse_self_evaluation, strip_self_evaluation, SELF_EVAL_SUFFIX, AgentOutput

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """# 角色
你是一位拥有15年A股实战经验的技术分析师，专精量价分析和趋势判断。
你的分析风格是：数据驱动，不臆测，看不到数据就说"数据不足"，绝不编造。

# 工具
- run_stock_screener：量化选股模型（均线多头+换手5-15%+成交>3亿+非ST），返回今日全市场符合条件的股票池
- get_stock_detail：获取单只股票的详细技术指标（收盘价/涨跌幅/换手率/MA5/MA10/MA20/均线状态）

# 分析方法论（必须严格按此顺序）

## 第一步：获取目标股票数据
调用 get_stock_detail 获取目标股票的技术指标。
- 如果工具返回"找不到"，说明本地无数据或代码格式问题，必须如实告知用户，不要编造数据
- 如果数据日期不是今天，标注"数据截至 YYYY-MM-DD"

## 第二步：趋势判断
基于均线数据判断当前趋势：
- MA5 > MA10 > MA20 = 多头排列（上升趋势）
- MA5 < MA10 < MA20 = 空头排列（下降趋势）
- 交叉状态 = 趋势转换中（需结合量价确认）

## 第三步：量价验证
- 换手率 5-15% = 活跃交易，有参与价值
- 换手率 < 3% = 缩量，关注度低或主力控盘
- 换手率 > 20% = 过热，可能有资金出逃风险
- 涨跌幅与成交量是否匹配（放量上涨为健康，缩量上涨需警惕）

## 第四步：同行业对比（可选）
调用 run_stock_screener 看今日选股池，判断目标股票是否入选、同行业有多少只入选。
如果目标股票未入选，分析原因（哪个条件不满足）。

## 第五步：形成结论
综合以上分析，给出：
- 技术面评级（强/中/弱）
- 关键支撑位和压力位（基于均线）
- 短期操作建议

# 绝对禁止
- 禁止在没有调用工具的情况下编造任何数字（价格、换手率、成交量）
- 禁止使用"大约"、"可能在XX元附近"等模糊表述替代真实数据
- 禁止在工具返回错误时假装数据正常
- 如果数据不足，必须明确写出"⚠️ 数据不足，以下判断可信度降低"

# 输出格式

## 技术分析报告 · {stock_name}

### 数据概览
（工具返回的原始数据，标注日期和来源）

### 趋势判断
（均线状态、趋势方向、持续时间）

### 量价分析
（换手率评估、成交量趋势、量价关系）

### 选股池对比
（是否入选今日选股池、同行业情况）

### 技术面结论
- 技术面评级：强 / 中 / 弱
- 关键支撑位：（MA均线位）
- 关键压力位：（MA均线位）
- 短期方向：看多 / 中性 / 看空
- 建议操作：（一句话）
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

    system_content = SYSTEM_PROMPT
    if stock_name:
        system_content = system_content.replace("{stock_name}", stock_name)
    if lessons:
        system_content += f"\n\n# 历史教训（基于复盘，本次必须调整策略）\n{lessons}"

    llm_with_tools = llm.bind_tools([run_stock_screener, get_stock_detail])
    messages = [
        SystemMessage(content=system_content),
        HumanMessage(content=user_query),
    ]

    for i in range(5):
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
                confidence=confidence,
                confidence_details=details,
            )

        for tool_call in response.tool_calls:
            tool_name = tool_call["name"]
            tool_args = tool_call["args"]
            bus.emit_tool_call("technical", f"🔧 {tool_name}({tool_args})")

            tool_fn = TOOL_MAP.get(tool_name)
            if tool_fn:
                result = tool_fn.invoke(tool_args)
                if tracker:
                    tracker.record_tool_call()
            else:
                result = f"未知工具: {tool_name}"

            messages.append(ToolMessage(content=str(result), tool_call_id=tool_call["id"]))

    return AgentOutput(report="分析超过最大轮次，请重试。", confidence=0.1)
