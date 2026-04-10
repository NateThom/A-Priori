"""EmbeddingService implementation using intfloat/e5-base-v2 (Story 2.4).

Model: intfloat/e5-base-v2 via sentence-transformers
Dimensions: 768
Prefix convention: "query: " for search, "passage: " for storage
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Literal

from sentence_transformers import SentenceTransformer

if TYPE_CHECKING:
    from apriori.storage.protocol import KnowledgeStore

logger = logging.getLogger(__name__)

_MODEL_NAME = "intfloat/e5-base-v2"
_DIMENSIONS = 768


class EmbeddingService:
    """Generates 768-dimensional text embeddings using intfloat/e5-base-v2.

    The model is downloaded on first initialization (~440MB) and cached by
    sentence-transformers in the default Hugging Face cache directory.
    Subsequent instantiations load from the local cache (2–5 seconds).

    Usage:
        service = EmbeddingService()
        # For storing a concept description:
        vec = service.generate_embedding("Parses Python AST nodes.", text_type="passage")
        # For a search query:
        vec = service.generate_embedding("find AST parsing code", text_type="query")
    """

    def __init__(self) -> None:
        print(
            f"Loading embedding model {_MODEL_NAME} (~440MB on first run, cached afterwards)..."
        )
        logger.info("Loading embedding model %s", _MODEL_NAME)
        self._model: SentenceTransformer = SentenceTransformer(_MODEL_NAME)
        logger.info("Embedding model %s loaded successfully", _MODEL_NAME)
        print(f"Embedding model {_MODEL_NAME} ready.")

    def generate_embedding(
        self,
        text: str,
        text_type: Literal["query", "passage"] = "passage",
    ) -> list[float]:
        """Generate a 768-dimensional embedding for the given text.

        Applies the e5-base-v2 required prefix automatically:
        - "query: " for search queries
        - "passage: " for documents (default)

        Args:
            text: The text to embed.
            text_type: Context type that determines the prefix applied.
                       Defaults to "passage" for document storage.

        Returns:
            List of 768 floats (L2-normalised).
        """
        prefix = "query: " if text_type == "query" else "passage: "
        prefixed = prefix + text
        vector = self._model.encode(prefixed, normalize_embeddings=True)
        return vector.tolist()

    def embed_all(self, store: KnowledgeStore, batch_size: int = 32) -> int:
        """Generate and store embeddings for all concepts in the store.

        Reads all Concepts via the KnowledgeStore protocol, generates a
        768-dimensional passage embedding for each concept's description, and
        writes the result back via ``store.store_embedding`` (arch:no-raw-sql,
        arch:core-lib-thin-shells).

        Args:
            store: The KnowledgeStore to read concepts from and write embeddings
                to. Must implement ``list_concepts()`` and ``store_embedding()``.
            batch_size: Number of concepts to process before printing progress.
                Does not affect embedding quality. Defaults to 32.

        Returns:
            The number of concepts embedded.
        """
        concepts = store.list_concepts()
        if not concepts:
            return 0

        total = len(concepts)
        print(f"  Embedding {total} concept(s)…")

        for i in range(0, total, batch_size):
            batch = concepts[i : i + batch_size]
            for concept in batch:
                vector = self.generate_embedding(concept.description, text_type="passage")
                store.store_embedding(concept.id, vector)
            done = min(i + batch_size, total)
            print(f"    Embedded {done}/{total}", end="\r")

        print(f"  Embeddings complete: {total} concept(s)")
        return total
