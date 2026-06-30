import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from memory.extraction import (
    extract_advice, extract_rating, extract_risk_level,
    extract_price_info, extract_sector_metrics, extract_structured_fields,
)


class TestExtractAdvice:
    def test_plain_format(self):
        assert extract_advice("操作建议：观望") == "观望"

    def test_bold_label_format(self):
        # 历史上出过的真实bug：LLM 没遵守"不要加粗"指令，标签被 ** 包裹导致旧正则匹配失败
        assert extract_advice("**操作建议**：买入") == "买入"

    def test_half_bold_format(self):
        assert extract_advice("*操作建议*：回避") == "回避"

    def test_missing_returns_unknown(self):
        assert extract_advice("没有相关字段的文本") == "未知"

    def test_embedded_in_larger_report(self):
        text = "## 核心结论\n- 综合评级：⭐⭐\n- 操作建议：观望\n- 建议仓位：0%"
        assert extract_advice(text) == "观望"


class TestExtractRating:
    def test_plain(self):
        assert extract_rating("综合评级：⭐⭐⭐") == "⭐⭐⭐"

    def test_bold(self):
        assert extract_rating("**综合评级**：⭐⭐⭐⭐") == "⭐⭐⭐⭐"

    def test_missing(self):
        assert extract_rating("无评级信息") == ""


class TestExtractRiskLevel:
    def test_new_format_text_before_emoji(self):
        assert extract_risk_level("风险等级：低 🟢") == "低"

    def test_old_format_emoji_before_text(self):
        assert extract_risk_level("风险等级：🟢低") == "低"

    def test_extreme_risk(self):
        assert extract_risk_level("风险等级：极高 ⛔") == "极高"

    def test_missing_returns_unknown(self):
        assert extract_risk_level("没有风险信息") == "未知"


class TestExtractPriceInfo:
    def test_found(self):
        assert extract_price_info("收盘价：18.20") == "收盘价约 18.20 元"

    def test_missing(self):
        assert extract_price_info("无价格信息") == ""


class TestExtractSectorMetrics:
    def test_full_metrics(self):
        text = "板块强度评分：75.0\n上涨：62 只\n股票总数：100\n平均涨幅：1.80\n资金持续流入"
        m = extract_sector_metrics(text)
        assert m["score"] == 75.0
        assert m["up_ratio"] == 62.0
        assert m["avg_pct"] == 1.8
        assert m["fund_trend"] == "持续流入"

    def test_no_score_returns_none(self):
        assert extract_sector_metrics("没有板块评分的文本") is None

    def test_partial_metrics_defaults(self):
        m = extract_sector_metrics("板块强度评分：50.0")
        assert m["score"] == 50.0
        assert m["up_ratio"] == 0.0
        assert m["fund_trend"] == "平稳"


class TestExtractStructuredFields:
    def test_full_pipeline(self):
        final_report = "操作建议：买入\n综合评级：⭐⭐⭐⭐\n收盘价：18.20"
        risk_report = "风险等级：低 🟢"
        sector_report = "板块强度评分：80.0\n上涨：70 只\n股票总数：100"
        fields = extract_structured_fields(final_report, risk_report, sector_report)
        assert fields["advice"] == "买入"
        assert fields["rating"] == "⭐⭐⭐⭐"
        assert fields["risk_level"] == "低"
        assert fields["price_info"] == "收盘价约 18.20 元"
        assert fields["sector_metrics"]["score"] == 80.0
