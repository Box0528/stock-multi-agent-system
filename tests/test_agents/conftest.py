import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import pytest


class FakeResponse:
    def __init__(self, content, tool_calls=None):
        self.content = content
        self.usage_metadata = {"input_tokens": 10, "output_tokens": 20}
        self.tool_calls = tool_calls or []


class FakeLLM:
    """假LLM：不发真实网络请求，直接返回预设文本，同时记录收到的messages供断言。
    支持 bind_tools()（risk_manager 这类带工具循环的agent需要），直接返回自身、
    不触发任何真实工具调用——tool_calls 默认为空，第一轮就结束循环。
    """
    def __init__(self, content):
        self._content = content
        self.invoked_messages = None
        self.invoke_count = 0

    def bind_tools(self, tools):
        return self

    def invoke(self, messages):
        self.invoked_messages = messages
        self.invoke_count += 1
        return FakeResponse(self._content)


@pytest.fixture
def make_fake_llm(monkeypatch):
    """返回一个工厂函数：fake_get_llm(module, content) 会 monkeypatch 指定模块的 get_llm，
    使其调用 llm.invoke() 时返回 content，并把创建出来的 FakeLLM 实例返回方便后续断言。
    """
    def _factory(module, content: str) -> FakeLLM:
        fake = FakeLLM(content)
        monkeypatch.setattr(module, "get_llm", lambda *a, **kw: fake)
        return fake
    return _factory


def system_content(fake_llm: FakeLLM) -> str:
    return fake_llm.invoked_messages[0].content


def human_content(fake_llm: FakeLLM) -> str:
    return fake_llm.invoked_messages[1].content
