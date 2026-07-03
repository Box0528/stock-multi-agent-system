import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging
from datetime import datetime
from langchain_core.messages import HumanMessage, SystemMessage
from config import get_llm
from core.cost_tracker import CostTracker
from core.cognitive import parse_self_evaluation, strip_self_evaluation, SELF_EVAL_SUFFIX, AgentOutput
from core.resilience import retry_llm_call

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """# 角色
你是一位管理50亿规模基金的资深基金经理，有20年A股投资经验。
你的投资哲学：多维共振时重仓出击，信号矛盾时宁可错过不可做错。

# 你的工作
你会收到三位分析师的报告（技术面/消息面/板块面），每份报告附带置信度评分。
你不直接分析数据，而是**整合判断**，做出最终投资决策。

# 决策框架

## 第一步：信号提取
从每份报告中提取核心信号，归类为：
- 📈 看多信号（明确支持买入的事实）
- 📉 看空信号（明确支持回避的事实）
- ⚖️ 中性信号（不构成方向性判断的信息）

## 第二步：共振检测
三个维度的信号是否指向同一方向？
- **三维共振**（技术+消息+板块同向）→ 高确定性，可以给出明确建议
- **两维共振**（两个同向，一个矛盾）→ 中确定性，倾向共振方向但降低仓位
- **无共振**（三个方向不一致）→ 低确定性，建议观望

## 第三步：置信度加权
- 高置信度（>70%）的报告结论权重高
- 低置信度（<50%）的报告结论需打折 → 在报告中标注"⚠️ 该维度分析数据不足"
- 如果所有报告置信度都低，整体结论必须偏保守

## 第四步：历史对比（如有历史记录）
- 上次建议 vs 本次信号变化
- 如果要改变建议方向（如从观望改为买入），必须有明确的新增信号支撑
- 如果信号无变化，维持上次建议并说明原因

## 第五步：形成决策
- 综合评级（⭐ 1-5星）：基于共振强度和确定性
- 操作建议：只能是 买入 / 观望 / 回避（不要模糊表述）
- 仓位建议：基于确定性（高确定性30-50%，中确定性10-20%，低确定性0%）

## 输出格式纪律（严格遵守，下游程序会按此解析）
- "标签：值"这类结构化字段一律用纯文本，**标签和值都不要加粗**（不要写成 `**操作建议**：观望`，要写成 `操作建议：观望`）
- 方向类字段不能只写emoji，必须是"文字+emoji"组合，如"看多 📈"、"看空 📉"、"中性 ⚖️"（不要只写 📈）

## 绝对禁止
- 禁止简单罗列三份报告内容（你是决策者不是搬运工）
- 禁止在信号矛盾时和稀泥（必须给出明确判断并解释选择哪边、为什么）
- 禁止无视低置信度警告
- 禁止给出"可以适当关注"这种不可执行的建议
- **禁止添加三份报告中没有提到的信息**（如果你写了报告中没有的数据或事件，必须标注[系统推断]）
- 所有引用的新闻、数据、评级必须能在上方三份报告中找到原文出处

# 输出格式

## 综合研究报告 · {stock_name}

### 核心结论
- 综合评级：⭐⭐⭐（1-5星）
- 操作建议：买入 / 观望 / 回避
- 建议仓位：XX%
- 决策确定性：高 / 中 / 低

### 三维信号图谱
| 维度 | 方向 | 置信度 | 核心信号 |
|------|------|--------|---------|
| 技术面 | 看多 📈 / 看空 📉 / 中性 ⚖️ | XX% | 一句话 |
| 消息面 | 看多 📈 / 看空 📉 / 中性 ⚖️ | XX% | 一句话 |
| 板块面 | 看多 📈 / 看空 📉 / 中性 ⚖️ | XX% | 一句话 |

### 共振分析
（信号是否共振、共振强度、矛盾点分析）

### 与历史对比（如有历史记录必填）
（本次 vs 上次：哪些信号变了、建议是否调整、调整理由）

### 关键催化剂与风险
- 上行催化：（可能推动上涨的事件）
- 下行风险：（可能导致下跌的因素）

### 操作建议
- 买入区间：（如适用）
- 止损位：（必填）
- 目标价：（如适用）
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
    technical_grounding: float = 1.0,
    news_grounding: float = 1.0,
    sector_grounding: float = 1.0,
    lessons: str = "",
    bus=None,
) -> AgentOutput:
    today = datetime.now().strftime("%Y年%m月%d日")

    alert_notes = []
    if technical_confidence < 0.5:
        alert_notes.append(f"⚠️ 技术分析置信度仅 {technical_confidence:.0%}，结论需谨慎采信")
    if news_confidence < 0.5:
        alert_notes.append(f"⚠️ 新闻分析置信度仅 {news_confidence:.0%}，结论需谨慎采信")
    if sector_confidence < 0.5:
        alert_notes.append(f"⚠️ 板块分析置信度仅 {sector_confidence:.0%}，结论需谨慎采信")
    if technical_grounding < 0.7:
        alert_notes.append(f"⚠️ 技术分析数据核实率仅 {technical_grounding:.0%}，报告中有数字未能在工具原始数据中找到依据，该维度结论须降权")
    if news_grounding < 0.7:
        alert_notes.append(f"⚠️ 新闻分析数据核实率仅 {news_grounding:.0%}，该维度结论须降权")
    if sector_grounding < 0.7:
        alert_notes.append(f"⚠️ 板块分析数据核实率仅 {sector_grounding:.0%}，该维度结论须降权")
    alert_block = "\n".join(alert_notes) if alert_notes else ""

    def _dim_header(label: str, conf: float, grounding: float) -> str:
        grounding_note = f" | 数据核实率：{grounding:.0%}" if grounding < 1.0 else ""
        low_warn = "  ⚠️ 数据核实率低，结论须降权" if grounding < 0.7 else ""
        return f"## {label}（置信度：{conf:.0%}{grounding_note}）{low_warn}"

    history_block = ""
    if memory_context:
        history_block = f"\n---\n## 历史记忆（请重点参考对比）\n{memory_context}\n"
        if last_advice:
            history_block += f"\n**上次操作建议为【{last_advice}】，如要改变方向需有新增信号支撑。**\n"

    user_content = f"""
请综合以下报告对【{stock_name}】做出最终投资判断。今日：{today}

{alert_block}

---
{_dim_header("技术分析报告", technical_confidence, technical_grounding)}
{technical_report}

---
{_dim_header("新闻舆情报告", news_confidence, news_grounding)}
{news_report}

---
{_dim_header("板块分析报告", sector_confidence, sector_grounding)}
{sector_report}
{history_block}
"""

    system_content = SYSTEM_PROMPT.format(stock_name=stock_name)
    if lessons:
        system_content += f"\n\n# 历史教训（基于复盘，本次必须调整策略）\n{lessons}"

    llm = get_llm(temperature=0.2)
    messages = [
        SystemMessage(content=system_content),
        HumanMessage(content=user_content),
    ]
    response = retry_llm_call(llm, messages)

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
