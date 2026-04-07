"""Tests for EmbeddingService — AC traceability: Story 2.4.

Acceptance Criteria:
  AC1: Given the EmbeddingService is initialized, when the model is not cached,
       then it downloads and caches the model with a clear progress message.
  AC2: Given a concept description string, when generate_embedding is called,
       then it returns a 768-dimensional float array.
  AC3: Given two semantically similar descriptions, when embeddings are generated
       and cosine similarity computed, then similarity is above 0.7.
  AC4: Given two unrelated descriptions, when cosine similarity is computed,
       then similarity is below the similar-pair threshold.
  AC5: Given the e5-base-v2 model requirement for "query: " and "passage: " prefixes,
       when embeddings are generated, then the correct prefix is applied automatically.
"""

import math
import time
from typing import Literal
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from apriori.embedding.service import EmbeddingService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def cosine_similarity(a: list[float], b: list[float]) -> float:
    va = np.array(a, dtype=float)
    vb = np.array(b, dtype=float)
    denom = np.linalg.norm(va) * np.linalg.norm(vb)
    if denom == 0:
        return 0.0
    return float(np.dot(va, vb) / denom)


# Session-scoped fixture: load the model once for the whole test session.
@pytest.fixture(scope="session")
def service() -> EmbeddingService:
    return EmbeddingService()


# ---------------------------------------------------------------------------
# AC1: Model initialization emits a clear progress message
# Given the EmbeddingService is initialized, when the model is not cached,
# then it downloads and caches the model with a clear progress message.
# ---------------------------------------------------------------------------
class TestModelInitialization:
    def test_progress_message_printed_to_stdout_on_init(self, capsys):
        """
        Given EmbeddingService is being initialized,
        when SentenceTransformer is loaded,
        then a human-readable progress message is printed to stdout.
        """
        mock_model = MagicMock()
        mock_model.encode.return_value = np.zeros(768, dtype=np.float32)

        with patch("apriori.embedding.service.SentenceTransformer", return_value=mock_model):
            EmbeddingService()

        captured = capsys.readouterr()
        assert captured.out.strip(), "Expected a progress message on stdout"
        # Must mention the model name so users know what is being loaded
        assert "e5-base-v2" in captured.out

    def test_model_is_stored_after_init(self):
        """
        Given EmbeddingService is initialized,
        when queried for its internal model,
        then the model object is not None.
        """
        mock_model = MagicMock()
        mock_model.encode.return_value = np.zeros(768, dtype=np.float32)

        with patch("apriori.embedding.service.SentenceTransformer", return_value=mock_model):
            svc = EmbeddingService()

        assert svc._model is not None


# ---------------------------------------------------------------------------
# AC2: generate_embedding returns a 768-dimensional float array
# Given a concept description string, when generate_embedding is called,
# then it returns a 768-dimensional float array.
# ---------------------------------------------------------------------------
class TestGenerateEmbedding:
    def test_returns_list_of_length_768(self, service):
        """
        Given a description string,
        when generate_embedding is called,
        then a list of length 768 is returned.
        """
        result = service.generate_embedding("Parses a Python source file into an AST.")
        assert len(result) == 768

    def test_returns_list_of_floats(self, service):
        """
        Given a description string,
        when generate_embedding is called,
        then every element in the returned list is a float.
        """
        result = service.generate_embedding("A utility function that sorts items.")
        assert isinstance(result, list)
        assert all(isinstance(v, float) for v in result)

    def test_default_text_type_is_passage(self, service):
        """
        Given generate_embedding is called without explicit text_type,
        when the result is compared to an explicit passage call,
        then they are identical (default = passage).
        """
        text = "A function that manages database connections."
        default_result = service.generate_embedding(text)
        passage_result = service.generate_embedding(text, text_type="passage")
        similarity = cosine_similarity(default_result, passage_result)
        assert similarity > 0.9999


# ---------------------------------------------------------------------------
# AC3: Semantically similar texts have cosine similarity > 0.7
# Given two semantically similar descriptions, when embeddings are generated
# and cosine similarity computed, then similarity is above 0.7.
# ---------------------------------------------------------------------------
class TestSemanticSimilarity:
    def test_similar_descriptions_have_cosine_similarity_above_0_7(self, service):
        """
        Given two descriptions about AST parsing (semantically similar),
        when embeddings are generated and cosine similarity is computed,
        then the similarity score is above 0.7.
        """
        e1 = service.generate_embedding("Parses Python source files using AST analysis.")
        e2 = service.generate_embedding(
            "Analyzes Python code structure through abstract syntax trees."
        )
        similarity = cosine_similarity(e1, e2)
        assert similarity > 0.7, (
            f"Expected similar texts to have cosine similarity > 0.7, got {similarity:.4f}"
        )


# ---------------------------------------------------------------------------
# AC4: Unrelated texts have lower similarity than the similar-pair threshold
# Given two unrelated descriptions, when cosine similarity is computed,
# then similarity is below the similar-pair threshold.
# ---------------------------------------------------------------------------
class TestUnrelatedSimilarity:
    def test_unrelated_descriptions_have_lower_similarity_than_similar_pair(self, service):
        """
        Given a similar pair and an unrelated pair,
        when cosine similarities are computed,
        then the unrelated pair score is below the similar pair score.
        """
        similar_e1 = service.generate_embedding(
            "Parses Python source files using AST analysis."
        )
        similar_e2 = service.generate_embedding(
            "Analyzes Python code structure through abstract syntax trees."
        )
        similar_score = cosine_similarity(similar_e1, similar_e2)

        unrelated_e1 = service.generate_embedding(
            "Parses Python source files using AST analysis."
        )
        unrelated_e2 = service.generate_embedding(
            "The database connection pool manages SQL transactions."
        )
        unrelated_score = cosine_similarity(unrelated_e1, unrelated_e2)

        assert unrelated_score < similar_score, (
            f"Unrelated score {unrelated_score:.4f} should be less than "
            f"similar score {similar_score:.4f}"
        )


# ---------------------------------------------------------------------------
# AC5: Correct prefix is applied automatically based on text_type
# Given the e5-base-v2 model requirement for "query: " and "passage: " prefixes,
# when embeddings are generated, then the correct prefix is applied automatically.
# ---------------------------------------------------------------------------
class TestPrefixHandling:
    def test_query_prefix_produces_different_embedding_than_passage_prefix(self, service):
        """
        Given the same text with query vs. passage text_type,
        when generate_embedding is called with each type,
        then the resulting embeddings are not identical (different prefixes applied).
        """
        text = "Parses Python source files."
        query_emb = service.generate_embedding(text, text_type="query")
        passage_emb = service.generate_embedding(text, text_type="passage")
        similarity = cosine_similarity(query_emb, passage_emb)
        # Prefixes differ, so embeddings must differ
        assert similarity < 0.9999, (
            "query: and passage: embeddings should differ, but were identical"
        )

    def test_same_text_type_produces_identical_embeddings(self, service):
        """
        Given the same text and text_type called twice,
        when generate_embedding is called twice,
        then the results are identical (deterministic).
        """
        text = "Manages knowledge graph storage."
        e1 = service.generate_embedding(text, text_type="passage")
        e2 = service.generate_embedding(text, text_type="passage")
        similarity = cosine_similarity(e1, e2)
        assert similarity > 0.9999

    def test_prefix_applied_to_text_before_encoding(self):
        """
        Given a mock model that records its input,
        when generate_embedding is called with text_type="query",
        then the model receives "query: <text>" as input.
        """
        captured_inputs: list[str] = []

        def mock_encode(text, normalize_embeddings=True):
            captured_inputs.append(text)
            return np.zeros(768, dtype=np.float32)

        mock_model = MagicMock()
        mock_model.encode.side_effect = mock_encode

        with patch("apriori.embedding.service.SentenceTransformer", return_value=mock_model):
            svc = EmbeddingService()
            svc.generate_embedding("explain the algorithm", text_type="query")
            svc.generate_embedding("stores a concept node", text_type="passage")

        assert captured_inputs[0] == "query: explain the algorithm"
        assert captured_inputs[1] == "passage: stores a concept node"
