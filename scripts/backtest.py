"""
历史回溯复盘脚本 — 用本地已有K线数据模拟过去某时间段的选股，立刻验证结果。

核心思路：
  选一个历史日期 T，把每只股票的 CSV 过滤到 date <= T，跑量化选股器，
  所有通过的股票方向 = bullish（选股器本身是多头动量过滤器），
  再从同一 CSV 读取 T+N 日的实际收盘价，计算涨跌幅，直接写入 review_results.json。

用法：
    python scripts/backtest.py --start-date 2025-05-01 --end-date 2025-06-20 --horizon 5
    python scripts/backtest.py --date 2025-06-01 --horizon 14
"""

import os
import sys
import argparse
import logging
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

from tools.stock_data import pick_stock, calc_indicators, META_FILE, DATA_DIR
from core.review import ReviewResult, append_results, load_results

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def _load_trading_dates(sample_csv: str) -> list[str]:
    """从一只股票的 CSV 提取所有已知交易日（排序后的日期字符串列表）。"""
    df = pd.read_csv(sample_csv)
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"]).sort_values("date")
    return [d.strftime("%Y-%m-%d") for d in df["date"]]


def _get_close_at_date(df: pd.DataFrame, target_date: str, tolerance_days: int = 5) -> tuple[float | None, str | None]:
    """
    从已排序的 DataFrame 里找 target_date 当天或之后最近一个交易日的收盘价。
    返回 (price, actual_date)，找不到返回 (None, None)。
    """
    target = pd.Timestamp(target_date)
    future = df[df["date"] >= target]
    if future.empty:
        return None, None
    row = future.iloc[0]
    actual_date = row["date"].strftime("%Y-%m-%d")
    # 如果顺延超过 tolerance_days 个日历日，认为数据不可用
    if (row["date"] - target).days > tolerance_days:
        return None, None
    return float(row["close"]), actual_date


def _nth_trading_date(all_dates: list[str], from_date: str, n: int) -> str | None:
    """
    从 all_dates（排序的交易日列表）里找 from_date 之后第 n 个交易日。
    返回日期字符串，不够则返回 None。
    """
    try:
        idx = all_dates.index(from_date)
    except ValueError:
        # from_date 不在交易日列表里（可能是非交易日），找最近的下一个
        idx = None
        for i, d in enumerate(all_dates):
            if d > from_date:
                idx = i
                break
        if idx is None:
            return None
    target_idx = idx + n
    if target_idx >= len(all_dates):
        return None
    return all_dates[target_idx]


def backtest_single_date(
    scan_date: str,
    horizon: int,
    all_trading_dates: list[str],
    meta_df: pd.DataFrame,
    top_n: int | None,
    existing_ids: set[str],
) -> list[ReviewResult]:
    """对 scan_date 跑一次历史选股，返回可直接写入的 ReviewResult 列表。"""
    review_date_target = _nth_trading_date(all_trading_dates, scan_date, horizon)
    if review_date_target is None:
        logger.debug("  %s 之后不足 %d 个交易日，跳过", scan_date, horizon)
        return []

    candidates = []
    for _, row in meta_df.iterrows():
        code = row["code"]
        name = row["name"]
        industry = row.get("industry_name", "未知行业")

        file_path = os.path.join(DATA_DIR, f"{code.replace('.', '_')}.csv")
        if not os.path.exists(file_path):
            continue

        try:
            df = pd.read_csv(file_path)
            if df.empty or "date" not in df.columns:
                continue

            df["date"] = pd.to_datetime(df["date"], errors="coerce")
            df = df.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)

            # 历史切片：只看 scan_date 当天及之前的数据
            scan_ts = pd.Timestamp(scan_date)
            df_hist = df[df["date"] <= scan_ts].reset_index(drop=True)

            if len(df_hist) < 20:
                continue

            df_hist = calc_indicators(df_hist)
            latest = df_hist.iloc[-1]

            # 确认最新一行确实是 scan_date 那天（容忍1个交易日偏差）
            if (scan_ts - latest["date"]).days > 3:
                continue

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

            if not pick_stock(candidate):
                continue

            price_at_scan = float(latest["close"]) if not pd.isna(latest.get("close")) else 0.0

            # 取 review_date 的实际收盘价（用全量数据，不做历史切片）
            price_at_review, actual_review_date = _get_close_at_date(df, review_date_target)
            if price_at_review is None or price_at_scan <= 0:
                continue

            return_pct = (price_at_review - price_at_scan) / price_at_scan * 100
            scan_id = f"{scan_date}_{code}_bt{horizon}d"

            if scan_id in existing_ids:
                continue

            candidates.append({
                "scan_id": scan_id,
                "code": code,
                "name": name,
                "industry": industry,
                "price_at_scan": price_at_scan,
                "price_at_review": price_at_review,
                "actual_review_date": actual_review_date,
                "return_pct": round(return_pct, 2),
                "pctChg": float(latest.get("pctChg", 0)),
            })

        except Exception as e:
            logger.debug("  %s %s 处理失败：%s", scan_date, code, e)
            continue

    if not candidates:
        return []

    # top_n 过滤（按当日涨幅降序，模拟"选最强的N只"）
    if top_n:
        candidates = sorted(candidates, key=lambda x: x["pctChg"], reverse=True)[:top_n]

    results = []
    for c in candidates:
        results.append(ReviewResult(
            scan_id=c["scan_id"],
            scan_date=scan_date,
            review_date=c["actual_review_date"],
            stock_code=c["code"],
            stock_name=c["name"],
            direction="bullish",
            price_at_scan=c["price_at_scan"],
            price_at_review=c["price_at_review"],
            return_pct=c["return_pct"],
            direction_correct=c["return_pct"] > 0,
            counted_in_stats=True,
        ))

    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="历史回溯复盘")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--date", help="单日回溯，格式 YYYY-MM-DD")
    group.add_argument("--start-date", help="起始日期")
    parser.add_argument("--end-date", help="结束日期（与 --start-date 配合）")
    parser.add_argument("--horizon", type=int, default=5, help="验证窗口（交易日数），默认5")
    parser.add_argument("--top-n", type=int, default=None, help="每日最多保留N只（按涨幅降序）")
    args = parser.parse_args()

    if args.date:
        start_date = end_date = args.date
    else:
        start_date = args.start_date
        end_date = args.end_date or args.start_date

    if not os.path.exists(META_FILE):
        logger.error("找不到 stock_meta.csv，请先运行 scripts/scheduled_refresh.py")
        return 1

    meta_df = pd.read_csv(META_FILE)
    logger.info("共加载 %d 只股票元数据", len(meta_df))

    # 从第一只有数据的股票提取交易日历
    all_trading_dates: list[str] = []
    for _, row in meta_df.iterrows():
        fp = os.path.join(DATA_DIR, f"{row['code'].replace('.', '_')}.csv")
        if os.path.exists(fp):
            all_trading_dates = _load_trading_dates(fp)
            break

    if not all_trading_dates:
        logger.error("无法加载交易日历，请确认 local_stock_data/ 目录有数据")
        return 1

    scan_dates = [d for d in all_trading_dates if start_date <= d <= end_date]
    if not scan_dates:
        logger.error("在 %s ~ %s 之间没有找到交易日，请检查日期范围和本地数据覆盖范围", start_date, end_date)
        return 1

    logger.info("将回溯 %d 个交易日（%s → %s），验证窗口 %d 个交易日",
                len(scan_dates), scan_dates[0], scan_dates[-1], args.horizon)

    existing_ids = {r["scan_id"] for r in load_results()}
    all_results: list[ReviewResult] = []

    for i, scan_date in enumerate(scan_dates):
        results = backtest_single_date(
            scan_date, args.horizon, all_trading_dates,
            meta_df, args.top_n, existing_ids,
        )
        all_results.extend(results)
        if results:
            logger.info("[%d/%d] %s → 选出 %d 只，已生成复盘记录",
                        i + 1, len(scan_dates), scan_date, len(results))
        else:
            logger.info("[%d/%d] %s → 无符合条件的股票", i + 1, len(scan_dates), scan_date)

    if all_results:
        append_results(all_results)
        counted = [r for r in all_results if r.counted_in_stats]
        correct = sum(1 for r in counted if r.direction_correct)
        logger.info("\n=== 回溯完成 ===")
        logger.info("共写入 %d 条复盘结果", len(all_results))
        if counted:
            logger.info("本批方向准确率：%d/%d = %.0f%%",
                        correct, len(counted), correct / len(counted) * 100)
    else:
        logger.info("本次回溯没有产生任何结果（可能日期范围内无选股信号，或 review_date 超出数据范围）")

    return 0


if __name__ == "__main__":
    sys.exit(main())
