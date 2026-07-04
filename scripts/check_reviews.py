"""
定时复盘脚本：检查到期的 pending_reviews，拉取实际价格，判断预测准确性。

运行方式：
  python scripts/check_reviews.py          # 检查今日到期的所有 pending
  python scripts/check_reviews.py --dry    # dry-run，只打印不写入

建议每个交易日收盘后（15:30+）运行一次，或通过 cron / Task Scheduler 定时触发。
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import argparse
import logging
from datetime import date, timedelta

import pandas as pd

from core.review import (
    PendingReview, ReviewResult,
    pop_due_pending, save_pending, append_results,
    direction_correct, load_pending,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data", "stocks")


# ── 交易日推算（跳过周末，不含法定节假日，精度满足演示需要）──────────
def _nth_trading_day_after(date_str: str, n: int) -> str:
    """返回 date_str 之后第 n 个交易日（工作日）的日期字符串。"""
    d = pd.Timestamp(date_str) + pd.Timedelta(days=1)
    bdays = pd.bdate_range(start=d, periods=n)
    return bdays[-1].strftime("%Y-%m-%d")


# ── 价格获取：先读本地 CSV，再 fallback 到 akshare ────────────────
def _get_price_on_date(stock_code: str, target_date: str) -> float | None:
    """
    获取 stock_code 在 target_date（或之后最近交易日）的收盘价。
    stock_code 格式：sh.600226 / sz.000001。
    """
    # 1. 本地 CSV
    try:
        fname = stock_code.replace(".", "_") + ".csv"
        fpath = os.path.join(DATA_DIR, fname)
        if os.path.exists(fpath):
            df = pd.read_csv(fpath, parse_dates=["date"])
            df = df.sort_values("date")
            # 取 target_date 当天或之后最近一行
            row = df[df["date"] >= pd.Timestamp(target_date)]
            if not row.empty:
                return float(row.iloc[0]["close"])
    except Exception as e:
        logger.debug("本地 CSV 读取失败 %s: %s", stock_code, e)

    # 2. akshare 历史行情
    try:
        import akshare as ak
        code_6 = stock_code.replace("sh.", "").replace("sz.", "").replace("bj.", "")
        end_date = (pd.Timestamp(target_date) + pd.Timedelta(days=7)).strftime("%Y%m%d")
        df = ak.stock_zh_a_hist(
            symbol=code_6,
            period="daily",
            start_date=target_date.replace("-", ""),
            end_date=end_date,
            adjust="",
        )
        if df is not None and not df.empty:
            col = "收盘" if "收盘" in df.columns else df.columns[-1]
            return float(df.iloc[0][col])
    except Exception as e:
        logger.warning("akshare 价格获取失败 %s: %s", stock_code, e)

    return None


# ── 核心检查逻辑 ──────────────────────────────────────────────────
def run_check(dry_run: bool = False, as_of: str | None = None) -> int:
    """检查今日到期的 pending reviews，返回处理条数。"""
    due, remaining = pop_due_pending(as_of=as_of)

    if not due:
        logger.info("今日无到期 pending reviews")
        return 0

    logger.info("共 %d 条到期记录需要检查", len(due))

    new_results: list[ReviewResult] = []
    still_pending: list[dict] = []   # 价格获取失败的，保留继续等

    for rec in due:
        code  = rec["stock_code"]
        name  = rec["stock_name"]
        rdate = rec["review_date"]

        price = _get_price_on_date(code, rdate)
        if price is None:
            logger.warning("价格获取失败，%s %s 保留 pending", name, rdate)
            still_pending.append(rec)
            continue

        price_at_scan = float(rec["price_at_scan"])
        if price_at_scan <= 0:
            logger.warning("%s 推荐价为0，跳过", name)
            continue

        ret_pct = (price - price_at_scan) / price_at_scan * 100
        from core.review import Direction
        direction: Direction = rec["direction"]
        is_correct, counted = direction_correct(direction, ret_pct)

        result = ReviewResult(
            scan_id          = rec["scan_id"],
            scan_date        = rec["scan_date"],
            review_date      = rdate,
            stock_code       = code,
            stock_name       = name,
            direction        = direction,
            price_at_scan    = price_at_scan,
            price_at_review  = price,
            return_pct       = round(ret_pct, 2),
            direction_correct= is_correct,
            counted_in_stats = counted,
            check_type       = rec.get("check_type", "t5"),
            source           = rec.get("source", "scan"),
        )
        new_results.append(result)

        tag = "✓" if is_correct else "✗" if counted else "○"
        logger.info("[%s] %s(%s) %s→%s 涨跌%.1f%% %s",
                    rec.get("check_type", "t5"), name, code,
                    price_at_scan, price, ret_pct, tag)

        # 回写 ChromaDB predictions（仅 research 模式，scan 模式用 review_results.json 统计）
        if rec.get("source") == "research" and counted:
            _write_back_to_chromadb(name, rec["scan_date"], is_correct, ret_pct)

    if not dry_run:
        if new_results:
            append_results(new_results)
            logger.info("已写入 %d 条复盘结果", len(new_results))
        # 把价格失败的重新放回 pending
        save_pending(remaining + still_pending)
    else:
        logger.info("[dry-run] 未写入，共 %d 条结果", len(new_results))

    return len(new_results)


def _write_back_to_chromadb(stock_name: str, pred_date: str,
                              was_correct: bool, price_change_pct: float) -> None:
    try:
        from memory.vector_store import update_prediction_outcome
        update_prediction_outcome(stock_name, pred_date, was_correct, price_change_pct)
        logger.info("ChromaDB 回写成功：%s %s", stock_name, pred_date)
    except Exception as e:
        logger.warning("ChromaDB 回写失败：%s", e)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="检查到期投研预测准确性")
    parser.add_argument("--dry", action="store_true", help="dry-run，不写入文件")
    parser.add_argument("--date", default=None, help="指定检查日期 YYYY-MM-DD（默认今天）")
    args = parser.parse_args()
    count = run_check(dry_run=args.dry, as_of=args.date)
    print(f"处理完成，共 {count} 条")
