"""
复盘验证脚本 — 手动触发，检查到期的预测记录并写入真实结果。

用法：
    python scripts/check_reviews.py

做的事：
  1. 读取 meta/pending_reviews.json，找出 review_date <= 今日 的记录
  2. 用 baostock 拉对应交易日的真实收盘价
  3. 计算 5 日涨跌幅，判断方向是否正确
  4. 写入 meta/review_results.json
  5. 从 pending 里移除已验证的记录

不做的事：
  - 不调 LLM 来"解读"结果
  - 不自动修改任何 agent 的 prompt 或权重
  - 不做任何复杂的市场归因（股票跌了不代表分析错，但我们只记客观数字）
"""

import os
import sys
import logging
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.review import (
    pop_due_pending, append_results, save_pending,
    ReviewResult, direction_correct,
)

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def _get_close_price(bs_code: str, trade_date: str) -> float | None:
    """用 baostock 拉指定交易日的收盘价，返回 None 表示数据不可用。"""
    try:
        import baostock as bs
        lg = bs.login()
        if lg.error_code != "0":
            logger.warning("baostock 登录失败：%s", lg.error_msg)
            return None

        rs = bs.query_history_k_data_plus(
            bs_code,
            "date,close",
            start_date=trade_date,
            end_date=trade_date,
            frequency="d",
            adjustflag="3",
        )
        data = []
        while rs.error_code == "0" and rs.next():
            data.append(rs.get_row_data())
        bs.logout()

        if data and data[0][1]:
            return float(data[0][1])
    except Exception as e:
        logger.warning("获取 %s 在 %s 的价格失败：%s", bs_code, trade_date, e)
    return None


def _nth_trading_day_after(start_date: str, n: int = 5) -> str:
    """
    简单近似：从 start_date 往后推，跳过周末，找第 n 个交易日。
    不做节假日精确判断（节假日在 baostock 里查不到数据时会返回 None，
    check_reviews 会顺延处理）。
    """
    from datetime import datetime, timedelta
    d = datetime.strptime(start_date, "%Y-%m-%d")
    count = 0
    while count < n:
        d += timedelta(days=1)
        if d.weekday() < 5:  # 0=Monday … 4=Friday
            count += 1
    return d.strftime("%Y-%m-%d")


def main() -> int:
    today = date.today().isoformat()
    due, remaining = pop_due_pending(as_of=today)

    if not due:
        logger.info("暂无到期需要验证的预测记录。")
        return 0

    logger.info("共 %d 条预测到期，开始验证...", len(due))

    results = []
    still_pending = []  # review_date 已到但数据还没出来（节假日顺延）

    for record in due:
        code = record["stock_code"]
        review_date = record["review_date"]
        price_at_scan = record["price_at_scan"]

        logger.info("  验证 %s(%s) review_date=%s ...", record["stock_name"], code, review_date)

        price_at_review = _get_close_price(code, review_date)

        if price_at_review is None:
            # 数据不可用（节假日/停牌），顺延一个交易日
            next_date = _nth_trading_day_after(review_date, n=1)
            logger.info("    %s 数据不可用，顺延至 %s", review_date, next_date)
            record["review_date"] = next_date
            still_pending.append(record)
            continue

        if price_at_scan <= 0:
            logger.warning("    推荐价为 0，跳过 %s", code)
            still_pending.append(record)
            continue

        return_pct = (price_at_review - price_at_scan) / price_at_scan * 100
        direction = record["direction"]
        is_correct, counted = direction_correct(direction, return_pct)

        result = ReviewResult(
            scan_id=record["scan_id"],
            scan_date=record["scan_date"],
            review_date=review_date,
            stock_code=code,
            stock_name=record["stock_name"],
            direction=direction,
            price_at_scan=price_at_scan,
            price_at_review=price_at_review,
            return_pct=round(return_pct, 2),
            direction_correct=is_correct,
            counted_in_stats=counted,
        )
        results.append(result)

        sign = "✓" if is_correct else "✗" if counted else "-"
        logger.info(
            "    %s %s → 5日涨跌 %.2f%% %s",
            direction, record["source_advice"], return_pct, sign,
        )

    # 持久化
    if results:
        append_results(results)
        logger.info("写入 %d 条复盘结果到 meta/review_results.json", len(results))

    save_pending(remaining + still_pending)

    # 打印简单汇总
    counted_results = [r for r in results if r.counted_in_stats]
    if counted_results:
        correct_count = sum(1 for r in counted_results if r.direction_correct)
        logger.info(
            "本次验证准确率：%d/%d = %.0f%%",
            correct_count, len(counted_results),
            correct_count / len(counted_results) * 100,
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
