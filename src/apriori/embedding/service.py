"""EmbeddingService implementation using intfloat/e5-base-v2 (Story 2.4).

Model: intfloat/e5-base-v2 via sentence-transformers
Dimensions: 768
Prefix convention: "query: " for search, "passage: " for storage
"""

import logging
from typing import Literal

from sentence_transformers import SentenceTransformer

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
