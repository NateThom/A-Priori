"""EmbeddingService protocol (arch:protocol-first).

Defines the interface consumed by storage (Layer 2) and retrieval (Layer 3)
so that those layers depend on the protocol, not the concrete implementation.
"""

from typing import Literal, Protocol, runtime_checkable


@runtime_checkable
class EmbeddingServiceProtocol(Protocol):
    """Protocol for generating text embeddings.

    Implementations must apply the e5-base-v2 prefix convention:
    - "query: " prefix for search queries
    - "passage: " prefix for documents being stored
    """

    def generate_embedding(
        self,
        text: str,
        text_type: Literal["query", "passage"] = "passage",
    ) -> list[float]:
        """Generate an embedding vector for the given text.

        Args:
            text: The text to embed.
            text_type: "passage" for documents being stored (default),
                       "query" for search queries.

        Returns:
            A list of floats with length equal to the model's output dimensions.
        """
        ...
