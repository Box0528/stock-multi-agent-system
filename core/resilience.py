"""
韧性模块 — LLM 调用重试（指数退避）+ 工具调用降级

用法：
    from core.resilience import retry_llm_call

    response = retry_llm_call(llm, messages, tracker=tracker)
"""

from __future__ import annotations

import time
import logging
from typing import Optional

from core.cost_tracker import CostTracker

logger = logging.getLogger(__name__)

DEFAULT_MAX_RETRIES = 3
DEFAULT_BACKOFF_BASE = 1.0  # 秒


def retry_llm_call(
    llm,
    messages: list,
    max_retries: int = DEFAULT_MAX_RETRIES,
    backoff_base: float = DEFAULT_BACKOFF_BASE,
    tracker: Optional[CostTracker] = None,
):
    """带指数退避重试的 LLM 调用。

    重试策略：第 n 次失败后等待 backoff_base * 2^(n-1) 秒。
    最终失败抛出异常，不静默吞掉。

    返回 LLM response 对象。
    """
    last_error = None

    for attempt in range(1, max_retries + 1):
        try:
            response = llm.invoke(messages)

            if tracker:
                usage = getattr(response, "usage_metadata", None) or {}
                tracker.record_llm_call(
                    input_tokens=usage.get("input_tokens", 0),
                    output_tokens=usage.get("output_tokens", 0),
                )

            return response

        except Exception as e:
            last_error = e
            if attempt < max_retries:
                wait = backoff_base * (2 ** (attempt - 1))
                logger.warning(
                    "LLM 调用失败（第 %d/%d 次），%0.1f 秒后重试：%s",
                    attempt, max_retries, wait, e,
                )
                time.sleep(wait)
            else:
                logger.error(
                    "LLM 调用最终失败（已重试 %d 次）：%s",
                    max_retries, e,
                )

    raise RuntimeError(f"LLM 调用失败，已重试 {max_retries} 次") from last_error


def retry_tool_call(tool_fn, tool_args: dict, tool_name: str, max_retries: int = 2) -> str:
    """带重试的工具调用，失败返回友好错误消息而非崩溃。"""
    last_error = None

    for attempt in range(1, max_retries + 1):
        try:
            return tool_fn.invoke(tool_args)
        except Exception as e:
            last_error = e
            if attempt < max_retries:
                logger.warning("工具 %s 调用失败（第 %d 次）：%s", tool_name, attempt, e)
                time.sleep(0.5 * attempt)

    logger.error("工具 %s 最终失败：%s", tool_name, last_error)
    return f"工具 {tool_name} 调用失败：{last_error}"
