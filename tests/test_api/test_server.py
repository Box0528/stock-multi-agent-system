import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from api.server import app, verify_access_key
    # 测试不应受本地 .env 里 ACCESS_KEY 配置的影响，鉴权逻辑由 test_auth.py 单独覆盖
    app.dependency_overrides[verify_access_key] = lambda: None
    yield TestClient(app)
    app.dependency_overrides.pop(verify_access_key, None)


class TestHealthEndpoint:
    def test_health(self, client):
        resp = client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "time" in data


class TestLookupEndpoint:
    def test_valid_code(self, client):
        resp = client.get("/api/lookup/600000")
        assert resp.status_code == 200
        data = resp.json()
        if data["found"]:
            assert data["name"] == "浦发银行"

    def test_invalid_code(self, client):
        resp = client.get("/api/lookup/999999")
        assert resp.status_code == 200
        data = resp.json()
        assert data["found"] is False


class TestResearchEndpoint:
    def test_invalid_stock_code_format(self, client):
        resp = client.post("/api/research", json={"stock_code": "abc"})
        assert resp.status_code == 400

    def test_not_found_stock(self, client):
        resp = client.post("/api/research", json={"stock_code": "999999"})
        assert resp.status_code == 404
