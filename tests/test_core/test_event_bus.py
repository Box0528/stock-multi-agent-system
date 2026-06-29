import asyncio
import threading
import pytest
from core.event_bus import EventBus, ConsoleEventBus, AgentEvent, get_event_bus


class TestEventBus:
    def _run_with_loop(self, coro):
        """在真正运行的事件循环中执行，保证 call_soon_threadsafe 生效。"""
        result = []

        async def runner():
            r = await coro()
            result.append(r)

        loop = asyncio.new_event_loop()
        loop.run_until_complete(runner())
        loop.close()
        return result[0] if result else None

    def test_emit_puts_event_in_queue(self):
        async def test():
            loop = asyncio.get_event_loop()
            queue = asyncio.Queue()
            bus = EventBus(queue, loop)

            # emit from a thread to match real usage
            t = threading.Thread(target=lambda: bus.emit("progress", "planner", "running", "测试消息"))
            t.start()
            t.join()

            await asyncio.sleep(0.05)
            assert not queue.empty()
            event = queue.get_nowait()
            assert isinstance(event, AgentEvent)
            assert event.agent == "planner"
            assert event.message == "测试消息"

        self._run_with_loop(test)

    def test_emit_progress_shortcut(self):
        async def test():
            loop = asyncio.get_event_loop()
            queue = asyncio.Queue()
            bus = EventBus(queue, loop)

            t = threading.Thread(target=lambda: bus.emit_progress("technical", "done", "完成"))
            t.start()
            t.join()
            await asyncio.sleep(0.05)

            event = queue.get_nowait()
            assert event.event_type == "progress"
            assert event.status == "done"

        self._run_with_loop(test)

    def test_multiple_events_ordered(self):
        async def test():
            loop = asyncio.get_event_loop()
            queue = asyncio.Queue()
            bus = EventBus(queue, loop)

            def emit_two():
                bus.emit_progress("a", "running", "msg1")
                bus.emit_progress("b", "done", "msg2")

            t = threading.Thread(target=emit_two)
            t.start()
            t.join()
            await asyncio.sleep(0.05)

            e1 = queue.get_nowait()
            e2 = queue.get_nowait()
            assert e1.agent == "a"
            assert e2.agent == "b"

        self._run_with_loop(test)


class TestConsoleEventBus:
    def test_emit_does_not_crash(self, capsys):
        bus = ConsoleEventBus()
        bus.emit("progress", "planner", "running", "测试")
        captured = capsys.readouterr()
        assert "planner" in captured.out

    def test_emit_error(self, capsys):
        bus = ConsoleEventBus()
        bus.emit_error("risk", "出错了")
        captured = capsys.readouterr()
        assert "❌" in captured.out


class TestGetEventBus:
    def test_returns_bus_from_config(self):
        loop = asyncio.new_event_loop()
        queue = asyncio.Queue()
        bus = EventBus(queue, loop)
        config = {"configurable": {"event_bus": bus}}

        result = get_event_bus(config)
        assert result is bus
        loop.close()

    def test_returns_console_bus_when_missing(self):
        result = get_event_bus({})
        assert isinstance(result, ConsoleEventBus)
