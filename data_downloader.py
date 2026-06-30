import os
import sys
import time
from math import ceil
from datetime import datetime, timedelta
from concurrent.futures import ProcessPoolExecutor, as_completed

import baostock as bs
import pandas as pd
import numpy as np


# =========================
# 配置
# =========================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "local_stock_data")
META_DIR = os.path.join(BASE_DIR, "meta")

ONLY_MAIN_BOARD = True
ADJUST_FLAG = "3"                 # 3=不复权, 2=前复权
DEFAULT_FULL_DAYS = 180           # 不传开始日期时，新文件默认下载天数

# 进度 / 重试
PROGRESS_EVERY = 10               # 每处理多少只打印一次进度
RETRY_TIMES = 5                   # 单只股票失败重试次数
RETRY_SLEEP = 2.0                 # 单只股票失败后重试等待（会乘 attempt）
LOOP_SLEEP_EVERY = 50             # 每处理多少只额外休息一下
LOOP_SLEEP_SECONDS = 1.0          # 批量节流
RELOGIN_EVERY = 500               # 每处理多少只主动重登一次

# 并发
MAX_WORKERS = 4                   # 你要求 2 并发；这里使用 2 个进程分块并发

REQUEST_TIMEOUT_HINT = "若频繁出现 WinError 10054，优先检查代理/TUN 模式/本机网络稳定性"


# =========================
# 工具函数
# =========================
def ensure_dirs():
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(META_DIR, exist_ok=True)


def safe_float(x, default=np.nan):
    try:
        if x == "" or x is None:
            return default
        return float(x)
    except Exception:
        return default


def normalize_date_str(date_str: str) -> str:
    return pd.to_datetime(date_str).strftime("%Y-%m-%d")


def is_main_board_code(code: str) -> bool:
    if code.startswith("sh.600"):
        return True
    if code.startswith("sh.601"):
        return True
    if code.startswith("sh.603"):
        return True
    if code.startswith("sh.605"):
        return True
    if code.startswith("sz.000"):
        return True
    if code.startswith("sz.001"):
        return True
    if code.startswith("sz.002"):
        return True
    if code.startswith("sz.003"):
        return True
    return False


def format_seconds(seconds: float) -> str:
    if seconds <= 0:
        return "0 秒"
    seconds = int(seconds)
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    if h > 0:
        return f"{h}小时{m}分钟{s}秒"
    if m > 0:
        return f"{m}分钟{s}秒"
    return f"{s}秒"


def chunk_list(seq, n):
    if n <= 0:
        return [seq]
    if not seq:
        return []
    size = ceil(len(seq) / n)
    return [seq[i:i + size] for i in range(0, len(seq), size)]


def parse_args():
    """
    用法：
    1) 默认更新到最新可用交易日：
       python data_downloader.py

    2) 只补某一天：
       python data_downloader.py 2026-03-30

    3) 自定义起止日期区间：
       python data_downloader.py 2025-09-01 2026-03-30
    """
    if len(sys.argv) == 1:
        return {
            "mode": "default",
            "custom_start_date": None,
            "custom_end_date": None,
            "single_date": None,
        }

    if len(sys.argv) == 2:
        single_date = normalize_date_str(sys.argv[1])
        return {
            "mode": "single_day",
            "custom_start_date": single_date,
            "custom_end_date": single_date,
            "single_date": single_date,
        }

    if len(sys.argv) == 3:
        custom_start_date = normalize_date_str(sys.argv[1])
        custom_end_date = normalize_date_str(sys.argv[2])
        return {
            "mode": "range",
            "custom_start_date": custom_start_date,
            "custom_end_date": custom_end_date,
            "single_date": None,
        }

    raise ValueError(
        "参数错误。\n"
        "示例1：python data_downloader.py\n"
        "示例2：python data_downloader.py 2026-03-30\n"
        "示例3：python data_downloader.py 2025-09-01 2026-03-30"
    )


# =========================
# baostock 登录 / 重登
# =========================
def login_baostock(max_retry: int = 10, base_sleep: float = 3.0):
    """
    baostock 登录重试版。
    重点解决：主进程首次 bs.login() 网络接收错误时，程序直接退出的问题。

    参数：
    - max_retry: 最大登录尝试次数
    - base_sleep: 基础等待秒数，第 n 次失败后等待 base_sleep * n 秒
    """
    last_code = None
    last_msg = None

    for attempt in range(1, max_retry + 1):
        try:
            print(f"[LOGIN] 正在登录 baostock，第 {attempt}/{max_retry} 次 ...")

            # 清理可能残留的旧连接状态，避免 socket 半连接影响下一次登录
            try:
                bs.logout()
            except Exception:
                pass

            time.sleep(1.0)

            lg = bs.login()
            last_code = getattr(lg, "error_code", None)
            last_msg = getattr(lg, "error_msg", None)

            if lg.error_code == "0":
                print("[LOGIN] baostock 登录成功")
                return True

            print(f"[LOGIN-WARN] 登录失败: error_code={lg.error_code}, error_msg={lg.error_msg}")

        except Exception as e:
            last_msg = str(e)
            print(f"[LOGIN-WARN] 登录异常: {e}")

        if attempt < max_retry:
            sleep_seconds = base_sleep * attempt
            print(f"[LOGIN] 等待 {sleep_seconds:.1f} 秒后重试 ...")
            time.sleep(sleep_seconds)

    raise RuntimeError(f"登录 baostock 失败，已重试 {max_retry} 次: {last_code}, {last_msg}")


def logout_baostock():
    try:
        bs.logout()
        print("已退出 baostock")
    except Exception:
        pass


def relogin_baostock():
    """
    重登也复用登录重试逻辑，避免单次重登失败直接中断。
    """
    print("[INFO] 准备重新登录 baostock ...")
    return login_baostock(max_retry=5, base_sleep=2.0)


def is_connection_error(err_text: str) -> bool:
    if not err_text:
        return False

    err_text_lower = err_text.lower()

    keywords = [
        "10054",
        "接收数据异常",
        "connection reset",
        "forcibly closed",
        "远程主机强迫关闭了一个现有的连接",
        "query_history_k_data_plus 失败",
        "遍历返回结果时异常",
        "网络接收错误",
        "no response",
        "socket",
    ]

    return any(k.lower() in err_text_lower for k in keywords)


# =========================
# baostock 基础获取
# =========================
def get_last_trade_date(end_date: str) -> str:
    start_date = (datetime.strptime(end_date, "%Y-%m-%d") - timedelta(days=30)).strftime("%Y-%m-%d")
    rs = bs.query_trade_dates(start_date=start_date, end_date=end_date)

    if rs.error_code != "0":
        raise RuntimeError(f"query_trade_dates 失败: {rs.error_code}, {rs.error_msg}")

    rows = []
    while rs.next():
        rows.append(rs.get_row_data())

    if not rows:
        raise ValueError("没有查到交易日数据")

    df = pd.DataFrame(rows, columns=rs.fields)
    df = df[df["is_trading_day"] == "1"]
    if df.empty:
        raise ValueError("没有有效交易日")

    return df.iloc[-1]["calendar_date"]


def get_prev_trade_date(base_date: str, lookback_days: int = 30) -> str | None:
    """
    找到 base_date 的前一个交易日。
    """
    start_date = (datetime.strptime(base_date, "%Y-%m-%d") - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
    rs = bs.query_trade_dates(start_date=start_date, end_date=base_date)

    if rs.error_code != "0":
        raise RuntimeError(f"query_trade_dates 失败: {rs.error_code}, {rs.error_msg}")

    rows = []
    while rs.next():
        rows.append(rs.get_row_data())

    if not rows:
        return None

    df = pd.DataFrame(rows, columns=rs.fields)
    df = df[df["is_trading_day"] == "1"].copy()
    if df.empty:
        return None

    df = df.sort_values("calendar_date").reset_index(drop=True)

    pos = df.index[df["calendar_date"] == base_date].tolist()
    if not pos:
        df2 = df[df["calendar_date"] < base_date]
        if df2.empty:
            return None
        return df2.iloc[-1]["calendar_date"]

    idx = pos[0]
    if idx == 0:
        return None

    return df.iloc[idx - 1]["calendar_date"]


def _query_all_stock_once(day: str | None) -> pd.DataFrame:
    rs = bs.query_all_stock(day=day)

    if rs.error_code != "0":
        raise RuntimeError(f"query_all_stock 失败: day={day}, {rs.error_code}, {rs.error_msg}")

    rows = []
    while rs.next():
        rows.append(rs.get_row_data())

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows, columns=rs.fields)
    df = df.rename(columns={"code_name": "name"})

    if ONLY_MAIN_BOARD:
        df = df[df["code"].apply(is_main_board_code)].copy()

    df = df.drop_duplicates(subset=["code"]).reset_index(drop=True)
    return df


def get_stock_basic(trade_date: str) -> tuple[pd.DataFrame, str]:
    """
    兜底顺序：
    1) 先查 trade_date
    2) 若为空，查前一交易日
    3) 若仍为空，查 day=None（让 baostock 自己给最近一个交易日）
    返回：
    - 股票基础表
    - 实际使用的股票列表日期标记
    """
    tried = []

    tried.append(f"day={trade_date}")
    df = _query_all_stock_once(trade_date)
    if not df.empty:
        print(f"[INFO] 股票列表获取成功: day={trade_date}, 数量={len(df)}")
        return df, trade_date

    print(f"[WARN] query_all_stock(day={trade_date}) 返回空数据，准备回退到前一交易日 ...")

    prev_trade_date = get_prev_trade_date(trade_date)
    if prev_trade_date:
        tried.append(f"day={prev_trade_date}")
        df = _query_all_stock_once(prev_trade_date)
        if not df.empty:
            print(f"[INFO] 股票列表回退成功: day={prev_trade_date}, 数量={len(df)}")
            return df, prev_trade_date

        print(f"[WARN] query_all_stock(day={prev_trade_date}) 仍为空，准备尝试 day=None ...")

    tried.append("day=None")
    df = _query_all_stock_once(None)
    if not df.empty:
        print(f"[INFO] 股票列表通过 day=None 获取成功, 数量={len(df)}")
        return df, "None(最近可用)"

    raise ValueError("query_all_stock 多次尝试后仍无数据，尝试顺序: " + " -> ".join(tried))


def get_stock_industry() -> pd.DataFrame:
    rs = bs.query_stock_industry()

    if rs.error_code != "0":
        print(f"[WARN] query_stock_industry 失败: {rs.error_code}, {rs.error_msg}")
        return pd.DataFrame(columns=["code", "industry_name"])

    rows = []
    while rs.next():
        rows.append(rs.get_row_data())

    if not rows:
        return pd.DataFrame(columns=["code", "industry_name"])

    df = pd.DataFrame(rows, columns=rs.fields)
    df = df.rename(columns={"industry": "industry_name"})
    df = df[["code", "industry_name"]].drop_duplicates(subset=["code"]).reset_index(drop=True)
    return df


def is_k_data_available_for_day(code: str, date_str: str) -> bool:
    """
    探测某只股票在某一天的日线是否已经可以从 baostock 获取。
    这里只用于判断“目标交易日是否已就绪”。
    """
    fields = "date,code,open,high,low,close"
    try:
        rs = bs.query_history_k_data_plus(
            code,
            fields,
            start_date=date_str,
            end_date=date_str,
            frequency="d",
            adjustflag=ADJUST_FLAG
        )

        if rs.error_code != "0":
            print(
                f"[WARN] 探测K线可用性失败: code={code}, date={date_str}, "
                f"error_code={rs.error_code}, error_msg={rs.error_msg}"
            )
            return False

        rows = []
        while rs.next():
            rows.append(rs.get_row_data())

        return len(rows) > 0

    except Exception as e:
        print(f"[WARN] 探测K线可用性异常: code={code}, date={date_str}, err={e}")
        return False


def resolve_real_trade_date(calendar_trade_date: str, probe_code: str = "sh.600000") -> str:
    """
    交易日历上的最近交易日，不一定代表 baostock 的日线已经可下载。
    若不可下载，则全局回退到前一交易日。
    """
    if is_k_data_available_for_day(probe_code, calendar_trade_date):
        print(f"[INFO] 目标交易日 {calendar_trade_date} 的日线数据已可用")
        return calendar_trade_date

    print(f"[WARN] 目标交易日 {calendar_trade_date} 的日线数据暂不可用，准备回退到前一交易日 ...")

    prev_trade_date = get_prev_trade_date(calendar_trade_date)
    if prev_trade_date is None:
        raise ValueError(f"无法为 {calendar_trade_date} 找到前一交易日")

    if is_k_data_available_for_day(probe_code, prev_trade_date):
        print(f"[INFO] 真实可用结束交易日回退成功: {prev_trade_date}")
        return prev_trade_date

    raise ValueError(
        f"calendar_trade_date={calendar_trade_date} 以及 prev_trade_date={prev_trade_date} 的K线都不可用，请稍后再试"
    )


def fetch_k_data(code: str, start_date: str, end_date: str) -> pd.DataFrame:
    fields = ",".join([
        "date",
        "code",
        "open",
        "high",
        "low",
        "close",
        "preclose",
        "volume",
        "amount",
        "turn",
        "pctChg",
        "isST"
    ])

    rs = bs.query_history_k_data_plus(
        code,
        fields,
        start_date=start_date,
        end_date=end_date,
        frequency="d",
        adjustflag=ADJUST_FLAG
    )

    if rs.error_code != "0":
        raise RuntimeError(
            f"query_history_k_data_plus 失败: code={code}, "
            f"start={start_date}, end={end_date}, "
            f"error_code={rs.error_code}, error_msg={rs.error_msg}"
        )

    rows = []
    try:
        while rs.next():
            rows.append(rs.get_row_data())
    except Exception as e:
        raise RuntimeError(
            f"遍历返回结果时异常: code={code}, start={start_date}, end={end_date}, err={e}"
        )

    if not rows:
        raise RuntimeError(
            f"返回空数据: code={code}, start={start_date}, end={end_date}, "
            f"error_code={rs.error_code}, error_msg={rs.error_msg}"
        )

    df = pd.DataFrame(rows, columns=rs.fields)

    numeric_cols = ["open", "high", "low", "close", "preclose", "volume", "amount", "turn", "pctChg"]
    for col in numeric_cols:
        df[col] = df[col].apply(safe_float)

    df["date"] = pd.to_datetime(df["date"])
    if "isST" in df.columns:
        df["isST"] = df["isST"].astype(str)

    df = df.sort_values("date").drop_duplicates(subset=["date"], keep="last").reset_index(drop=True)
    return df


# =========================
# 本地保存
# =========================
def get_file_path(code: str) -> str:
    return os.path.join(DATA_DIR, f"{code.replace('.', '_')}.csv")


def merge_and_save_csv(file_path: str, new_df: pd.DataFrame):
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


def get_local_file_status(code: str, target_trade_date: str) -> dict:
    """
    检查本地文件状态
    返回：
    - file_exists: 文件是否存在
    - last_date: 本地最后日期，不存在则为 None
    - need_download: 是否需要下载
    - download_start_date: 需要下载时的起始日期
    - reason: 判断原因
    """
    file_path = get_file_path(code)

    if not os.path.exists(file_path):
        return {
            "file_exists": False,
            "last_date": None,
            "need_download": True,
            "download_start_date": None,
            "reason": "file_not_exists"
        }

    try:
        df = pd.read_csv(file_path)
        if df.empty or "date" not in df.columns:
            return {
                "file_exists": True,
                "last_date": None,
                "need_download": True,
                "download_start_date": None,
                "reason": "file_empty_or_no_date"
            }

        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").drop_duplicates(subset=["date"]).reset_index(drop=True)

        last_date = df.iloc[-1]["date"].strftime("%Y-%m-%d")

        if last_date >= target_trade_date:
            return {
                "file_exists": True,
                "last_date": last_date,
                "need_download": False,
                "download_start_date": None,
                "reason": "already_latest"
            }

        next_day = (pd.to_datetime(last_date) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
        return {
            "file_exists": True,
            "last_date": last_date,
            "need_download": True,
            "download_start_date": next_day,
            "reason": "need_incremental_update"
        }

    except Exception:
        return {
            "file_exists": True,
            "last_date": None,
            "need_download": True,
            "download_start_date": None,
            "reason": "file_read_error"
        }


def choose_start_date(code: str, trade_date: str, custom_start_date: str | None, mode: str) -> tuple[str | None, str]:
    """
    返回:
    - start_date: 实际下载起始日期；如果返回 None，表示这只股票可以跳过
    - download_mode: skip/full/incremental/single_day/custom_range
    """
    status = get_local_file_status(code, trade_date)

    # 只补某一天
    if mode == "single_day":
        single_day = custom_start_date

        if status["reason"] == "already_latest" and status["last_date"] is not None and status["last_date"] >= single_day:
            return None, "skip"

        return single_day, "single_day"

    # 自定义区间
    if mode == "range":
        actual_end = trade_date

        if status["reason"] == "already_latest" and status["last_date"] is not None and status["last_date"] >= actual_end:
            actual_start = custom_start_date
        else:
            if status["download_start_date"] is not None:
                actual_start = max(custom_start_date, status["download_start_date"])
            else:
                actual_start = custom_start_date

        if actual_start > actual_end:
            return None, "skip"

        return actual_start, "custom_range"

    # 默认逻辑
    if not status["need_download"]:
        return None, "skip"

    if status["reason"] == "file_not_exists":
        start_date = (datetime.strptime(trade_date, "%Y-%m-%d") - timedelta(days=DEFAULT_FULL_DAYS)).strftime("%Y-%m-%d")
        return start_date, "full"

    if status["download_start_date"] is not None:
        return status["download_start_date"], "incremental"

    start_date = (datetime.strptime(trade_date, "%Y-%m-%d") - timedelta(days=DEFAULT_FULL_DAYS)).strftime("%Y-%m-%d")
    return start_date, "full"


# =========================
# 单只股票处理
# =========================
def process_one_stock(code: str, name: str, industry_name: str, start_date: str, end_date: str) -> dict:
    last_err = None

    for attempt in range(1, RETRY_TIMES + 1):
        try:
            new_df = fetch_k_data(code, start_date, end_date)
            merge_and_save_csv(get_file_path(code), new_df)

            return {
                "code": code,
                "name": name,
                "industry_name": industry_name,
                "ok": True,
                "rows": len(new_df),
                "msg": "ok"
            }

        except Exception as e:
            last_err = str(e)
            print(f"[WARN] {code} {name} 第 {attempt}/{RETRY_TIMES} 次失败: {last_err}")

            # 单日空数据，不再死命重试太久；但这里只做保险兜底
            if "返回空数据" in last_err and start_date == end_date:
                return {
                    "code": code,
                    "name": name,
                    "industry_name": industry_name,
                    "ok": True,
                    "rows": 0,
                    "msg": "empty_but_not_ready"
                }

            if is_connection_error(last_err):
                try:
                    print(f"[INFO] 检测到连接类异常，准备重登 baostock: {code}")
                    relogin_baostock()
                except Exception as relogin_err:
                    print(f"[WARN] 重新登录失败: {relogin_err}")

            if attempt < RETRY_TIMES:
                sleep_seconds = RETRY_SLEEP * attempt
                print(f"[INFO] {code} 等待 {sleep_seconds:.1f} 秒后重试 ...")
                time.sleep(sleep_seconds)

    return {
        "code": code,
        "name": name,
        "industry_name": industry_name,
        "ok": False,
        "msg": last_err if last_err else "unknown error"
    }


# =========================
# worker 进程
# =========================
def worker_run(worker_id: int, rows: list[dict], trade_date: str, mode: str, custom_start_date: str | None):
    worker_name = f"Worker-{worker_id}"
    worker_start_ts = time.time()

    success_count = 0
    fail_count = 0
    skip_count = 0

    full_count = 0
    incremental_count = 0
    single_day_count = 0
    custom_range_count = 0

    total_new_rows = 0
    error_records = []

    total = len(rows)

    print(f"[{worker_name}] 启动，分配股票数: {total}")

    try:
        login_baostock()

        for i, row in enumerate(rows):
            code = row["code"]
            name = row["name"]
            industry_name = row["industry_name"]

            start_date, download_mode = choose_start_date(code, trade_date, custom_start_date, mode)
            done = i + 1

            if download_mode == "skip" or start_date is None:
                skip_count += 1
            else:
                if download_mode == "full":
                    full_count += 1
                elif download_mode == "incremental":
                    incremental_count += 1
                elif download_mode == "single_day":
                    single_day_count += 1
                elif download_mode == "custom_range":
                    custom_range_count += 1

                print(f"[{worker_name}] [DEBUG] {code} | {name} | mode={download_mode} | start={start_date} | end={trade_date}")

                result = process_one_stock(code, name, industry_name, start_date, trade_date)

                if result["ok"]:
                    success_count += 1
                    total_new_rows += result.get("rows", 0)
                else:
                    fail_count += 1
                    error_records.append({
                        "code": code,
                        "name": name,
                        "industry_name": industry_name,
                        "download_mode": download_mode,
                        "start_date": start_date,
                        "end_date": trade_date,
                        "error_msg": result["msg"],
                        "worker_id": worker_id,
                    })

            if done % PROGRESS_EVERY == 0 or done == total:
                elapsed = time.time() - worker_start_ts
                speed = done / elapsed if elapsed > 0 else 0
                remain = (total - done) / speed if speed > 0 else 0
                percent = done / total * 100 if total > 0 else 0

                print(
                    f"[{worker_name}] 进度: {done}/{total} | "
                    f"{percent:.1f}% | "
                    f"成功: {success_count} | "
                    f"跳过: {skip_count} | "
                    f"失败: {fail_count} | "
                    f"全量: {full_count} | "
                    f"增量: {incremental_count} | "
                    f"单日补: {single_day_count} | "
                    f"区间补: {custom_range_count} | "
                    f"速度: {speed:.2f} 只/秒 | "
                    f"预计剩余: {format_seconds(remain)}"
                )

            if done % LOOP_SLEEP_EVERY == 0:
                print(f"[{worker_name}] [INFO] 已处理 {done} 只，休息 {LOOP_SLEEP_SECONDS} 秒，降低连接压力 ...")
                time.sleep(LOOP_SLEEP_SECONDS)

            if done % RELOGIN_EVERY == 0:
                try:
                    print(f"[{worker_name}] [INFO] 已处理 {done} 只，主动重登 baostock，防止长连接失效 ...")
                    relogin_baostock()
                except Exception as e:
                    print(f"[{worker_name}] [WARN] 主动重登失败: {e}")

        elapsed = time.time() - worker_start_ts
        print(f"[{worker_name}] 完成，总耗时: {elapsed:.2f} 秒")

        return {
            "worker_id": worker_id,
            "total": total,
            "success_count": success_count,
            "skip_count": skip_count,
            "fail_count": fail_count,
            "full_count": full_count,
            "incremental_count": incremental_count,
            "single_day_count": single_day_count,
            "custom_range_count": custom_range_count,
            "total_new_rows": total_new_rows,
            "elapsed_seconds": round(elapsed, 2),
            "error_records": error_records,
        }

    finally:
        logout_baostock()


# =========================
# 主程序
# =========================
def main():
    ensure_dirs()
    args = parse_args()

    mode = args["mode"]
    custom_start_date = args["custom_start_date"]
    custom_end_date = args["custom_end_date"]
    single_date = args["single_date"]

    print("=" * 100)
    print(f"本地日线库构建 / 更新程序（{MAX_WORKERS}进程并发版）")
    print("=" * 100)
    print(f"数据目录: {DATA_DIR}")
    print(f"元数据目录: {META_DIR}")
    print(f"运行模式: {mode}")
    print(f"并发进程数: {MAX_WORKERS}")
    print(REQUEST_TIMEOUT_HINT)

    start_ts = time.time()

    try:
        print("正在登录 baostock ...")
        login_baostock()

        raw_end_date = custom_end_date if custom_end_date else datetime.now().strftime("%Y-%m-%d")
        calendar_trade_date = get_last_trade_date(raw_end_date)
        trade_date = resolve_real_trade_date(calendar_trade_date)

        if custom_start_date and custom_start_date > trade_date:
            raise ValueError("开始日期不能晚于实际可用结束交易日")

        print(f"交易日历识别的最近交易日: {calendar_trade_date}")
        print(f"实际使用结束交易日: {trade_date}")

        if mode == "default":
            print(f"未指定开始日期：新文件默认下载 {DEFAULT_FULL_DAYS} 天，已有文件按缺口增量补齐")
        elif mode == "single_day":
            print(f"单日补数模式：只补 {single_date}")
        elif mode == "range":
            print(f"自定义区间模式：{custom_start_date} ~ {trade_date}")

        print("正在获取股票基础信息 ...")
        stock_df, stock_list_day = get_stock_basic(trade_date)
        print(f"[INFO] 股票基础信息获取完成，实际使用股票列表日期: {stock_list_day}，数量={len(stock_df)}")

        print("正在获取行业分类信息 ...")
        industry_df = get_stock_industry()

        meta_df = pd.merge(
            stock_df[["code", "name"]],
            industry_df,
            on="code",
            how="left"
        )
        meta_df["industry_name"] = meta_df["industry_name"].fillna("未知行业")
        meta_df = meta_df.drop_duplicates(subset=["code"]).reset_index(drop=True)

        meta_file = os.path.join(META_DIR, "stock_meta.csv")
        meta_df.to_csv(meta_file, index=False, encoding="utf-8-sig")

        total = len(meta_df)
        print(f"待处理股票数: {total}")

        row_dicts = meta_df.to_dict("records")
        chunks = chunk_list(row_dicts, MAX_WORKERS)
        actual_workers = len(chunks)

        print(f"开始分块并发构建/更新本地日线库 ... 实际分块数: {actual_workers}")

        all_results = []

        with ProcessPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = []
            for idx, chunk_rows in enumerate(chunks, start=1):
                futures.append(
                    executor.submit(
                        worker_run,
                        idx,
                        chunk_rows,
                        trade_date,
                        mode,
                        custom_start_date
                    )
                )

            for future in as_completed(futures):
                result = future.result()
                all_results.append(result)
                print(
                    f"[MAIN] Worker-{result['worker_id']} 已完成 | "
                    f"总数: {result['total']} | 成功: {result['success_count']} | "
                    f"跳过: {result['skip_count']} | 失败: {result['fail_count']} | "
                    f"耗时: {result['elapsed_seconds']} 秒"
                )

        success_count = sum(x["success_count"] for x in all_results)
        fail_count = sum(x["fail_count"] for x in all_results)
        skip_count = sum(x["skip_count"] for x in all_results)

        full_count = sum(x["full_count"] for x in all_results)
        incremental_count = sum(x["incremental_count"] for x in all_results)
        single_day_count = sum(x["single_day_count"] for x in all_results)
        custom_range_count = sum(x["custom_range_count"] for x in all_results)

        total_new_rows = sum(x["total_new_rows"] for x in all_results)

        error_records = []
        for item in all_results:
            error_records.extend(item.get("error_records", []))

        elapsed = time.time() - start_ts

        summary_df = pd.DataFrame([{
            "run_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "mode": mode,
            "trade_date": trade_date,
            "calendar_trade_date": calendar_trade_date,
            "stock_list_day": stock_list_day,
            "custom_start_date": custom_start_date,
            "custom_end_date": custom_end_date,
            "single_date": single_date,
            "max_workers": MAX_WORKERS,
            "total": total,
            "success_count": success_count,
            "skip_count": skip_count,
            "fail_count": fail_count,
            "full_count": full_count,
            "incremental_count": incremental_count,
            "single_day_count": single_day_count,
            "custom_range_count": custom_range_count,
            "total_new_rows": total_new_rows,
            "elapsed_seconds": round(elapsed, 2),
        }])
        summary_path = os.path.join(META_DIR, "last_update_summary.csv")
        summary_df.to_csv(summary_path, index=False, encoding="utf-8-sig")

        error_file_path = os.path.join(META_DIR, "update_errors.csv")
        if error_records:
            pd.DataFrame(error_records).to_csv(
                error_file_path,
                index=False,
                encoding="utf-8-sig"
            )

        print("\n" + "=" * 100)
        print("本地日线库构建/更新完成")
        print("=" * 100)
        print(f"总股票数: {total}")
        print(f"成功下载数: {success_count}")
        print(f"跳过数: {skip_count}")
        print(f"失败数: {fail_count}")
        print(f"全量下载数: {full_count}")
        print(f"增量补齐数: {incremental_count}")
        print(f"单日补数数: {single_day_count}")
        print(f"自定义区间下载数: {custom_range_count}")
        print(f"本次累计写入新行数: {total_new_rows}")
        print(f"交易日历识别日期: {calendar_trade_date}")
        print(f"实际可用结束交易日: {trade_date}")
        print(f"股票列表实际使用日期: {stock_list_day}")
        print(f"并发进程数: {MAX_WORKERS}")
        print(f"总耗时: {elapsed:.2f} 秒")
        print(f"股票元数据文件: {meta_file}")
        print(f"股票日线目录: {DATA_DIR}")
        print(f"汇总文件: {summary_path}")

        if error_records:
            print(f"错误记录文件: {error_file_path}")
        else:
            print("错误记录文件: 无")

    finally:
        logout_baostock()


if __name__ == "__main__":
    main()