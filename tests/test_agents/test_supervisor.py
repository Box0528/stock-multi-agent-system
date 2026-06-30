import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import agents.supervisor as supervisor_module
from agents.supervisor import run_supervisor
from tests.test_agents.conftest import system_content, human_content


SELF_EVAL_BLOCK = """

---自评估---
- 数据充分性：4/5
- 逻辑自洽性：5/5
- 置信度：80%
- 薄弱环节：消息面样本偏少
"""


def _call(make_fake_llm, content="## 综合研究报告 · 亨通股份\n操作建议：观望" + SELF_EVAL_BLOCK, **kwargs):
    fake = make_fake_llm(supervisor_module, content)
    result = run_supervisor(
        stock_name="亨通股份",
        technical_report="技术面：均线多头排列",
        news_report="消息面：无重大利好",
        sector_report="板块面：强度中等",
        **kwargs,
    )
    return fake, result


class TestOutputFormatDiscipline:
    """回归测试：system prompt 必须明确要求'不加粗' + '方向字段文字+emoji'，
    这是这次反复出现'操作建议解析失败'bug的根因修复，不能在后续改动里被悄悄删掉。"""

    def test_forbids_bold_labels(self, make_fake_llm):
        fake, _ = _call(make_fake_llm)
        assert "不要加粗" in system_content(fake)

    def test_requires_text_plus_emoji_direction(self, make_fake_llm):
        fake, _ = _call(make_fake_llm)
        assert "文字+emoji" in system_content(fake)


class TestConfidenceHandling:
    def test_low_confidence_warning_injected(self, make_fake_llm):
        fake, _ = _call(make_fake_llm, technical_confidence=0.3)
        assert "技术分析置信度仅 30%" in human_content(fake)

    def test_high_confidence_no_warning(self, make_fake_llm):
        fake, _ = _call(make_fake_llm, technical_confidence=0.9, news_confidence=0.9, sector_confidence=0.9)
        assert "置信度仅" not in human_content(fake)


class TestHistoryContext:
    def test_memory_context_included(self, make_fake_llm):
        fake, _ = _call(make_fake_llm, memory_context="上次分析：观望")
        assert "历史记忆" in human_content(fake)
        assert "上次分析：观望" in human_content(fake)

    def test_last_advice_constraint_injected(self, make_fake_llm):
        fake, _ = _call(make_fake_llm, memory_context="上次分析：观望", last_advice="观望")
        assert "上次操作建议为【观望】" in human_content(fake)

    def test_no_memory_context_means_no_history_block(self, make_fake_llm):
        fake, _ = _call(make_fake_llm)
        assert "历史记忆" not in human_content(fake)


class TestLessonsInjection:
    def test_lessons_appended_to_system_prompt(self, make_fake_llm):
        fake, _ = _call(make_fake_llm, lessons="上次过度依赖单一指标，本次需交叉验证")
        assert "历史教训" in system_content(fake)
        assert "上次过度依赖单一指标" in system_content(fake)


class TestSelfEvaluationPostProcessing:
    def test_confidence_parsed_from_self_eval_block(self, make_fake_llm):
        _, result = _call(make_fake_llm)
        assert result.confidence == 0.8

    def test_self_eval_block_stripped_from_report(self, make_fake_llm):
        _, result = _call(make_fake_llm)
        assert "自评估" not in result.report
        assert "操作建议：观望" in result.report

    def test_cost_tracker_records_usage(self, make_fake_llm):
        calls = []

        class FakeTracker:
            def record_llm_call(self, input_tokens, output_tokens):
                calls.append((input_tokens, output_tokens))

        _call(make_fake_llm, tracker=FakeTracker())
        assert calls == [(10, 20)]
