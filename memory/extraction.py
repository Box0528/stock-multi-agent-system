"""从 agent 生成的 markdown 报告文本里提取结构化字段。

纯函数，不做任何 I/O —— 这样能在不连 ChromaDB、不调 LLM 的情况下单独测试。
正则都做了 `\\*{0,2}` 容错（允许标签被 markdown 加粗包裹），因为历史上 LLM
不严格遵守"标签不要加粗"的 prompt 指令导致过解析失败（操作建议显示空白的那次bug）。
"""

import re


def extract_advice(final_report: str) -> str:
    m = re.search(r'\*{0,2}操作建议\*{0,2}[：:]\s*(买入|观望|回避)', final_report)
    return m.group(1) if m else '未知'


def extract_rating(final_report: str) -> str:
    m = re.search(r'\*{0,2}综合评级\*{0,2}[：:]\s*(⭐+)', final_report)
    return m.group(1) if m else ''


def extract_risk_level(risk_report: str) -> str:
    """兼容两种格式：'风险等级：低 🟢'（文字在前，新规范）和 '风险等级：🟢低'（emoji在前，旧格式）。"""
    m = re.search(r'\*{0,2}风险等级\*{0,2}[：:][^低中高极\n]*([低中高极]+)', risk_report)
    return m.group(1) if m else '未知'


def extract_price_info(combined_text: str) -> str:
    # 按优先级依次尝试常见价格标签
    for pattern in [
        r'收盘价[：:]\s*([\d.]+)',
        r'最新价[：:]\s*([\d.]+)',
        r'当前价[：:]\s*([\d.]+)',
        r'现价\s*([\d.]+)',
        r'当前股价[：:]\s*([\d.]+)',
    ]:
        m = re.search(pattern, combined_text)
        if m:
            return f"收盘价约 {m.group(1)} 元"
    return ""


def extract_sector_metrics(sector_report: str) -> dict | None:
    """返回 None 表示报告里没有板块强度评分（不应该记录第二层记忆）。"""
    score_match = re.search(r'板块强度评分[：:]\s*([\d.]+)', sector_report)
    if not score_match:
        return None
    up_m = re.search(r'上涨[：:]?\s*(\d+)\s*只', sector_report)
    tot_m = re.search(r'股票总数[：:]\s*(\d+)', sector_report)
    avg_m = re.search(r'平均涨幅[：:]\s*([-\d.]+)', sector_report)
    fund_m = re.search(r'资金(持续流入|平稳|开始撤退)', sector_report)
    return {
        "score": float(score_match.group(1)),
        "up_ratio": (int(up_m.group(1)) / int(tot_m.group(1)) * 100) if up_m and tot_m else 0.0,
        "avg_pct": float(avg_m.group(1)) if avg_m else 0.0,
        "fund_trend": fund_m.group(1) if fund_m else "平稳",
    }


def extract_structured_fields(final_report: str, risk_report: str, sector_report: str) -> dict:
    combined = final_report + risk_report + sector_report
    return {
        "advice": extract_advice(final_report),
        "rating": extract_rating(final_report),
        "risk_level": extract_risk_level(risk_report),
        "price_info": extract_price_info(combined),
        "sector_metrics": extract_sector_metrics(sector_report),
    }
