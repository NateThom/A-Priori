"""Shared parameterized adapter protocol test suite — Story 6.4 (ERD §4.1).

Runs identical behavioral assertions against both the Anthropic and Ollama adapters
using mocked HTTP responses. No real network calls are made.

AC coverage:
1. Successful prompt/response  (both adapters)
2. Correct model_name in AnalysisResult  (both adapters)
3. Token count estimation  (both adapters)
4. Retry on transient failure  (AnthropicAdapter — retries on 429/500)
5. Immediate failure on permanent error  (both adapters, adapter-specific errors)
"""

from __future__ import annotations

import contextlib
from typing import Generator
from unittest.mock import AsyncMock, MagicMock, patch

import anthropic
import httpx
import pytest

from apriori.adapters.anthropic import AnthropicAdapter
from apriori.adapters.base import AnalysisResult, LLMAdapter
from apriori.adapters.ollama import OllamaAdapter, OllamaConnectionError, OllamaModelError
from apriori.config import LLMConfig


# ──────────────────────────────────────────────────────────────────────────────
# Shared test parameters
# ──────────────────────────────────────────────────────────────────────────────

ADAPTER_IDS = ["anthropic", "ollama"]

# ──────────────────────────────────────────────────────────────────────────────
# Mock-setup helpers
# ──────────────────────────────────────────────────────────────────────────────


def _anthropic_config(model: str) -> LLMConfig:
    return LLMConfig(
        provider="anthropic",
        api_key_env="ANTHROPIC_API_KEY",
        model=model,
        timeout_seconds=30,
    )


def _anthropic_mock_msg(content: str, model: str, tokens: int = 30) -> MagicMock:
    msg = MagicMock()
    msg.content = [MagicMock(text=content)]
    msg.model = model
    msg.usage.input_tokens = tokens // 2
    msg.usage.output_tokens = tokens - tokens // 2
    return msg


def _anthropic_status_error(error_class, status_code: int):
    response = MagicMock()
    response.status_code = status_code
    return error_class("error", response=response, body=None)


@contextlib.contextmanager
def _anthropic_success(
    content: str, model: str, tokens: int = 30
) -> Generator[AnthropicAdapter, None, None]:
    """Yield an AnthropicAdapter that returns a successful mock response."""
    mock_msg = _anthropic_mock_msg(content, model, tokens)
    with patch("anthropic.AsyncAnthropic") as mock_cls, patch.dict(
        "os.environ", {"ANTHROPIC_API_KEY": "test-key"}
    ):
        mock_cls.return_value.messages.create = AsyncMock(return_value=mock_msg)
        yield AnthropicAdapter(_anthropic_config(model))


@contextlib.contextmanager
def _anthropic_permanent_error() -> Generator[tuple[AnthropicAdapter, MagicMock], None, None]:
    """Yield (adapter, mock_create) where create raises AuthenticationError immediately."""
    auth_error = _anthropic_status_error(anthropic.AuthenticationError, 401)
    with patch("anthropic.AsyncAnthropic") as mock_cls, patch.dict(
        "os.environ", {"ANTHROPIC_API_KEY": "invalid"}
    ), patch("asyncio.sleep"):
        mock_create = AsyncMock(side_effect=auth_error)
        mock_cls.return_value.messages.create = mock_create
        yield AnthropicAdapter(_anthropic_config("claude-opus-4-6")), mock_create


@contextlib.contextmanager
def _anthropic_transient_then_success(
    content: str, model: str, fail_count: int = 2
) -> Generator[tuple[AnthropicAdapter, MagicMock], None, None]:
    """Yield (adapter, mock_create) where create fails `fail_count` times then succeeds."""
    rate_limit_err = _anthropic_status_error(anthropic.RateLimitError, 429)
    mock_msg = _anthropic_mock_msg(content, model)
    side_effects = [rate_limit_err] * fail_count + [mock_msg]

    with patch("anthropic.AsyncAnthropic") as mock_cls, patch.dict(
        "os.environ", {"ANTHROPIC_API_KEY": "test-key"}
    ), patch("asyncio.sleep"):
        mock_create = AsyncMock(side_effect=side_effects)
        mock_cls.return_value.messages.create = mock_create
        yield AnthropicAdapter(_anthropic_config(model)), mock_create


@contextlib.contextmanager
def _ollama_success(content: str, model: str) -> Generator[OllamaAdapter, None, None]:
    """Yield an OllamaAdapter that returns a successful mock response."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "model": model,
        "response": content,
        "done": True,
        "prompt_eval_count": 10,
        "eval_count": 20,
    }
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)

    with patch("apriori.adapters.ollama.httpx.AsyncClient") as mock_cls:
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=None)
        yield OllamaAdapter(model=model)


@contextlib.contextmanager
def _ollama_permanent_error(model: str = "unknown-model") -> Generator[tuple[OllamaAdapter, AsyncMock], None, None]:
    """Yield (adapter, mock_post) where post returns a model-not-found error body."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "error": f"model '{model}' not found, try pulling it first"
    }
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_post = AsyncMock(return_value=mock_response)
    mock_client.post = mock_post

    with patch("apriori.adapters.ollama.httpx.AsyncClient") as mock_cls:
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=None)
        yield OllamaAdapter(model=model), mock_post


# ──────────────────────────────────────────────────────────────────────────────
# Parametrize fixture
# ──────────────────────────────────────────────────────────────────────────────


@pytest.fixture(params=ADAPTER_IDS)
def adapter_name(request) -> str:
    return request.param


# ──────────────────────────────────────────────────────────────────────────────
# AC-1: Successful prompt/response → AnalysisResult returned with expected fields
# ──────────────────────────────────────────────────────────────────────────────


class TestSuccessfulResponse:
    """Given a valid prompt and context, when analyze is called, then AnalysisResult is returned."""

    async def test_analyze_returns_analysis_result_instance(self, adapter_name: str) -> None:
        """Both adapters return an AnalysisResult on success."""
        model = "claude-opus-4-6" if adapter_name == "anthropic" else "llama3"
        ctx = _anthropic_success if adapter_name == "anthropic" else _ollama_success

        with ctx("The function parses Python files.", model) as adapter:
            result = await adapter.analyze("Explain this function.", "def parse(f): ...")

        assert isinstance(result, AnalysisResult)

    async def test_analyze_result_content_matches_response(self, adapter_name: str) -> None:
        """The content field in AnalysisResult matches the mocked response text."""
        model = "claude-opus-4-6" if adapter_name == "anthropic" else "llama3"
        expected_content = "This function reads a file and returns its contents."
        ctx = _anthropic_success if adapter_name == "anthropic" else _ollama_success

        with ctx(expected_content, model) as adapter:
            result = await adapter.analyze("Explain this.", "def read_file(p): ...")

        assert result.content == expected_content

    async def test_analyze_tokens_used_is_non_negative_integer(self, adapter_name: str) -> None:
        """tokens_used is a non-negative integer for both adapters."""
        model = "claude-opus-4-6" if adapter_name == "anthropic" else "llama3"
        ctx = _anthropic_success if adapter_name == "anthropic" else _ollama_success

        with ctx("Analysis complete.", model) as adapter:
            result = await adapter.analyze("What does this do?", "x = 1")

        assert isinstance(result.tokens_used, int)
        assert result.tokens_used >= 0

    async def test_analyze_raw_response_is_not_none(self, adapter_name: str) -> None:
        """raw_response is set (not None) on successful calls."""
        model = "claude-opus-4-6" if adapter_name == "anthropic" else "llama3"
        ctx = _anthropic_success if adapter_name == "anthropic" else _ollama_success

        with ctx("Raw response present.", model) as adapter:
            result = await adapter.analyze("Analyze.", "code here")

        assert result.raw_response is not None

    def test_adapter_satisfies_llm_adapter_protocol(self, adapter_name: str) -> None:
        """Both adapter classes satisfy the LLMAdapter runtime-checkable protocol."""
        if adapter_name == "anthropic":
            with patch("anthropic.AsyncAnthropic"), patch.dict(
                "os.environ", {"ANTHROPIC_API_KEY": "test-key"}
            ):
                adapter = AnthropicAdapter(_anthropic_config("claude-opus-4-6"))
        else:
            adapter = OllamaAdapter(model="llama3")

        assert isinstance(adapter, LLMAdapter)


# ──────────────────────────────────────────────────────────────────────────────
# AC-2: Correct model_name in AnalysisResult
# ──────────────────────────────────────────────────────────────────────────────


class TestModelNameInResult:
    """model_name in AnalysisResult must reflect the model that produced the response."""

    async def test_model_name_matches_configured_model(self, adapter_name: str) -> None:
        """model_name in the result equals the configured model identifier."""
        model = "claude-opus-4-6" if adapter_name == "anthropic" else "mistral:7b"
        ctx = _anthropic_success if adapter_name == "anthropic" else _ollama_success

        with ctx("Some analysis.", model) as adapter:
            result = await adapter.analyze("Explain this.", "context")

        assert result.model_name == model

    async def test_model_name_is_a_non_empty_string(self, adapter_name: str) -> None:
        """model_name is always a non-empty string."""
        model = "claude-opus-4-6" if adapter_name == "anthropic" else "llama3"
        ctx = _anthropic_success if adapter_name == "anthropic" else _ollama_success

        with ctx("analysis", model) as adapter:
            result = await adapter.analyze("prompt", "ctx")

        assert isinstance(result.model_name, str)
        assert len(result.model_name) > 0

    def test_get_model_info_returns_configured_model_name(self, adapter_name: str) -> None:
        """get_model_info().model_name matches the model passed at construction."""
        if adapter_name == "anthropic":
            with patch("anthropic.AsyncAnthropic"), patch.dict(
                "os.environ", {"ANTHROPIC_API_KEY": "test-key"}
            ):
                adapter = AnthropicAdapter(_anthropic_config("claude-opus-4-6"))
            expected_model = "claude-opus-4-6"
        else:
            adapter = OllamaAdapter(model="llama3")
            expected_model = "llama3"

        info = adapter.get_model_info()
        assert info.model_name == expected_model

    def test_get_model_info_provider_is_correct(self, adapter_name: str) -> None:
        """get_model_info().provider matches the adapter's provider name."""
        if adapter_name == "anthropic":
            with patch("anthropic.AsyncAnthropic"), patch.dict(
                "os.environ", {"ANTHROPIC_API_KEY": "test-key"}
            ):
                adapter = AnthropicAdapter(_anthropic_config("claude-opus-4-6"))
            expected_provider = "anthropic"
        else:
            adapter = OllamaAdapter(model="llama3")
            expected_provider = "ollama"

        info = adapter.get_model_info()
        assert info.provider == expected_provider


# ──────────────────────────────────────────────────────────────────────────────
# AC-3: Token count estimation
# ──────────────────────────────────────────────────────────────────────────────


class TestTokenCountEstimation:
    """get_token_count returns a non-negative integer that scales with text length."""

    def test_token_count_is_non_negative_integer(self, adapter_name: str) -> None:
        """get_token_count always returns a non-negative integer."""
        if adapter_name == "anthropic":
            with patch("anthropic.AsyncAnthropic"), patch.dict(
                "os.environ", {"ANTHROPIC_API_KEY": "test-key"}
            ):
                adapter = AnthropicAdapter(_anthropic_config("claude-opus-4-6"))
        else:
            adapter = OllamaAdapter(model="llama3")

        count = adapter.get_token_count("Hello, world!")
        assert isinstance(count, int)
        assert count >= 0

    def test_token_count_scales_with_text_length(self, adapter_name: str) -> None:
        """Longer text produces a higher token count than shorter text."""
        if adapter_name == "anthropic":
            with patch("anthropic.AsyncAnthropic"), patch.dict(
                "os.environ", {"ANTHROPIC_API_KEY": "test-key"}
            ):
                adapter = AnthropicAdapter(_anthropic_config("claude-opus-4-6"))
        else:
            adapter = OllamaAdapter(model="llama3")

        short = adapter.get_token_count("Hi")
        long = adapter.get_token_count(
            "This is a much longer sentence that should produce significantly more tokens "
            "than the short greeting above, because it contains many more characters and words."
        )
        assert long > short

    def test_token_count_empty_string_returns_zero_or_more(self, adapter_name: str) -> None:
        """get_token_count('') returns zero or a non-negative value."""
        if adapter_name == "anthropic":
            with patch("anthropic.AsyncAnthropic"), patch.dict(
                "os.environ", {"ANTHROPIC_API_KEY": "test-key"}
            ):
                adapter = AnthropicAdapter(_anthropic_config("claude-opus-4-6"))
        else:
            adapter = OllamaAdapter(model="llama3")

        count = adapter.get_token_count("")
        assert count >= 0


# ──────────────────────────────────────────────────────────────────────────────
# AC-4: Retry on transient failure (Anthropic adapter)
# ──────────────────────────────────────────────────────────────────────────────


class TestRetryOnTransientFailure:
    """AnthropicAdapter retries on 429/500 errors with exponential backoff.

    Ollama does not implement retry — transient network errors are surfaced
    immediately as OllamaConnectionError (tested in TestImmediateFailureOnError).
    """

    @pytest.mark.parametrize("adapter_name", ["anthropic"])
    async def test_retries_on_rate_limit_then_succeeds(self, adapter_name: str) -> None:
        """Given two 429 errors then success, the adapter succeeds and retries twice."""
        with _anthropic_transient_then_success("Analysis done.", "claude-opus-4-6", fail_count=2) as (
            adapter,
            mock_create,
        ):
            result = await adapter.analyze("Explain this.", "def f(): pass")

        assert isinstance(result, AnalysisResult)
        assert mock_create.call_count == 3  # 2 failures + 1 success

    @pytest.mark.parametrize("adapter_name", ["anthropic"])
    async def test_retries_on_internal_server_error_then_succeeds(self, adapter_name: str) -> None:
        """Given a 500 error then success, the adapter succeeds on the second attempt."""
        server_error = _anthropic_status_error(anthropic.InternalServerError, 500)
        mock_msg = _anthropic_mock_msg("Recovered.", "claude-opus-4-6")

        with patch("anthropic.AsyncAnthropic") as mock_cls, patch.dict(
            "os.environ", {"ANTHROPIC_API_KEY": "test-key"}
        ), patch("asyncio.sleep"):
            mock_create = AsyncMock(side_effect=[server_error, mock_msg])
            mock_cls.return_value.messages.create = mock_create
            adapter = AnthropicAdapter(_anthropic_config("claude-opus-4-6"))
            result = await adapter.analyze("prompt", "context")

        assert isinstance(result, AnalysisResult)
        assert mock_create.call_count == 2  # 1 failure + 1 success

    @pytest.mark.parametrize("adapter_name", ["anthropic"])
    async def test_raises_after_all_retries_exhausted(self, adapter_name: str) -> None:
        """Given all 4 attempts fail, the transient error is propagated."""
        rate_limit_err = _anthropic_status_error(anthropic.RateLimitError, 429)

        with patch("anthropic.AsyncAnthropic") as mock_cls, patch.dict(
            "os.environ", {"ANTHROPIC_API_KEY": "test-key"}
        ), patch("asyncio.sleep"):
            mock_create = AsyncMock(side_effect=rate_limit_err)
            mock_cls.return_value.messages.create = mock_create
            adapter = AnthropicAdapter(_anthropic_config("claude-opus-4-6"))

            with pytest.raises(anthropic.RateLimitError):
                await adapter.analyze("prompt", "context")

        assert mock_create.call_count == 4  # 1 initial + 3 retries


# ──────────────────────────────────────────────────────────────────────────────
# AC-5: Immediate failure on permanent error
# ──────────────────────────────────────────────────────────────────────────────


class TestImmediateFailureOnPermanentError:
    """Both adapters raise immediately (no retry) on permanent/unrecoverable errors."""

    @pytest.mark.parametrize("adapter_name", ["anthropic"])
    async def test_anthropic_raises_immediately_on_auth_error(self, adapter_name: str) -> None:
        """Given a 401 AuthenticationError, AnthropicAdapter raises without retrying."""
        with _anthropic_permanent_error() as (adapter, mock_create):
            with pytest.raises(anthropic.AuthenticationError):
                await adapter.analyze("prompt", "context")

        assert mock_create.call_count == 1  # no retries

    @pytest.mark.parametrize("adapter_name", ["ollama"])
    async def test_ollama_raises_immediately_on_model_not_found(self, adapter_name: str) -> None:
        """Given a model-not-found error, OllamaAdapter raises OllamaModelError immediately."""
        with _ollama_permanent_error("nonexistent-model") as (adapter, mock_post):
            with pytest.raises(OllamaModelError):
                await adapter.analyze("prompt", "context")

        assert mock_post.call_count == 1  # no retries

    @pytest.mark.parametrize("adapter_name", ["ollama"])
    async def test_ollama_raises_immediately_on_connection_error(self, adapter_name: str) -> None:
        """Given Ollama is unreachable, OllamaAdapter raises OllamaConnectionError immediately."""
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(
            side_effect=httpx.ConnectError("Connection refused")
        )
        with patch("apriori.adapters.ollama.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=None)
            adapter = OllamaAdapter(model="llama3")

            with pytest.raises(OllamaConnectionError):
                await adapter.analyze("prompt", "context")

        assert mock_client.post.call_count == 1  # no retries
