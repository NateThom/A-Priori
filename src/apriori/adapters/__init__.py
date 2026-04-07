"""LLM adapter protocol and types."""

from apriori.adapters.anthropic import AnthropicAdapter
from apriori.adapters.base import AnalysisResult, LLMAdapter, ModelInfo
from apriori.adapters.ollama import OllamaAdapter, OllamaConnectionError, OllamaModelError

__all__ = [
    "AnthropicAdapter",
    "AnalysisResult",
    "LLMAdapter",
    "ModelInfo",
    "OllamaAdapter",
    "OllamaConnectionError",
    "OllamaModelError",
]
