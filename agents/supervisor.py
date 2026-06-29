import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging
from datetime import datetime
from langchain_core.messages import HumanMessage, SystemMessage
from config import get_llm
from core.cost_tracker import CostTracker
from core.cognitive import run_reasoning, parse_self_evaluation, strip_self_evaluation, SELF_EVAL_SUFFIX, AgentOutput

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """你是一位资深基金经理，负责整合多位分析师的研究报告，做出最终投资判断。

你会收到三份分析报告（附带各分析师的置信度），以及可能包含的历史分析记录。

你的职责：
1. 如果有历史记录，必须明确对比本次与上次的变化
2. 综合三份报告，找出多重共振信号
3. 识别报告间的矛盾并给出判断
4. **按置信度加权**：高置信度报告的结论权重更高，低置信度报告的结论需谨慎采信
5. 给出明确的操作建议和仓位

输出格式：

## 综合研究报告 · {stock_name}

### 核心结论
- 综合评级：⭐⭐⭐（1-5星）
- 操作建议：买入 / 观望 / 回避
- 建议仓位：XX%

### 与历史对比（如有历史记录必填）
（本次 vs 上次的变化：评级变化、建议变化、关键信号变化）

### 多维信号共振分析
（技术面 + 消息面 + 板块面的共同指向）

### 主要矛盾点
（三份报告中不一致的地方及判断）

### 关键催化剂与风险
- 短期催化剂：
- 主要风险：

### 操作建议
（买入区间、目标价、止损位）
""" + SELF_EVAL_SUFFIX


def run_supervisor(
    stock_name: str,
    technical_report: str,
    news_report: str,
    sector_report: str,
    memory_context: str = "",
    last_advice: str = "",
    tracker: CostTracker = None,
    technical_confidence: float = 0.7,
    news_confidence: float = 0.7,
    sector_confidence: float = 0.7,
    lessons: str = "",
    bus=None,
) -> AgentOutput:
    today = datetime.now().strftime("%Y年%m月%d日")
    llm = get_llm(temperature=0.2)

    # ── 推理阶段 ──
    context = (
        f"技术面置信度:{technical_confidence:.0%} | "
        f"消息面置信度:{news_confidence:.0%} | "
        f"板块面置信度:{sector_confidence:.0%}"
    )
    reasoning = run_reasoning(
        llm=get_llm(temperature=0.05),
        agent_name="supervisor",
        stock_name=stock_name,
        context=context,
        lessons=lessons,
        bus=bus,
        tracker=tracker,
    )

    # ── 行动阶段 ──
    confidence_notes = []
    if technical_confidence < 0.5:
        confidence_notes.append(f"⚠️ 技术分析置信度仅 {technical_confidence:.0%}，结论需谨慎采信")
    if news_confidence < 0.5:
        confidence_notes.append(f"⚠️ 新闻分析置信度仅 {news_confidence:.0%}，结论需谨慎采信")
    if sector_confidence < 0.5:
        confidence_notes.append(f"⚠️ 板块分析置信度仅 {sector_confidence:.0%}，结论需谨慎采信")
    confidence_block = "\n".join(confidence_notes) if confidence_notes else ""

    history_block = ""
    if memory_context:
        history_block = f"\n---\n## 历史记忆（请重点参考对比）\n{memory_context}\n"
        if last_advice:
            history_block += f"\n**上次操作建议为【{last_advice}】，请评估本次是否应调整。**\n"

    user_content = f"""
请综合以下报告对【{stock_name}】做出最终投资判断。今日：{today}

{confidence_block}

---
## 技术分析报告（置信度：{technical_confidence:.0%}）
{technical_report}

---
## 新闻舆情报告（置信度：{news_confidence:.0%}）
{news_report}

---
## 板块分析报告（置信度：{sector_confidence:.0%}）
{sector_report}
{history_block}
"""

    system_content = SYSTEM_PROMPT.format(stock_name=stock_name)
    if lessons:
        system_content += f"\n\n## 历史教训（必须参考）\n{lessons}"

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
        reasoning_trace=reasoning,
        confidence=confidence,
        confidence_details=details,
    )
