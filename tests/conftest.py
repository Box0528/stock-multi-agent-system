import sys, os
import pytest
import tempfile
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture
def sample_stock_csv(tmp_path):
    """生成一份包含30天数据的示例股票CSV。"""
    dates = pd.date_range("2026-06-01", periods=30, freq="B")
    df = pd.DataFrame({
        "date": dates,
        "code": "sh.600226",
        "open": [10.0 + i * 0.1 for i in range(30)],
        "high": [10.5 + i * 0.1 for i in range(30)],
        "low": [9.8 + i * 0.1 for i in range(30)],
        "close": [10.2 + i * 0.1 for i in range(30)],
        "preclose": [10.1 + i * 0.1 for i in range(30)],
        "volume": [50000000 + i * 1000000 for i in range(30)],
        "amount": [500000000 + i * 10000000 for i in range(30)],
        "turn": [8.0 + i * 0.2 for i in range(30)],
        "pctChg": [1.0 + i * 0.1 for i in range(30)],
        "isST": [0] * 30,
    })
    file_path = tmp_path / "sh_600226.csv"
    df.to_csv(file_path, index=False)
    return str(file_path), df


@pytest.fixture
def sample_meta_csv(tmp_path):
    """生成示例股票元数据。"""
    df = pd.DataFrame({
        "code": ["sh.600226", "sh.600000", "sz.000001"],
        "name": ["亨通股份", "浦发银行", "平安银行"],
        "industry_name": ["D44电力", "J66货币金融服务", "J66货币金融服务"],
    })
    file_path = tmp_path / "stock_meta.csv"
    df.to_csv(file_path, index=False)
    return str(file_path), df
