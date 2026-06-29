import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import re
import json
import chromadb
from datetime import datetime
from chromadb.utils import embedding_functions

# ── 初始化 ChromaDB ───────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH  = os.path.join(BASE_DIR, "memory", "chroma_db")

_client = None
_ef     = None

def _get_client():
    global _client, _ef
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
) -> str:
    col = _get_collection("predictions")
    now = datetime.now()
    doc_id = f"{stock_name}_{now.strftime('%Y%m%d_%H%M%S')}"

    meta = {
        "stock_name": stock_name,
        "industry":   industry,
        "advice":     advice,
        "rating":     rating,
        "risk_level": risk_level,
        "price_info": price_info,
        "date":       now.strftime("%Y-%m-%d"),
        "timestamp":  now.isoformat(),
    }
    embed_text = f"{stock_name} {industry} 建议:{advice} 评级:{rating} 风险:{risk_level} {final_report[:500]}"
    col.add(documents=[embed_text], metadatas=[meta], ids=[doc_id])
    print(f"[Memory] 预测记录已保存：{doc_id}")
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
) -> None:
    col = _get_collection("sector_scores")
    now = datetime.now()
    doc_id = f"{industry}_{now.strftime('%Y%m%d_%H%M%S')}"
    meta = {
        "industry":       industry,
        "strength_score": strength_score,
        "up_ratio":       up_ratio,
        "fund_trend":     fund_trend,
        "avg_pct":        avg_pct,
        "date":           now.strftime("%Y-%m-%d"),
        "timestamp":      now.isoformat(),
    }
    embed_text = f"{industry} 强度:{strength_score} 上涨:{up_ratio}% 资金:{fund_trend}"
    col.add(documents=[embed_text], metadatas=[meta], ids=[doc_id])
    print(f"[Memory] 板块评分已保存：{industry} {strength_score}分")


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
) -> None:
    col = _get_collection("risk_records")
    now = datetime.now()
    doc_id = f"{stock_name}_risk_{now.strftime('%Y%m%d_%H%M%S')}"
    meta = {
        "stock_name":   stock_name,
        "risk_level":   risk_level,
        "risk_signals": json.dumps(risk_signals, ensure_ascii=False),
        "conclusion":   conclusion,
        "date":         now.strftime("%Y-%m-%d"),
        "timestamp":    now.isoformat(),
    }
    embed_text = f"{stock_name} 风险:{risk_level} 信号:{','.join(risk_signals)} 结论:{conclusion}"
    col.add(documents=[embed_text], metadatas=[meta], ids=[doc_id])
    print(f"[Memory] 风控记录已保存：{stock_name} {risk_level}")


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
) -> None:
    """分析完成后，提取关键信息存入三层记忆"""
    combined = final_report + risk_report + sector_report

    advice     = (re.search(r'操作建议[：:]\s*(买入|观望|回避)', final_report) or [None,''])[1] or '未知'
    rating     = (re.search(r'综合评级[：:]\s*(⭐+)',             final_report) or [None,''])[1] or ''
    risk_level = (re.search(r'风险等级[：:][^低中高\n]*([低中高极]+)',risk_report) or [None,''])[1] or '未知'
    price_match = re.search(r'收盘价[：:]\s*([\d.]+)', combined)
    price_info  = f"收盘价约 {price_match.group(1)} 元" if price_match else ""

    # 第一层
    save_prediction(stock_name, real_industry or industry, advice, rating, risk_level, final_report, price_info)

    # 第二层
    score_match = re.search(r'板块强度评分[：:]\s*([\d.]+)', sector_report)
    if score_match and (real_industry or industry):
        up_m    = re.search(r'上涨[：:]?\s*(\d+)\s*只', sector_report)
        tot_m   = re.search(r'股票总数[：:]\s*(\d+)', sector_report)
        avg_m   = re.search(r'平均涨幅[：:]\s*([-\d.]+)', sector_report)
        fund_m  = re.search(r'资金(持续流入|平稳|开始撤退)', sector_report)
        up_ratio   = (int(up_m.group(1)) / int(tot_m.group(1)) * 100) if up_m and tot_m else 0.0
        avg_pct    = float(avg_m.group(1)) if avg_m else 0.0
        fund_trend = fund_m.group(1) if fund_m else "平稳"
        save_sector_score(real_industry or industry, float(score_match.group(1)), up_ratio, fund_trend, avg_pct)

    # 第三层
    risk_signals   = re.findall(r'⚠️警告[^\|]*\|[^\|]*\|([^\n|]+)', risk_report)
    risk_conclusion = ''
    m = re.search(r'风控结论[^\n]*\n([^\n]+)', risk_report)
    if m:
        risk_conclusion = m.group(1).strip()
    save_risk_record(stock_name, risk_level, risk_signals[:5], risk_conclusion or risk_level)

    print(f"[Memory] ✓ 三层记忆全部保存完成")


def load_all_memory(stock_name: str, industry: str) -> dict:
    """分析开始前加载历史记忆"""
    pred_records    = get_prediction_history(stock_name)
    sector_records  = get_sector_trend(industry)
    risk_records    = get_risk_history(stock_name)
    return {
        "has_history":       len(pred_records) > 0,
        "prediction_text":   format_prediction_history(pred_records),
        "sector_trend_text": format_sector_trend(industry, sector_records),
        "risk_history_text": format_risk_history(risk_records),
        "pred_count":        len(pred_records),
        "last_advice":       pred_records[0]["advice"] if pred_records else "",
        "last_date":         pred_records[0]["date"]   if pred_records else "",
    }


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