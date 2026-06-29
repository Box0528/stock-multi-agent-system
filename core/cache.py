"""
文件缓存 — 同一查询当天内只调一次外部 API。

缓存路径：cache/{YYYY-MM-DD}/{query_hash}.json
TTL：当天有效，次日自动失效（按日期目录隔离）。
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_DIR = os.path.join(BASE_DIR, "cache")


def _cache_key(query: str, days: int, search_depth: str) -> str:
    raw = f"{query}|days={days}|depth={search_depth}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def _cache_path(key: str, date_str: str) -> str:
    day_dir = os.path.join(CACHE_DIR, date_str)
    return os.path.join(day_dir, f"{key}.json")


def get_cached(query: str, days: int, search_depth: str = "advanced") -> Optional[dict]:
    today = datetime.now().strftime("%Y-%m-%d")
    key = _cache_key(query, days, search_depth)
    path = _cache_path(key, today)

    if not os.path.exists(path):
        return None

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        logger.debug("缓存命中：%s", query[:50])
        return data
    except Exception as e:
        logger.warning("缓存读取失败：%s", e)
        return None


def set_cached(query: str, days: int, search_depth: str, results: dict) -> None:
    today = datetime.now().strftime("%Y-%m-%d")
    key = _cache_key(query, days, search_depth)
    path = _cache_path(key, today)

    os.makedirs(os.path.dirname(path), exist_ok=True)

    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        logger.debug("缓存写入：%s", query[:50])
    except Exception as e:
        logger.warning("缓存写入失败：%s", e)
