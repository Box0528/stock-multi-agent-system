import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client_with_access_key(monkeypatch):
    """临时给 settings.access_key 赋值，验证鉴权依赖的真实行为（不依赖本地 .env 是否配置了 ACCESS_KEY）。"""
    import api.server as server_module
    monkeypatch.setattr(server_module.settings, "access_key", "test-secret")
    return TestClient(server_module.app)


class TestAccessKeyAuth:
    def test_missing_key_rejected(self, client_with_access_key):
        resp = client_with_access_key.get("/api/lookup/600000")
        assert resp.status_code == 401

    def test_wrong_key_rejected(self, client_with_access_key):
        resp = client_with_access_key.get("/api/lookup/600000", headers={"X-API-Key": "wrong"})
        assert resp.status_code == 401

    def test_correct_key_accepted(self, client_with_access_key):
        resp = client_with_access_key.get("/api/lookup/600000", headers={"X-API-Key": "test-secret"})
        assert resp.status_code == 200

    def test_health_never_requires_key(self, client_with_access_key):
        resp = client_with_access_key.get("/api/health")
        assert resp.status_code == 200
