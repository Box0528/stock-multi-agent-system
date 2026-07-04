import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from config import get_llm
from tools.stock_data import run_stock_screener, get_stock_detail, get_stock_trend, get_volume_analysis
from core.event_bus import ConsoleEventBus
from core.cost_tracker import CostTracker
from core.cognitive import parse_self_evaluation, strip_self_evaluation, SELF_EVAL_SUFFIX, AgentOutput
from core.grounding import check_grounding
from core.resilience import retry_llm_call, retry_tool_call

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """# 角色
你是一位拥有15年A股实战经验的技术分析师，专精量价分析和趋势判断。
你的分析风格是：数据驱动，不臆测，看不到数据就说"数据不足"，绝不编造。

# 工具
- get_stock_detail：获取单只股票最新一天的技术指标
- get_stock_trend：获取最近N天的价格/成交量/均线序列（判断趋势用）
- get_volume_analysis：分析量价关系、连续放量缩量、异常成交检测
- run_stock_screener：量化选股模型，返回今日全市场符合条件的股票池

# 分析方法论（必须严格按此顺序）

## 第一步：获取目标股票数据
调用 get_stock_detail 获取最新技术指标。
- 如果工具返回"找不到"，必须如实告知用户，不要编造数据
- 如果数据日期不是今天，标注"数据截至 YYYY-MM-DD"

## 第二步：趋势分析
调用 get_stock_trend 获取最近20天的趋势序列，判断：
- 趋势方向：上升/下降/横盘
- 均线状态：多头排列/空头排列/交叉整理（均线是在收敛还是发散？）
- 近期有无关键突破/跌破（价格突破MA20、MA均线金叉/死叉等）

## 第三步：量价验证
调用 get_volume_analysis 分析量价关系：
- 放量上涨 = 健康上攻
- 缩量上涨 = 动力不足，警惕回调
- 放量下跌 = 资金出逃
- 缩量下跌 = 正常调整
- 异常放量/缩量需特别标注

## 第四步：同行业对比
调用 run_stock_screener 看今日选股池：
- 目标股票是否入选？不入选是哪个条件不满足？
- 同行业有多少只入选？（入选多说明行业整体强势）

## 第五步：形成结论
综合以上数据，给出：
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
    "get_stock_trend": get_stock_trend,
    "get_volume_analysis": get_volume_analysis,
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

    llm_with_tools = llm.bind_tools([get_stock_detail, get_stock_trend, get_volume_analysis, run_stock_screener])
    messages = [
        SystemMessage(content=system_content),
        HumanMessage(content=user_query),
    ]
    receipts: list[dict] = []  # Tool Receipts：工具调用的"参数+原始返回"，用于事后溯源校验
    tool_called = False

    for i in range(8):
        response = retry_llm_call(llm_with_tools, messages)
        messages.append(response)

        if tracker:
            usage = getattr(response, "usage_metadata", None) or {}
            tracker.record_llm_call(
                input_tokens=usage.get("input_tokens", 0),
                output_tokens=usage.get("output_tokens", 0),
            )

        if not response.tool_calls:
            # 至少要调用一次工具，否则报告完全依赖模型记忆而非实时数据
            if not tool_called:
                messages.append(HumanMessage(content="请先调用工具获取实时数据，再输出分析报告。"))
                continue
            raw_report = response.content
            confidence, details = parse_self_evaluation(raw_report)
            clean_report = strip_self_evaluation(raw_report)
            grounding = check_grounding(clean_report, receipts)
            return AgentOutput(
                report=clean_report,
                confidence=confidence,
                confidence_details=details,
                grounding_score=grounding["grounding_score"],
                ungrounded_claims=grounding["ungrounded_claims"],
            )

        tool_called = True
        for tool_call in response.tool_calls:
            tool_name = tool_call["name"]
            tool_args = tool_call["args"]
            bus.emit_tool_call("technical", f"🔧 {tool_name}({tool_args})")

            tool_fn = TOOL_MAP.get(tool_name)
            if tool_fn:
                result = retry_tool_call(tool_fn, tool_args, tool_name)
                if tracker:
                    tracker.record_tool_call()
            else:
                result = f"未知工具: {tool_name}"

            receipts.append({"tool_name": tool_name, "args": tool_args, "result": str(result)})
            messages.append(ToolMessage(content=str(result), tool_call_id=tool_call["id"]))

    return AgentOutput(report="分析超过最大轮次，请重试。", confidence=0.1)
