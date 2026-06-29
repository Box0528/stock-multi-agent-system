import os
import pandas as pd
import numpy as np
from langchain_core.tools import tool

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "local_stock_data")
META_FILE = os.path.join(BASE_DIR, "meta", "stock_meta.csv")

def calc_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["ma5"] = df["close"].rolling(5).mean()
    df["ma10"] = df["close"].rolling(10).mean()
    df["ma20"] = df["close"].rolling(20).mean()
    return df

def pick_stock(row: pd.Series) -> bool:
    ma5 = row.get("ma5", np.nan)
    ma10 = row.get("ma10", np.nan)
    ma20 = row.get("ma20", np.nan)
    close = row.get("close", np.nan)
    turn = row.get("turn", np.nan)
    amount_yi = row.get("amount_yi", np.nan)
    pct = row.get("pctChg", np.nan)
    is_st = str(row.get("isST", "0"))

    if pd.isna(ma5) or pd.isna(ma10) or pd.isna(ma20):
        return False
    if not (ma5 > ma10 > ma20):
        return False
    if close <= ma5:
        return False
    if pd.isna(turn) or not (5.0 <= turn <= 15.0):
        return False
    if pd.isna(amount_yi) or amount_yi < 3.0:
        return False
    if pd.isna(pct) or pct <= 0:
        return False
    if is_st == "1":
        return False
    return True

@tool
def run_stock_screener(top_n_industries: int = 10) -> str:
    """
    运行量化选股模型，返回符合条件的股票池。
    筛选条件：均线多头排列、换手率5-15%、成交额>3亿、当日涨幅为正、非ST。
    """
    if not os.path.exists(META_FILE):
        return "错误：找不到stock_meta.csv，请先运行数据下载脚本。"

    meta_df = pd.read_csv(META_FILE)
    results = []

    for _, row in meta_df.iterrows():
        code = row["code"]
        name = row["name"]
        industry = row.get("industry_name", "未知行业")

        file_path = os.path.join(DATA_DIR, f"{code.replace('.', '_')}.csv")
        if not os.path.exists(file_path):
            continue

        try:
            df = pd.read_csv(file_path)
            if df.empty or len(df) < 20 or "date" not in df.columns:
                continue

            df["date"] = pd.to_datetime(df["date"], errors="coerce")
            df = df.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)
            df = calc_indicators(df)
            latest = df.iloc[-1]

            amount_raw = latest.get("amount", np.nan)
            amount_yi = amount_raw / 1e8 if not pd.isna(amount_raw) else np.nan

            candidate = pd.Series({
                "code": code, "name": name, "industry_name": industry,
                "close": latest.get("close", np.nan),
                "pctChg": latest.get("pctChg", np.nan),
                "turn": latest.get("turn", np.nan),
                "amount_yi": amount_yi,
                "ma5": latest.get("ma5", np.nan),
                "ma10": latest.get("ma10", np.nan),
                "ma20": latest.get("ma20", np.nan),
                "isST": str(latest.get("isST", "0")),
            })

            if pick_stock(candidate):
                results.append(candidate.to_dict())
        except Exception:
            continue

    if not results:
        return "今日没有符合条件的股票。"

    result_df = pd.DataFrame(results)

    # 行业强度排名
    industry_rank = (
        result_df.groupby("industry_name")
        .agg(avg_pct=("pctChg", "mean"), count=("code", "count"))
        .sort_values(["avg_pct", "count"], ascending=[False, False])
        .head(top_n_industries)
        .reset_index()
    )
    top_industries = industry_rank["industry_name"].tolist()
    final_df = result_df[result_df["industry_name"].isin(top_industries)].copy()

    # 格式化输出给LLM
    output_lines = [f"共筛选出 {len(final_df)} 只股票，覆盖 {len(top_industries)} 个强势行业：\n"]

    for industry in top_industries:
        row = industry_rank[industry_rank["industry_name"] == industry].iloc[0]
        output_lines.append(f"【{industry}】平均涨幅 {row['avg_pct']:.2f}%，入选 {int(row['count'])} 只")
        stocks = final_df[final_df["industry_name"] == industry]
        for _, s in stocks.iterrows():
            output_lines.append(
                f"  {s['name']}({s['code']}) 涨幅{s['pctChg']:.2f}% "
                f"换手{s['turn']:.2f}% 成交{s['amount_yi']:.2f}亿"
            )
        output_lines.append("")

    return "\n".join(output_lines)

def _normalize_stock_code(raw_code: str) -> str:
    """将各种格式的股票代码统一映射到本地文件名（如 sh_600226）。
    支持：600226.SH / sh.600226 / 600226 / SH600226 等。"""
    code = raw_code.strip().upper()
    # 去掉所有点号
    code = code.replace(".", "")
    # 提取6位数字
    digits = "".join(c for c in code if c.isdigit())
    if len(digits) < 6:
        return raw_code.replace(".", "_")
    digits = digits[-6:]
    # 判断市场前缀
    prefix = "sh" if digits[0] in ("6", "9") else "sz"
    return f"{prefix}_{digits}"


@tool
def get_stock_detail(stock_code: str) -> str:
    """
    获取单只股票的详细技术指标数据。
    输入股票代码，如 '600519' 或 '600519.SH' 或 'sh.600519'
    """
    normalized = _normalize_stock_code(stock_code)
    file_path = os.path.join(DATA_DIR, f"{normalized}.csv")
    if not os.path.exists(file_path):
        return f"找不到股票 {stock_code} 的本地数据（尝试文件：{normalized}.csv）。"

    df = pd.read_csv(file_path)
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)
    df = calc_indicators(df)
    latest = df.iloc[-1]

    return (
        f"股票代码：{stock_code}\n"
        f"日期：{latest['date'].strftime('%Y-%m-%d')}\n"
        f"收盘价：{latest['close']:.2f}\n"
        f"涨跌幅：{latest['pctChg']:.2f}%\n"
        f"换手率：{latest['turn']:.2f}%\n"
        f"MA5：{latest['ma5']:.2f}  MA10：{latest['ma10']:.2f}  MA20：{latest['ma20']:.2f}\n"
        f"均线状态：{'多头排列 ✓' if latest['ma5'] > latest['ma10'] > latest['ma20'] else '非多头排列'}"
    )
@tool
def analyze_sector(industry_name: str, top_n: int = 5) -> str:
    """
    分析指定行业板块的整体强弱、资金流向和成交额趋势。
    输入行业名称（如"计算机、通信和其他电子设备制造业"），返回板块统计分析。
    """
    if not os.path.exists(META_FILE):
        return "错误：找不到stock_meta.csv，请先运行数据下载脚本。"

    meta_df = pd.read_csv(META_FILE)
    sector_stocks = meta_df[meta_df["industry_name"] == industry_name]

    if sector_stocks.empty:
        return f"未找到行业'{industry_name}'的股票数据。"

    results = []

    for _, row in sector_stocks.iterrows():
        code = row["code"]
        name = row["name"]
        file_path = os.path.join(DATA_DIR, f"{code.replace('.', '_')}.csv")

        if not os.path.exists(file_path):
            continue

        try:
            df = pd.read_csv(file_path)
            if df.empty or len(df) < 10 or "date" not in df.columns:
                continue

            df["date"] = pd.to_datetime(df["date"], errors="coerce")
            df = df.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)
            df = calc_indicators(df)

            latest = df.iloc[-1]
            prev5 = df.tail(6).head(5)  # 近5日数据

            amount_raw = latest.get("amount", np.nan)
            amount_yi = amount_raw / 1e8 if not pd.isna(amount_raw) else np.nan

            # 近5日平均成交额
            prev5_amount = prev5["amount"].apply(lambda x: x / 1e8 if not pd.isna(x) else np.nan).mean()

            # 成交额变化趋势
            amount_trend = "放量" if (not pd.isna(amount_yi) and not pd.isna(prev5_amount)
                                      and amount_yi > prev5_amount * 1.2) else \
                           "缩量" if (not pd.isna(amount_yi) and not pd.isna(prev5_amount)
                                      and amount_yi < prev5_amount * 0.8) else "平稳"

            results.append({
                "code": code,
                "name": name,
                "close": latest.get("close", np.nan),
                "pctChg": latest.get("pctChg", np.nan),
                "turn": latest.get("turn", np.nan),
                "amount_yi": amount_yi,
                "prev5_amount_yi": round(prev5_amount, 2) if not pd.isna(prev5_amount) else np.nan,
                "amount_trend": amount_trend,
                "ma5": latest.get("ma5", np.nan),
                "ma10": latest.get("ma10", np.nan),
                "ma20": latest.get("ma20", np.nan),
                "ma_status": "多头" if (not pd.isna(latest.get("ma5")) and
                                        not pd.isna(latest.get("ma10")) and
                                        not pd.isna(latest.get("ma20")) and
                                        latest["ma5"] > latest["ma10"] > latest["ma20"]) else "非多头",
            })
        except Exception:
            continue

    if not results:
        return f"行业'{industry_name}'暂无可分析的股票数据。"

    df_result = pd.DataFrame(results)

    # 板块统计
    total = len(df_result)
    up_count = len(df_result[df_result["pctChg"] > 0])
    down_count = len(df_result[df_result["pctChg"] < 0])
    avg_pct = df_result["pctChg"].mean()
    total_amount = df_result["amount_yi"].sum()
    prev5_total_amount = df_result["prev5_amount_yi"].mean()
    bullish_count = len(df_result[df_result["ma_status"] == "多头"])

    # 板块资金趋势
    sector_trend = "资金持续流入" if total_amount > prev5_total_amount * 1.2 else \
                   "资金开始撤退" if total_amount < prev5_total_amount * 0.8 else "资金平稳"

    # 强度评分（0-100）
    strength_score = 0
    strength_score += min(30, max(0, avg_pct * 3))           # 平均涨幅贡献
    strength_score += (up_count / total * 30) if total > 0 else 0  # 上涨比例贡献
    strength_score += (bullish_count / total * 20) if total > 0 else 0  # 均线多头比例
    strength_score += 20 if sector_trend == "资金持续流入" else \
                      0 if sector_trend == "资金开始撤退" else 10
    strength_score = round(min(100, max(0, strength_score)), 1)

    # 涨幅前N只
    top_stocks = df_result.nlargest(top_n, "pctChg")[
        ["name", "code", "pctChg", "turn", "amount_yi", "ma_status", "amount_trend"]
    ]

    output_lines = [
        f"=== 板块分析：{industry_name} ===\n",
        f"板块股票总数：{total} 只",
        f"今日上涨：{up_count} 只 | 下跌：{down_count} 只 | 平盘：{total - up_count - down_count} 只",
        f"板块平均涨幅：{avg_pct:.2f}%",
        f"板块今日总成交额：{total_amount:.2f} 亿",
        f"近5日平均成交额：{prev5_total_amount:.2f} 亿",
        f"资金流向：{sector_trend}",
        f"均线多头股票数：{bullish_count} 只（占比 {bullish_count/total*100:.1f}%）",
        f"板块强度评分：{strength_score} / 100\n",
        f"--- 涨幅前{top_n}只 ---",
    ]

    for _, s in top_stocks.iterrows():
        output_lines.append(
            f"  {s['name']}({s['code']}) "
            f"涨幅{s['pctChg']:.2f}% "
            f"换手{s['turn']:.2f}% "
            f"成交{s['amount_yi']:.2f}亿 "
            f"均线:{s['ma_status']} "
            f"量能:{s['amount_trend']}"
        )

    return "\n".join(output_lines)