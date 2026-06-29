import os
import json
import pytest
from unittest.mock import patch
from core.cache import get_cached, set_cached, _cache_key


class TestCache:
    def test_cache_key_deterministic(self):
        k1 = _cache_key("test query", 7, "advanced")
        k2 = _cache_key("test query", 7, "advanced")
        assert k1 == k2

    def test_cache_key_varies_with_params(self):
        k1 = _cache_key("test query", 7, "advanced")
        k2 = _cache_key("test query", 1, "advanced")
        k3 = _cache_key("different query", 7, "advanced")
        assert k1 != k2
        assert k1 != k3

    def test_set_and_get(self, tmp_path):
        with patch("core.cache.CACHE_DIR", str(tmp_path)):
            data = {"results": [{"title": "test"}]}
            set_cached("my query", 7, "advanced", data)
            result = get_cached("my query", 7, "advanced")

            assert result is not None
            assert result["results"][0]["title"] == "test"

    def test_miss_returns_none(self, tmp_path):
        with patch("core.cache.CACHE_DIR", str(tmp_path)):
            result = get_cached("nonexistent", 7)
            assert result is None

    def test_different_query_not_cached(self, tmp_path):
        with patch("core.cache.CACHE_DIR", str(tmp_path)):
            set_cached("query A", 7, "advanced", {"data": 1})
            result = get_cached("query B", 7)
            assert result is None
