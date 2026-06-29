"""
成本追踪器 — 统计单次请求的 LLM 调用次数、token 用量、搜索/工具调用次数。

与 EventBus 配合使用，请求结束时推送 cost_summary 事件。
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class CostSnapshot:
    llm_calls: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    search_api_calls: int = 0
    tool_calls: int = 0
    cache_hits: int = 0

    @property
    def total_tokens(self) -> int:
        return self.total_input_tokens + self.total_output_tokens

    def to_dict(self) -> dict:
        return {
            "llm_calls": self.llm_calls,
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "total_tokens": self.total_tokens,
            "search_api_calls": self.search_api_calls,
            "tool_calls": self.tool_calls,
            "cache_hits": self.cache_hits,
        }


class CostTracker:
    """线程安全的成本追踪器，跟踪单次请求的资源消耗。"""

    def __init__(self):
        self._lock = threading.Lock()
        self._data = CostSnapshot()

    def record_llm_call(self, input_tokens: int = 0, output_tokens: int = 0) -> None:
        with self._lock:
            self._data.llm_calls += 1
            self._data.total_input_tokens += input_tokens
            self._data.total_output_tokens += output_tokens
        logger.debug(
            "LLM call #%d: +%d/%d tokens",
            self._data.llm_calls, input_tokens, output_tokens,
        )

    def record_search_call(self) -> None:
        with self._lock:
            self._data.search_api_calls += 1

    def record_tool_call(self) -> None:
        with self._lock:
            self._data.tool_calls += 1

    def record_cache_hit(self) -> None:
        with self._lock:
            self._data.cache_hits += 1

    def snapshot(self) -> CostSnapshot:
        with self._lock:
            return CostSnapshot(
                llm_calls=self._data.llm_calls,
                total_input_tokens=self._data.total_input_tokens,
                total_output_tokens=self._data.total_output_tokens,
                search_api_calls=self._data.search_api_calls,
                tool_calls=self._data.tool_calls,
                cache_hits=self._data.cache_hits,
            )


def get_cost_tracker(config: dict) -> CostTracker:
    """从 LangGraph RunnableConfig 中提取 CostTracker。"""
    return config.get("configurable", {}).get("cost_tracker", CostTracker())
