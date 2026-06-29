"""
认知协议（Cognitive Protocol）— 将 "prompt模板" 升级为 "真正的智能体"

每个 Agent 遵循统一的认知循环：
  感知(Perceive) → 推理(Reason) → 行动(Act) → 评估(Evaluate)

认知能力按角色分级：
  - 全认知（5步）：Technical / News / Sector Analyst — 有工具循环 + 推理 + 自评估
  - 轻认知（推理+评估）：Supervisor / Risk Manager — 无工具但有推理和自评估
  - 最轻（仅推理）：Planner — 推理即输出
"""

from __future__ import annotations

import re
import logging
from dataclasses import dataclass, field
from typing import Optional

from core.cost_tracker import CostTracker
from core.event_bus import ConsoleEventBus

logger = logging.getLogger(__name__)


@dataclass
class AgentOutput:
    """Agent 的标准化输出，包含报告、推理链、置信度和成本。"""
    report: str
    reasoning_trace: str = ""
    confidence: float = 0.0
    confidence_details: dict = field(default_factory=dict)


def run_reasoning(
    llm,
    agent_name: str,
    stock_name: str,
    context: str,
    lessons: str = "",
    bus=None,
    tracker: CostTracker = None,
) -> str:
    """执行推理阶段：Agent 在行动前先思考策略。

    用低温度 + 短 max_tokens 控制成本。
    返回推理文本，同时通过 EventBus 推送给前端。
    """
    if bus is None:
        bus = ConsoleEventBus()

    lesson_block = ""
    if lessons:
        lesson_block = f"\n## 历史教训（基于复盘，必须参考）\n{lessons}\n"

    reasoning_prompt = f"""你是{agent_name}，在正式分析之前，请先思考策略。

当前任务：分析【{stock_name}】
{lesson_block}
## 已知上下文
{context[:800]}

请用以下格式简要输出你的思考（不超过200字）：
- 目标股票的关键特征
- 历史教训对本次分析的影响（如有）
- 本次分析策略调整
- 计划调用的工具和顺序
"""

    from langchain_core.messages import HumanMessage, SystemMessage
    response = llm.invoke(
        [SystemMessage(content="你是一位严谨的分析师，正在进行分析前的策略思考。简洁输出。"),
         HumanMessage(content=reasoning_prompt)],
    )

    if tracker:
        usage = getattr(response, "usage_metadata", None) or {}
        tracker.record_llm_call(
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
        )

    reasoning_text = response.content
    bus.emit_reasoning(agent_name, reasoning_text)
    logger.debug("[%s] 推理完成：%s", agent_name, reasoning_text[:100])
    return reasoning_text


def parse_self_evaluation(report_text: str) -> tuple[float, dict]:
    """从报告末尾提取自评估信息。

    Agent 的 system prompt 要求输出报告后附加自评估块：
    ```
    ---自评估---
    - 数据充分性：X/5
    - 逻辑自洽性：X/5
    - 置信度：XX%
    - 薄弱环节：...
    ```

    返回 (confidence_float, details_dict)。提取失败返回默认值。
    """
    confidence = 0.7  # 默认值
    details = {}

    # 尝试提取置信度百分比
    m = re.search(r'置信度[：:]\s*(\d+)%', report_text)
    if m:
        confidence = int(m.group(1)) / 100.0

    # 提取各维度评分
    for dim in ["数据充分性", "逻辑自洽性"]:
        m = re.search(rf'{dim}[：:]\s*(\d)/5', report_text)
        if m:
            details[dim] = int(m.group(1))

    # 提取薄弱环节
    m = re.search(r'薄弱环节[：:]\s*(.+?)(?:\n|$)', report_text)
    if m:
        details["薄弱环节"] = m.group(1).strip()

    return confidence, details


def strip_self_evaluation(report_text: str) -> str:
    """从报告中移除自评估块，返回纯报告内容。"""
    parts = re.split(r'---\s*自评估\s*---', report_text, maxsplit=1)
    return parts[0].rstrip()


SELF_EVAL_SUFFIX = """

完成分析后，请在报告末尾附加自评估（这部分不会展示给用户，仅供系统内部使用）：

---自评估---
- 数据充分性：X/5（1=严重不足，5=非常充分）
- 逻辑自洽性：X/5（1=存在矛盾，5=完全自洽）
- 置信度：XX%（0-100，你对本次分析结论的信心）
- 薄弱环节：（一句话，本次分析最大的不确定性来源）
"""
