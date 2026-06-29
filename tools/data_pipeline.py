"""
数据管道 — 分析前自动检测数据新鲜度并按需更新。

核心逻辑从 data_downloader.py 提取，适配两种场景：
  - 单股更新（模式二）：只更新目标股票，约 2 秒
  - 全量增量更新（模式一）：更新全部股票，约 5-10 分钟
"""

from __future__ import annotations

import os
import time
import logging
from datetime import datetime, timedelta

import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "local_stock_data")
META_FILE = os.path.join(BASE_DIR, "meta", "stock_meta.csv")

ADJUST_FLAG = "3"
DEFAULT_FULL_DAYS = 180
RETRY_TIMES = 3
RETRY_SLEEP = 1.5


def _safe_float(x, default=np.nan):
    try:
        if x == "" or x is None:
            return default
        return float(x)
    except Exception:
        return default


def _get_file_path(code: str) -> str:
    return os.path.join(DATA_DIR, f"{code.replace('.', '_')}.csv")


def _login_baostock(max_retry: int = 5, base_sleep: float = 2.0) -> bool:
    """带重试的 baostock 登录，处理 socket 残留问题。"""
    import baostock as bs
    for attempt in range(1, max_retry + 1):
        try:
            try:
                bs.logout()
            except Exception:
                pass
            time.sleep(0.5)
            lg = bs.login()
            if lg.error_code == "0":
                logger.info("baostock 登录成功（第 %d 次）", attempt)
                return True
            logger.warning("baostock 登录失败（第 %d 次）：%s", attempt, lg.error_msg)
        except Exception as e:
            logger.warning("baostock 登录异常（第 %d 次）：%s", attempt, e)
        if attempt < max_retry:
            time.sleep(base_sleep * attempt)
    return False


def _logout_baostock():
    import baostock as bs
    try:
        bs.logout()
    except Exception:
        pass


def _is_connection_error(err_text: str) -> bool:
    keywords = ["10054", "10038", "接收数据异常", "connection reset",
                "forcibly closed", "网络接收错误", "socket", "no response"]
    return any(k.lower() in err_text.lower() for k in keywords)


def _get_last_trade_date(end_date: str) -> str:
    import baostock as bs
    start = (datetime.strptime(end_date, "%Y-%m-%d") - timedelta(days=30)).strftime("%Y-%m-%d")
    rs = bs.query_trade_dates(start_date=start, end_date=end_date)
    if rs.error_code != "0":
        raise RuntimeError(f"query_trade_dates 失败：{rs.error_code}")
    rows = []
    while rs.next():
        rows.append(rs.get_row_data())
    df = pd.DataFrame(rows, columns=rs.fields)
    df = df[df["is_trading_day"] == "1"]
    if df.empty:
        raise ValueError("未找到有效交易日")
    return df.iloc[-1]["calendar_date"]


def _fetch_k_data(code: str, start_date: str, end_date: str) -> pd.DataFrame:
    import baostock as bs
    fields = "date,code,open,high,low,close,preclose,volume,amount,turn,pctChg,isST"
    rs = bs.query_history_k_data_plus(
        code, fields,
        start_date=start_date, end_date=end_date,
        frequency="d", adjustflag=ADJUST_FLAG,
    )
    if rs.error_code != "0":
        raise RuntimeError(f"K线查询失败：{code} {rs.error_code} {rs.error_msg}")

    rows = []
    while rs.next():
        rows.append(rs.get_row_data())

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows, columns=rs.fields)
    for col in ["open", "high", "low", "close", "preclose", "volume", "amount", "turn", "pctChg"]:
        df[col] = df[col].apply(_safe_float)
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").drop_duplicates(subset=["date"], keep="last").reset_index(drop=True)
    return df


def _merge_and_save(file_path: str, new_df: pd.DataFrame) -> None:
    if os.path.exists(file_path):
        try:
            old_df = pd.read_csv(file_path)
            if not old_df.empty and "date" in old_df.columns:
                old_df["date"] = pd.to_datetime(old_df["date"])
                merged = pd.concat([old_df, new_df], ignore_index=True)
            else:
                merged = new_df.copy()
        except Exception:
            merged = new_df.copy()
    else:
        merged = new_df.copy()

    merged = merged.sort_values("date").drop_duplicates(subset=["date"], keep="last").reset_index(drop=True)
    merged.to_csv(file_path, index=False, encoding="utf-8-sig")


def _get_local_last_date(file_path: str) -> str | None:
    """获取本地 CSV 的最后日期。"""
    if not os.path.exists(file_path):
        return None
    try:
        df = pd.read_csv(file_path)
        if df.empty or "date" not in df.columns:
            return None
        df["date"] = pd.to_datetime(df["date"])
        return df["date"].max().strftime("%Y-%m-%d")
    except Exception:
        return None


# ════════════════════════════════════════════════════════════════
# 公开接口
# ════════════════════════════════════════════════════════════════

def check_data_freshness(stock_code: str) -> dict:
    """检查单只股票的数据新鲜度。

    返回 {"is_fresh": bool, "last_date": str|None, "file_exists": bool}
    """
    file_path = _get_file_path(stock_code)
    last_date = _get_local_last_date(file_path)
    today = datetime.now().strftime("%Y-%m-%d")

    # 周末/节假日不强制要求当天数据
    is_fresh = last_date is not None and last_date >= (
        datetime.now() - timedelta(days=3)
    ).strftime("%Y-%m-%d")

    return {
        "is_fresh": is_fresh,
        "last_date": last_date,
        "file_exists": os.path.exists(file_path),
        "today": today,
    }


def refresh_single_stock(stock_code: str, bus=None) -> dict:
    """更新单只股票的本地数据（模式二使用）。

    返回 {"ok": bool, "rows": int, "message": str}
    """
    from core.event_bus import ConsoleEventBus
    if bus is None:
        bus = ConsoleEventBus()

    file_path = _get_file_path(stock_code)
    last_date = _get_local_last_date(file_path)
    today = datetime.now().strftime("%Y-%m-%d")

    if last_date and last_date >= (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d"):
        bus.emit_progress("system", "done", f"📡 数据已是最新（{last_date}）")
        return {"ok": True, "rows": 0, "message": f"数据已最新：{last_date}"}

    bus.emit_progress("system", "running", f"📡 正在更新 {stock_code} 行情数据...")

    try:
        if not _login_baostock():
            return {"ok": False, "rows": 0, "message": "baostock 登录失败"}

        trade_date = _get_last_trade_date(today)

        if last_date:
            start_date = (pd.to_datetime(last_date) + timedelta(days=1)).strftime("%Y-%m-%d")
        else:
            start_date = (datetime.now() - timedelta(days=DEFAULT_FULL_DAYS)).strftime("%Y-%m-%d")

        if start_date > trade_date:
            bus.emit_progress("system", "done", f"📡 数据已是最新（{last_date}）")
            return {"ok": True, "rows": 0, "message": "无需更新"}

        last_err = None
        for attempt in range(1, RETRY_TIMES + 1):
            try:
                new_df = _fetch_k_data(stock_code, start_date, trade_date)
                if new_df.empty:
                    bus.emit_progress("system", "done", "📡 无新数据")
                    return {"ok": True, "rows": 0, "message": "查询到空数据"}

                os.makedirs(DATA_DIR, exist_ok=True)
                _merge_and_save(file_path, new_df)
                msg = f"更新成功：+{len(new_df)} 行（{start_date} → {trade_date}）"
                bus.emit_progress("system", "done", f"📡 {msg}")
                logger.info("%s %s", stock_code, msg)
                return {"ok": True, "rows": len(new_df), "message": msg}

            except Exception as e:
                last_err = str(e)
                if _is_connection_error(last_err):
                    logger.info("检测到连接异常，尝试重登 baostock")
                    _login_baostock(max_retry=3)
                if attempt < RETRY_TIMES:
                    time.sleep(RETRY_SLEEP * attempt)

        return {"ok": False, "rows": 0, "message": f"更新失败（重试{RETRY_TIMES}次）：{last_err}"}

    except Exception as e:
        logger.error("数据更新异常：%s", e)
        return {"ok": False, "rows": 0, "message": str(e)}

    finally:
        _logout_baostock()


MAX_WORKERS = 4
RELOGIN_EVERY = 500
LOOP_SLEEP_EVERY = 50
LOOP_SLEEP_SECONDS = 1.0


def _worker_batch(worker_id: int, rows: list[dict], trade_date: str) -> dict:
    """单个 worker 进程：独立登录 baostock，处理分配的股票。"""
    import baostock as bs

    updated = 0
    skipped = 0
    failed = 0
    total = len(rows)

    try:
        bs.logout()
    except Exception:
        pass
    time.sleep(0.5)
    lg = bs.login()
    if lg.error_code != "0":
        return {"worker_id": worker_id, "updated": 0, "skipped": 0, "failed": total,
                "total": total, "message": f"Worker-{worker_id} 登录失败"}

    for i, row in enumerate(rows):
        code = row["code"]
        file_path = _get_file_path(code)
        last_date = _get_local_last_date(file_path)

        if last_date and last_date >= trade_date:
            skipped += 1
            continue

        start_date = (pd.to_datetime(last_date) + timedelta(days=1)).strftime("%Y-%m-%d") if last_date else \
            (datetime.now() - timedelta(days=DEFAULT_FULL_DAYS)).strftime("%Y-%m-%d")

        if start_date > trade_date:
            skipped += 1
            continue

        for attempt in range(1, RETRY_TIMES + 1):
            try:
                new_df = _fetch_k_data(code, start_date, trade_date)
                if not new_df.empty:
                    os.makedirs(DATA_DIR, exist_ok=True)
                    _merge_and_save(file_path, new_df)
                    updated += 1
                else:
                    skipped += 1
                break
            except Exception as e:
                err = str(e)
                if _is_connection_error(err):
                    try:
                        bs.logout()
                        time.sleep(1)
                        bs.login()
                    except Exception:
                        pass
                if attempt == RETRY_TIMES:
                    failed += 1
                else:
                    time.sleep(RETRY_SLEEP * attempt)

        if (i + 1) % LOOP_SLEEP_EVERY == 0:
            time.sleep(LOOP_SLEEP_SECONDS)

        if (i + 1) % RELOGIN_EVERY == 0:
            try:
                bs.logout()
                time.sleep(0.5)
                bs.login()
            except Exception:
                pass

    try:
        bs.logout()
    except Exception:
        pass

    return {"worker_id": worker_id, "updated": updated, "skipped": skipped,
            "failed": failed, "total": total}


def refresh_all_stocks(bus=None) -> dict:
    """增量更新全部股票（模式一扫描前调用），4 进程并发。

    返回 {"ok": bool, "updated": int, "skipped": int, "failed": int, "total": int}
    """
    from math import ceil
    from concurrent.futures import ProcessPoolExecutor, as_completed
    from core.event_bus import ConsoleEventBus

    if bus is None:
        bus = ConsoleEventBus()

    if not os.path.exists(META_FILE):
        return {"ok": False, "updated": 0, "skipped": 0, "failed": 0, "total": 0,
                "message": "stock_meta.csv 不存在"}

    meta_df = pd.read_csv(META_FILE)
    total = len(meta_df)
    bus.emit_progress("system", "running", f"📡 开始全量增量更新（{total} 只，{MAX_WORKERS} 进程并发）...")

    # 先在主进程获取最新交易日
    try:
        if not _login_baostock():
            return {"ok": False, "updated": 0, "skipped": 0, "failed": 0, "total": total,
                    "message": "baostock 登录失败"}

        today = datetime.now().strftime("%Y-%m-%d")
        trade_date = _get_last_trade_date(today)
        _logout_baostock()
    except Exception as e:
        _logout_baostock()
        return {"ok": False, "updated": 0, "skipped": 0, "failed": 0, "total": total,
                "message": f"获取交易日失败：{e}"}

    bus.emit_progress("system", "running", f"📡 最新交易日：{trade_date}，开始分块并发更新...")

    # 分块
    row_dicts = meta_df.to_dict("records")
    chunk_size = ceil(len(row_dicts) / MAX_WORKERS)
    chunks = [row_dicts[i:i + chunk_size] for i in range(0, len(row_dicts), chunk_size)]

    updated = 0
    skipped = 0
    failed = 0

    with ProcessPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(_worker_batch, idx, chunk, trade_date): idx
            for idx, chunk in enumerate(chunks, 1)
        }
        for future in as_completed(futures):
            try:
                result = future.result()
                updated += result["updated"]
                skipped += result["skipped"]
                failed += result["failed"]
                bus.emit_progress("system", "running",
                    f"📡 Worker-{result['worker_id']} 完成（更新{result['updated']} 跳过{result['skipped']} 失败{result['failed']}）")
            except Exception as e:
                wid = futures[future]
                logger.error("Worker-%d 异常：%s", wid, e)
                failed += len(chunks[wid - 1]) if wid <= len(chunks) else 0

    msg = f"全量更新完成：更新{updated} 跳过{skipped} 失败{failed}/{total}"
    bus.emit_progress("system", "done", f"📡 {msg}")
    return {"ok": True, "updated": updated, "skipped": skipped, "failed": failed, "total": total,
            "message": msg}
