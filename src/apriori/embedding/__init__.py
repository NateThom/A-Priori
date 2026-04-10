"""Embedding module for A-Priori (Story 2.4).

Provides EmbeddingServiceProtocol and EmbeddingService using
intfloat/e5-base-v2 via sentence-transformers (768-dimensional vectors).
"""

from apriori.embedding.protocol import EmbeddingServiceProtocol

try:
    from apriori.embedding.service import EmbeddingService
except ModuleNotFoundError:  # pragma: no cover - optional runtime dependency path
    EmbeddingService = None  # type: ignore[assignment]

__all__ = ["EmbeddingService", "EmbeddingServiceProtocol"]
