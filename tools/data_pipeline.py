"""
数据管道 — 分析前自动检测数据新鲜度并按需更新。

直接调用 data_downloader.py 的成熟逻辑（4进程并发、重试重登、节流），
不重写 baostock 交互代码。

两种场景：
  - 单股更新（模式二）：只更新目标股票，约 2-5 秒
  - 全量增量更新（模式一）：调用 data_downloader 的完整流程
"""

from __future__ import annotations

import os
import sys
import subprocess
import logging
from datetime import datetime, timedelta

import pandas as pd

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "local_stock_data")
META_FILE = os.path.join(BASE_DIR, "meta", "stock_meta.csv")

# data_downloader.py 的路径（你的原始下载脚本）
DOWNLOADER_SCRIPT = os.path.join(
    os.path.dirname(BASE_DIR), "股市模型", "data_downloader.py"
)


def _get_file_path(code: str) -> str:
    return os.path.join(DATA_DIR, f"{code.replace('.', '_')}.csv")


def _get_local_last_date(file_path: str) -> str | None:
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


def _code_from_name(stock_name: str) -> str:
    """从 meta 查股票代码。"""
    if not os.path.exists(META_FILE):
        return ""
    try:
        meta_df = pd.read_csv(META_FILE)
        match = meta_df[meta_df["name"] == stock_name]
        if not match.empty:
            return match.iloc[0]["code"]
    except Exception:
        pass
    return ""


# ════════════════════════════════════════════════════════════════
# 公开接口
# ════════════════════════════════════════════════════════════════

def check_data_freshness(stock_code: str) -> dict:
    """检查单只股票的数据新鲜度。"""
    file_path = _get_file_path(stock_code)
    last_date = _get_local_last_date(file_path)
    is_fresh = last_date is not None and last_date >= (
        datetime.now() - timedelta(days=3)
    ).strftime("%Y-%m-%d")

    return {
        "is_fresh": is_fresh,
        "last_date": last_date,
        "file_exists": os.path.exists(file_path),
    }


def refresh_single_stock(stock_code: str, bus=None) -> dict:
    """更新单只股票的本地数据（模式二使用）。

    直接用 baostock 拉这一只的增量数据，复用 data_downloader 的核心函数。
    """
    from core.event_bus import ConsoleEventBus
    if bus is None:
        bus = ConsoleEventBus()

    file_path = _get_file_path(stock_code)
    last_date = _get_local_last_date(file_path)

    if last_date and last_date >= (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d"):
        bus.emit_progress("system", "done", f"📡 数据已是最新（{last_date}）")
        return {"ok": True, "rows": 0, "message": f"数据已最新：{last_date}", "trade_date": last_date}

    bus.emit_progress("system", "running", f"📡 正在更新 {stock_code} 行情数据...")

    # 统一代码格式为 baostock 的 sh.600000 / sz.000001 格式
    bs_code = stock_code
    if "." not in bs_code:
        digits = "".join(c for c in bs_code if c.isdigit())[-6:]
        prefix = "sh" if digits[0] in ("6", "9") else "sz"
        bs_code = f"{prefix}.{digits}"
    elif "_" in bs_code:
        bs_code = bs_code.replace("_", ".")

    try:
        downloader_dir = os.path.dirname(DOWNLOADER_SCRIPT)
        if downloader_dir not in sys.path:
            sys.path.insert(0, downloader_dir)

        from data_downloader import (
            login_baostock, logout_baostock, fetch_k_data,
            merge_and_save_csv, get_last_trade_date, resolve_real_trade_date,
            get_file_path as dl_get_file_path
        )

        login_baostock()

        today = datetime.now().strftime("%Y-%m-%d")
        calendar_date = get_last_trade_date(today)
        trade_date = resolve_real_trade_date(calendar_date)

        if last_date:
            start_date = (pd.to_datetime(last_date) + timedelta(days=1)).strftime("%Y-%m-%d")
        else:
            start_date = (datetime.now() - timedelta(days=180)).strftime("%Y-%m-%d")

        if start_date > trade_date:
            logout_baostock()
            bus.emit_progress("system", "done", f"📡 数据已是最新（{last_date}）")
            return {"ok": True, "rows": 0, "message": "无需更新", "trade_date": last_date or trade_date}

        new_df = fetch_k_data(bs_code, start_date, trade_date)
        logout_baostock()

        if new_df.empty:
            bus.emit_progress("system", "done", "📡 无新数据")
            return {"ok": True, "rows": 0, "message": "查询到空数据", "trade_date": last_date or trade_date}

        os.makedirs(DATA_DIR, exist_ok=True)
        merge_and_save_csv(file_path, new_df)
        msg = f"更新成功：+{len(new_df)} 行（{start_date} → {trade_date}）"
        bus.emit_progress("system", "done", f"📡 {msg}")
        return {"ok": True, "rows": len(new_df), "message": msg, "trade_date": trade_date}

    except ImportError:
        logger.warning("未找到 data_downloader.py，跳过数据更新")
        bus.emit_progress("system", "running", "📡 未找到数据下载脚本，使用本地缓存")
        return {"ok": False, "rows": 0, "message": "data_downloader.py 未找到", "trade_date": last_date}

    except Exception as e:
        try:
            logout_baostock()
        except Exception:
            pass
        logger.error("单股数据更新失败：%s", e)
        bus.emit_progress("system", "running", f"📡 数据更新失败：{e}，使用本地缓存继续")
        return {"ok": False, "rows": 0, "message": str(e), "trade_date": last_date}


def refresh_industry_stocks(industry: str, bus=None) -> dict:
    """更新某个行业的所有股票（板块分析前调用）。

    一个行业约 50-100 只，逐只增量更新，约 1-3 分钟。
    """
    from core.event_bus import ConsoleEventBus
    if bus is None:
        bus = ConsoleEventBus()

    if not os.path.exists(META_FILE):
        return {"ok": False, "updated": 0, "total": 0, "message": "stock_meta.csv 不存在"}

    meta_df = pd.read_csv(META_FILE)
    sector_stocks = meta_df[meta_df["industry_name"] == industry]
    total = len(sector_stocks)

    if total == 0:
        return {"ok": False, "updated": 0, "total": 0, "message": f"未找到行业 {industry}"}

    bus.emit_progress("sector", "running", f"📡 正在更新 {industry} 行业数据（{total} 只）...")

    try:
        downloader_dir = os.path.dirname(DOWNLOADER_SCRIPT)
        if downloader_dir not in sys.path:
            sys.path.insert(0, downloader_dir)

        from data_downloader import (
            login_baostock, logout_baostock, fetch_k_data,
            merge_and_save_csv, get_last_trade_date, resolve_real_trade_date,
        )

        login_baostock()
        today = datetime.now().strftime("%Y-%m-%d")
        calendar_date = get_last_trade_date(today)
        trade_date = resolve_real_trade_date(calendar_date)

        updated = 0
        skipped = 0
        failed = 0
        # 每处理约10只（行业大时按比例放宽到最多20条心跳），推一次进度，避免SSE长时间静默看起来像卡死
        heartbeat_every = max(10, total // 10)

        for i, (_, row) in enumerate(sector_stocks.iterrows()):
            if i > 0 and i % heartbeat_every == 0:
                bus.emit_progress("sector", "running", f"📡 {industry} 数据更新中 {i}/{total}...")
            code = row["code"]
            file_path = _get_file_path(code)
            last_date = _get_local_last_date(file_path)

            if last_date and last_date >= trade_date:
                skipped += 1
                continue

            start_date = (pd.to_datetime(last_date) + timedelta(days=1)).strftime("%Y-%m-%d") if last_date else \
                (datetime.now() - timedelta(days=180)).strftime("%Y-%m-%d")

            if start_date > trade_date:
                skipped += 1
                continue

            try:
                # 统一代码格式
                bs_code = code if "." in code else f"{'sh' if code[0] in '69' else 'sz'}.{code}"
                new_df = fetch_k_data(bs_code, start_date, trade_date)
                if not new_df.empty:
                    os.makedirs(DATA_DIR, exist_ok=True)
                    merge_and_save_csv(file_path, new_df)
                    updated += 1
                else:
                    skipped += 1
            except Exception as e:
                failed += 1
                if failed <= 3:
                    logger.warning("行业股票更新失败 %s：%s", code, e)

        logout_baostock()
        msg = f"{industry} 更新完成：更新{updated} 跳过{skipped} 失败{failed}/{total}"
        bus.emit_progress("sector", "running", f"📡 {msg}")
        return {"ok": True, "updated": updated, "skipped": skipped, "failed": failed, "total": total, "message": msg}

    except ImportError:
        logger.warning("未找到 data_downloader.py，跳过行业数据更新")
        return {"ok": False, "updated": 0, "total": total, "message": "data_downloader.py 未找到"}
    except Exception as e:
        try:
            logout_baostock()
        except Exception:
            pass
        logger.error("行业数据更新异常：%s", e)
        return {"ok": False, "updated": 0, "total": total, "message": str(e)}


def refresh_all_stocks(bus=None) -> dict:
    """增量更新全部股票（模式一扫描前调用）。

    直接调用 data_downloader.py 作为子进程，复用其完整的
    4进程并发 + 重试重登 + 节流 + 进度统计逻辑。
    """
    from core.event_bus import ConsoleEventBus
    if bus is None:
        bus = ConsoleEventBus()

    if not os.path.exists(DOWNLOADER_SCRIPT):
        bus.emit_progress("system", "running", "📡 未找到 data_downloader.py，跳过全量更新")
        return {"ok": False, "message": f"未找到 {DOWNLOADER_SCRIPT}"}

    bus.emit_progress("system", "running", "📡 正在启动全量增量更新（4进程并发）...")

    try:
        python_exe = sys.executable
        result = subprocess.run(
            [python_exe, DOWNLOADER_SCRIPT],
            capture_output=True,
            text=True,
            timeout=1800,  # 30分钟超时
            cwd=os.path.dirname(DOWNLOADER_SCRIPT),
        )

        if result.returncode == 0:
            # 从输出中提取统计信息
            output = result.stdout
            msg = "全量更新完成"
            for line in output.split("\n"):
                if "成功下载数" in line:
                    msg = line.strip()
                    break
            bus.emit_progress("system", "done", f"📡 {msg}")
            return {"ok": True, "message": msg, "stdout": output[-500:]}
        else:
            logger.error("data_downloader 执行失败：%s", result.stderr[-300:])
            bus.emit_progress("system", "running", "📡 全量更新执行失败，使用现有数据继续")
            return {"ok": False, "message": result.stderr[-200:]}

    except subprocess.TimeoutExpired:
        bus.emit_progress("system", "running", "📡 全量更新超时（30分钟），使用现有数据继续")
        return {"ok": False, "message": "更新超时"}
    except Exception as e:
        logger.error("全量更新异常：%s", e)
        bus.emit_progress("system", "running", f"📡 全量更新异常：{e}")
        return {"ok": False, "message": str(e)}
