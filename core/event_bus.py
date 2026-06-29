"""
结构化事件总线 — 替代 monkey-patch builtins.print

每个请求创建独立的 EventBus 实例，通过 LangGraph RunnableConfig
的 configurable 传递给各节点，解决并发请求的竞态条件。
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

logger = logging.getLogger(__name__)


@dataclass
class AgentEvent:
    event_type: str          # progress / tool_call / reasoning / error
    agent: str               # planner / technical / news / sector / supervisor / risk / reflection / system
    status: str              # running / done / error
    message: str             # 用户可见的描述
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


class EventBus:
    """异步事件总线，持有 asyncio.Queue，供 SSE 消费。"""

    def __init__(self, queue: asyncio.Queue, loop: asyncio.AbstractEventLoop):
        self._queue = queue
        self._loop = loop

    def emit(
        self,
        event_type: str,
        agent: str,
        status: str,
        message: str,
        metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        event = AgentEvent(
            event_type=event_type,
            agent=agent,
            status=status,
            message=message,
            metadata=metadata or {},
        )
        self._loop.call_soon_threadsafe(self._queue.put_nowait, event)
        logger.debug("Event emitted: %s [%s] %s", agent, event_type, message)

    def emit_progress(self, agent: str, status: str, message: str) -> None:
        self.emit("progress", agent, status, message)

    def emit_tool_call(self, agent: str, message: str) -> None:
        self.emit("tool_call", agent, "running", message)

    def emit_reasoning(self, agent: str, message: str) -> None:
        self.emit("reasoning", agent, "running", message)

    def emit_error(self, agent: str, message: str) -> None:
        self.emit("error", agent, "error", message)


class ConsoleEventBus:
    """CLI 模式下的事件总线，直接 print 到终端。接口与 EventBus 一致。"""

    def emit(
        self,
        event_type: str,
        agent: str,
        status: str,
        message: str,
        metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        icon = {"running": "⏳", "done": "✅", "error": "❌"}.get(status, "📌")
        print(f"{icon} [{agent}] {message}")

    def emit_progress(self, agent: str, status: str, message: str) -> None:
        self.emit("progress", agent, status, message)

    def emit_tool_call(self, agent: str, message: str) -> None:
        self.emit("tool_call", agent, "running", message)

    def emit_reasoning(self, agent: str, message: str) -> None:
        self.emit("reasoning", agent, "running", message)

    def emit_error(self, agent: str, message: str) -> None:
        self.emit("error", agent, "error", message)


def get_event_bus(config: dict) -> EventBus | ConsoleEventBus:
    """从 LangGraph RunnableConfig 中提取 EventBus。"""
    return config.get("configurable", {}).get("event_bus", ConsoleEventBus())
