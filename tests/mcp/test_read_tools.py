"""Tests for MCP read tools (Story 4.2 — AP-70).

Each test is directly traceable to a Given/When/Then acceptance criterion.

AC1: Given keyword query "payment", search(mode="keyword") returns matching concepts (FTS5).
AC2: Given semantic query, search(mode="semantic") returns concepts by vector similarity.
AC3: Given exact concept name, search(mode="exact") returns that concept.
AC4: Given file path, search(mode="file") returns concepts referencing that file.
AC5: Given start concept and max_hops=2, traverse returns all within 2 edges.
AC6: Given concept id, get_concept returns full data including code_references and edges.
AC7: Given graph state, get_status returns accurate metric counts.
AC8: Given Phase 1, blast_radius returns "not yet available" message.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Generator

import pytest
import apriori.mcp.server as mcp_server
from apriori.models.concept import Concept, CodeReference
from apriori.models.edge import Edge
from apriori.storage.sqlite_store import SQLiteStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _concept(name: str, description: str = "") -> Concept:
    return Concept(
        name=name,
        description=description or f"Description of {name}",
        created_by="agent",
    )


def _code_ref(file_path: str = "src/payment.py") -> CodeReference:
    return CodeReference(
        symbol="SomeClass",
        file_path=file_path,
        content_hash="a" * 64,
        semantic_anchor="SomeClass definition",
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def store(tmp_path: Path) -> Generator[SQLiteStore, None, None]:
    """Provide a fresh SQLiteStore injected into the MCP module."""
    s = SQLiteStore(db_path=tmp_path / "test.db")
    mcp_server._store = s
    yield s
    mcp_server._store = None


# ---------------------------------------------------------------------------
# AC1: search — keyword mode
# ---------------------------------------------------------------------------

def test_search_keyword_returns_matching_concepts(store: SQLiteStore) -> None:
    """Given a keyword query 'payment', search(mode='keyword') returns concepts
    whose name or description contains 'payment'."""
    store.create_concept(_concept("payment_processor", "Processes payments"))
    store.create_concept(_concept("order_service", "Manages orders"))

    results = mcp_server.search("payment", mode="keyword")

    assert isinstance(results, list)
    assert len(results) == 1
    assert results[0]["name"] == "payment_processor"


def test_search_keyword_returns_empty_on_no_match(store: SQLiteStore) -> None:
    """search(mode='keyword') returns empty list when no match."""
    store.create_concept(_concept("order_service"))

    results = mcp_server.search("payment", mode="keyword")

    assert results == []


# ---------------------------------------------------------------------------
# AC2: search — semantic mode
# ---------------------------------------------------------------------------

def test_search_semantic_returns_concepts_by_vector_similarity(tmp_path: Path) -> None:
    """Given a semantic query, search(mode='semantic') returns semantically
    similar concepts ranked by vector similarity."""

    class _FixedEmbedding:
        """Returns a fixed 768-dim vector for any input."""

        def generate_embedding(
            self, text: str, text_type: str = "passage"
        ) -> list[float]:
            return [0.5] * 768

    embedding_svc = _FixedEmbedding()
    s = SQLiteStore(
        db_path=tmp_path / "sem.db",
        embedding_service=embedding_svc,
    )
    # create_concept automatically stores the embedding when embedding_service is set.
    s.create_concept(_concept("SemanticTarget", "Semantic search target"))

    mcp_server._store = s
    mcp_server._embedding_service = _FixedEmbedding()
    try:
        results = mcp_server.search("find semantic targets", mode="semantic")

        assert isinstance(results, list)
        assert len(results) >= 1
        assert results[0]["name"] == "SemanticTarget"
    finally:
        mcp_server._store = None
        mcp_server._embedding_service = None


# ---------------------------------------------------------------------------
# AC3: search — exact mode
# ---------------------------------------------------------------------------

def test_search_exact_returns_matching_concept(store: SQLiteStore) -> None:
    """Given exact concept name, search(mode='exact') returns the matching concept."""
    store.create_concept(_concept("PaymentService"))
    store.create_concept(_concept("PaymentProcessor"))

    results = mcp_server.search("PaymentService", mode="exact")

    assert len(results) == 1
    assert results[0]["name"] == "PaymentService"


def test_search_exact_returns_empty_for_no_match(store: SQLiteStore) -> None:
    """search(mode='exact') returns empty list when name does not match."""
    store.create_concept(_concept("OtherConcept"))

    results = mcp_server.search("NonExistent", mode="exact")

    assert results == []


# ---------------------------------------------------------------------------
# AC4: search — file mode
# ---------------------------------------------------------------------------

def test_search_file_returns_concepts_for_file(store: SQLiteStore) -> None:
    """Given a file path, search(mode='file') returns all concepts referencing that file."""
    c1 = _concept("PaymentConcept")
    c1.code_references = [_code_ref("src/payment.py")]
    c2 = _concept("OrderConcept")
    c2.code_references = [_code_ref("src/order.py")]
    store.create_concept(c1)
    store.create_concept(c2)

    results = mcp_server.search("src/payment.py", mode="file")

    assert len(results) == 1
    assert results[0]["name"] == "PaymentConcept"


def test_search_file_returns_empty_for_no_references(store: SQLiteStore) -> None:
    """search(mode='file') returns empty list when no concept references the file."""
    store.create_concept(_concept("Concept"))

    results = mcp_server.search("nonexistent.py", mode="file")

    assert results == []


# ---------------------------------------------------------------------------
# AC5: traverse
# ---------------------------------------------------------------------------

def test_traverse_returns_concepts_within_max_hops(store: SQLiteStore) -> None:
    """Given start concept and max_hops=2, traverse returns all concepts within 2 edges
    but not those 3 hops away."""
    c_a = store.create_concept(_concept("ConceptA"))
    c_b = store.create_concept(_concept("ConceptB"))
    c_c = store.create_concept(_concept("ConceptC"))
    c_d = store.create_concept(_concept("ConceptD"))  # 3 hops — excluded

    store.create_edge(Edge(source_id=c_a.id, target_id=c_b.id, edge_type="calls", evidence_type="structural"))
    store.create_edge(Edge(source_id=c_b.id, target_id=c_c.id, edge_type="calls", evidence_type="structural"))
    store.create_edge(Edge(source_id=c_c.id, target_id=c_d.id, edge_type="calls", evidence_type="structural"))

    results = mcp_server.traverse(str(c_a.id), max_hops=2)

    names = {r["name"] for r in results}
    assert "ConceptA" in names
    assert "ConceptB" in names
    assert "ConceptC" in names
    assert "ConceptD" not in names


def test_traverse_returns_only_start_for_isolated_concept(store: SQLiteStore) -> None:
    """traverse on a concept with no edges returns only the start concept."""
    c = store.create_concept(_concept("IsolatedConcept"))

    results = mcp_server.traverse(str(c.id), max_hops=3)

    assert len(results) == 1
    assert results[0]["name"] == "IsolatedConcept"


# ---------------------------------------------------------------------------
# AC6: get_concept — full data
# ---------------------------------------------------------------------------

def test_get_concept_returns_full_concept_data(store: SQLiteStore) -> None:
    """get_concept returns concept with metadata, code_references, edges, and impact_profile."""
    c1 = _concept("PaymentService")
    c1.code_references = [_code_ref("src/payment.py")]
    c1 = store.create_concept(c1)

    c2 = store.create_concept(_concept("OrderService"))
    store.create_edge(Edge(
        source_id=c1.id,
        target_id=c2.id,
        edge_type="calls",
        evidence_type="structural",
    ))

    result = mcp_server.get_concept(str(c1.id))

    assert result["name"] == "PaymentService"
    assert len(result["code_references"]) == 1
    assert result["code_references"][0]["file_path"] == "src/payment.py"
    assert len(result["edges"]) == 1
    assert result["edges"][0]["edge_type"] == "calls"


def test_get_concept_raises_tool_error_for_unknown_id(store: SQLiteStore) -> None:
    """get_concept raises ToolError when the concept UUID does not exist."""
    from mcp.server.fastmcp.exceptions import ToolError

    with pytest.raises(ToolError):
        mcp_server.get_concept(str(uuid.uuid4()))


# ---------------------------------------------------------------------------
# AC7: get_status
# ---------------------------------------------------------------------------

def test_get_status_returns_accurate_metrics(store: SQLiteStore) -> None:
    """get_status returns accurate counts for all entity types."""
    c1 = store.create_concept(_concept("Alpha"))
    c2 = store.create_concept(_concept("Beta"))
    store.create_edge(Edge(
        source_id=c1.id,
        target_id=c2.id,
        edge_type="calls",
        evidence_type="structural",
    ))

    status = mcp_server.get_status()

    assert status["concept_count"] == 2
    assert status["edge_count"] == 1
    assert "work_item_count" in status
    assert "review_outcome_count" in status


def test_get_status_returns_zeros_for_empty_graph(store: SQLiteStore) -> None:
    """get_status returns zero counts for an empty graph."""
    status = mcp_server.get_status()

    assert status["concept_count"] == 0
    assert status["edge_count"] == 0


# ---------------------------------------------------------------------------
# AC8: blast_radius — placeholder
# ---------------------------------------------------------------------------

def test_blast_radius_returns_placeholder_message(store: SQLiteStore) -> None:
    """Given Phase 1, blast_radius returns a 'not yet available' message."""
    result = mcp_server.blast_radius(str(uuid.uuid4()))

    assert isinstance(result, str)
    assert "not yet available" in result.lower()


def test_blast_radius_accepts_any_concept_id(store: SQLiteStore) -> None:
    """blast_radius returns placeholder regardless of whether the concept exists."""
    c = store.create_concept(_concept("SomeConcept"))

    result = mcp_server.blast_radius(str(c.id))

    assert "not yet available" in result.lower()


# ---------------------------------------------------------------------------
# list_edge_types — registered and returns vocabulary
# ---------------------------------------------------------------------------

def test_list_edge_types_returns_list_of_strings(store: SQLiteStore) -> None:
    """list_edge_types returns a non-empty list of edge type strings."""
    result = mcp_server.list_edge_types()

    assert isinstance(result, list)
    assert len(result) > 0
    assert all(isinstance(t, str) for t in result)
    assert "calls" in result
