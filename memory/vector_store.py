import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import re
import json
import logging
import threading
import chromadb
from datetime import datetime
from chromadb.utils import embedding_functions

logger = logging.getLogger(__name__)

# ── 初始化 ChromaDB ───────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH  = os.path.join(BASE_DIR, "memory", "chroma_db")

_client = None
_ef     = None
_client_lock = threading.Lock()

def _get_client():
    global _client, _ef
    if _client is None:
        with _client_lock:
            if _client is None:
                _client = chromadb.PersistentClient(path=DB_PATH)
                _ef = embedding_functions.SentenceTransformerEmbeddingFunction(
                    model_name="paraphrase-multilingual-MiniLM-L12-v2"
                )
    return _client, _ef

def _get_collection(name: str):
    client, ef = _get_client()
    return client.get_or_create_collection(name=name, embedding_function=ef)


# ════════════════════════════════════════════════════════════════
# 第一层：预测追踪记忆
# 记录每次分析的结论 + 时间 + 价格，下次对比追踪
# ════════════════════════════════════════════════════════════════

def save_prediction(
    stock_name:   str,
    industry:     str,
    advice:       str,
    rating:       str,
    risk_level:   str,
    final_report: str,
    price_info:   str = "",
    trade_date:   str = None,
) -> str:
    col = _get_collection("predictions")
    now = datetime.now()
    date_str = trade_date or now.strftime("%Y-%m-%d")
    # 同股同"数据实际交易日"只保留最新一次（upsert），防止多次分析污染复盘
    doc_id = f"{stock_name}_{date_str.replace('-', '')}"

    meta = {
        "stock_name": stock_name,
        "industry":   industry,
        "advice":     advice,
        "rating":     rating,
        "risk_level": risk_level,
        "price_info": price_info,
        "date":       date_str,
        "timestamp":  now.isoformat(),
    }
    embed_text = f"{stock_name} {industry} 建议:{advice} 评级:{rating} 风险:{risk_level} {final_report[:500]}"
    col.upsert(documents=[embed_text], metadatas=[meta], ids=[doc_id])
    logger.info("预测记录已保存（upsert）：%s", doc_id)
    return doc_id


def get_prediction_history(stock_name: str, top_k: int = 3) -> list:
    col = _get_collection("predictions")
    try:
        count = col.count()
        if count == 0:
            return []
        results = col.query(
            query_texts=[stock_name],
            n_results=min(top_k, count),
            where={"stock_name": stock_name},
        )
        if not results["ids"][0]:
            return []
        records = list(results["metadatas"][0])
        records.sort(key=lambda x: x["timestamp"], reverse=True)
        return records
    except Exception as e:
        print(f"[Memory] 查询历史失败：{e}")
        return []


def format_prediction_history(records: list) -> str:
    if not records:
        return ""
    lines = ["## 📚 历史分析记录（供参考对比）\n"]
    for i, r in enumerate(records):
        lines.append(f"**第{i+1}次分析** · {r['date']}")
        lines.append(f"- 操作建议：{r['advice']}  评级：{r['rating']}  风险：{r['risk_level']}")
        if r.get("price_info"):
            lines.append(f"- 当时价格：{r['price_info']}")
        lines.append("")
    return "\n".join(lines)


# ════════════════════════════════════════════════════════════════
# 第二层：板块轮动记忆
# 记录每次板块强度评分，形成时间序列，识别板块轮动趋势
# ════════════════════════════════════════════════════════════════

def save_sector_score(
    industry:       str,
    strength_score: float,
    up_ratio:       float,
    fund_trend:     str,
    avg_pct:        float,
    trade_date:     str = None,
) -> None:
    col = _get_collection("sector_scores")
    now = datetime.now()
    date_str = trade_date or now.strftime("%Y-%m-%d")
    doc_id = f"{industry}_{date_str.replace('-', '')}"
    meta = {
        "industry":       industry,
        "strength_score": strength_score,
        "up_ratio":       up_ratio,
        "fund_trend":     fund_trend,
        "avg_pct":        avg_pct,
        "date":           date_str,
        "timestamp":      now.isoformat(),
    }
    embed_text = f"{industry} 强度:{strength_score} 上涨:{up_ratio}% 资金:{fund_trend}"
    col.upsert(documents=[embed_text], metadatas=[meta], ids=[doc_id])
    logger.info("板块评分已保存（upsert）：%s %.1f分", industry, strength_score)


def get_sector_trend(industry: str, top_k: int = 5) -> list:
    col = _get_collection("sector_scores")
    try:
        count = col.count()
        if count == 0:
            return []
        results = col.query(
            query_texts=[industry],
            n_results=min(top_k, count),
            where={"industry": industry},
        )
        if not results["ids"][0]:
            return []
        records = list(results["metadatas"][0])
        records.sort(key=lambda x: x["timestamp"])
        return records
    except Exception as e:
        print(f"[Memory] 查询板块趋势失败：{e}")
        return []


def format_sector_trend(industry: str, records: list) -> str:
    if not records:
        return ""
    lines = [f"## 📈 板块历史强度趋势\n"]
    scores = [r["strength_score"] for r in records]
    if len(scores) >= 2:
        trend = "↑持续上升" if scores[-1] > scores[0] else "↓持续下降" if scores[-1] < scores[0] else "→区间震荡"
        lines.append(f"**趋势：{trend}**（{scores[0]}分 → {scores[-1]}分，共{len(records)}次记录）\n")
    for r in records:
        lines.append(
            f"- {r['date']}：强度 **{r['strength_score']}分** | "
            f"上涨比例 {r['up_ratio']:.0f}% | 资金{r['fund_trend']} | 均涨{r['avg_pct']:.2f}%"
        )
    return "\n".join(lines)


# ════════════════════════════════════════════════════════════════
# 第三层：风控历史记忆
# 记录每次风险信号，Risk Manager 参考历史风险模式
# ════════════════════════════════════════════════════════════════

def save_risk_record(
    stock_name:   str,
    risk_level:   str,
    risk_signals: list,
    conclusion:   str,
    trade_date:   str = None,
) -> None:
    col = _get_collection("risk_records")
    now = datetime.now()
    date_str = trade_date or now.strftime("%Y-%m-%d")
    doc_id = f"{stock_name}_risk_{date_str.replace('-', '')}"
    meta = {
        "stock_name":   stock_name,
        "risk_level":   risk_level,
        "risk_signals": json.dumps(risk_signals, ensure_ascii=False),
        "conclusion":   conclusion,
        "date":         date_str,
        "timestamp":    now.isoformat(),
    }
    embed_text = f"{stock_name} 风险:{risk_level} 信号:{','.join(risk_signals)} 结论:{conclusion}"
    col.upsert(documents=[embed_text], metadatas=[meta], ids=[doc_id])
    logger.info("风控记录已保存（upsert）：%s %s", stock_name, risk_level)


def get_risk_history(stock_name: str, top_k: int = 3) -> list:
    col = _get_collection("risk_records")
    try:
        count = col.count()
        if count == 0:
            return []
        results = col.query(
            query_texts=[stock_name],
            n_results=min(top_k, count),
            where={"stock_name": stock_name},
        )
        if not results["ids"][0]:
            return []
        records = list(results["metadatas"][0])
        records.sort(key=lambda x: x["timestamp"], reverse=True)
        return records
    except Exception as e:
        print(f"[Memory] 查询风控历史失败：{e}")
        return []


def format_risk_history(records: list) -> str:
    if not records:
        return ""
    lines = ["## ⚠️ 历史风控记录\n"]
    high_count = sum(1 for r in records if r["risk_level"] in ["高", "极高"])
    if high_count > 0:
        lines.append(f"**注意：该股票历史上有 {high_count} 次高风险标记**\n")
    for r in records:
        signals = json.loads(r.get("risk_signals", "[]"))
        lines.append(f"- {r['date']}：风险 **{r['risk_level']}** | {r['conclusion']}")
        if signals:
            lines.append(f"  触发：{', '.join(signals)}")
    return "\n".join(lines)


# ════════════════════════════════════════════════════════════════
# 统一入口
# ════════════════════════════════════════════════════════════════

def save_all_memory(
    stock_name:    str,
    industry:      str,
    real_industry: str,
    final_report:  str,
    risk_report:   str,
    sector_report: str,
    trade_date:    str = None,
) -> None:
    """分析完成后，提取关键信息存入三层记忆。

    trade_date：本次数据实际对应的交易日（来自 data_refresh 阶段的 resolve_real_trade_date），
    而非系统运行时刻——避免 baostock 数据滞后时记忆被错误地记到"今天"。
    缺省时（如 CLI 模式未接入数据管道）回退到当前系统日期。
    """
    from memory.extraction import extract_structured_fields
    fields = extract_structured_fields(final_report, risk_report, sector_report)
    advice, rating, risk_level, price_info = (
        fields["advice"], fields["rating"], fields["risk_level"], fields["price_info"]
    )

    # 第一层
    save_prediction(stock_name, real_industry or industry, advice, rating, risk_level, final_report, price_info, trade_date)

    # 第二层
    sector_metrics = fields["sector_metrics"]
    if sector_metrics and (real_industry or industry):
        save_sector_score(
            real_industry or industry, sector_metrics["score"],
            sector_metrics["up_ratio"], sector_metrics["fund_trend"], sector_metrics["avg_pct"], trade_date,
        )

    # 第三层：从风控表格里提取触发⚠️的风险项名称
    # 匹配格式：| 换手率风险 | 警示 ⚠️ | 具体数值 |
    risk_signals   = re.findall(r'\|\s*([^|]+?)\s*\|\s*[^|]*⚠️[^|]*\|', risk_report)
    risk_conclusion = ''
    m = re.search(r'风控结论[^\n]*\n([^\n]+)', risk_report)
    if m:
        risk_conclusion = m.group(1).strip()
    save_risk_record(stock_name, risk_level, risk_signals[:5], risk_conclusion or risk_level, trade_date)

    print(f"[Memory] ✓ 三层记忆全部保存完成")


def load_all_memory(stock_name: str, industry: str) -> dict:
    """分析开始前加载历史记忆"""
    pred_records    = get_prediction_history(stock_name)
    sector_records  = get_sector_trend(industry)
    risk_records    = get_risk_history(stock_name)
    lessons         = load_agent_lessons(stock_name, industry)
    return {
        "has_history":       len(pred_records) > 0,
        "prediction_text":   format_prediction_history(pred_records),
        "sector_trend_text": format_sector_trend(industry, sector_records),
        "risk_history_text": format_risk_history(risk_records),
        "agent_lessons":     lessons,
        "pred_count":        len(pred_records),
        "last_advice":       pred_records[0]["advice"] if pred_records else "",
        "last_date":         pred_records[0]["date"]   if pred_records else "",
    }


# ════════════════════════════════════════════════════════════════
# 第四层：Agent 行为教训（复盘闭环的关键）
# Reflection 输出的行为修正建议存入此层，
# 下次分析时自动加载到对应 agent 的 prompt 中。
# ════════════════════════════════════════════════════════════════

def save_agent_lessons(
    stock_name: str,
    industry: str,
    lessons: dict[str, str],
    trade_date: str = None,
) -> None:
    """保存复盘产生的各 agent 行为修正建议。

    lessons 格式: {"technical": "降低短期均线权重", "news": "增加政策搜索", ...}
    """
    col = _get_collection("agent_lessons")
    now = datetime.now()
    date_str = trade_date or now.strftime("%Y-%m-%d")

    for agent_name, lesson_text in lessons.items():
        if not lesson_text:
            continue
        doc_id = f"{stock_name}_{agent_name}_{date_str.replace('-', '')}"
        meta = {
            "stock_name": stock_name,
            "industry": industry,
            "agent_name": agent_name,
            "date": date_str,
            "timestamp": now.isoformat(),
        }
        col.upsert(documents=[lesson_text], metadatas=[meta], ids=[doc_id])

    logger.info("Agent 教训已保存：%s, %d 条", stock_name, len(lessons))


def load_agent_lessons(stock_name: str, industry: str) -> dict[str, str]:
    """加载与当前股票/行业相关的 agent 行为教训。

    返回 {"technical": "...", "news": "...", "sector": "...", ...}
    优先匹配同股票的教训，其次匹配同行业的教训。
    """
    col = _get_collection("agent_lessons")
    try:
        count = col.count()
        if count == 0:
            return {}

        lessons: dict[str, list[str]] = {}

        # 先查同股票的教训
        results = col.query(
            query_texts=[stock_name],
            n_results=min(10, count),
            where={"stock_name": stock_name},
        )
        if results["ids"][0]:
            for doc, meta in zip(results["documents"][0], results["metadatas"][0]):
                agent = meta["agent_name"]
                if agent not in lessons:
                    lessons[agent] = []
                lessons[agent].append(f"[{meta['date']}] {doc}")

        # 再查同行业的教训（补充，不覆盖）
        if industry:
            results = col.query(
                query_texts=[industry],
                n_results=min(5, count),
                where={"industry": industry},
            )
            if results["ids"][0]:
                for doc, meta in zip(results["documents"][0], results["metadatas"][0]):
                    agent = meta["agent_name"]
                    if agent not in lessons:
                        lessons[agent] = []
                    lessons[agent].append(f"[{meta['date']}·同行业] {doc}")

        # 每个 agent 只保留最近 3 条教训
        return {agent: "\n".join(texts[-3:]) for agent, texts in lessons.items()}

    except Exception as e:
        logger.error("加载 agent 教训失败：%s", e)
        return {}


def update_prediction_outcome(
    stock_name: str,
    last_date: str,
    was_correct: bool,
    price_change_pct: float,
) -> None:
    """复盘后将实际结果回写到对应预测记录。"""
    col = _get_collection("predictions")
    doc_id = f"{stock_name}_{last_date.replace('-', '')}"
    try:
        existing = col.get(ids=[doc_id])
        if not existing["ids"]:
            logger.warning("update_prediction_outcome：找不到记录 %s", doc_id)
            return
        meta = existing["metadatas"][0]
        meta["outcome_correct"] = str(was_correct)
        meta["price_change_pct"] = round(price_change_pct, 2)
        col.update(ids=[doc_id], metadatas=[meta])
        logger.info("预测结果已回写：%s was_correct=%s chg=%.2f%%", doc_id, was_correct, price_change_pct)
    except Exception as e:
        logger.error("回写预测结果失败：%s", e)


if __name__ == "__main__":
    print("=== Memory System 测试 ===\n")
    save_prediction("有研新材","C32有色金属冶炼和压延加工业","观望","⭐⭐⭐","高","测试报告","收盘价约18.2元")
    save_sector_score("C32有色金属冶炼和压延加工业", 75.0, 62.0, "资金持续流入", 1.8)
    save_risk_record("有研新材","高",["追高风险","换手率过热"],"建议回避")
    print()
    mem = load_all_memory("有研新材","C32有色金属冶炼和压延加工业")
    print(f"有历史记录：{mem['has_history']}")
    print(f"上次建议：{mem['last_advice']} ({mem['last_date']})")
    print(mem["prediction_text"])
    print(mem["sector_trend_text"])
    print(mem["risk_history_text"])