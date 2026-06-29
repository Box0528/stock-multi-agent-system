import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging
from langchain_core.messages import HumanMessage, SystemMessage
from config import get_llm
from core.cost_tracker import CostTracker
from core.cognitive import parse_self_evaluation, strip_self_evaluation, SELF_EVAL_SUFFIX, AgentOutput

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """# 角色
你是一位有权否决任何投资建议的风控总监。你的唯一职责是保护本金。
你的信条：宁可错过十次机会，不可承受一次致命亏损。

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

# 输出格式

## 风控评估报告

### 风险等级：🟢低 / 🟡中 / 🔴高 / ⛔极高

### 历史风险回顾（如有历史记录必填）
（该股票历史风险模式，与本次对比，是否有改善/恶化）

### 风险信号扫描
| 风险项 | 状态 | 数据依据 |
|--------|------|---------|
| 换手率风险 | ✅/⚠️ | 具体数值和判断理由 |
| 追高风险   | ✅/⚠️ | 具体数值和判断理由 |
| ST风险     | ✅/⚠️ | 具体状态 |
| 资金流向   | ✅/⚠️ | 具体数据 |
| 舆情风险   | ✅/⚠️ | 情感评分和关键事件 |

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
{technical_report[:1500]}
{history_block}
"""
    llm = get_llm(temperature=0.1)
    messages = [
        SystemMessage(content=system_content),
        HumanMessage(content=user_content),
    ]
    response = llm.invoke(messages)

    if tracker:
        usage = getattr(response, "usage_metadata", None) or {}
        tracker.record_llm_call(
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
        )

    raw_report = response.content
    confidence, details = parse_self_evaluation(raw_report)
    clean_report = strip_self_evaluation(raw_report)

    return AgentOutput(
        report=clean_report,
        confidence=confidence,
        confidence_details=details,
    )
