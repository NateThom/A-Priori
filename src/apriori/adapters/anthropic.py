"""Anthropic API adapter implementing the LLMAdapter protocol (Story 6.2, ERD §4.1.2).

Wraps the Anthropic Python SDK's async client. Retries transient errors (rate
limit, 500) with exponential backoff; raises immediately on persistent errors (401).
"""

from __future__ import annotations

import asyncio
import os

import anthropic

from apriori.adapters.base import AnalysisResult, ModelInfo
from apriori.config import LLMConfig

# Errors that indicate a transient failure — safe to retry.
_TRANSIENT_ERRORS = (anthropic.RateLimitError, anthropic.InternalServerError)

# Delay in seconds before each retry attempt (1st, 2nd, 3rd).
_RETRY_DELAYS: tuple[float, ...] = (1.0, 2.0, 4.0)

# Characters per token heuristic used by get_token_count.
_CHARS_PER_TOKEN = 4


class AnthropicAdapter:
    """LLMAdapter implementation backed by the Anthropic Messages API.

    Instantiate with an LLMConfig. The API key is read from the environment
    variable named in config.api_key_env at construction time.
    """

    def __init__(self, config: LLMConfig) -> None:
        api_key = os.environ.get(config.api_key_env)
        self._client = anthropic.AsyncAnthropic(api_key=api_key)
        self._model = config.model

    async def analyze(self, prompt: str, context: str) -> AnalysisResult:
        """Send prompt and context to the configured Claude model.

        Retries up to 3 times on transient errors (rate limit, 500) with
        exponential backoff delays of 1s, 2s, 4s. Raises immediately on
        persistent errors (e.g. 401 AuthenticationError).
        """
        last_error: Exception | None = None

        for attempt in range(len(_RETRY_DELAYS) + 1):  # up to 4 total attempts
            try:
                full_content = f"{context}\n\n{prompt}" if context else prompt
                message = await self._client.messages.create(
                    model=self._model,
                    max_tokens=4096,
                    messages=[{"role": "user", "content": full_content}],
                )
                content = message.content[0].text
                tokens_used = message.usage.input_tokens + message.usage.output_tokens
                return AnalysisResult(
                    content=content,
                    model_name=message.model,
                    tokens_used=tokens_used,
                    raw_response=message,
                )
            except anthropic.AuthenticationError:
                raise
            except _TRANSIENT_ERRORS as exc:
                last_error = exc
                if attempt < len(_RETRY_DELAYS):
                    await asyncio.sleep(_RETRY_DELAYS[attempt])

        raise last_error  # type: ignore[misc]

    def get_token_count(self, text: str) -> int:
        """Estimate token count using a ~4 characters-per-token heuristic."""
        return max(0, len(text) // _CHARS_PER_TOKEN)

    def get_model_info(self) -> ModelInfo:
        """Return metadata about the configured model."""
        return ModelInfo(
            model_name=self._model,
            provider="anthropic",
            context_window=200_000,
        )
