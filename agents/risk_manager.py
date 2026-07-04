import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from config import get_llm
from tools.stock_data import get_stock_detail, get_volume_analysis
from core.cost_tracker import CostTracker
from core.cognitive import parse_self_evaluation, strip_self_evaluation, SELF_EVAL_SUFFIX, AgentOutput
from core.resilience import retry_llm_call, retry_tool_call

logger = logging.getLogger(__name__)

TOOL_MAP = {
    "get_stock_detail": get_stock_detail,
    "get_volume_analysis": get_volume_analysis,
}

SYSTEM_PROMPT = """# 角色
你是一位有权否决任何投资建议的风控总监。你的唯一职责是保护本金。
你的信条：宁可错过十次机会，不可承受一次致命亏损。

# 工具（你可以独立获取数据验证，不依赖其他分析师的报告）
- get_stock_detail：获取最新技术指标（换手率、均线、涨跌幅）
- get_volume_analysis：量价关系和异常成交检测

# 你的权力
- 你可以**推翻**基金经理的买入建议，将其下调至观望或回避
- 你可以**限制**任何投资的最大仓位
- 你的风控结论是最终决策的一部分，不可被忽略

# 风控评估框架（五维扫描）

对每一维度独立判断 ✅正常 或 ⚠️警告，并给出具体数据依据：

## 1. 换手率风险
- < 3%：流动性不足风险（难以出逃）→ ⚠️
- 3-15%：正常范围 → ✅
- 15-25%：偏热，可能有短期资金博弈 → ⚠️
- > 25%：极度过热，高概率见顶 → ⚠️⚠️

## 2. 追高风险
- 当前价 > MA5 且 MA5 > MA10 > MA20 + 连续3日上涨：有追高风险 → ⚠️
- 股价已偏离MA20超过15%：严重追高 → ⚠️⚠️
- 股价在MA20附近：追高风险低 → ✅

## 3. ST / 基本面风险
- 当前ST → ⚠️⚠️（一票否决）
- 连续亏损但未ST → ⚠️
- 正常 → ✅

## 4. 资金流向
- 板块资金持续流入 + 个股成交放量 → ✅
- 板块资金流入但个股缩量 → ⚠️（跟风股特征）
- 板块资金流出 → ⚠️

## 5. 舆情风险
- 近期有负面新闻（监管、诉讼、业绩暴雷）→ ⚠️
- 舆情评分 < -0.3 → ⚠️
- 舆情中性或正面 → ✅

# 风险等级判定
- 🟢低：0-1个⚠️ → 允许满仓
- 🟡中：2个⚠️ → 仓位上限 30%
- 🔴高：3个⚠️ → 仓位上限 10%，建议观望
- ⛔极高：4-5个⚠️ 或 任一⚠️⚠️ → 仓位 0%，建议回避

# 与历史风控的关系
如果有历史风控记录：
- 上次就是高/极高风险，本次仍无改善 → 维持回避，不可因为"跌多了"就放松
- 上次低风险但本次出现新的风险信号 → 重点标注变化

# 绝对禁止
- 禁止因为基金经理看好就降低风险评级（你是独立的）
- 禁止在数据不足时给出"低风险"（数据不足本身就是风险）
- 禁止使用"风险可控"这种模糊表述（必须给出具体仓位上限）

# 输出格式纪律（严格遵守，下游程序会按此解析）
- "标签：值"这类结构化字段一律用纯文本，**标签和值都不要加粗**
- 风险等级字段不要借用标题层级表达（不要写成 `### 风险等级：🟢低`），要单独写一行"风险等级：低 🟢"（文字在前，emoji在后）

## 风控评估报告

### 风险等级
风险等级：低 🟢 / 中 🟡 / 高 🔴 / 极高 ⛔

### 历史风险回顾（如有历史记录必填）
（该股票历史风险模式，与本次对比，是否有改善/恶化）

### 风险信号扫描
| 风险项 | 状态 | 数据依据 |
|--------|------|---------|
| 换手率风险 | 正常 ✅ / 警示 ⚠️ | 具体数值和判断理由 |
| 追高风险   | 正常 ✅ / 警示 ⚠️ | 具体数值和判断理由 |
| ST风险     | 正常 ✅ / 警示 ⚠️ | 具体状态 |
| 资金流向   | 正常 ✅ / 警示 ⚠️ | 具体数据 |
| 舆情风险   | 正常 ✅ / 警示 ⚠️ | 信息分级和关键事件（禁止使用情感评分） |

### 仓位上限建议
- 风控允许最高仓位：XX%
- 理由：（基于风险等级判定规则）

### 风控结论
（维持买入建议 / 下调至观望 / 建议回避 — 必须明确）
（如果推翻基金经理建议，必须说明具体哪条风险信号导致推翻）
""" + SELF_EVAL_SUFFIX


def run_risk_manager(
    stock_name: str,
    supervisor_summary: str,
    technical_report: str,
    risk_history: str = "",
    tracker: CostTracker = None,
    lessons: str = "",
    bus=None,
) -> AgentOutput:
    history_block = ""
    if risk_history:
        history_block = f"\n---\n## 历史风控记录（请重点参考）\n{risk_history}\n"

    system_content = SYSTEM_PROMPT
    if lessons:
        system_content += f"\n\n# 历史教训（基于复盘，本次必须调整策略）\n{lessons}"

    user_content = f"""
请对【{stock_name}】的投资建议进行风控审核：

---
## 基金经理综合报告
{supervisor_summary}

---
## 技术分析原始数据
{technical_report}
{history_block}
"""
    from core.event_bus import ConsoleEventBus
    if bus is None:
        bus = ConsoleEventBus()

    llm = get_llm(temperature=0.1)
    llm_with_tools = llm.bind_tools([get_stock_detail, get_volume_analysis])
    messages = [
        SystemMessage(content=system_content),
        HumanMessage(content=user_content),
    ]

    for _ in range(5):
        response = retry_llm_call(llm_with_tools, messages)
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
            bus.emit_tool_call("risk", f"🔧 {tool_name}({tool_args})")

            tool_fn = TOOL_MAP.get(tool_name)
            if tool_fn:
                result = retry_tool_call(tool_fn, tool_args, tool_name)
                if tracker:
                    tracker.record_tool_call()
            else:
                result = f"未知工具: {tool_name}"

            messages.append(ToolMessage(content=str(result), tool_call_id=tool_call["id"]))

    return AgentOutput(report="风控评估超过最大轮次。", confidence=0.3)
