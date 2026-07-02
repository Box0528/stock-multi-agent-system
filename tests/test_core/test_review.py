"""core/review.py 的单元测试 — 纯函数部分，不做任何 I/O。"""

import pytest
from core.review import (
    advice_to_direction,
    direction_correct,
    build_accuracy_summary,
)


class TestAdviceToDirection:
    def test_buy(self):
        assert advice_to_direction("买入") == "bullish"

    def test_avoid(self):
        assert advice_to_direction("回避") == "bearish"

    def test_watch(self):
        assert advice_to_direction("观望") == "neutral"

    def test_unknown(self):
        assert advice_to_direction("未知") == "neutral"


class TestDirectionCorrect:
    def test_bullish_positive_return(self):
        correct, counted = direction_correct("bullish", 3.5)
        assert correct is True
        assert counted is True

    def test_bullish_negative_return(self):
        correct, counted = direction_correct("bullish", -2.0)
        assert correct is False
        assert counted is True

    def test_bearish_negative_return(self):
        correct, counted = direction_correct("bearish", -5.0)
        assert correct is True
        assert counted is True

    def test_bearish_positive_return(self):
        correct, counted = direction_correct("bearish", 1.0)
        assert correct is False
        assert counted is True

    def test_neutral_not_counted(self):
        correct, counted = direction_correct("neutral", 10.0)
        assert counted is False

    def test_zero_return_bullish(self):
        # 0 涨跌幅：bullish 不算正确（没涨）
        correct, counted = direction_correct("bullish", 0.0)
        assert correct is False
        assert counted is True


class TestBuildAccuracySummary:
    def test_empty_returns_empty_string(self, tmp_path, monkeypatch):
        monkeypatch.setattr("core.review.load_results", lambda: [])
        result = build_accuracy_summary()
        assert result == ""

    def test_summary_content(self, monkeypatch):
        fake_results = [
            {"direction": "bullish", "direction_correct": True,  "counted_in_stats": True},
            {"direction": "bullish", "direction_correct": False, "counted_in_stats": True},
            {"direction": "bearish", "direction_correct": True,  "counted_in_stats": True},
            {"direction": "neutral", "direction_correct": False, "counted_in_stats": False},
        ]
        monkeypatch.setattr("core.review.load_results", lambda: fake_results)
        summary = build_accuracy_summary(last_n=20)
        assert "66%" in summary or "67%" in summary  # 2/3 correct among counted
        assert "历史复盘参考" in summary
        assert "不作为本次决策的硬约束" in summary

    def test_neutral_excluded_from_stats(self, monkeypatch):
        fake_results = [
            {"direction": "neutral", "direction_correct": False, "counted_in_stats": False},
        ] * 10
        monkeypatch.setattr("core.review.load_results", lambda: fake_results)
        result = build_accuracy_summary()
        assert result == ""
