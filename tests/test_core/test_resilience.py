import pytest
from unittest.mock import MagicMock, patch
from core.resilience import retry_llm_call, retry_tool_call
from core.cost_tracker import CostTracker


class TestRetryLlmCall:
    def test_success_on_first_try(self):
        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.usage_metadata = {"input_tokens": 100, "output_tokens": 50}
        mock_llm.invoke.return_value = mock_response
        tracker = CostTracker()

        result = retry_llm_call(mock_llm, ["msg"], tracker=tracker)

        assert result is mock_response
        assert mock_llm.invoke.call_count == 1
        assert tracker.snapshot().llm_calls == 1

    def test_success_after_retry(self):
        mock_llm = MagicMock()
        mock_llm.invoke.side_effect = [
            Exception("timeout"),
            MagicMock(usage_metadata={"input_tokens": 50, "output_tokens": 25}),
        ]

        result = retry_llm_call(mock_llm, ["msg"], max_retries=2, backoff_base=0.01)

        assert result is not None
        assert mock_llm.invoke.call_count == 2

    def test_all_retries_fail(self):
        mock_llm = MagicMock()
        mock_llm.invoke.side_effect = Exception("permanent failure")

        with pytest.raises(RuntimeError, match="已重试 2 次"):
            retry_llm_call(mock_llm, ["msg"], max_retries=2, backoff_base=0.01)

        assert mock_llm.invoke.call_count == 2


class TestRetryToolCall:
    def test_success(self):
        mock_tool = MagicMock()
        mock_tool.invoke.return_value = "结果"

        result = retry_tool_call(mock_tool, {}, "test_tool")
        assert result == "结果"

    def test_graceful_failure(self):
        mock_tool = MagicMock()
        mock_tool.invoke.side_effect = Exception("network error")

        result = retry_tool_call(mock_tool, {}, "test_tool", max_retries=2)
        assert "调用失败" in result
        assert "network error" in result
