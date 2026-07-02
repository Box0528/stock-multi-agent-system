"""
独立的全量数据刷新入口（离线任务，不在请求路径里运行）。

直接同步调用 data_downloader.py（未做任何改动），跑多久都没关系——
这里没有 SSE/HTTP 连接的超时压力。跑完后写入 meta/last_full_refresh.txt
时间戳，供 tools/data_pipeline.py 的 check_market_freshness() 判断模式一
扫描前数据是否需要提示用户手动刷新。

当前阶段：用户手动运行。
    python scripts/scheduled_refresh.py

未来计划：接入 Windows 计划任务，在每天收盘后自动运行（见 HANDOFF.md 待办）。
"""

import os
import sys
import subprocess
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOWNLOADER_SCRIPT = os.path.join(BASE_DIR, "data_downloader.py")
LAST_REFRESH_FILE = os.path.join(BASE_DIR, "meta", "last_full_refresh.txt")


def main() -> int:
    if not os.path.exists(DOWNLOADER_SCRIPT):
        print(f"[ERROR] 未找到 {DOWNLOADER_SCRIPT}")
        return 1

    print(f"[{datetime.now()}] 开始全量增量更新 ...")
    result = subprocess.run(
        [sys.executable, DOWNLOADER_SCRIPT],
        cwd=BASE_DIR,
    )

    if result.returncode != 0:
        print(f"[{datetime.now()}] data_downloader.py 执行失败，退出码 {result.returncode}，不写入刷新时间戳")
        return result.returncode

    os.makedirs(os.path.dirname(LAST_REFRESH_FILE), exist_ok=True)
    with open(LAST_REFRESH_FILE, "w", encoding="utf-8") as f:
        f.write(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    print(f"[{datetime.now()}] 全量更新完成，已写入 {LAST_REFRESH_FILE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
