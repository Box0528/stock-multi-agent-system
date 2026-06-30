import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import agents.technical_analyst as ta_module
from agents.technical_analyst import run_technical_analyst
from tests.test_agents.conftest import system_content


def test_stock_name_placeholder_replaced(make_fake_llm):
    fake = make_fake_llm(ta_module, "## 技术分析报告 · 亨通股份\n...")
    run_technical_analyst("请分析亨通股份(600226)", stock_name="亨通股份")
    assert "{stock_name}" not in system_content(fake)
    assert "亨通股份" in system_content(fake)


def test_lessons_appended(make_fake_llm):
    fake = make_fake_llm(ta_module, "...")
    run_technical_analyst("分析600226", lessons="上次过度依赖MA5信号，本次需结合成交量")
    assert "历史教训" in system_content(fake)
    assert "上次过度依赖MA5信号" in system_content(fake)


def test_self_eval_parsed_and_stripped(make_fake_llm):
    content = "## 技术分析报告\n趋势：多头排列\n\n---自评估---\n- 置信度：85%"
    make_fake_llm(ta_module, content)
    result = run_technical_analyst("分析600226")
    assert result.confidence == 0.85
    assert "自评估" not in result.report
    assert "趋势：多头排列" in result.report


def test_tool_call_dispatched_to_real_tool_then_final_report(make_fake_llm_sequence, monkeypatch):
    """模拟'先调一次工具、再给最终报告'的真实循环路径，验证 TOOL_MAP 调度和 ToolMessage 拼接正确。"""
    captured_tool_args = {}

    class FakeTool:
        def invoke(self, args):
            captured_tool_args.update(args)
            return "收盘价：18.20，MA5：17.8，MA10：17.5，MA20：17.0"

    monkeypatch.setattr(ta_module, "TOOL_MAP", {"get_stock_detail": FakeTool()})

    tool_call = {"name": "get_stock_detail", "args": {"stock_code": "600226"}, "id": "call_1"}
    fake = make_fake_llm_sequence(ta_module, [
        ("", [tool_call]),
        ("## 技术分析报告\n趋势：多头排列", []),
    ])

    result = run_technical_analyst("分析600226", stock_name="亨通股份")

    assert captured_tool_args == {"stock_code": "600226"}
    assert fake.invoke_count == 2
    assert "趋势：多头排列" in result.report
    # 第二轮的messages里应该包含第一轮工具调用结果（ToolMessage）
    second_round_messages = fake.invoked_messages_history[1]
    assert any(getattr(m, "content", "") == "收盘价：18.20，MA5：17.8，MA10：17.5，MA20：17.0"
               for m in second_round_messages)


def test_grounding_score_perfect_when_all_numbers_match_tool_output(make_fake_llm_sequence, monkeypatch):
    class FakeTool:
        def invoke(self, args):
            return "收盘价：18.20，MA5：17.80"

    monkeypatch.setattr(ta_module, "TOOL_MAP", {"get_stock_detail": FakeTool()})
    tool_call = {"name": "get_stock_detail", "args": {"stock_code": "600226"}, "id": "call_1"}
    make_fake_llm_sequence(ta_module, [
        ("", [tool_call]),
        ("## 技术分析报告\n收盘价18.20元，MA5为17.80", []),
    ])

    result = run_technical_analyst("分析600226")
    assert result.grounding_score == 1.0
    assert result.ungrounded_claims == []


def test_grounding_score_flags_fabricated_number(make_fake_llm_sequence, monkeypatch):
    """回归测试核心场景：LLM编造了一个工具数据里没有的数字（典型幻觉），应该被溯源校验抓到。"""
    class FakeTool:
        def invoke(self, args):
            return "收盘价：18.20"

    monkeypatch.setattr(ta_module, "TOOL_MAP", {"get_stock_detail": FakeTool()})
    tool_call = {"name": "get_stock_detail", "args": {"stock_code": "600226"}, "id": "call_1"}
    make_fake_llm_sequence(ta_module, [
        ("", [tool_call]),
        ("## 技术分析报告\n收盘价18.20元，目标价35.50元", []),  # 35.50 是编造的
    ])

    result = run_technical_analyst("分析600226")
    assert result.grounding_score == 0.5
    assert len(result.ungrounded_claims) == 1
    assert result.ungrounded_claims[0].value == "35.50"


def test_cost_tracker_records_each_round(make_fake_llm):
    calls = []

    class FakeTracker:
        def record_llm_call(self, input_tokens, output_tokens):
            calls.append((input_tokens, output_tokens))

    make_fake_llm(ta_module, "...")
    run_technical_analyst("分析600226", tracker=FakeTracker())
    assert calls == [(10, 20)]
