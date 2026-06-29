import threading
from core.cost_tracker import CostTracker, get_cost_tracker


class TestCostTracker:
    def test_initial_state(self):
        t = CostTracker()
        s = t.snapshot()
        assert s.llm_calls == 0
        assert s.total_tokens == 0
        assert s.search_api_calls == 0

    def test_record_llm_call(self):
        t = CostTracker()
        t.record_llm_call(input_tokens=100, output_tokens=50)
        t.record_llm_call(input_tokens=200, output_tokens=100)

        s = t.snapshot()
        assert s.llm_calls == 2
        assert s.total_input_tokens == 300
        assert s.total_output_tokens == 150
        assert s.total_tokens == 450

    def test_record_search_and_tool(self):
        t = CostTracker()
        t.record_search_call()
        t.record_search_call()
        t.record_tool_call()

        s = t.snapshot()
        assert s.search_api_calls == 2
        assert s.tool_calls == 1

    def test_record_cache_hit(self):
        t = CostTracker()
        t.record_cache_hit()
        assert t.snapshot().cache_hits == 1

    def test_snapshot_is_independent_copy(self):
        t = CostTracker()
        t.record_llm_call(100, 50)
        s1 = t.snapshot()
        t.record_llm_call(200, 100)
        s2 = t.snapshot()
        assert s1.llm_calls == 1
        assert s2.llm_calls == 2

    def test_to_dict(self):
        t = CostTracker()
        t.record_llm_call(100, 50)
        d = t.snapshot().to_dict()
        assert isinstance(d, dict)
        assert d["llm_calls"] == 1
        assert d["total_tokens"] == 150

    def test_thread_safety(self):
        t = CostTracker()

        def worker():
            for _ in range(100):
                t.record_llm_call(10, 5)

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for th in threads:
            th.start()
        for th in threads:
            th.join()

        assert t.snapshot().llm_calls == 400
        assert t.snapshot().total_tokens == 6000


class TestGetCostTracker:
    def test_returns_tracker_from_config(self):
        tracker = CostTracker()
        config = {"configurable": {"cost_tracker": tracker}}
        assert get_cost_tracker(config) is tracker

    def test_returns_new_tracker_when_missing(self):
        result = get_cost_tracker({})
        assert isinstance(result, CostTracker)
