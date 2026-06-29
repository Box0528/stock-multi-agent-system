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
def get_stock_trend(stock_code: str, days: int = 20) -> str:
    """获取单只股票最近N天的价格和成交量趋势序列。
    用于判断趋势方向、量价关系、均线收敛/发散等。"""
    normalized = _normalize_stock_code(stock_code)
    file_path = os.path.join(DATA_DIR, f"{normalized}.csv")
    if not os.path.exists(file_path):
        return f"找不到股票 {stock_code} 的本地数据。"

    df = pd.read_csv(file_path)
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)
    df = calc_indicators(df)

    recent = df.tail(days)
    if recent.empty:
        return "数据不足"

    lines = [f"股票 {stock_code} 最近 {len(recent)} 个交易日趋势：\n"]
    lines.append("日期 | 收盘价 | 涨跌幅% | 换手率% | 成交额(亿) | MA5 | MA10 | MA20")
    lines.append("---|---|---|---|---|---|---|---")

    for _, row in recent.iterrows():
        amount_yi = row.get("amount", 0) / 1e8
        ma5 = f"{row['ma5']:.2f}" if pd.notna(row.get('ma5')) else "-"
        ma10 = f"{row['ma10']:.2f}" if pd.notna(row.get('ma10')) else "-"
        ma20 = f"{row['ma20']:.2f}" if pd.notna(row.get('ma20')) else "-"
        lines.append(
            f"{row['date'].strftime('%m-%d')} | {row['close']:.2f} | "
            f"{row.get('pctChg', 0):.2f} | {row.get('turn', 0):.2f} | "
            f"{amount_yi:.2f} | {ma5} | {ma10} | {ma20}"
        )

    # 趋势摘要
    first_close = recent.iloc[0]["close"]
    last_close = recent.iloc[-1]["close"]
    total_chg = (last_close - first_close) / first_close * 100
    avg_turn = recent["turn"].mean()
    vol_trend = recent["amount"].tail(5).mean() / recent["amount"].head(5).mean() if len(recent) >= 10 else 1.0

    lines.append(f"\n--- 趋势摘要 ---")
    lines.append(f"区间涨跌：{total_chg:+.2f}%（{first_close:.2f} → {last_close:.2f}）")
    lines.append(f"平均换手率：{avg_turn:.2f}%")
    lines.append(f"成交量趋势：近5日均量 / 前5日均量 = {vol_trend:.2f}x（{'放量' if vol_trend > 1.2 else '缩量' if vol_trend < 0.8 else '平稳'}）")

    # 均线趋势
    if pd.notna(recent.iloc[-1].get("ma5")) and pd.notna(recent.iloc[-1].get("ma20")):
        ma5_last = recent.iloc[-1]["ma5"]
        ma10_last = recent.iloc[-1]["ma10"]
        ma20_last = recent.iloc[-1]["ma20"]
        if ma5_last > ma10_last > ma20_last:
            lines.append("均线状态：多头排列 ✓（MA5 > MA10 > MA20）")
        elif ma5_last < ma10_last < ma20_last:
            lines.append("均线状态：空头排列 ✗（MA5 < MA10 < MA20）")
        else:
            # 检查收敛/发散
            spread = abs(ma5_last - ma20_last) / ma20_last * 100
            lines.append(f"均线状态：交叉整理中，MA5-MA20 价差 {spread:.2f}%（{'发散' if spread > 3 else '收敛'}）")

    return "\n".join(lines)


@tool
def get_volume_analysis(stock_code: str) -> str:
    """分析单只股票的量价关系和资金动向。
    返回连续放量/缩量天数、量价配合度、异常成交检测。"""
    normalized = _normalize_stock_code(stock_code)
    file_path = os.path.join(DATA_DIR, f"{normalized}.csv")
    if not os.path.exists(file_path):
        return f"找不到股票 {stock_code} 的本地数据。"

    df = pd.read_csv(file_path)
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)

    if len(df) < 10:
        return "数据不足（需要至少10天数据）"

    recent = df.tail(20).copy()
    recent["vol_ma5"] = recent["amount"].rolling(5).mean()
    recent["vol_ratio"] = recent["amount"] / recent["vol_ma5"]

    # 连续放量/缩量天数
    last_5 = recent.tail(5)
    vol_up_days = 0
    vol_down_days = 0
    for _, row in last_5.iloc[::-1].iterrows():
        ratio = row.get("vol_ratio", 1.0)
        if pd.isna(ratio):
            break
        if ratio > 1.1:
            vol_up_days += 1
        elif ratio < 0.9:
            vol_down_days += 1
        else:
            break

    # 量价配合度
    last_row = recent.iloc[-1]
    pct = last_row.get("pctChg", 0)
    vol_ratio = last_row.get("vol_ratio", 1.0)

    if pct > 0 and vol_ratio > 1.2:
        vp_match = "放量上涨（健康，资金进场）"
    elif pct > 0 and vol_ratio < 0.8:
        vp_match = "缩量上涨（警惕，上涨动力不足）"
    elif pct < 0 and vol_ratio > 1.2:
        vp_match = "放量下跌（危险，资金出逃）"
    elif pct < 0 and vol_ratio < 0.8:
        vp_match = "缩量下跌（正常调整，抛压减弱）"
    else:
        vp_match = "量价平稳"

    # 异常成交检测
    avg_amount_20 = recent["amount"].mean()
    today_amount = last_row["amount"]
    anomaly = ""
    if today_amount > avg_amount_20 * 2.5:
        anomaly = "⚠️ 今日成交额为20日均值的 {:.1f} 倍，异常放量".format(today_amount / avg_amount_20)
    elif today_amount < avg_amount_20 * 0.3:
        anomaly = "⚠️ 今日成交额仅为20日均值的 {:.1f} 倍，异常缩量".format(today_amount / avg_amount_20)

    lines = [
        f"量价分析 · {stock_code}",
        f"",
        f"今日量价关系：{vp_match}",
        f"今日成交额：{today_amount/1e8:.2f}亿（vs 5日均量 {recent['vol_ma5'].iloc[-1]/1e8:.2f}亿）",
        f"量比：{vol_ratio:.2f}",
        f"连续放量天数：{vol_up_days}" if vol_up_days > 0 else f"连续缩量天数：{vol_down_days}" if vol_down_days > 0 else "成交量无明显趋势",
    ]
    if anomaly:
        lines.append(anomaly)

    return "\n".join(lines)


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
                "data_date": latest["date"].strftime("%Y-%m-%d") if pd.notna(latest.get("date")) else "",
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

    # 数据日期标注
    dates = [r.get("data_date", "") for r in results if r.get("data_date")]
    if dates:
        latest_date = max(dates)
        oldest_date = min(dates)
        date_note = f"数据日期：{latest_date}" if latest_date == oldest_date else f"数据日期：{oldest_date} ~ {latest_date}"
    else:
        date_note = "数据日期：未知"

    output_lines = [
        f"=== 板块分析：{industry_name} ===",
        f"⏰ {date_note}\n",
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