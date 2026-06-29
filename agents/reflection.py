import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import re
import logging
from datetime import datetime
from langchain_core.messages import HumanMessage, SystemMessage
from config import get_llm
from core.cost_tracker import CostTracker

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """你是一位专业的投研复盘分析师，负责对过去的投资预测进行客观评估。

你会收到：
- 上次分析的结论（建议、评级、风险判断、当时价格）
- 上次到现在的实际价格变化
- 本次最新分析报告

你的职责：
1. 客观评估上次预测是否准确
2. 分析预测正确或错误的原因
3. 提炼本次分析应该特别注意的教训
4. 给出系统自我改进建议

评估标准：
- 建议"买入"且实际上涨 > 3%  → 预测正确 ✓
- 建议"回避"且实际下跌 > 3%  → 预测正确 ✓
- 建议"观望"且波动 < 5%      → 预测合理 ○
- 其他情况                    → 预测偏差 ✗

输出格式：

## 🔍 投研复盘报告

### 预测准确性评估
- 上次建议：{上次建议} （{上次日期}，价格 {上次价格}）
- 实际结果：价格从 X 元 → Y 元，涨跌幅 Z%
- 评估结论：✓ 正确 / ○ 合理 / ✗ 偏差

### 预测偏差分析
（如果预测正确，分析是哪些信号起了关键作用）
（如果预测错误，分析是哪个维度判断失误：技术面？消息面？板块面？）

### 本次分析修正点
（基于上次复盘，本次分析应该重点关注什么、警惕什么）

### 系统学习记录
- 该股票预测准确率：X/Y次正确
- 主要失误模式：（如果有规律性错误）
- 下次重点关注：（一句话）
"""


def run_reflection(
    stock_name:      str,
    last_advice:     str,
    last_date:       str,
    last_price_info: str,
    current_price:   dict,
    current_report:  str,
    history_records: list,
    tracker:         CostTracker = None,
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

## 历史预测准确率
{accuracy_text}

---
## 本次最新分析报告（节选）
{current_report[:1500]}
---

请按格式输出复盘报告。
"""

    llm = get_llm(temperature=0.2)
    messages = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=user_content),
    ]

    logger.info("开始复盘分析：%s", stock_name)
    response = llm.invoke(messages)

    if tracker:
        usage = getattr(response, "usage_metadata", None) or {}
        tracker.record_llm_call(
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
        )

    logger.info("复盘完成：%s", stock_name)
    return response.content


def _calc_price_change(last_price_info: str, current_price: dict) -> str:
    if not last_price_info or current_price["source"] == "unavailable":
        return "价格数据不可用，无法计算涨跌幅"

    match = re.search(r'([\d.]+)\s*元', last_price_info)
    if not match:
        return f"当前价格：{current_price['price']:.2f}元（无法提取上次价格进行对比）"

    last_price    = float(match.group(1))
    current_price_val = current_price["price"]

    if last_price == 0:
        return "上次价格记录异常"

    change_pct = (current_price_val - last_price) / last_price * 100
    direction  = "上涨" if change_pct > 0 else "下跌"
    source_note = "（实时数据）" if current_price["source"] == "realtime" else "（本地缓存）"

    return (
        f"价格从 {last_price:.2f}元 → {current_price_val:.2f}元\n"
        f"区间涨跌：{direction} {abs(change_pct):.2f}% {source_note}\n"
        f"当前数据日期：{current_price['date']}"
    )


def _calc_accuracy(history_records: list) -> str:
    if len(history_records) < 2:
        return "历史记录不足，暂无统计数据"

    total  = len(history_records) - 1
    lines  = [f"共有 {total} 次历史预测记录："]
    for r in history_records[1:]:
        lines.append(f"- {r['date']}：{r['advice']}  风险:{r['risk_level']}")
    return "\n".join(lines)


def save_reflection_to_memory(
    stock_name:       str,
    reflection_text:  str,
    was_correct:      bool,
) -> None:
    try:
        from memory.vector_store import _get_collection
        col = _get_collection("reflections")
        now = datetime.now()
        doc_id = f"{stock_name}_reflection_{now.strftime('%Y%m%d_%H%M%S')}"

        col.add(
            documents=[reflection_text[:1000]],
            metadatas=[{
                "stock_name":  stock_name,
                "date":        now.strftime("%Y-%m-%d"),
                "timestamp":   now.isoformat(),
                "was_correct": str(was_correct),
            }],
            ids=[doc_id]
        )
        logger.info("复盘结论已存入 Memory")
    except Exception as e:
        logger.error("复盘存储失败：%s", e)


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
