"""Tests for Story 10.1 AC-10: Semantic anchor fallback in code reference resolution.

AC traceability:
AC-10: Given the LLM adapter is now available, when a code reference's symbol and hash
       both fail, then the semantic anchor fallback path correctly invokes the LLM.
"""

from __future__ import annotations

import hashlib
from unittest.mock import AsyncMock, MagicMock

import pytest

from apriori.adapters.base import AnalysisResult, ModelInfo
from apriori.librarian.reference_resolver import (
    _find_by_content_hash,
    _find_by_symbol,
    resolve_code_reference,
)
from apriori.models.concept import CodeReference


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SAMPLE_FILE = """\
def foo_function(x: int) -> str:
    \"\"\"Converts an integer to its string representation with validation.\"\"\"
    if x < 0:
        raise ValueError("x must be non-negative")
    return str(x)


class BarClass:
    \"\"\"Manages bar-related operations with thread safety.\"\"\"

    def __init__(self, name: str) -> None:
        self.name = name

    def process(self) -> str:
        return f"processed:{self.name}"
"""


def _make_code_ref(
    symbol: str = "foo_function",
    file_path: str = "test.py",
    content_hash: str | None = None,
    semantic_anchor: str = "A function that converts integers to strings with validation.",
) -> CodeReference:
    if content_hash is None:
        content_hash = "a" * 64  # invalid hash (won't match)
    return CodeReference(
        symbol=symbol,
        file_path=file_path,
        content_hash=content_hash,
        semantic_anchor=semantic_anchor,
    )


def _make_adapter(response: str) -> MagicMock:
    adapter = MagicMock()
    adapter.get_model_info.return_value = ModelInfo(
        name="test-model", provider="test", context_window=100000, cost_per_token=0.0
    )

    async def _analyze(prompt: str, context: str) -> AnalysisResult:
        return AnalysisResult(
            content=response,
            model_name="test-model",
            tokens_used=50,
            raw_response={},
        )

    adapter.analyze = _analyze
    return adapter


# ---------------------------------------------------------------------------
# Symbol lookup tests
# ---------------------------------------------------------------------------

class TestSymbolLookup:
    def test_finds_function_by_symbol_name(self):
        """Given a file containing the symbol, _find_by_symbol returns the definition."""
        result = _find_by_symbol("foo_function", _SAMPLE_FILE)
        assert result is not None
        assert "foo_function" in result
        assert "ValueError" in result

    def test_finds_class_by_symbol_name(self):
        """Given a file containing a class, _find_by_symbol returns the class body."""
        result = _find_by_symbol("BarClass", _SAMPLE_FILE)
        assert result is not None
        assert "BarClass" in result

    def test_returns_none_for_missing_symbol(self):
        """Given a symbol not in the file, _find_by_symbol returns None."""
        result = _find_by_symbol("NonExistentSymbol", _SAMPLE_FILE)
        assert result is None


# ---------------------------------------------------------------------------
# Content hash lookup tests
# ---------------------------------------------------------------------------

class TestContentHashLookup:
    def test_finds_block_by_correct_hash(self):
        """Given a valid SHA-256 hash of a block, _find_by_content_hash returns it."""
        # Pick a block from the sample file
        block = "def foo_function(x: int) -> str:\n    \"\"\"Converts an integer to its string representation with validation.\"\"\"\n    if x < 0:\n        raise ValueError(\"x must be non-negative\")\n    return str(x)"
        block_hash = hashlib.sha256(block.encode()).hexdigest()

        result = _find_by_content_hash(block_hash, _SAMPLE_FILE)
        assert result is not None
        assert "foo_function" in result

    def test_returns_none_for_wrong_hash(self):
        """Given a hash that doesn't match any block, returns None."""
        result = _find_by_content_hash("a" * 64, _SAMPLE_FILE)
        assert result is None


# ---------------------------------------------------------------------------
# Semantic anchor fallback tests (AC-10)
# ---------------------------------------------------------------------------

class TestSemanticAnchorFallback:
    @pytest.mark.asyncio
    async def test_llm_invoked_when_symbol_and_hash_fail(self):
        """Given symbol and hash both fail, LLM is called with the semantic anchor."""
        from apriori.librarian.reference_resolver import _resolve_via_semantic_anchor

        llm_calls: list[str] = []
        adapter = MagicMock()
        adapter.get_model_info.return_value = ModelInfo(
            name="test-model", provider="test", context_window=100000, cost_per_token=0.0
        )

        async def _analyze(prompt: str, context: str) -> AnalysisResult:
            llm_calls.append(prompt)
            return AnalysisResult(
                content="def foo(): pass",
                model_name="test-model",
                tokens_used=10,
                raw_response={},
            )

        adapter.analyze = _analyze

        ref = _make_code_ref(
            symbol="missing_symbol",
            content_hash="a" * 64,
            semantic_anchor="A function that validates and converts integers.",
        )

        result = await _resolve_via_semantic_anchor(
            ref.semantic_anchor, ref.symbol, _SAMPLE_FILE, adapter
        )

        assert len(llm_calls) == 1
        assert ref.semantic_anchor in llm_calls[0]
        assert result == "def foo(): pass"

    @pytest.mark.asyncio
    async def test_resolve_code_reference_uses_symbol_first(self):
        """Given symbol match in file, resolve_code_reference returns it without LLM call."""
        llm_call_count = [0]
        adapter = MagicMock()
        adapter.get_model_info.return_value = ModelInfo(
            name="test-model", provider="test", context_window=100000, cost_per_token=0.0
        )

        async def _analyze(prompt: str, context: str) -> AnalysisResult:
            llm_call_count[0] += 1
            return AnalysisResult(
                content="fallback", model_name="test-model", tokens_used=5, raw_response={}
            )

        adapter.analyze = _analyze

        ref = _make_code_ref(symbol="foo_function", content_hash="a" * 64)
        result = await resolve_code_reference(ref, _SAMPLE_FILE, adapter)

        assert result is not None
        assert "foo_function" in result
        assert llm_call_count[0] == 0  # LLM not called

    @pytest.mark.asyncio
    async def test_resolve_code_reference_falls_back_to_llm(self):
        """Given both symbol and hash fail, resolve_code_reference invokes LLM."""
        llm_response = "def missing_symbol(): return 42"
        adapter = _make_adapter(llm_response)

        ref = _make_code_ref(
            symbol="missing_symbol",
            content_hash="a" * 64,
            semantic_anchor="A function that returns 42 with no inputs.",
        )
        result = await resolve_code_reference(ref, _SAMPLE_FILE, adapter)

        assert result == llm_response

    @pytest.mark.asyncio
    async def test_resolve_code_reference_returns_none_on_empty_llm_response(self):
        """Given LLM returns empty string, resolve_code_reference returns None."""
        adapter = _make_adapter("")

        ref = _make_code_ref(
            symbol="missing_symbol",
            content_hash="a" * 64,
            semantic_anchor="Something that is missing.",
        )
        result = await resolve_code_reference(ref, _SAMPLE_FILE, adapter)

        assert result is None
