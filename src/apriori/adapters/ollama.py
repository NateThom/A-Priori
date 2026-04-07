"""Ollama LLM adapter — wraps Ollama HTTP API (Story 6.3, ERD §4.1.2).

Implements the LLMAdapter protocol for locally-running Ollama instances.
All network calls use httpx.AsyncClient. Token counting uses a heuristic
(characters / 4) since Ollama does not expose a tokenizer endpoint.

Error handling:
- OllamaConnectionError: Ollama process is not reachable (ConnectError).
- OllamaModelError: The requested model has not been pulled locally.
"""

from __future__ import annotations

import httpx

from apriori.adapters.base import AnalysisResult, ModelInfo


class OllamaConnectionError(RuntimeError):
    """Raised when the Ollama service cannot be reached."""


class OllamaModelError(RuntimeError):
    """Raised when the requested model is not available locally."""


class OllamaAdapter:
    """LLM adapter for the Ollama HTTP API.

    Args:
        model: Ollama model name (e.g. "llama3", "mistral:7b").
        base_url: Base URL for the Ollama API. Defaults to http://localhost:11434.
    """

    def __init__(
        self,
        model: str,
        base_url: str = "http://localhost:11434",
    ) -> None:
        self._model = model
        self._base_url = base_url.rstrip("/")

    async def analyze(self, prompt: str, context: str) -> AnalysisResult:
        """Send prompt + context to Ollama and return the analysis result.

        Raises:
            OllamaConnectionError: If Ollama is not running or unreachable.
            OllamaModelError: If the model has not been pulled locally.
            RuntimeError: For other Ollama API errors.
        """
        full_prompt = f"{context}\n\n{prompt}" if context else prompt

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self._base_url}/api/generate",
                    json={"model": self._model, "prompt": full_prompt, "stream": False},
                    timeout=120.0,
                )
        except httpx.ConnectError:
            raise OllamaConnectionError(
                "Ollama is not running. Start it with `ollama serve` or check if"
                " it's running on the configured port."
            )

        data = response.json()

        # Ollama returns errors in the JSON body regardless of status code.
        if "error" in data:
            self._raise_for_error(data["error"])

        if response.status_code == 404:
            raise OllamaModelError(
                f"Model '{self._model}' not found."
                f" Try pulling it first: `ollama pull {self._model}`"
            )

        response.raise_for_status()

        tokens_used = (
            data.get("prompt_eval_count", 0) + data.get("eval_count", 0)
            or self.get_token_count(full_prompt) + self.get_token_count(data["response"])
        )

        return AnalysisResult(
            content=data["response"],
            model_name=data["model"],
            tokens_used=tokens_used,
            raw_response=data,
        )

    def _raise_for_error(self, error_msg: str) -> None:
        """Translate an Ollama error string into the appropriate exception."""
        if "not found" in error_msg:
            raise OllamaModelError(
                f"Model '{self._model}' not found."
                f" Try pulling it first: `ollama pull {self._model}`"
            )
        raise RuntimeError(f"Ollama error: {error_msg}")

    def get_token_count(self, text: str) -> int:
        """Estimate token count using the characters/4 heuristic."""
        return len(text) // 4

    def get_model_info(self) -> ModelInfo:
        """Return metadata about the Ollama model."""
        return ModelInfo(model_name=self._model, provider="ollama")
