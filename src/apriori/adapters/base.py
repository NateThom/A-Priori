"""LLM adapter protocol and result types (Story 6.1, ERD §4.1.1).

Adding a new LLM provider requires only implementing the LLMAdapter protocol:

    class MyAdapter:
        async def analyze(self, prompt: str, context: str) -> AnalysisResult: ...
        def get_token_count(self, text: str) -> int: ...
        def get_model_info(self) -> ModelInfo: ...

No base class inheritance required. The protocol is structurally typed — any class
with matching method signatures satisfies it. Use @runtime_checkable for isinstance()
checks in tests and factory code.

Retry logic, rate-limit handling, and telemetry belong in a shared mixin or wrapper,
not in the protocol. Keep adapter implementations minimal.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel


class AnalysisResult(BaseModel):
    """Result returned by LLMAdapter.analyze().

    Fields:
        content: The LLM's textual analysis response.
        model_name: The model that produced the response (e.g. "claude-3-5-sonnet-20241022").
        tokens_used: Total tokens consumed by the request (prompt + completion).
        raw_response: Provider-specific raw response object for debugging or metadata access.
    """

    content: str
    model_name: str
    tokens_used: int
    raw_response: Any


class ModelInfo(BaseModel):
    """Metadata about the LLM model backing an adapter.

    Fields:
        model_name: Model identifier as used by the provider API.
        provider: Provider name (e.g. "anthropic", "ollama").
        context_window: Maximum token context supported, if known.
    """

    model_name: str
    provider: str
    context_window: int | None = None


@runtime_checkable
class LLMAdapter(Protocol):
    """Protocol for LLM provider adapters.

    All LLM calls in the A-Priori system go through this protocol (arch:adapter-pattern).
    The analyze method is async because it performs network I/O. get_token_count and
    get_model_info are synchronous — they return local data without network calls.
    """

    async def analyze(self, prompt: str, context: str) -> AnalysisResult:
        """Send a prompt and context to the LLM; return the analysis result."""
        ...

    def get_token_count(self, text: str) -> int:
        """Return the number of tokens in text according to this model's tokenizer."""
        ...

    def get_model_info(self) -> ModelInfo:
        """Return metadata about the underlying model."""
        ...
