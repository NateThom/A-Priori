"""Tests for LLMAdapter protocol, AnalysisResult, and ModelInfo — AC: Story 6.1."""

import asyncio
import inspect

import pytest
from pydantic import ValidationError

from apriori.adapters.base import AnalysisResult, LLMAdapter, ModelInfo


# ---------------------------------------------------------------------------
# AC: Given the protocol definition, when inspected, then it includes
#     async analyze(prompt, context) -> AnalysisResult,
#     get_token_count(text) -> int, and get_model_info() -> ModelInfo.
# ---------------------------------------------------------------------------
class TestLLMAdapterProtocolShape:
    def test_protocol_has_analyze_method(self):
        assert hasattr(LLMAdapter, "analyze")

    def test_analyze_is_async(self):
        assert inspect.iscoroutinefunction(LLMAdapter.analyze)

    def test_protocol_has_get_token_count(self):
        assert hasattr(LLMAdapter, "get_token_count")

    def test_protocol_has_get_model_info(self):
        assert hasattr(LLMAdapter, "get_model_info")


# ---------------------------------------------------------------------------
# AC: Given the protocol, when analyze is called, then the response includes
#     content, model_name, tokens_used, and raw_response.
# ---------------------------------------------------------------------------
class TestAnalysisResult:
    def test_analysis_result_has_all_required_fields(self):
        result = AnalysisResult(
            content="This function parses Python source files.",
            model_name="claude-3-5-sonnet-20241022",
            tokens_used=42,
            raw_response={"id": "msg_123"},
        )
        assert result.content == "This function parses Python source files."
        assert result.model_name == "claude-3-5-sonnet-20241022"
        assert result.tokens_used == 42
        assert result.raw_response == {"id": "msg_123"}

    def test_analysis_result_missing_content_raises(self):
        with pytest.raises(ValidationError):
            AnalysisResult(model_name="m", tokens_used=1, raw_response={})

    def test_analysis_result_missing_model_name_raises(self):
        with pytest.raises(ValidationError):
            AnalysisResult(content="x", tokens_used=1, raw_response={})

    def test_analysis_result_missing_tokens_used_raises(self):
        with pytest.raises(ValidationError):
            AnalysisResult(content="x", model_name="m", raw_response={})

    def test_analysis_result_missing_raw_response_raises(self):
        with pytest.raises(ValidationError):
            AnalysisResult(content="x", model_name="m", tokens_used=1)

    def test_analysis_result_raw_response_accepts_none(self):
        result = AnalysisResult(
            content="analysis", model_name="m", tokens_used=0, raw_response=None
        )
        assert result.raw_response is None


# ---------------------------------------------------------------------------
# AC: Given the protocol, when reviewed, then adding a new provider requires
#     only implementing the protocol (structural subtyping).
# ---------------------------------------------------------------------------
class TestLLMAdapterProtocolCompliance:
    def test_complete_implementation_satisfies_protocol(self):
        class MockAdapter:
            async def analyze(self, prompt: str, context: str) -> AnalysisResult:
                return AnalysisResult(
                    content="analysis",
                    model_name="mock-model",
                    tokens_used=10,
                    raw_response=None,
                )

            def get_token_count(self, text: str) -> int:
                return len(text.split())

            def get_model_info(self) -> ModelInfo:
                return ModelInfo(model_name="mock-model", provider="mock")

        assert isinstance(MockAdapter(), LLMAdapter)

    def test_missing_get_token_count_fails_protocol(self):
        class IncompleteAdapter:
            async def analyze(self, prompt: str, context: str) -> AnalysisResult:
                return AnalysisResult(
                    content="analysis",
                    model_name="mock-model",
                    tokens_used=10,
                    raw_response=None,
                )

            def get_model_info(self) -> ModelInfo:
                return ModelInfo(model_name="mock-model", provider="mock")

        assert not isinstance(IncompleteAdapter(), LLMAdapter)

    def test_missing_get_model_info_fails_protocol(self):
        class IncompleteAdapter:
            async def analyze(self, prompt: str, context: str) -> AnalysisResult:
                return AnalysisResult(
                    content="analysis",
                    model_name="mock-model",
                    tokens_used=10,
                    raw_response=None,
                )

            def get_token_count(self, text: str) -> int:
                return len(text.split())

        assert not isinstance(IncompleteAdapter(), LLMAdapter)

    def test_analyze_coroutine_returns_analysis_result(self):
        class StubAdapter:
            async def analyze(self, prompt: str, context: str) -> AnalysisResult:
                return AnalysisResult(
                    content=f"Analysis of: {prompt}",
                    model_name="stub",
                    tokens_used=5,
                    raw_response={"prompt": prompt},
                )

            def get_token_count(self, text: str) -> int:
                return len(text.split())

            def get_model_info(self) -> ModelInfo:
                return ModelInfo(model_name="stub", provider="test")

        adapter = StubAdapter()
        result = asyncio.run(adapter.analyze("Explain parse_file", "def parse_file(): ..."))
        assert isinstance(result, AnalysisResult)
        assert result.content == "Analysis of: Explain parse_file"
        assert result.tokens_used == 5


# ---------------------------------------------------------------------------
# ModelInfo tests
# ---------------------------------------------------------------------------
class TestModelInfo:
    def test_model_info_required_fields(self):
        info = ModelInfo(model_name="claude-3-opus-20240229", provider="anthropic")
        assert info.model_name == "claude-3-opus-20240229"
        assert info.provider == "anthropic"
        assert info.context_window is None

    def test_model_info_with_context_window(self):
        info = ModelInfo(
            model_name="llama3", provider="ollama", context_window=128000
        )
        assert info.context_window == 128000

    def test_model_info_missing_model_name_raises(self):
        with pytest.raises(ValidationError):
            ModelInfo(provider="anthropic")

    def test_model_info_missing_provider_raises(self):
        with pytest.raises(ValidationError):
            ModelInfo(model_name="claude-3-opus-20240229")
