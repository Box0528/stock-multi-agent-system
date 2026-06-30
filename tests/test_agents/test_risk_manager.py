import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import agents.risk_manager as risk_manager_module
from agents.risk_manager import run_risk_manager
from tests.test_agents.conftest import system_content, human_content


SELF_EVAL_BLOCK = """

---自评估---
- 数据充分性：5/5
- 逻辑自洽性：4/5
- 置信度：75%
- 薄弱环节：资金流向数据滞后
"""


def _call(make_fake_llm, content="### 风险等级\n风险等级：中 🟡" + SELF_EVAL_BLOCK, **kwargs):
    fake = make_fake_llm(risk_manager_module, content)
    result = run_risk_manager(
        stock_name="亨通股份",
        supervisor_summary="基金经理建议：买入",
        technical_report="均线多头排列，换手率8%",
        **kwargs,
    )
    return fake, result


class TestOutputFormatDiscipline:
    """回归测试：风险等级不能再用'### 风险等级：🟢低'这种把数据塞进标题的写法。"""

    def test_forbids_bold_labels(self, make_fake_llm):
        fake, _ = _call(make_fake_llm)
        assert "不要加粗" in system_content(fake)

    def test_risk_level_format_is_text_before_emoji(self, make_fake_llm):
        fake, _ = _call(make_fake_llm)
        assert "文字在前，emoji在后" in system_content(fake)

    def test_sentiment_scoring_forbidden(self, make_fake_llm):
        # 项目明确要求移除情感评分，prompt里不应该再要求"情感评分"
        fake, _ = _call(make_fake_llm)
        assert "禁止使用情感评分" in system_content(fake)


class TestHistoryContext:
    def test_risk_history_included(self, make_fake_llm):
        fake, _ = _call(make_fake_llm, risk_history="上次风险等级：高")
        assert "历史风控记录" in human_content(fake)
        assert "上次风险等级：高" in human_content(fake)

    def test_no_history_means_no_block(self, make_fake_llm):
        fake, _ = _call(make_fake_llm)
        assert "历史风控记录" not in human_content(fake)


class TestLessonsInjection:
    def test_lessons_appended_to_system_prompt(self, make_fake_llm):
        fake, _ = _call(make_fake_llm, lessons="上次对ST风险判断过松")
        assert "历史教训" in system_content(fake)
        assert "上次对ST风险判断过松" in system_content(fake)


class TestSelfEvaluationPostProcessing:
    def test_confidence_parsed(self, make_fake_llm):
        _, result = _call(make_fake_llm)
        assert result.confidence == 0.75

    def test_self_eval_stripped_from_report(self, make_fake_llm):
        _, result = _call(make_fake_llm)
        assert "自评估" not in result.report
        assert "风险等级：中" in result.report

    def test_loop_terminates_without_tool_calls(self, make_fake_llm):
        """FakeLLM 默认 tool_calls=[]，应该一轮就结束，不应该死循环到5轮上限。"""
        fake, _ = _call(make_fake_llm)
        assert fake.invoke_count == 1

    def test_cost_tracker_records_usage(self, make_fake_llm):
        calls = []

        class FakeTracker:
            def record_llm_call(self, input_tokens, output_tokens):
                calls.append((input_tokens, output_tokens))

        _call(make_fake_llm, tracker=FakeTracker())
        assert calls == [(10, 20)]
