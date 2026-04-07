"""Tests for AnthropicAdapter — AC: Story 6.2.

Each test class maps to a specific Given/When/Then acceptance criterion.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, call, patch

import anthropic
import pytest

from apriori.adapters.base import AnalysisResult, LLMAdapter, ModelInfo
from apriori.config import LLMConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_llm_config(**overrides) -> LLMConfig:
    defaults = {
        "provider": "anthropic",
        "api_key_env": "ANTHROPIC_API_KEY",
        "model": "claude-opus-4-6",
        "timeout_seconds": 30,
    }
    defaults.update(overrides)
    return LLMConfig(**defaults)


def _make_mock_message(
    content: str = "Test analysis.",
    model: str = "claude-opus-4-6",
    input_tokens: int = 10,
    output_tokens: int = 20,
) -> MagicMock:
    """Create a mock Anthropic API response message."""
    msg = MagicMock()
    msg.content = [MagicMock(text=content)]
    msg.model = model
    msg.usage.input_tokens = input_tokens
    msg.usage.output_tokens = output_tokens
    return msg


def _make_api_status_error(error_class, status_code: int, message: str = "test error"):
    """Create an anthropic APIStatusError subclass instance for testing."""
    response = MagicMock()
    response.status_code = status_code
    return error_class(message, response=response, body=None)


# ---------------------------------------------------------------------------
# AC: Protocol compliance — AnthropicAdapter satisfies LLMAdapter
# ---------------------------------------------------------------------------
class TestAnthropicAdapterProtocolCompliance:
    """AnthropicAdapter must satisfy the LLMAdapter runtime-checkable protocol."""

    def test_adapter_is_instance_of_llm_adapter_protocol(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        with patch("anthropic.AsyncAnthropic"):
            from apriori.adapters.anthropic import AnthropicAdapter
            adapter = AnthropicAdapter(_make_llm_config())
        assert isinstance(adapter, LLMAdapter)


# ---------------------------------------------------------------------------
# AC: Given a valid API key and prompt, when analyze is called, then the
#     adapter sends the prompt to the configured model and returns a
#     structured AnalysisResult.
# ---------------------------------------------------------------------------
class TestAnthropicAdapterAnalyzeSuccess:
    """Successful analyze call returns a fully populated AnalysisResult."""

    async def test_analyze_returns_analysis_result_instance(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        mock_msg = _make_mock_message(content="Analysis content.", input_tokens=15, output_tokens=25)

        with patch("anthropic.AsyncAnthropic") as mock_cls:
            mock_cls.return_value.messages.create = AsyncMock(return_value=mock_msg)
            from apriori.adapters.anthropic import AnthropicAdapter
            adapter = AnthropicAdapter(_make_llm_config())
            result = await adapter.analyze("Explain this function.", "def foo(): pass")

        assert isinstance(result, AnalysisResult)
        assert result.content == "Analysis content."
        assert result.tokens_used == 40  # 15 + 25

    async def test_analyze_raw_response_is_api_message(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        mock_msg = _make_mock_message()

        with patch("anthropic.AsyncAnthropic") as mock_cls:
            mock_cls.return_value.messages.create = AsyncMock(return_value=mock_msg)
            from apriori.adapters.anthropic import AnthropicAdapter
            adapter = AnthropicAdapter(_make_llm_config())
            result = await adapter.analyze("prompt", "context")

        assert result.raw_response is mock_msg

    async def test_analyze_api_key_loaded_from_env_var_in_config(self, monkeypatch):
        """API key is read from the env var name specified in config."""
        monkeypatch.setenv("MY_CUSTOM_KEY", "secret-key-xyz")
        mock_msg = _make_mock_message()

        with patch("anthropic.AsyncAnthropic") as mock_cls:
            mock_cls.return_value.messages.create = AsyncMock(return_value=mock_msg)
            from apriori.adapters.anthropic import AnthropicAdapter
            AnthropicAdapter(_make_llm_config(api_key_env="MY_CUSTOM_KEY"))
            mock_cls.assert_called_once_with(api_key="secret-key-xyz")


# ---------------------------------------------------------------------------
# AC: Given any successful response, when the AnalysisResult is inspected,
#     then model_name matches the configured model string.
# ---------------------------------------------------------------------------
class TestAnthropicAdapterModelName:
    """model_name in AnalysisResult must match the configured model string."""

    async def test_model_name_matches_configured_model(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        configured_model = "claude-opus-4-6"
        mock_msg = _make_mock_message(model=configured_model)

        with patch("anthropic.AsyncAnthropic") as mock_cls:
            mock_cls.return_value.messages.create = AsyncMock(return_value=mock_msg)
            from apriori.adapters.anthropic import AnthropicAdapter
            adapter = AnthropicAdapter(_make_llm_config(model=configured_model))
            result = await adapter.analyze("Analyze this.", "context")

        assert result.model_name == configured_model

    async def test_model_name_with_different_configured_model(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        configured_model = "claude-3-5-sonnet-20241022"
        mock_msg = _make_mock_message(model=configured_model)

        with patch("anthropic.AsyncAnthropic") as mock_cls:
            mock_cls.return_value.messages.create = AsyncMock(return_value=mock_msg)
            from apriori.adapters.anthropic import AnthropicAdapter
            adapter = AnthropicAdapter(_make_llm_config(model=configured_model))
            result = await adapter.analyze("Analyze this.", "context")

        assert result.model_name == configured_model


# ---------------------------------------------------------------------------
# AC: Given a transient API error (rate limit, 500), when analyze is called,
#     then the adapter retries with exponential backoff (up to 3 retries).
# ---------------------------------------------------------------------------
class TestAnthropicAdapterTransientRetry:
    """Transient errors (429, 500) are retried up to 3 times before raising."""

    async def test_retries_on_rate_limit_then_succeeds(self, monkeypatch):
        """Two 429 failures followed by success: 3 total attempts, 2 sleeps."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        mock_msg = _make_mock_message()
        rate_limit_error = _make_api_status_error(anthropic.RateLimitError, 429)

        with (
            patch("anthropic.AsyncAnthropic") as mock_cls,
            patch("asyncio.sleep") as mock_sleep,
        ):
            mock_client = mock_cls.return_value
            mock_client.messages.create = AsyncMock(
                side_effect=[rate_limit_error, rate_limit_error, mock_msg]
            )
            from apriori.adapters.anthropic import AnthropicAdapter
            adapter = AnthropicAdapter(_make_llm_config())
            result = await adapter.analyze("prompt", "context")

        assert isinstance(result, AnalysisResult)
        assert mock_client.messages.create.call_count == 3
        assert mock_sleep.call_count == 2

    async def test_retries_on_internal_server_error_then_succeeds(self, monkeypatch):
        """A 500 failure followed by success: 2 total attempts, 1 sleep."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        mock_msg = _make_mock_message()
        server_error = _make_api_status_error(anthropic.InternalServerError, 500)

        with (
            patch("anthropic.AsyncAnthropic") as mock_cls,
            patch("asyncio.sleep") as mock_sleep,
        ):
            mock_client = mock_cls.return_value
            mock_client.messages.create = AsyncMock(
                side_effect=[server_error, mock_msg]
            )
            from apriori.adapters.anthropic import AnthropicAdapter
            adapter = AnthropicAdapter(_make_llm_config())
            result = await adapter.analyze("prompt", "context")

        assert isinstance(result, AnalysisResult)
        assert mock_client.messages.create.call_count == 2
        assert mock_sleep.call_count == 1

    async def test_raises_after_all_retries_exhausted(self, monkeypatch):
        """All 4 attempts fail: the transient error is eventually re-raised."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        rate_limit_error = _make_api_status_error(anthropic.RateLimitError, 429)

        with (
            patch("anthropic.AsyncAnthropic") as mock_cls,
            patch("asyncio.sleep"),
        ):
            mock_client = mock_cls.return_value
            mock_client.messages.create = AsyncMock(side_effect=rate_limit_error)
            from apriori.adapters.anthropic import AnthropicAdapter
            adapter = AnthropicAdapter(_make_llm_config())

            with pytest.raises(anthropic.RateLimitError):
                await adapter.analyze("prompt", "context")

        assert mock_client.messages.create.call_count == 4  # 1 initial + 3 retries

    async def test_backoff_delays_are_1_2_4_seconds(self, monkeypatch):
        """Exponential backoff sleeps: 1s, 2s, 4s between attempts."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        rate_limit_error = _make_api_status_error(anthropic.RateLimitError, 429)

        with (
            patch("anthropic.AsyncAnthropic") as mock_cls,
            patch("asyncio.sleep") as mock_sleep,
        ):
            mock_cls.return_value.messages.create = AsyncMock(side_effect=rate_limit_error)
            from apriori.adapters.anthropic import AnthropicAdapter
            adapter = AnthropicAdapter(_make_llm_config())

            with pytest.raises(anthropic.RateLimitError):
                await adapter.analyze("prompt", "context")

        assert mock_sleep.call_args_list == [call(1.0), call(2.0), call(4.0)]


# ---------------------------------------------------------------------------
# AC: Given a persistent API error (invalid key, 401), when analyze is
#     called, then the adapter raises immediately with no retry.
# ---------------------------------------------------------------------------
class TestAnthropicAdapterPersistentError:
    """AuthenticationError (401) must raise immediately with no retry attempts."""

    async def test_raises_immediately_on_auth_error(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "invalid-key")
        auth_error = _make_api_status_error(anthropic.AuthenticationError, 401, "Invalid API key")

        with (
            patch("anthropic.AsyncAnthropic") as mock_cls,
            patch("asyncio.sleep") as mock_sleep,
        ):
            mock_client = mock_cls.return_value
            mock_client.messages.create = AsyncMock(side_effect=auth_error)
            from apriori.adapters.anthropic import AnthropicAdapter
            adapter = AnthropicAdapter(_make_llm_config())

            with pytest.raises(anthropic.AuthenticationError):
                await adapter.analyze("prompt", "context")

        assert mock_client.messages.create.call_count == 1
        mock_sleep.assert_not_called()


# ---------------------------------------------------------------------------
# AC: Given a prompt, when get_token_count is called, then it returns a
#     reasonable token estimate.
# ---------------------------------------------------------------------------
class TestAnthropicAdapterTokenCount:
    """get_token_count returns a positive integer that scales with text length."""

    def test_token_count_returns_positive_integer_for_non_empty_text(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        with patch("anthropic.AsyncAnthropic"):
            from apriori.adapters.anthropic import AnthropicAdapter
            adapter = AnthropicAdapter(_make_llm_config())

        count = adapter.get_token_count("Hello world")
        assert isinstance(count, int)
        assert count > 0

    def test_token_count_scales_with_text_length(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        with patch("anthropic.AsyncAnthropic"):
            from apriori.adapters.anthropic import AnthropicAdapter
            adapter = AnthropicAdapter(_make_llm_config())

        short = adapter.get_token_count("Hi")
        long = adapter.get_token_count(
            "This is a much longer piece of text with many words and sentences. "
            "It should produce a significantly higher token count than a short greeting."
        )
        assert long > short

    def test_token_count_empty_string_returns_non_negative(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        with patch("anthropic.AsyncAnthropic"):
            from apriori.adapters.anthropic import AnthropicAdapter
            adapter = AnthropicAdapter(_make_llm_config())

        count = adapter.get_token_count("")
        assert count >= 0


# ---------------------------------------------------------------------------
# get_model_info — synchronous metadata access
# ---------------------------------------------------------------------------
class TestAnthropicAdapterModelInfo:
    """get_model_info returns ModelInfo with correct provider and model name."""

    def test_get_model_info_returns_model_info(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        with patch("anthropic.AsyncAnthropic"):
            from apriori.adapters.anthropic import AnthropicAdapter
            adapter = AnthropicAdapter(_make_llm_config(model="claude-opus-4-6"))

        info = adapter.get_model_info()

        assert isinstance(info, ModelInfo)
        assert info.model_name == "claude-opus-4-6"
        assert info.provider == "anthropic"

    def test_get_model_info_context_window_is_positive(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        with patch("anthropic.AsyncAnthropic"):
            from apriori.adapters.anthropic import AnthropicAdapter
            adapter = AnthropicAdapter(_make_llm_config())

        info = adapter.get_model_info()

        assert info.context_window is not None
        assert info.context_window > 0

    def test_get_model_info_model_name_reflects_config(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        with patch("anthropic.AsyncAnthropic"):
            from apriori.adapters.anthropic import AnthropicAdapter
            adapter = AnthropicAdapter(_make_llm_config(model="claude-3-5-sonnet-20241022"))

        info = adapter.get_model_info()

        assert info.model_name == "claude-3-5-sonnet-20241022"
