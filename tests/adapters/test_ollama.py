"""Tests for OllamaAdapter — AC: Story 6.3 (ERD §4.1.2)."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from apriori.adapters.base import AnalysisResult, LLMAdapter, ModelInfo
from apriori.adapters.ollama import OllamaAdapter, OllamaConnectionError, OllamaModelError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_client(response_data: dict, status_code: int = 200):
    """Return a mocked httpx.AsyncClient that returns the given response."""
    mock_response = MagicMock()
    mock_response.status_code = status_code
    mock_response.json.return_value = response_data
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)
    return mock_client


def _patch_client(mock_client):
    """Patch httpx.AsyncClient as a context manager returning mock_client."""
    patcher = patch("apriori.adapters.ollama.httpx.AsyncClient")
    mock_cls = patcher.start()
    mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
    mock_cls.return_value.__aexit__ = AsyncMock(return_value=None)
    return patcher


# ---------------------------------------------------------------------------
# AC: Protocol compliance — OllamaAdapter satisfies LLMAdapter
# ---------------------------------------------------------------------------
class TestOllamaAdapterProtocolCompliance:
    def test_satisfies_llm_adapter_protocol(self):
        """Given OllamaAdapter, when checked, then isinstance(adapter, LLMAdapter) is True."""
        adapter = OllamaAdapter(model="llama3")
        assert isinstance(adapter, LLMAdapter)

    def test_has_analyze_method(self):
        adapter = OllamaAdapter(model="llama3")
        assert hasattr(adapter, "analyze")

    def test_has_get_token_count_method(self):
        adapter = OllamaAdapter(model="llama3")
        assert hasattr(adapter, "get_token_count")

    def test_has_get_model_info_method(self):
        adapter = OllamaAdapter(model="llama3")
        assert hasattr(adapter, "get_model_info")


# ---------------------------------------------------------------------------
# AC: Given running Ollama + loaded model, when analyze is called,
#     then returns AnalysisResult with correct fields.
# ---------------------------------------------------------------------------
class TestOllamaAdapterSuccessfulAnalysis:
    async def test_analyze_returns_analysis_result(self):
        """Given a successful Ollama response, analyze returns an AnalysisResult."""
        mock_client = _make_mock_client({
            "model": "llama3",
            "response": "The sky is blue due to Rayleigh scattering.",
            "done": True,
        })
        patcher = _patch_client(mock_client)
        try:
            adapter = OllamaAdapter(model="llama3")
            result = await adapter.analyze("Why is the sky blue?", "")
        finally:
            patcher.stop()

        assert isinstance(result, AnalysisResult)
        assert result.content == "The sky is blue due to Rayleigh scattering."

    async def test_analyze_model_name_matches_ollama_model_string(self):
        """Given a successful response, model_name in AnalysisResult matches the Ollama model string."""
        mock_client = _make_mock_client({
            "model": "mistral:latest",
            "response": "Some analysis.",
            "done": True,
        })
        patcher = _patch_client(mock_client)
        try:
            adapter = OllamaAdapter(model="mistral:latest")
            result = await adapter.analyze("Explain this", "context here")
        finally:
            patcher.stop()

        assert result.model_name == "mistral:latest"

    async def test_analyze_raw_response_contains_full_json(self):
        """Given a successful response, raw_response contains the full Ollama JSON."""
        response_data = {
            "model": "llama3",
            "response": "Analysis complete.",
            "done": True,
            "total_duration": 1234567,
        }
        mock_client = _make_mock_client(response_data)
        patcher = _patch_client(mock_client)
        try:
            adapter = OllamaAdapter(model="llama3")
            result = await adapter.analyze("Analyze this", "")
        finally:
            patcher.stop()

        assert result.raw_response == response_data

    async def test_analyze_posts_to_generate_endpoint(self):
        """Given analyze is called, it POSTs to /api/generate."""
        mock_client = _make_mock_client({
            "model": "llama3",
            "response": "result",
            "done": True,
        })
        patcher = _patch_client(mock_client)
        try:
            adapter = OllamaAdapter(model="llama3")
            await adapter.analyze("prompt", "context")
        finally:
            patcher.stop()

        mock_client.post.assert_called_once()
        call_args = mock_client.post.call_args
        assert "/api/generate" in call_args[0][0]

    async def test_analyze_sends_stream_false(self):
        """Given analyze is called, it sends stream=False to get a single response."""
        mock_client = _make_mock_client({
            "model": "llama3",
            "response": "result",
            "done": True,
        })
        patcher = _patch_client(mock_client)
        try:
            adapter = OllamaAdapter(model="llama3")
            await adapter.analyze("prompt", "")
        finally:
            patcher.stop()

        call_kwargs = mock_client.post.call_args[1]
        assert call_kwargs["json"]["stream"] is False

    async def test_analyze_tokens_used_is_positive_integer(self):
        """Given a successful response, tokens_used is a positive integer."""
        mock_client = _make_mock_client({
            "model": "llama3",
            "response": "Some analysis text here.",
            "done": True,
        })
        patcher = _patch_client(mock_client)
        try:
            adapter = OllamaAdapter(model="llama3")
            result = await adapter.analyze("What is gravity?", "Physics context.")
        finally:
            patcher.stop()

        assert isinstance(result.tokens_used, int)
        assert result.tokens_used >= 0


# ---------------------------------------------------------------------------
# AC: Given Ollama is not running, when analyze is called,
#     then raises OllamaConnectionError with clear message.
# ---------------------------------------------------------------------------
class TestOllamaAdapterConnectionError:
    async def test_ollama_not_running_raises_connection_error(self):
        """Given Ollama is not running, analyze raises OllamaConnectionError."""
        with patch("apriori.adapters.ollama.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(
                side_effect=httpx.ConnectError("Connection refused")
            )
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=None)

            adapter = OllamaAdapter(model="llama3")
            with pytest.raises(OllamaConnectionError):
                await adapter.analyze("prompt", "")

    async def test_connection_error_message_mentions_ollama_serve(self):
        """Given Ollama not running, error message mentions 'ollama serve'."""
        with patch("apriori.adapters.ollama.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(
                side_effect=httpx.ConnectError("Connection refused")
            )
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=None)

            adapter = OllamaAdapter(model="llama3")
            with pytest.raises(OllamaConnectionError, match="ollama serve"):
                await adapter.analyze("prompt", "")

    async def test_connection_error_message_exact_text(self):
        """Given Ollama not running, error message matches the required text."""
        with patch("apriori.adapters.ollama.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(
                side_effect=httpx.ConnectError("Connection refused")
            )
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=None)

            adapter = OllamaAdapter(model="llama3")
            with pytest.raises(OllamaConnectionError) as exc_info:
                await adapter.analyze("prompt", "")

        assert "Ollama is not running" in str(exc_info.value)
        assert "ollama serve" in str(exc_info.value)


# ---------------------------------------------------------------------------
# AC: Given model not pulled, when analyze is called, then error mentions
#     model name and suggests `ollama pull <model>`.
# ---------------------------------------------------------------------------
class TestOllamaAdapterModelNotFound:
    async def test_model_not_found_raises_model_error(self):
        """Given model not pulled, analyze raises OllamaModelError."""
        mock_client = _make_mock_client(
            {"error": "model 'unknown-model' not found, try pulling it first"},
            status_code=200,
        )
        patcher = _patch_client(mock_client)
        try:
            adapter = OllamaAdapter(model="unknown-model")
            with pytest.raises(OllamaModelError):
                await adapter.analyze("prompt", "")
        finally:
            patcher.stop()

    async def test_model_not_found_error_mentions_model_name(self):
        """Given model not pulled, error message mentions the model name."""
        mock_client = _make_mock_client(
            {"error": "model 'codellama:13b' not found, try pulling it first"},
            status_code=200,
        )
        patcher = _patch_client(mock_client)
        try:
            adapter = OllamaAdapter(model="codellama:13b")
            with pytest.raises(OllamaModelError, match="codellama:13b"):
                await adapter.analyze("prompt", "")
        finally:
            patcher.stop()

    async def test_model_not_found_error_suggests_ollama_pull(self):
        """Given model not pulled, error message suggests 'ollama pull <model>'."""
        mock_client = _make_mock_client(
            {"error": "model 'codellama:13b' not found, try pulling it first"},
            status_code=200,
        )
        patcher = _patch_client(mock_client)
        try:
            adapter = OllamaAdapter(model="codellama:13b")
            with pytest.raises(OllamaModelError, match="ollama pull codellama:13b"):
                await adapter.analyze("prompt", "")
        finally:
            patcher.stop()

    async def test_model_not_found_via_404_status(self):
        """Given Ollama returns 404, analyze raises OllamaModelError."""
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.json.return_value = {
            "error": "model 'no-such-model' not found"
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch("apriori.adapters.ollama.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=None)

            adapter = OllamaAdapter(model="no-such-model")
            with pytest.raises(OllamaModelError):
                await adapter.analyze("prompt", "")


# ---------------------------------------------------------------------------
# Token counting and model info
# ---------------------------------------------------------------------------
class TestOllamaAdapterTokenCountAndModelInfo:
    def test_get_token_count_uses_character_heuristic(self):
        """get_token_count returns len(text) // 4 as documented heuristic."""
        adapter = OllamaAdapter(model="llama3")
        text = "Hello, world!"  # 13 chars → 3 tokens
        assert adapter.get_token_count(text) == len(text) // 4

    def test_get_token_count_empty_string(self):
        adapter = OllamaAdapter(model="llama3")
        assert adapter.get_token_count("") == 0

    def test_get_token_count_long_text(self):
        adapter = OllamaAdapter(model="llama3")
        text = "a" * 400
        assert adapter.get_token_count(text) == 100

    def test_get_model_info_provider_is_ollama(self):
        """get_model_info returns ModelInfo with provider='ollama'."""
        adapter = OllamaAdapter(model="llama3")
        info = adapter.get_model_info()
        assert isinstance(info, ModelInfo)
        assert info.provider == "ollama"

    def test_get_model_info_name_matches_init(self):
        # Given: ERD §3.1.6 specifies field name as 'name' not 'model_name'
        # When: get_model_info() is called on an OllamaAdapter
        # Then: info.name resolves to the model string without AttributeError
        adapter = OllamaAdapter(model="mistral:7b")
        info = adapter.get_model_info()
        assert info.name == "mistral:7b"

    def test_get_model_info_cost_per_token_is_zero(self):
        # Given: Ollama is a local/free inference engine (ERD §3.1.6)
        # When: get_model_info() is called on an OllamaAdapter
        # Then: cost_per_token is 0.0 (no cost for local inference)
        adapter = OllamaAdapter(model="llama3")
        info = adapter.get_model_info()
        assert info.cost_per_token == 0.0

    def test_get_model_info_context_window_is_int(self):
        # Given: ERD §3.1.6 requires context_window: int (not optional)
        # When: get_model_info() is called on an OllamaAdapter
        # Then: context_window is an int (not None)
        adapter = OllamaAdapter(model="llama3")
        info = adapter.get_model_info()
        assert isinstance(info.context_window, int)
        assert info.context_window > 0

    def test_custom_base_url(self):
        """OllamaAdapter accepts a custom base_url."""
        adapter = OllamaAdapter(model="llama3", base_url="http://192.168.1.100:11434")
        # If model info is correct, init succeeded
        info = adapter.get_model_info()
        assert info.name == "llama3"

    async def test_analyze_uses_custom_base_url(self):
        """Given a custom base_url, analyze POSTs to that URL."""
        mock_client = _make_mock_client({
            "model": "llama3",
            "response": "result",
            "done": True,
        })
        patcher = _patch_client(mock_client)
        try:
            adapter = OllamaAdapter(model="llama3", base_url="http://remote:11434")
            await adapter.analyze("prompt", "")
        finally:
            patcher.stop()

        call_args = mock_client.post.call_args
        assert "http://remote:11434" in call_args[0][0]


# ---------------------------------------------------------------------------
# AC-114-2: LLMConfig-based constructor (uniform construction from config)
# ---------------------------------------------------------------------------
class TestOllamaAdapterLLMConfigConstructor:
    """OllamaAdapter must accept an LLMConfig object as its first argument."""

    def test_constructs_from_llm_config(self):
        """Given an LLMConfig with provider='ollama', OllamaAdapter(config) succeeds."""
        from apriori.config import LLMConfig
        config = LLMConfig(
            provider="ollama",
            model="llama3",
            base_url="http://localhost:11434",
        )
        adapter = OllamaAdapter(config)
        info = adapter.get_model_info()
        assert info.name == "llama3"
        assert info.provider == "ollama"

    def test_llm_config_base_url_is_used(self):
        """Given LLMConfig with custom base_url, the adapter uses that URL."""
        from apriori.config import LLMConfig
        config = LLMConfig(
            provider="ollama",
            model="mistral:7b",
            base_url="http://192.168.1.50:11434",
        )
        adapter = OllamaAdapter(config)
        # Inspect internal state to verify URL was extracted from config
        assert "192.168.1.50" in adapter._base_url

    def test_llm_config_model_is_used(self):
        """Given LLMConfig with model='llama3', the adapter uses that model."""
        from apriori.config import LLMConfig
        config = LLMConfig(
            provider="ollama",
            model="llama3",
            base_url="http://localhost:11434",
        )
        adapter = OllamaAdapter(config)
        assert adapter._model == "llama3"

    def test_backward_compat_string_constructor_still_works(self):
        """Given OllamaAdapter(model='llama3'), backward-compat still works."""
        adapter = OllamaAdapter(model="llama3")
        assert adapter._model == "llama3"

    def test_backward_compat_with_custom_base_url(self):
        """Given OllamaAdapter(model=..., base_url=...), backward-compat still works."""
        adapter = OllamaAdapter(model="llama3", base_url="http://custom:11434")
        assert "custom" in adapter._base_url


# ---------------------------------------------------------------------------
# AC-114-3: Prompt/context ordering — context first (Ollama already does this,
#            verify it matches the new Anthropic behavior)
# ---------------------------------------------------------------------------
class TestOllamaAdapterPromptOrdering:
    """OllamaAdapter.analyze must send context-first: f'{context}\\n\\n{prompt}'."""

    async def test_context_sent_before_prompt(self):
        """Given prompt and context, when analyze is called,
        then the request prompt is context + newlines + prompt.
        """
        mock_client = _make_mock_client({
            "model": "llama3",
            "response": "result",
            "done": True,
            "prompt_eval_count": 10,
            "eval_count": 5,
        })
        patcher = _patch_client(mock_client)
        try:
            adapter = OllamaAdapter(model="llama3")
            await adapter.analyze("Explain this", "def f(): pass")
        finally:
            patcher.stop()

        call_kwargs = mock_client.post.call_args[1]
        sent_prompt = call_kwargs["json"]["prompt"]
        assert sent_prompt == "def f(): pass\n\nExplain this"

    async def test_empty_context_sends_only_prompt(self):
        """Given empty context, when analyze is called, then only the prompt is sent."""
        mock_client = _make_mock_client({
            "model": "llama3",
            "response": "result",
            "done": True,
        })
        patcher = _patch_client(mock_client)
        try:
            adapter = OllamaAdapter(model="llama3")
            await adapter.analyze("Explain this", "")
        finally:
            patcher.stop()

        call_kwargs = mock_client.post.call_args[1]
        sent_prompt = call_kwargs["json"]["prompt"]
        assert sent_prompt == "Explain this"
