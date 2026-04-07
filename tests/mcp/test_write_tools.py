"""Tests for MCP write tools (Story 4.3).

AC traceability:

AC1: Given valid concept data, when ``create_concept`` is called, then the
     concept is created in both SQLite and YAML and the created concept is
     returned.
AC2: Given an existing concept, when ``update_concept`` is called with a new
     description, then the concept is updated and returned.
AC3: Given a concept with edges, when ``delete_concept`` is called, then the
     concept and its edges are removed.
AC4: Given two existing concepts and a valid edge type, when ``create_edge``
     is called, then the edge is created.
AC5: Given an existing edge, when ``update_edge`` is called with a new type,
     confidence, or metadata, then the edge is updated.
AC6: Given an existing edge, when ``delete_edge`` is called, then the edge
     is removed.
AC7: Given an invalid edge type, when ``create_edge`` is called, then an
     ``isError=True`` response is returned listing valid types.
AC8: Given a knowledge gap description, when ``report_gap`` is called, then
     a ``reported_gap`` work item is created.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from apriori.models.edge import EDGE_TYPE_VOCABULARY, EdgeTypeVocabulary
from apriori.storage.dual_writer import DualWriter
from apriori.storage.sqlite_store import SQLiteStore
from apriori.storage.yaml_store import YamlStore


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def yaml_dir(tmp_path: Path) -> Path:
    d = tmp_path / "yaml_backup"
    d.mkdir()
    return d


@pytest.fixture
def dual_store(tmp_path: Path, yaml_dir: Path, monkeypatch) -> DualWriter:
    """Inject a fresh DualWriter into the server module's module-level state."""
    import apriori.mcp.server as server_mod

    store = DualWriter(
        sqlite_store=SQLiteStore(tmp_path / "test.db"),
        yaml_store=YamlStore(base_dir=yaml_dir),
    )
    vocab = EdgeTypeVocabulary(EDGE_TYPE_VOCABULARY)

    monkeypatch.setattr(server_mod, "_store", store)
    monkeypatch.setattr(server_mod, "_edge_vocabulary", vocab)
    return store


# Helpers -------------------------------------------------------------------


def _make_concept_via_tool(name: str, description: str = "desc", labels=None):
    from apriori.mcp.server import create_concept

    return create_concept(name=name, description=description, labels=labels)


def _make_edge_via_tool(source_id: str, target_id: str, edge_type: str = "depends-on"):
    from apriori.mcp.server import create_edge

    return create_edge(source_id=source_id, target_id=target_id, edge_type=edge_type)


# ---------------------------------------------------------------------------
# AC1: create_concept — created in both stores and returned
# ---------------------------------------------------------------------------


class TestCreateConcept:
    """AC1: Given valid concept data, when create_concept is called, then the
    concept is created in both SQLite and YAML and the created concept is
    returned."""

    def test_returns_concept_dict_with_name_and_description(self, dual_store):
        """Given valid data, create_concept returns a dict with the correct fields."""
        from apriori.mcp.server import create_concept

        result = create_concept(name="Authentication Flow", description="Handles login.")
        assert result["name"] == "Authentication Flow"
        assert result["description"] == "Handles login."
        assert "id" in result

    def test_concept_persisted_in_sqlite(self, dual_store):
        """Given create_concept succeeds, the concept is retrievable from SQLite."""
        from apriori.mcp.server import create_concept

        result = create_concept(name="Dependency Injection", description="DI pattern.")
        fetched = dual_store.get_concept(uuid.UUID(result["id"]))
        assert fetched is not None
        assert fetched.name == "Dependency Injection"

    def test_concept_persisted_in_yaml(self, dual_store, yaml_dir):
        """Given create_concept succeeds, a YAML file is written under yaml_dir/concepts/."""
        from apriori.mcp.server import create_concept

        create_concept(name="Event Sourcing", description="Records events.")
        yaml_files = list((yaml_dir / "concepts").glob("*.yaml"))
        assert len(yaml_files) >= 1, "Expected at least one concept YAML file"

    def test_labels_are_stored(self, dual_store):
        """Given labels are provided, they are included in the returned concept."""
        from apriori.mcp.server import create_concept

        result = create_concept(name="Caching", description="Cache layer.", labels=["verified"])
        assert "verified" in result["labels"]

    def test_labels_default_to_empty(self, dual_store):
        """Given no labels, the returned concept has an empty label set."""
        from apriori.mcp.server import create_concept

        result = create_concept(name="Logging", description="Log output.")
        assert result["labels"] == [] or result["labels"] == set()


# ---------------------------------------------------------------------------
# AC2: update_concept — updated and returned
# ---------------------------------------------------------------------------


class TestUpdateConcept:
    """AC2: Given an existing concept, when update_concept is called with a new
    description, then the concept is updated and returned."""

    def test_update_description_returns_updated_concept(self, dual_store):
        """Given an existing concept, update_concept updates its description."""
        from apriori.mcp.server import create_concept, update_concept

        created = _make_concept_via_tool("Rate Limiting")
        result = update_concept(
            concept_id=created["id"], description="Updated: throttle requests."
        )
        assert result["description"] == "Updated: throttle requests."

    def test_update_description_persists_in_sqlite(self, dual_store):
        """After update_concept, the new description is readable from SQLite."""
        from apriori.mcp.server import create_concept, update_concept

        created = _make_concept_via_tool("Circuit Breaker")
        update_concept(concept_id=created["id"], description="Breaks the circuit.")
        fetched = dual_store.get_concept(uuid.UUID(created["id"]))
        assert fetched is not None
        assert fetched.description == "Breaks the circuit."

    def test_update_name_leaves_description_unchanged(self, dual_store):
        """Updating only name leaves the description unchanged."""
        from apriori.mcp.server import create_concept, update_concept

        created = _make_concept_via_tool("Saga Pattern", description="Choreograph transactions.")
        result = update_concept(concept_id=created["id"], name="Saga Orchestration")
        assert result["name"] == "Saga Orchestration"
        assert result["description"] == "Choreograph transactions."

    def test_update_concept_not_found_raises_tool_error(self, dual_store):
        """Given a non-existent concept_id, update_concept raises ToolError."""
        from mcp.server.fastmcp.exceptions import ToolError

        from apriori.mcp.server import update_concept

        missing_id = str(uuid.uuid4())
        with pytest.raises(ToolError):
            update_concept(concept_id=missing_id, description="Does not exist.")

    def test_update_labels_replaces_label_set(self, dual_store):
        """update_concept with new labels replaces the existing label set."""
        from apriori.mcp.server import create_concept, update_concept

        created = _make_concept_via_tool("CQRS", labels=["needs-review"])
        result = update_concept(concept_id=created["id"], labels=["verified"])
        assert "verified" in result["labels"]


# ---------------------------------------------------------------------------
# AC3: delete_concept — concept and edges removed
# ---------------------------------------------------------------------------


class TestDeleteConcept:
    """AC3: Given a concept with edges, when delete_concept is called, then the
    concept and its edges are removed."""

    def test_delete_concept_removes_concept_from_sqlite(self, dual_store):
        """Given an existing concept, delete_concept removes it from the store."""
        from apriori.mcp.server import create_concept, delete_concept

        created = _make_concept_via_tool("Outbox Pattern")
        delete_concept(concept_id=created["id"])
        assert dual_store.get_concept(uuid.UUID(created["id"])) is None

    def test_delete_concept_removes_dependent_edges(self, dual_store):
        """Given a concept with outgoing edges, delete_concept cascades to edges."""
        from apriori.mcp.server import create_concept, create_edge, delete_concept

        c1 = _make_concept_via_tool("Source Concept")
        c2 = _make_concept_via_tool("Target Concept")
        _make_edge_via_tool(c1["id"], c2["id"])
        delete_concept(concept_id=c1["id"])
        remaining = dual_store.list_edges(source_id=uuid.UUID(c1["id"]))
        assert len(remaining) == 0

    def test_delete_concept_returns_confirmation_string(self, dual_store):
        """delete_concept returns a string confirmation message."""
        from apriori.mcp.server import create_concept, delete_concept

        created = _make_concept_via_tool("Idempotency Key")
        result = delete_concept(concept_id=created["id"])
        assert isinstance(result, str)
        assert created["id"] in result

    def test_delete_concept_not_found_raises_tool_error(self, dual_store):
        """Given a non-existent concept_id, delete_concept raises ToolError."""
        from mcp.server.fastmcp.exceptions import ToolError

        from apriori.mcp.server import delete_concept

        with pytest.raises(ToolError):
            delete_concept(concept_id=str(uuid.uuid4()))


# ---------------------------------------------------------------------------
# AC4: create_edge — edge created
# ---------------------------------------------------------------------------


class TestCreateEdge:
    """AC4: Given two existing concepts and a valid edge type, when create_edge
    is called, then the edge is created."""

    def test_create_edge_returns_edge_dict(self, dual_store):
        """Given two concepts and a valid type, create_edge returns an edge dict."""
        from apriori.mcp.server import create_concept, create_edge

        c1 = _make_concept_via_tool("Service A")
        c2 = _make_concept_via_tool("Service B")
        result = create_edge(source_id=c1["id"], target_id=c2["id"], edge_type="calls")
        assert result["edge_type"] == "calls"
        assert result["source_id"] == c1["id"]
        assert result["target_id"] == c2["id"]
        assert "id" in result

    def test_create_edge_persisted_in_sqlite(self, dual_store):
        """After create_edge, the edge is retrievable from the store."""
        from apriori.mcp.server import create_concept, create_edge

        c1 = _make_concept_via_tool("Module X")
        c2 = _make_concept_via_tool("Module Y")
        result = create_edge(source_id=c1["id"], target_id=c2["id"], edge_type="imports")
        fetched = dual_store.get_edge(uuid.UUID(result["id"]))
        assert fetched is not None
        assert fetched.edge_type == "imports"

    def test_create_edge_persisted_in_yaml(self, dual_store, yaml_dir):
        """After create_edge, a YAML file is written under yaml_dir/edges/."""
        from apriori.mcp.server import create_concept, create_edge

        c1 = _make_concept_via_tool("ClassA")
        c2 = _make_concept_via_tool("ClassB")
        result = create_edge(source_id=c1["id"], target_id=c2["id"], edge_type="inherits")
        yaml_files = list((yaml_dir / "edges").glob("*.yaml"))
        assert len(yaml_files) >= 1


# ---------------------------------------------------------------------------
# AC5: update_edge — edge updated
# ---------------------------------------------------------------------------


class TestUpdateEdge:
    """AC5: Given an existing edge, when update_edge is called with a new type,
    confidence, or metadata, then the edge is updated."""

    def test_update_edge_confidence(self, dual_store):
        """update_edge with a new confidence updates and returns the edge."""
        from apriori.mcp.server import create_concept, create_edge, update_edge

        c1 = _make_concept_via_tool("Alpha")
        c2 = _make_concept_via_tool("Beta")
        edge = _make_edge_via_tool(c1["id"], c2["id"])
        result = update_edge(edge_id=edge["id"], confidence=0.75)
        assert abs(result["confidence"] - 0.75) < 0.001

    def test_update_edge_type(self, dual_store):
        """update_edge with a new valid edge_type updates the type."""
        from apriori.mcp.server import create_concept, create_edge, update_edge

        c1 = _make_concept_via_tool("Gamma")
        c2 = _make_concept_via_tool("Delta")
        edge = _make_edge_via_tool(c1["id"], c2["id"], "calls")
        result = update_edge(edge_id=edge["id"], edge_type="extends")
        assert result["edge_type"] == "extends"

    def test_update_edge_metadata(self, dual_store):
        """update_edge with new metadata stores the metadata on the edge."""
        from apriori.mcp.server import create_concept, create_edge, update_edge

        c1 = _make_concept_via_tool("Epsilon")
        c2 = _make_concept_via_tool("Zeta")
        edge = _make_edge_via_tool(c1["id"], c2["id"])
        result = update_edge(edge_id=edge["id"], metadata={"note": "verified"})
        assert result["metadata"] is not None
        assert result["metadata"]["note"] == "verified"

    def test_update_edge_persists_in_sqlite(self, dual_store):
        """After update_edge, the updated confidence is readable from SQLite."""
        from apriori.mcp.server import create_concept, create_edge, update_edge

        c1 = _make_concept_via_tool("Eta")
        c2 = _make_concept_via_tool("Theta")
        edge = _make_edge_via_tool(c1["id"], c2["id"])
        update_edge(edge_id=edge["id"], confidence=0.3)
        fetched = dual_store.get_edge(uuid.UUID(edge["id"]))
        assert fetched is not None
        assert abs(fetched.confidence - 0.3) < 0.001

    def test_update_edge_invalid_type_raises_tool_error(self, dual_store):
        """update_edge with invalid edge_type raises ToolError."""
        from mcp.server.fastmcp.exceptions import ToolError

        from apriori.mcp.server import create_concept, create_edge, update_edge

        c1 = _make_concept_via_tool("Iota")
        c2 = _make_concept_via_tool("Kappa")
        edge = _make_edge_via_tool(c1["id"], c2["id"])
        with pytest.raises(ToolError):
            update_edge(edge_id=edge["id"], edge_type="bad-type")

    def test_update_edge_not_found_raises_tool_error(self, dual_store):
        """update_edge with a non-existent edge_id raises ToolError."""
        from mcp.server.fastmcp.exceptions import ToolError

        from apriori.mcp.server import update_edge

        with pytest.raises(ToolError):
            update_edge(edge_id=str(uuid.uuid4()), confidence=0.5)


# ---------------------------------------------------------------------------
# AC6: delete_edge — edge removed
# ---------------------------------------------------------------------------


class TestDeleteEdge:
    """AC6: Given an existing edge, when delete_edge is called, then the edge
    is removed."""

    def test_delete_edge_removes_edge_from_store(self, dual_store):
        """After delete_edge, the edge is no longer retrievable from the store."""
        from apriori.mcp.server import create_concept, create_edge, delete_edge

        c1 = _make_concept_via_tool("Lambda")
        c2 = _make_concept_via_tool("Mu")
        edge = _make_edge_via_tool(c1["id"], c2["id"])
        delete_edge(edge_id=edge["id"])
        assert dual_store.get_edge(uuid.UUID(edge["id"])) is None

    def test_delete_edge_returns_confirmation_string(self, dual_store):
        """delete_edge returns a string confirmation message."""
        from apriori.mcp.server import create_concept, create_edge, delete_edge

        c1 = _make_concept_via_tool("Nu")
        c2 = _make_concept_via_tool("Xi")
        edge = _make_edge_via_tool(c1["id"], c2["id"])
        result = delete_edge(edge_id=edge["id"])
        assert isinstance(result, str)
        assert edge["id"] in result

    def test_delete_edge_not_found_raises_tool_error(self, dual_store):
        """delete_edge with a non-existent edge_id raises ToolError."""
        from mcp.server.fastmcp.exceptions import ToolError

        from apriori.mcp.server import delete_edge

        with pytest.raises(ToolError):
            delete_edge(edge_id=str(uuid.uuid4()))


# ---------------------------------------------------------------------------
# AC7: Invalid edge type → isError=True response listing valid types
# ---------------------------------------------------------------------------


class TestEdgeTypeValidation:
    """AC7: Given an invalid edge type, when create_edge is called, then an
    isError=True response is returned listing valid types."""

    def test_invalid_edge_type_raises_tool_error(self, dual_store):
        """create_edge with an unknown edge type raises ToolError."""
        from mcp.server.fastmcp.exceptions import ToolError

        from apriori.mcp.server import create_concept, create_edge

        c1 = _make_concept_via_tool("Omicron")
        c2 = _make_concept_via_tool("Pi")
        with pytest.raises(ToolError):
            create_edge(source_id=c1["id"], target_id=c2["id"], edge_type="not-a-real-type")

    def test_invalid_edge_type_error_lists_valid_types(self, dual_store):
        """The ToolError message names the invalid type and lists valid alternatives."""
        from mcp.server.fastmcp.exceptions import ToolError

        from apriori.mcp.server import create_concept, create_edge

        c1 = _make_concept_via_tool("Rho")
        c2 = _make_concept_via_tool("Sigma")
        with pytest.raises(ToolError) as exc_info:
            create_edge(source_id=c1["id"], target_id=c2["id"], edge_type="totally-wrong")
        msg = str(exc_info.value)
        assert "totally-wrong" in msg
        # At least one known valid type should appear in the message
        assert any(t in msg for t in EDGE_TYPE_VOCABULARY)

    def test_valid_edge_type_does_not_raise(self, dual_store):
        """create_edge with a valid edge type succeeds without error."""
        from apriori.mcp.server import create_concept, create_edge

        c1 = _make_concept_via_tool("Tau")
        c2 = _make_concept_via_tool("Upsilon")
        result = create_edge(source_id=c1["id"], target_id=c2["id"], edge_type="relates-to")
        assert result["edge_type"] == "relates-to"


# ---------------------------------------------------------------------------
# AC8: report_gap — creates a reported_gap work item
# ---------------------------------------------------------------------------


class TestReportGap:
    """AC8: Given a knowledge gap description, when report_gap is called, then
    a ``reported_gap`` work item is created."""

    def test_report_gap_returns_work_item_with_correct_type(self, dual_store):
        """report_gap returns a dict with item_type == 'reported_gap'."""
        from apriori.mcp.server import report_gap

        result = report_gap(description="Missing docs for auth token refresh flow.")
        assert result["item_type"] == "reported_gap"

    def test_report_gap_description_in_work_item(self, dual_store):
        """report_gap includes the provided description in the work item."""
        from apriori.mcp.server import report_gap

        desc = "No edge type covering 'reads from' relationship."
        result = report_gap(description=desc)
        assert desc in result["description"]

    def test_report_gap_optional_context_included(self, dual_store):
        """When context is provided, it is included in the work item description."""
        from apriori.mcp.server import report_gap

        result = report_gap(
            description="Missing docs.",
            context="Observed during code review of payment module.",
        )
        assert "payment module" in result["description"]

    def test_report_gap_work_item_persisted(self, dual_store):
        """The reported_gap work item is retrievable from the store after creation."""
        from apriori.mcp.server import report_gap

        result = report_gap(description="No concept for retry logic.")
        work_item = dual_store.get_work_item(uuid.UUID(result["id"]))
        assert work_item is not None
        assert work_item.item_type == "reported_gap"

    def test_report_gap_without_context(self, dual_store):
        """report_gap works when context is omitted."""
        from apriori.mcp.server import report_gap

        result = report_gap(description="Gap with no context.")
        assert result["item_type"] == "reported_gap"
