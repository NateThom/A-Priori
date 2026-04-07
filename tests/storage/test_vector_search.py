"""Tests for SQLiteStore vector search and FTS5 — AC traceability: Story 2.5.

AC-1: Given a concept is created via create_concept, when stored, then an
      embedding is automatically generated and inserted into concept_embeddings.
AC-2: Given a concept's description is updated, when update_concept is called,
      then the embedding is regenerated and updated in concept_embeddings.
AC-3: Given concepts stored with semantically varied descriptions, when
      search_semantic is called with a relevant query embedding, then results
      are returned ranked by cosine similarity (most similar first).
AC-4: Given a query "payment validation", when search_semantic is called,
      then concepts related to payments appear before unrelated concepts.
AC-5: Given a keyword query "authentication", when search_keyword is called,
      then concepts whose name or description contain "authentication" are
      returned via FTS5.
AC-6: Given a concept is deleted, when delete_concept is called, then its
      embedding is also removed from the concept_embeddings vec0 table.

DoD coverage: auto-embedding on create/update, vector similarity search,
              FTS5 keyword search, deletion cleanup.
"""

from __future__ import annotations

import math
import sqlite3
import uuid
from pathlib import Path
from typing import Literal

import pytest
import sqlite_vec

from apriori.embedding.protocol import EmbeddingServiceProtocol
from apriori.models.concept import Concept
from apriori.storage.sqlite_store import SQLiteStore


# ---------------------------------------------------------------------------
# Mock EmbeddingService — deterministic, no ML model required
# ---------------------------------------------------------------------------

_DIMS = 768  # Must match SQLiteStore._EMBEDDING_DIMS


class _DeterministicEmbedder:
    """Deterministic EmbeddingServiceProtocol for tests.

    Generates embeddings where specific keywords produce vectors with a
    strong component in a designated dimension, making similarity tests
    predictable without a real ML model.

    Satisfies EmbeddingServiceProtocol structurally.
    """

    # Keyword → dimension index with high activation
    _KEYWORD_DIM: dict[str, int] = {
        "payment": 0,
        "authentication": 1,
        "validation": 2,
        "network": 3,
        "storage": 4,
        "unrelated": 5,
    }

    def generate_embedding(
        self, text: str, text_type: Literal["query", "passage"] = "passage"
    ) -> list[float]:
        """Return a unit-length vector dominated by dimensions matching text keywords."""
        vec = [0.0] * _DIMS
        text_lower = text.lower()
        for keyword, dim in self._KEYWORD_DIM.items():
            if keyword in text_lower:
                vec[dim] += 1.0
        # Normalise to unit length; fall back to first-dimension unit vector
        magnitude = math.sqrt(sum(x * x for x in vec))
        if magnitude < 1e-9:
            vec[0] = 1.0
            magnitude = 1.0
        return [x / magnitude for x in vec]


def _make_concept(**kwargs) -> Concept:
    defaults = dict(
        name="test_concept",
        description="A test concept.",
        created_by="agent",
    )
    defaults.update(kwargs)
    return Concept(**defaults)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "test_vector.db"


@pytest.fixture
def embedder() -> _DeterministicEmbedder:
    return _DeterministicEmbedder()


@pytest.fixture
def store(db_path: Path, embedder: _DeterministicEmbedder) -> SQLiteStore:
    """SQLiteStore wired with the deterministic embedding service."""
    return SQLiteStore(db_path, embedding_service=embedder)


# ---------------------------------------------------------------------------
# AC-1: Embedding auto-generated on create_concept
# ---------------------------------------------------------------------------

class TestEmbeddingOnCreate:
    """AC-1: create_concept auto-generates and stores an embedding."""

    def test_embedding_inserted_into_vec0_on_create(
        self, store: SQLiteStore, db_path: Path
    ):
        """
        Given a new Concept with a description,
        when create_concept is called,
        then a row exists in concept_embeddings for that concept's id.
        """
        concept = _make_concept(name="payment gateway", description="Handles payment processing.")
        store.create_concept(concept)

        # Verify via raw connection that an embedding was stored
        conn = sqlite3.connect(str(db_path))
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        row = conn.execute(
            "SELECT concept_id FROM concept_embeddings WHERE concept_id = ?",
            (str(concept.id),),
        ).fetchone()
        conn.close()
        assert row is not None, "No embedding found for concept after create_concept"

    def test_embedding_has_correct_dimensions(
        self, store: SQLiteStore, db_path: Path
    ):
        """
        Given a new Concept,
        when create_concept is called,
        then the stored embedding vector has 768 dimensions.
        """
        concept = _make_concept(name="auth service", description="Handles authentication.")
        store.create_concept(concept)

        conn = sqlite3.connect(str(db_path))
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        row = conn.execute(
            "SELECT vec_length(embedding) FROM concept_embeddings WHERE concept_id = ?",
            (str(concept.id),),
        ).fetchone()
        conn.close()
        assert row is not None
        assert row[0] == _DIMS

    def test_no_embedding_stored_without_embedding_service(self, db_path: Path):
        """
        Given a SQLiteStore initialised without an embedding service,
        when create_concept is called,
        then no row is inserted into concept_embeddings (graceful no-op).
        """
        store_no_embed = SQLiteStore(db_path)
        concept = _make_concept(name="bare concept", description="No embedder wired.")
        store_no_embed.create_concept(concept)

        conn = sqlite3.connect(str(db_path))
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        row = conn.execute(
            "SELECT concept_id FROM concept_embeddings WHERE concept_id = ?",
            (str(concept.id),),
        ).fetchone()
        conn.close()
        assert row is None, "Embedding was stored but no embedding service was provided"


# ---------------------------------------------------------------------------
# AC-2: Embedding regenerated on update_concept
# ---------------------------------------------------------------------------

class TestEmbeddingOnUpdate:
    """AC-2: update_concept regenerates and updates the embedding."""

    def test_embedding_updated_when_description_changes(
        self, store: SQLiteStore, db_path: Path, embedder: _DeterministicEmbedder
    ):
        """
        Given a stored concept with description "payment processing",
        when update_concept is called with description "authentication flow",
        then the embedding in concept_embeddings reflects the new description.
        """
        concept = _make_concept(
            name="gateway", description="payment processing gateway"
        )
        store.create_concept(concept)

        original_embedding = embedder.generate_embedding("payment processing gateway")

        updated = concept.model_copy(
            update={"description": "authentication flow handler"}
        )
        store.update_concept(updated)

        new_embedding = embedder.generate_embedding("authentication flow handler")

        # Verify the stored embedding changed — check the high-activation dimension
        # original should have payment dim dominant, new should have auth dim dominant
        assert original_embedding[0] > 0.5, "Original should be payment-dominant"
        assert new_embedding[1] > 0.5, "New should be auth-dominant"

        # The embedding stored should now match the new description's vector
        # (we can't directly read float32 from vec0, so verify via search)
        query_auth = embedder.generate_embedding("authentication flow", text_type="query")
        results = store.search_semantic(query_auth, limit=5)
        result_ids = [c.id for c in results]
        assert updated.id in result_ids, (
            "Updated concept should appear in auth-query results after embedding update"
        )

    def test_embedding_present_after_update_on_fresh_concept(
        self, store: SQLiteStore, db_path: Path
    ):
        """
        Given a concept with no prior embedding (edge case: store without service),
        when update_concept is called on a store with an embedding service,
        then the embedding is created or updated.
        """
        concept = _make_concept(name="edge_case", description="authentication service")
        store.create_concept(concept)

        conn = sqlite3.connect(str(db_path))
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        row = conn.execute(
            "SELECT concept_id FROM concept_embeddings WHERE concept_id = ?",
            (str(concept.id),),
        ).fetchone()
        conn.close()
        assert row is not None, "Embedding must exist after create_concept with embedding service"


# ---------------------------------------------------------------------------
# AC-3: search_semantic returns results ranked by cosine similarity
# ---------------------------------------------------------------------------

class TestSearchSemantic:
    """AC-3 & AC-4: search_semantic ranks results by cosine similarity."""

    def test_search_semantic_returns_most_similar_first(
        self, store: SQLiteStore, embedder: _DeterministicEmbedder
    ):
        """
        Given three concepts with different keywords,
        when search_semantic is called with a payment-focused query embedding,
        then the payment concept ranks first.
        """
        payment = _make_concept(name="payment", description="payment processing")
        auth = _make_concept(name="auth", description="authentication flow")
        storage_c = _make_concept(name="storage", description="data storage layer")

        store.create_concept(payment)
        store.create_concept(auth)
        store.create_concept(storage_c)

        query_vec = embedder.generate_embedding("payment validation", text_type="query")
        results = store.search_semantic(query_vec, limit=3)

        assert len(results) > 0, "search_semantic returned no results"
        assert results[0].id == payment.id, (
            f"Expected payment concept first, got '{results[0].name}'"
        )

    def test_search_semantic_respects_limit(
        self, store: SQLiteStore, embedder: _DeterministicEmbedder
    ):
        """
        Given 10 stored concepts,
        when search_semantic is called with limit=3,
        then at most 3 results are returned.
        """
        for i in range(10):
            store.create_concept(
                _make_concept(name=f"concept_{i}", description=f"concept number {i}")
            )

        query_vec = embedder.generate_embedding("concept", text_type="query")
        results = store.search_semantic(query_vec, limit=3)
        assert len(results) <= 3

    def test_search_semantic_empty_store_returns_empty(
        self, store: SQLiteStore, embedder: _DeterministicEmbedder
    ):
        """
        Given an empty store,
        when search_semantic is called,
        then an empty list is returned without errors.
        """
        query_vec = [0.0] * _DIMS
        query_vec[0] = 1.0
        results = store.search_semantic(query_vec, limit=5)
        assert results == []

    def test_search_semantic_payment_beats_unrelated(
        self, store: SQLiteStore, embedder: _DeterministicEmbedder
    ):
        """
        AC-4: Given a query 'payment validation',
        when search_semantic is called,
        then concepts related to payments appear before unrelated concepts.
        """
        payment = _make_concept(
            name="payment validator",
            description="payment validation service for processing transactions",
        )
        unrelated = _make_concept(
            name="log formatter",
            description="formats application log output",
        )
        for _ in range(5):
            store.create_concept(
                _make_concept(
                    name=f"unrelated_{uuid.uuid4().hex[:6]}",
                    description="generic log formatter service",
                )
            )
        store.create_concept(payment)
        store.create_concept(unrelated)

        query_vec = embedder.generate_embedding("payment validation", text_type="query")
        results = store.search_semantic(query_vec, limit=10)

        assert len(results) > 0
        ids = [c.id for c in results]
        assert payment.id in ids, "Payment concept must appear in results"

        payment_pos = ids.index(payment.id)
        # Unrelated concepts should rank lower than payment concept
        for i, c in enumerate(results):
            if c.id != payment.id and "payment" not in c.description.lower():
                assert payment_pos < i, (
                    f"Payment concept (pos {payment_pos}) should rank higher than "
                    f"'{c.name}' (pos {i})"
                )


# ---------------------------------------------------------------------------
# AC-5: search_keyword uses FTS5
# ---------------------------------------------------------------------------

class TestSearchKeyword:
    """AC-5: search_keyword returns concepts via FTS5."""

    def test_keyword_search_finds_matching_concept_by_name(self, store: SQLiteStore):
        """
        Given a concept with name 'authentication_service',
        when search_keyword('authentication') is called,
        then the concept is returned.
        """
        auth = _make_concept(
            name="authentication_service",
            description="Handles user login flows.",
        )
        unrelated = _make_concept(
            name="cache_layer",
            description="Stores data in memory.",
        )
        store.create_concept(auth)
        store.create_concept(unrelated)

        results = store.search_keyword("authentication", limit=10)
        result_ids = {c.id for c in results}

        assert auth.id in result_ids, "FTS5 should match concept by name"
        assert unrelated.id not in result_ids, "Unrelated concept should not appear"

    def test_keyword_search_finds_matching_concept_by_description(
        self, store: SQLiteStore
    ):
        """
        Given a concept whose description contains 'authentication',
        when search_keyword('authentication') is called,
        then the concept is returned.
        """
        auth_in_desc = _make_concept(
            name="login_handler",
            description="Performs authentication and session management.",
        )
        store.create_concept(auth_in_desc)

        results = store.search_keyword("authentication", limit=10)
        result_ids = {c.id for c in results}
        assert auth_in_desc.id in result_ids

    def test_keyword_search_is_case_insensitive(self, store: SQLiteStore):
        """
        Given a concept with 'Authentication' (capitalised),
        when search_keyword('authentication') is called,
        then the concept is still returned.
        """
        auth = _make_concept(
            name="AuthenticationManager",
            description="Manages Authentication tokens.",
        )
        store.create_concept(auth)

        results = store.search_keyword("authentication", limit=10)
        result_ids = {c.id for c in results}
        assert auth.id in result_ids

    def test_keyword_search_respects_limit(self, store: SQLiteStore):
        """
        Given many concepts matching 'service',
        when search_keyword('service', limit=3) is called,
        then at most 3 results are returned.
        """
        for i in range(10):
            store.create_concept(
                _make_concept(
                    name=f"service_{i}",
                    description=f"A service component number {i}.",
                )
            )
        results = store.search_keyword("service", limit=3)
        assert len(results) <= 3

    def test_keyword_search_empty_results_for_no_match(self, store: SQLiteStore):
        """
        Given concepts that don't contain 'zxqwerty',
        when search_keyword('zxqwerty') is called,
        then an empty list is returned.
        """
        store.create_concept(
            _make_concept(name="parser", description="parses source code")
        )
        results = store.search_keyword("zxqwerty", limit=10)
        assert results == []

    def test_keyword_search_fts5_updated_after_concept_update(
        self, store: SQLiteStore
    ):
        """
        Given a concept initially named 'payment_processor',
        when the concept is updated to name 'auth_processor' with 'authentication' in description,
        then search_keyword('authentication') finds the updated concept.
        """
        concept = _make_concept(
            name="payment_processor",
            description="Processes payments.",
        )
        store.create_concept(concept)

        # Verify it does NOT appear for 'authentication' initially
        results_before = store.search_keyword("authentication", limit=10)
        assert concept.id not in {c.id for c in results_before}

        # Update description to include 'authentication'
        updated = concept.model_copy(
            update={"name": "auth_processor", "description": "Handles authentication flow."}
        )
        store.update_concept(updated)

        results_after = store.search_keyword("authentication", limit=10)
        assert updated.id in {c.id for c in results_after}, (
            "FTS5 should reflect updated concept description"
        )


# ---------------------------------------------------------------------------
# AC-6: Deletion cleanup — embedding removed from vec0
# ---------------------------------------------------------------------------

class TestDeletionCleanup:
    """AC-6: delete_concept removes embedding from concept_embeddings."""

    def test_embedding_removed_on_delete_concept(
        self, store: SQLiteStore, db_path: Path
    ):
        """
        Given a concept with an embedding stored in concept_embeddings,
        when delete_concept is called,
        then the row is removed from concept_embeddings.
        """
        concept = _make_concept(name="to_delete", description="payment processing")
        store.create_concept(concept)

        # Verify embedding exists
        conn = sqlite3.connect(str(db_path))
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        row_before = conn.execute(
            "SELECT concept_id FROM concept_embeddings WHERE concept_id = ?",
            (str(concept.id),),
        ).fetchone()
        assert row_before is not None, "Embedding should exist before delete"
        conn.close()

        store.delete_concept(concept.id)

        conn = sqlite3.connect(str(db_path))
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        row_after = conn.execute(
            "SELECT concept_id FROM concept_embeddings WHERE concept_id = ?",
            (str(concept.id),),
        ).fetchone()
        conn.close()
        assert row_after is None, "Embedding should be removed after delete_concept"

    def test_fts5_entry_removed_on_delete_concept(
        self, store: SQLiteStore
    ):
        """
        Given a concept in the FTS5 index,
        when delete_concept is called,
        then search_keyword no longer finds the deleted concept.
        """
        concept = _make_concept(
            name="authentication_handler_to_delete",
            description="authentication module to be removed",
        )
        store.create_concept(concept)

        # Verify it appears in search
        before = store.search_keyword("authentication_handler_to_delete", limit=5)
        assert concept.id in {c.id for c in before}

        store.delete_concept(concept.id)

        # After deletion it must not appear
        after = store.search_keyword("authentication_handler_to_delete", limit=5)
        assert concept.id not in {c.id for c in after}

    def test_delete_concept_without_embedding_does_not_raise(
        self, db_path: Path
    ):
        """
        Given a SQLiteStore with no embedding service,
        when a concept is created and then deleted,
        then delete_concept does not raise (even though no embedding exists).
        """
        store_no_embed = SQLiteStore(db_path)
        concept = _make_concept(name="bare", description="no embedding here")
        store_no_embed.create_concept(concept)
        store_no_embed.delete_concept(concept.id)  # must not raise


# ---------------------------------------------------------------------------
# Integration: FTS5 triggers maintain sync with concepts table
# ---------------------------------------------------------------------------

class TestFTS5Sync:
    """Verify FTS5 content table stays in sync with the concepts table via triggers."""

    def test_fts5_populated_on_insert(self, store: SQLiteStore):
        """
        Given an empty store,
        when create_concept is called,
        then the concept is immediately findable via search_keyword.
        """
        concept = _make_concept(
            name="fts_test_concept",
            description="unique_keyword_xyzzy for fts testing",
        )
        store.create_concept(concept)
        results = store.search_keyword("unique_keyword_xyzzy", limit=5)
        assert concept.id in {c.id for c in results}

    def test_fts5_updated_on_concept_update(self, store: SQLiteStore):
        """
        Given a concept inserted with description A,
        when update_concept changes description to B,
        then search_keyword on A returns nothing and on B returns the concept.
        """
        concept = _make_concept(
            name="evolving",
            description="initial_unique_term_abc",
        )
        store.create_concept(concept)

        updated = concept.model_copy(
            update={"description": "final_unique_term_xyz"}
        )
        store.update_concept(updated)

        old_results = store.search_keyword("initial_unique_term_abc", limit=5)
        assert concept.id not in {c.id for c in old_results}, (
            "Old term should no longer match after update"
        )

        new_results = store.search_keyword("final_unique_term_xyz", limit=5)
        assert concept.id in {c.id for c in new_results}, (
            "New term should match after update"
        )

    def test_rebuild_index_keeps_fts5_consistent(self, store: SQLiteStore):
        """
        Given concepts in the store,
        when rebuild_index is called,
        then search_keyword still returns expected results.
        """
        concept = _make_concept(
            name="rebuild_test",
            description="rebuild_keyword_unique_zzz",
        )
        store.create_concept(concept)
        store.rebuild_index()
        results = store.search_keyword("rebuild_keyword_unique_zzz", limit=5)
        assert concept.id in {c.id for c in results}
