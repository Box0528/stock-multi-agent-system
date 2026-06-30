import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from core.grounding import extract_numeric_claims, check_grounding


class TestExtractNumericClaims:
    def test_extracts_price_with_unit(self):
        claims = extract_numeric_claims("收盘价：18.20元")
        assert len(claims) == 1
        assert claims[0].value == "18.20"
        assert claims[0].unit == "元"

    def test_extracts_percentage(self):
        claims = extract_numeric_claims("涨跌幅：2.30%")
        assert claims[0].value == "2.30"
        assert claims[0].unit == "%"

    def test_extracts_multiple_claims(self):
        text = "MA5：17.80  MA10：17.50  MA20：17.00"
        claims = extract_numeric_claims(text)
        assert [c.value for c in claims] == ["17.80", "17.50", "17.00"]

    def test_ignores_integers_without_decimal(self):
        # 整数（如"3个⚠️"）不算"具体数字声明"，避免噪音
        claims = extract_numeric_claims("触发3个警告")
        assert claims == []

    def test_no_claims_in_plain_text(self):
        assert extract_numeric_claims("均线呈多头排列，趋势向好") == []


class TestCheckGrounding:
    def test_all_claims_grounded(self):
        receipts = [{"tool_name": "get_stock_detail", "args": {}, "result": "收盘价：18.20\nMA5：17.80"}]
        report = "收盘价18.20元，MA5为17.80"
        result = check_grounding(report, receipts)
        assert result["grounding_score"] == 1.0
        assert result["ungrounded_claims"] == []

    def test_fabricated_number_flagged_ungrounded(self):
        receipts = [{"tool_name": "get_stock_detail", "args": {}, "result": "收盘价：18.20"}]
        report = "收盘价18.20元，目标价25.00元"  # 25.00 是编造的，收据里没有
        result = check_grounding(report, receipts)
        assert result["grounding_score"] == 0.5
        assert len(result["ungrounded_claims"]) == 1
        assert result["ungrounded_claims"][0].value == "25.00"

    def test_precision_variant_still_grounded(self):
        # 收据里是17.8，报告写成17.80 —— 精度差异不应该被误判为"未核验"
        receipts = [{"tool_name": "get_stock_detail", "args": {}, "result": "MA5: 17.8"}]
        report = "MA5为17.80"
        result = check_grounding(report, receipts)
        assert result["grounding_score"] == 1.0

    def test_no_claims_returns_perfect_score(self):
        result = check_grounding("均线呈多头排列", [])
        assert result["grounding_score"] == 1.0
        assert result["total_claims"] == 0

    def test_no_receipts_all_claims_ungrounded(self):
        result = check_grounding("收盘价18.20元", [])
        assert result["grounding_score"] == 0.0
        assert result["total_claims"] == 1

    def test_multiple_receipts_concatenated(self):
        receipts = [
            {"tool_name": "get_stock_detail", "args": {}, "result": "收盘价：18.20"},
            {"tool_name": "get_stock_trend", "args": {}, "result": "MA5：17.80"},
        ]
        report = "收盘价18.20元，MA5为17.80"
        result = check_grounding(report, receipts)
        assert result["grounding_score"] == 1.0
