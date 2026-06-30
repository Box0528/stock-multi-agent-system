import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import agents.reflection as reflection_module
from agents.reflection import run_reflection, _calc_price_change, _calc_accuracy, _extract_agent_lessons
from tests.test_agents.conftest import system_content, human_content


class TestCalcPriceChange:
    def test_normal_increase(self):
        current = {"source": "realtime", "price": 20.0, "date": "2026-07-01"}
        text = _calc_price_change("收盘价约 18.20 元", current)
        assert "上涨" in text
        assert "18.20元" in text
        assert "20.00元" in text

    def test_normal_decrease(self):
        current = {"source": "realtime", "price": 15.0, "date": "2026-07-01"}
        text = _calc_price_change("收盘价约 18.20 元", current)
        assert "下跌" in text

    def test_unavailable_price_source(self):
        current = {"source": "unavailable", "price": 0, "date": "2026-07-01"}
        assert "不可用" in _calc_price_change("收盘价约 18.20 元", current)

    def test_no_last_price_info(self):
        current = {"source": "realtime", "price": 20.0, "date": "2026-07-01"}
        assert "不可用" in _calc_price_change("", current)

    def test_unparseable_last_price(self):
        current = {"source": "realtime", "price": 20.0, "date": "2026-07-01"}
        text = _calc_price_change("价格未知", current)
        assert "无法提取上次价格" in text


class TestCalcAccuracy:
    def test_insufficient_history(self):
        assert "不足" in _calc_accuracy([{"date": "2026-06-01", "advice": "观望", "risk_level": "低"}])

    def test_with_history(self):
        records = [
            {"date": "2026-07-01", "advice": "观望", "risk_level": "低"},
            {"date": "2026-06-01", "advice": "买入", "risk_level": "中"},
        ]
        text = _calc_accuracy(records)
        assert "共有 1 次历史预测记录" in text
        assert "买入" in text
        assert "观望" not in text  # 当前这次记录(index 0)不应该出现在历史统计里


class TestExtractAgentLessons:
    def test_extracts_all_agents(self):
        text = (
            "### 行为修正建议\n"
            "- → Technical Analyst：降低短期均线权重\n"
            "- → News Analyst：增加政策搜索频次\n"
            "- → Sector Analyst：关注轮动阶段\n"
            "- → Risk Manager：对该行业提高风险系数\n"
            "- → Supervisor：消息面矛盾时优先听消息面\n"
        )
        lessons = _extract_agent_lessons(text)
        assert lessons["technical"] == "降低短期均线权重"
        assert lessons["news"] == "增加政策搜索频次"
        assert lessons["sector"] == "关注轮动阶段"
        assert lessons["risk"] == "对该行业提高风险系数"
        assert lessons["supervisor"] == "消息面矛盾时优先听消息面"

    def test_skips_placeholder_none(self):
        text = "- → Technical Analyst：无\n"
        assert "technical" not in _extract_agent_lessons(text)

    def test_skips_too_short(self):
        text = "- → Technical Analyst：ok\n"
        assert "technical" not in _extract_agent_lessons(text)

    def test_missing_agent_not_in_result(self):
        text = "- → Technical Analyst：降低短期均线权重\n"
        lessons = _extract_agent_lessons(text)
        assert "news" not in lessons
        assert len(lessons) == 1


class TestRunReflection:
    def test_returns_empty_without_last_advice(self, make_fake_llm):
        make_fake_llm(reflection_module, "不应该被调用")
        result = run_reflection(
            stock_name="亨通股份", last_advice="", last_date="",
            last_price_info="", current_price={"source": "unavailable", "price": 0, "date": ""},
            current_report="", history_records=[],
        )
        assert result == ""

    def test_prompt_includes_last_advice_and_today(self, make_fake_llm):
        fake = make_fake_llm(reflection_module, "## 🔍 投研复盘报告\n...")
        run_reflection(
            stock_name="亨通股份", last_advice="观望", last_date="2026-06-30",
            last_price_info="收盘价约 18.20 元",
            current_price={"source": "realtime", "price": 19.0, "date": "2026-07-01"},
            current_report="本次结论：观望", history_records=[],
        )
        assert "观望" in human_content(fake)
        assert "2026-06-30" in human_content(fake)

    def test_cost_tracker_records(self, make_fake_llm):
        calls = []

        class FakeTracker:
            def record_llm_call(self, input_tokens, output_tokens):
                calls.append((input_tokens, output_tokens))

        make_fake_llm(reflection_module, "...")
        run_reflection(
            stock_name="亨通股份", last_advice="观望", last_date="2026-06-30",
            last_price_info="收盘价约 18.20 元",
            current_price={"source": "realtime", "price": 19.0, "date": "2026-07-01"},
            current_report="...", history_records=[], tracker=FakeTracker(),
        )
        assert calls == [(10, 20)]
