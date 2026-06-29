import os
import pytest
import pandas as pd
import numpy as np
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from tools.stock_data import _normalize_stock_code, calc_indicators


class TestNormalizeStockCode:
    def test_plain_6_digits_sh(self):
        assert _normalize_stock_code("600226") == "sh_600226"

    def test_plain_6_digits_sz(self):
        assert _normalize_stock_code("000001") == "sz_000001"

    def test_dot_suffix_sh(self):
        assert _normalize_stock_code("600226.SH") == "sh_600226"

    def test_dot_suffix_sz(self):
        assert _normalize_stock_code("000001.SZ") == "sz_000001"

    def test_dot_prefix(self):
        assert _normalize_stock_code("sh.600226") == "sh_600226"

    def test_lowercase(self):
        assert _normalize_stock_code("600226.sh") == "sh_600226"

    def test_no_dot_prefix(self):
        assert _normalize_stock_code("SH600226") == "sh_600226"

    def test_sz_prefix(self):
        assert _normalize_stock_code("sz.000001") == "sz_000001"

    def test_002_series(self):
        assert _normalize_stock_code("002415") == "sz_002415"

    def test_900_series(self):
        assert _normalize_stock_code("900901") == "sh_900901"


class TestCalcIndicators:
    def test_adds_ma_columns(self):
        df = pd.DataFrame({"close": list(range(1, 31))})
        result = calc_indicators(df)
        assert "ma5" in result.columns
        assert "ma10" in result.columns
        assert "ma20" in result.columns

    def test_ma5_values(self):
        df = pd.DataFrame({"close": [10.0] * 10})
        result = calc_indicators(df)
        assert result["ma5"].iloc[-1] == 10.0

    def test_ma_nan_for_insufficient_data(self):
        df = pd.DataFrame({"close": [1.0, 2.0, 3.0]})
        result = calc_indicators(df)
        assert pd.isna(result["ma5"].iloc[0])
