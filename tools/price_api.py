import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
from datetime import datetime

BASE_DIR  = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR  = os.path.join(BASE_DIR, "local_stock_data")
META_FILE = os.path.join(BASE_DIR, "meta", "stock_meta.csv")


def _name_to_code(stock_name: str) -> str:
    try:
        meta = pd.read_csv(META_FILE)
        match = meta[meta["name"] == stock_name]
        if not match.empty:
            raw = match.iloc[0]["code"]
            return raw.replace("sh.", "").replace("sz.", "").replace(".", "")
    except Exception:
        pass
    return ""


def _code_for_akshare(stock_name: str) -> str:
    code = _name_to_code(stock_name)
    if not code:
        return ""
    return f"sh{code}" if code.startswith("6") else f"sz{code}"


def _is_trading_hours() -> tuple:
    """判断当前是否为A股交易时间，返回 (是否交易中, 说明文字)"""
    now     = datetime.now()
    weekday = now.weekday()
    days    = ['周一','周二','周三','周四','周五','周六','周日']

    if weekday >= 5:
        return False, f"当前为{days[weekday]}，价格为最近交易日收盘价"

    t = now.hour * 60 + now.minute
    if   9*60+30 <= t <= 11*60+30:
        return True,  "上午盘中（09:30-11:30）"
    elif 13*60    <= t <= 15*60:
        return True,  "下午盘中（13:00-15:00）"
    elif t < 9*60+30:
        return False, "盘前，价格为昨日收盘价"
    elif 11*60+30 < t < 13*60:
        return False, "午休（11:30-13:00），价格为上午收盘价"
    else:
        return False, "已收盘，价格为今日收盘价"


def get_realtime_price(stock_name: str) -> dict:
    """
    获取股票当前价格。
    优先 akshare，失败自动降级本地缓存。
    """
    try:
        result = _fetch_akshare(stock_name)
        if result:
            return result
    except Exception as e:
        print(f"[PriceAPI] akshare 失败：{e}，降级到本地缓存")

    return _fetch_local(stock_name)


def _fetch_akshare(stock_name: str) -> dict:
    import akshare as ak

    ak_code = _code_for_akshare(stock_name)
    if not ak_code:
        raise ValueError(f"找不到股票代码：{stock_name}")

    is_trading, time_note = _is_trading_hours()

    df     = ak.stock_zh_a_spot_em()
    code_6 = ak_code[-6:]
    row    = df[df["代码"] == code_6]

    if row.empty:
        raise ValueError(f"akshare 未返回 {stock_name} 的数据")

    row        = row.iloc[0]
    price      = float(row.get("最新价", 0) or 0)
    change_pct = float(row.get("涨跌幅", 0) or 0)

    if price == 0:
        raise ValueError("价格为0，数据异常")

    # 交易时间内 → realtime；非交易时间 → last_close
    source = "realtime" if is_trading else "last_close"
    print(f"[PriceAPI] ✓ {time_note}：{stock_name} {price:.2f}元 ({change_pct:+.2f}%)")

    return {
        "price":      price,
        "change_pct": change_pct,
        "date":       datetime.now().strftime("%Y-%m-%d"),
        "source":     source,
        "time_note":  time_note,
        "error":      "",
    }


def _fetch_local(stock_name: str) -> dict:
    try:
        meta   = pd.read_csv(META_FILE)
        match  = meta[meta["name"] == stock_name]
        if match.empty:
            return _empty(stock_name, "找不到股票代码")

        raw_code = match.iloc[0]["code"]
        fname    = raw_code.replace(".", "_") + ".csv"
        path     = os.path.join(DATA_DIR, fname)

        if not os.path.exists(path):
            return _empty(stock_name, f"本地文件不存在：{fname}")

        df = pd.read_csv(path)
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df = df.dropna(subset=["date"]).sort_values("date")
        last = df.iloc[-1]

        price      = float(last.get("close", 0) or 0)
        change_pct = float(last.get("pctChg", 0) or 0)
        date_str   = last["date"].strftime("%Y-%m-%d")

        print(f"[PriceAPI] ⚠ 本地缓存：{stock_name} {price:.2f}元 ({date_str})")
        return {
            "price":      price,
            "change_pct": change_pct,
            "date":       date_str,
            "source":     "local_cache",
            "time_note":  "本地历史数据",
            "error":      "akshare 不可用，使用本地缓存",
        }
    except Exception as e:
        return _empty(stock_name, str(e))


def _empty(stock_name: str, error: str) -> dict:
    print(f"[PriceAPI] ✗ 无法获取价格：{stock_name} — {error}")
    return {
        "price":      0.0,
        "change_pct": 0.0,
        "date":       datetime.now().strftime("%Y-%m-%d"),
        "source":     "unavailable",
        "time_note":  "",
        "error":      error,
    }


def format_price_info(price_data: dict) -> str:
    """格式化成可存入 Memory 的字符串"""
    if price_data["source"] == "unavailable":
        return ""
    source_map = {
        "realtime":   "实时",
        "last_close": "收盘价",
        "local_cache":"本地缓存",
    }
    label = source_map.get(price_data["source"], price_data["source"])
    note  = f" · {price_data['time_note']}" if price_data.get("time_note") else ""
    return (
        f"收盘价约 {price_data['price']:.2f} 元 "
        f"({price_data['change_pct']:+.2f}%) "
        f"[{label}{note} · {price_data['date']}]"
    )


if __name__ == "__main__":
    print("=== 实时价格模块测试 ===\n")
    is_t, note = _is_trading_hours()
    print(f"当前交易状态：{'交易中' if is_t else '非交易时间'} — {note}\n")
    for name in ["有研新材", "紫金矿业"]:
        data = get_realtime_price(name)
        print(f"{name}: {format_price_info(data)}")
        print(f"  来源:{data['source']}  备注:{data.get('time_note','')}  错误:{data['error'] or '无'}\n")