import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import re
import logging
from datetime import datetime
from langchain_core.messages import HumanMessage, SystemMessage
from config import get_llm
from core.cost_tracker import CostTracker
from core.resilience import retry_llm_call

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """# 角色
你是投研团队的复盘分析师，负责对过去的预测进行客观审计。
你不做新的预测，只审查旧预测的准确性，找出系统性偏差。

# 复盘方法论

## 第一步：事实还原
客观记录：
- 上次建议是什么、基于什么信号
- 实际价格怎么变化了
- 偏差有多大（用百分比量化）

## 第二步：归因分析（这是最重要的）
预测对了或错了，原因是什么？必须具体到维度：
- 技术面判断是否准确？（均线/量价信号是否如预期发展）
- 消息面是否有预期外事件？（突发利好/利空）
- 板块面判断是否准确？（板块轮动方向是否如预期）
- 风控判断是否合理？（风险评估是否过高/过低）

## 第三步：模式识别
如果有多次历史记录，寻找规律：
- 是否存在系统性偏差？（比如总是高估技术面信号）
- 哪个维度的判断最准确？哪个最不靠谱？
- 是否存在"该果断时犹豫、该谨慎时激进"的模式？

## 第四步：行为修正建议（供下次分析使用）
针对每个 agent 给出具体、可执行的调整建议：
- → Technical Analyst：（如"降低短期均线权重"或"增加成交量分析权重"）
- → News Analyst：（如"增加行业政策搜索频次"或"注意区分噪音和信号"）
- → Sector Analyst：（如"关注板块轮动阶段而非只看强度评分"）
- → Risk Manager：（如"对该行业提高风险系数"或"降低追高风险阈值"）
- → Supervisor：（如"当技术面和消息面矛盾时优先听消息面"）

# 评估标准
- 建议"买入"且实际上涨 > 3% → ✓ 正确
- 建议"回避"且实际下跌 > 3% → ✓ 正确
- 建议"观望"且波动 < 5% → ○ 合理
- 其他 → ✗ 偏差

# 绝对禁止
- 禁止事后诸葛亮（"早就应该看到XX信号" — 如果当时的数据不支持，就不算失误）
- 禁止因为结果对了就说分析过程对（可能是运气）
- 禁止给出模糊的改进建议（"下次注意一下" → 注意什么？怎么注意？）

# 输出格式

## 🔍 投研复盘报告

### 预测准确性评估
- 上次建议：{建议}（{日期}，价格 {价格}）
- 实际结果：价格 X 元 → Y 元，涨跌幅 Z%
- 评估结论：✓ 正确 / ○ 合理 / ✗ 偏差

### 归因分析
| 维度 | 当时判断 | 实际发展 | 准确性 |
|------|---------|---------|--------|
| 技术面 | ... | ... | ✓/✗ |
| 消息面 | ... | ... | ✓/✗ |
| 板块面 | ... | ... | ✓/✗ |
| 风控   | ... | ... | ✓/✗ |

### 模式识别
（如有多次记录，分析系统性偏差）

### 行为修正建议
- → Technical Analyst：（具体可执行的调整）
- → News Analyst：（具体可执行的调整）
- → Sector Analyst：（具体可执行的调整）
- → Risk Manager：（具体可执行的调整）
- → Supervisor：（具体可执行的调整）

### 系统学习记录
- 该股票预测准确率：X/Y次
- 主要失误模式：（一句话总结）
"""


def run_reflection(
    stock_name: str,
    last_advice: str,
    last_date: str,
    last_price_info: str,
    current_price: dict,
    current_report: str,
    history_records: list,
    tracker: CostTracker = None,
) -> str:
    if not last_advice or not last_date:
        return ""

    price_change_text = _calc_price_change(last_price_info, current_price)
    accuracy_text = _calc_accuracy(history_records)
    today = datetime.now().strftime("%Y年%m月%d日")

    user_content = f"""
请对【{stock_name}】的历史预测进行复盘分析。今日：{today}

---
## 上次预测信息
- 分析日期：{last_date}
- 操作建议：{last_advice}
- 当时价格：{last_price_info or '未记录'}

## 价格实际变化
{price_change_text}

## 历史预测记录
{accuracy_text}

---
## 本次最新分析报告（节选）
{current_report[:1500]}
---

请按格式输出复盘报告，重点是归因分析和行为修正建议。
"""

    llm = get_llm(temperature=0.2)
    messages = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=user_content),
    ]

    response = retry_llm_call(llm, messages)

    if tracker:
        usage = getattr(response, "usage_metadata", None) or {}
        tracker.record_llm_call(
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
        )

    return response.content


def _calc_price_change(last_price_info: str, current_price: dict) -> str:
    if not last_price_info or current_price["source"] == "unavailable":
        return "价格数据不可用，无法计算涨跌幅"

    match = re.search(r'([\d.]+)\s*元', last_price_info)
    if not match:
        return f"当前价格：{current_price['price']:.2f}元（无法提取上次价格进行对比）"

    last_price = float(match.group(1))
    current_price_val = current_price["price"]

    if last_price == 0:
        return "上次价格记录异常"

    change_pct = (current_price_val - last_price) / last_price * 100
    direction = "上涨" if change_pct > 0 else "下跌"
    source_note = "（实时数据）" if current_price["source"] == "realtime" else "（本地缓存）"

    return (
        f"价格从 {last_price:.2f}元 → {current_price_val:.2f}元\n"
        f"区间涨跌：{direction} {abs(change_pct):.2f}% {source_note}\n"
        f"当前数据日期：{current_price['date']}"
    )


def _calc_accuracy(history_records: list) -> str:
    if len(history_records) < 2:
        return "历史记录不足，暂无统计数据"

    past = history_records[1:]
    lines = [f"共有 {len(past)} 次历史预测记录："]

    reviewed = [r for r in past if "outcome_correct" in r]
    if reviewed:
        correct = sum(1 for r in reviewed if str(r["outcome_correct"]) == "True")
        lines.insert(1, f"已复盘 {len(reviewed)} 次，判断正确 {correct} 次（准确率 {correct/len(reviewed):.0%}）\n")

    for r in past:
        outcome_tag = ""
        if "outcome_correct" in r:
            outcome_tag = " ✓" if str(r["outcome_correct"]) == "True" else " ✗"
        chg_note = ""
        if "price_change_pct" in r:
            chg_note = f"  实际涨跌：{float(r['price_change_pct']):+.1f}%"
        lines.append(f"- {r['date']}：{r['advice']}  风险:{r['risk_level']}{outcome_tag}{chg_note}")

    return "\n".join(lines)


def save_reflection_to_memory(
    stock_name: str,
    reflection_text: str,
    was_correct: bool,
    industry: str = "",
    price_change_pct: float = 0.0,
) -> None:
    try:
        from memory.vector_store import _get_collection, save_agent_lessons
        col = _get_collection("reflections")
        now = datetime.now()
        doc_id = f"{stock_name}_reflection_{now.strftime('%Y%m%d')}"

        col.upsert(
            documents=[reflection_text[:1000]],
            metadatas=[{
                "stock_name": stock_name,
                "date": now.strftime("%Y-%m-%d"),
                "timestamp": now.isoformat(),
                "was_correct": str(was_correct),
            }],
            ids=[doc_id]
        )
        logger.info("复盘结论已存入 Memory")

        # 把本次复盘的结果（涨跌幅、是否判断正确）回写到上一次预测记录
        # top_k=2：records[0] 是本次刚写入的预测，records[1] 才是需要被复盘的上次预测
        from memory.vector_store import update_prediction_outcome, get_prediction_history
        records = get_prediction_history(stock_name, top_k=2)
        if len(records) >= 2:
            update_prediction_outcome(stock_name, records[1]["date"], was_correct, price_change_pct)

        # 解析行为修正建议并存入 agent_lessons
        lessons = _extract_agent_lessons(reflection_text)
        if lessons:
            save_agent_lessons(stock_name, industry, lessons)
            logger.info("行为修正建议已存入：%s", list(lessons.keys()))

    except Exception as e:
        logger.error("复盘存储失败：%s", e)


def _extract_agent_lessons(reflection_text: str) -> dict[str, str]:
    """从复盘报告中提取各 agent 的行为修正建议。"""
    agent_map = {
        "Technical Analyst": "technical",
        "News Analyst": "news",
        "Sector Analyst": "sector",
        "Risk Manager": "risk",
        "Supervisor": "supervisor",
    }
    lessons = {}
    for display_name, key in agent_map.items():
        pattern = rf'→\s*{display_name}[：:]\s*(.+?)(?:\n|$)'
        m = re.search(pattern, reflection_text)
        if m:
            lesson = m.group(1).strip()
            if lesson and lesson != "无" and len(lesson) > 5:
                lessons[key] = lesson
    return lessons


def get_reflection_history(stock_name: str) -> str:
    try:
        from memory.vector_store import _get_collection
        col = _get_collection("reflections")
        count = col.count()
        if count == 0:
            return ""
        results = col.query(
            query_texts=[stock_name],
            n_results=min(2, count),
            where={"stock_name": stock_name},
        )
        if not results["ids"][0]:
            return ""
        docs = results["documents"][0]
        metas = results["metadatas"][0]
        lines = ["## 📋 历史复盘记录\n"]
        for doc, meta in zip(docs, metas):
            lines.append(f"**{meta['date']}** 复盘摘要：")
            lines.append(doc[:300] + "...")
            lines.append("")
        return "\n".join(lines)
    except Exception as e:
        logger.error("查询历史复盘失败：%s", e)
        return ""
