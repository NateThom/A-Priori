"""Tests for read-only Graph API (Story 11.2a).

AC traceability:
- AC-1: GET /api/concepts with filters returns filtered concepts.
- AC-2: GET /api/concepts/{id} returns full concept with edges and impact profile.
- AC-3: GET /api/graph?center={id}&radius=2 returns Cytoscape-format subgraph.
- AC-4: GET /api/activity?limit=20 returns 20 most recent librarian iterations.
- AC-5: GET /api/health returns metrics, targets, effective weights, queue depth.
"""

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import pytest
from fastapi.testclient import TestClient

from apriori.config import Config
from apriori.models.concept import CodeReference, Concept
from apriori.models.edge import Edge
from apriori.models.impact import ImpactProfile, ImpactEntry
from apriori.models.review_outcome import ReviewOutcome
from apriori.models.work_item import FailureRecord, WorkItem
from apriori.storage.protocol import KnowledgeStore


# ---------------------------------------------------------------------------
# In-memory store for testing — mirrors _InMemoryStore from test_knowledge_store_protocol.py
# Includes list_work_items added by Story 11.2a.
# ---------------------------------------------------------------------------


class _TestStore:
    """In-memory KnowledgeStore satisfying the full protocol including list_work_items."""

    def __init__(self) -> None:
        self._concepts: dict[uuid.UUID, Concept] = {}
        self._edges: dict[uuid.UUID, Edge] = {}
        self._work_items: dict[uuid.UUID, WorkItem] = {}
        self._review_outcomes: list[ReviewOutcome] = []

    # --- Concept CRUD ---

    def create_concept(self, concept: Concept) -> Concept:
        self._concepts[concept.id] = concept
        return concept

    def get_concept(self, concept_id: uuid.UUID) -> Optional[Concept]:
        return self._concepts.get(concept_id)

    def update_concept(self, concept: Concept) -> Concept:
        self._concepts[concept.id] = concept
        return concept

    def delete_concept(self, concept_id: uuid.UUID) -> None:
        self._concepts.pop(concept_id, None)

    def list_concepts(self, labels: Optional[set[str]] = None) -> list[Concept]:
        concepts = list(self._concepts.values())
        if labels:
            concepts = [c for c in concepts if labels & c.labels]
        return concepts

    # --- Edge CRUD ---

    def create_edge(self, edge: Edge) -> Edge:
        self._edges[edge.id] = edge
        return edge

    def get_edge(self, edge_id: uuid.UUID) -> Optional[Edge]:
        return self._edges.get(edge_id)

    def update_edge(self, edge: Edge) -> Edge:
        self._edges[edge.id] = edge
        return edge

    def delete_edge(self, edge_id: uuid.UUID) -> None:
        self._edges.pop(edge_id, None)

    def list_edges(
        self,
        source_id: Optional[uuid.UUID] = None,
        target_id: Optional[uuid.UUID] = None,
        edge_type: Optional[str] = None,
    ) -> list[Edge]:
        edges = list(self._edges.values())
        if source_id:
            edges = [e for e in edges if e.source_id == source_id]
        if target_id:
            edges = [e for e in edges if e.target_id == target_id]
        if edge_type:
            edges = [e for e in edges if e.edge_type == edge_type]
        return edges

    # --- Work Item operations ---

    def create_work_item(self, work_item: WorkItem) -> WorkItem:
        self._work_items[work_item.id] = work_item
        return work_item

    def get_work_item(self, work_item_id: uuid.UUID) -> Optional[WorkItem]:
        return self._work_items.get(work_item_id)

    def update_work_item(self, work_item: WorkItem) -> WorkItem:
        self._work_items[work_item.id] = work_item
        return work_item

    def resolve_work_item(self, work_item_id: uuid.UUID) -> WorkItem:
        wi = self._work_items[work_item_id]
        updated = wi.model_copy(
            update={"resolved": True, "resolved_at": datetime.now(timezone.utc)}
        )
        self._work_items[work_item_id] = updated
        return updated

    def get_pending_work_items(self) -> list[WorkItem]:
        return [wi for wi in self._work_items.values() if not wi.resolved]

    def list_work_items(self, limit: int = 20) -> list[WorkItem]:
        items = sorted(
            self._work_items.values(),
            key=lambda wi: wi.created_at,
            reverse=True,
        )
        return items[:limit]

    def record_failure(
        self, work_item_id: uuid.UUID, record: FailureRecord
    ) -> WorkItem:
        wi = self._work_items[work_item_id]
        updated = wi.model_copy(
            update={
                "failure_count": wi.failure_count + 1,
                "failure_records": wi.failure_records + [record],
            }
        )
        self._work_items[work_item_id] = updated
        return updated

    def escalate_work_item(self, work_item_id: uuid.UUID) -> WorkItem:
        wi = self._work_items[work_item_id]
        updated = wi.model_copy(update={"escalated": True})
        self._work_items[work_item_id] = updated
        return updated

    def get_escalated_items(self) -> list[WorkItem]:
        return [wi for wi in self._work_items.values() if wi.escalated]

    def get_work_item_stats(self) -> dict[str, int]:
        items = list(self._work_items.values())
        return {
            "total": len(items),
            "pending": sum(1 for wi in items if not wi.resolved),
            "resolved": sum(1 for wi in items if wi.resolved),
            "escalated": sum(1 for wi in items if wi.escalated),
        }

    def delete_old_work_items(self, days: int) -> int:
        from datetime import timedelta
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        to_delete = [
            wid
            for wid, wi in self._work_items.items()
            if wi.resolved and wi.resolved_at is not None and wi.resolved_at < cutoff
        ]
        for wid in to_delete:
            del self._work_items[wid]
        return len(to_delete)

    # --- Review Outcome operations ---

    def create_review_outcome(self, outcome: ReviewOutcome) -> ReviewOutcome:
        self._review_outcomes.append(outcome)
        return outcome

    def get_review_outcomes_for_concept(
        self, concept_id: uuid.UUID
    ) -> list[ReviewOutcome]:
        return [o for o in self._review_outcomes if o.concept_id == concept_id]

    def list_review_outcomes(self) -> list[ReviewOutcome]:
        return list(self._review_outcomes)

    # --- Search ---

    def search_semantic(
        self, query_embedding: list[float], limit: int = 10
    ) -> list[Concept]:
        return list(self._concepts.values())[:limit]

    def search_keyword(self, query: str, limit: int = 10) -> list[Concept]:
        return [
            c
            for c in self._concepts.values()
            if query.lower() in c.name.lower()
            or query.lower() in c.description.lower()
        ][:limit]

    def search_by_file(self, file_path: str) -> list[Concept]:
        return [
            c
            for c in self._concepts.values()
            if any(ref.file_path == file_path for ref in c.code_references)
        ]

    # --- Graph traversal ---

    def get_neighbors(
        self,
        concept_id: uuid.UUID,
        edge_type: Optional[str] = None,
        direction: str = "both",
    ) -> list[Concept]:
        neighbor_ids: set[uuid.UUID] = set()
        for edge in self._edges.values():
            if edge_type and edge.edge_type != edge_type:
                continue
            if direction in ("outgoing", "both") and edge.source_id == concept_id:
                neighbor_ids.add(edge.target_id)
            if direction in ("incoming", "both") and edge.target_id == concept_id:
                neighbor_ids.add(edge.source_id)
        return [
            self._concepts[cid] for cid in neighbor_ids if cid in self._concepts
        ]

    def traverse_graph(
        self, start_id: uuid.UUID, max_depth: int = 3
    ) -> list[Concept]:
        visited: set[uuid.UUID] = set()
        result: list[Concept] = []
        frontier = [start_id]
        depth = 0
        while frontier and depth <= max_depth:
            next_frontier: list[uuid.UUID] = []
            for cid in frontier:
                if cid in visited:
                    continue
                visited.add(cid)
                if cid in self._concepts:
                    result.append(self._concepts[cid])
                if depth < max_depth:
                    for edge in self._edges.values():
                        if edge.source_id == cid and edge.target_id not in visited:
                            next_frontier.append(edge.target_id)
            frontier = next_frontier
            depth += 1
        return result

    # --- Metrics ---

    def get_metrics(self) -> dict[str, Any]:
        return {
            "concept_count": len(self._concepts),
            "edge_count": len(self._edges),
            "work_item_count": len(self._work_items),
            "review_outcome_count": len(self._review_outcomes),
        }

    def count_covered_files(self) -> int:
        seen: set[str] = set()
        for c in self._concepts.values():
            for ref in c.code_references:
                seen.add(ref.file_path)
        return len(seen)

    def count_fresh_active_concepts(self, active_days: int = 30) -> tuple[int, int]:
        from datetime import timedelta
        cutoff = datetime.now(timezone.utc) - timedelta(days=active_days)
        active = [
            c
            for c in self._concepts.values()
            if c.updated_at is not None and c.updated_at >= cutoff
        ]
        fresh = sum(
            1
            for c in active
            if c.last_verified is not None and c.last_verified > c.updated_at
        )
        return fresh, len(active)

    def count_blast_radius_complete(self) -> tuple[int, int]:
        total = len(self._concepts)
        with_profile = sum(
            1 for c in self._concepts.values() if c.impact_profile is not None
        )
        return with_profile, total

    def rebuild_index(self) -> None:
        pass


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def store() -> _TestStore:
    return _TestStore()


@pytest.fixture
def config() -> Config:
    return Config()


@pytest.fixture
def client(store: _TestStore, config: Config) -> TestClient:
    from apriori.shells.ui.server import create_app
    app = create_app(store, config)  # type: ignore[arg-type]
    return TestClient(app)


def _make_concept(name: str = "TestConcept", labels: set[str] | None = None) -> Concept:
    return Concept(
        name=name,
        description=f"Description for {name}.",
        created_by="agent",
        labels=labels or set(),
    )


def _make_edge(source_id: uuid.UUID, target_id: uuid.UUID) -> Edge:
    return Edge(
        source_id=source_id,
        target_id=target_id,
        edge_type="depends-on",
        evidence_type="semantic",
    )


def _make_work_item(concept_id: uuid.UUID, description: str = "Work item") -> WorkItem:
    return WorkItem(
        item_type="verify_concept",
        concept_id=concept_id,
        description=description,
    )


# ---------------------------------------------------------------------------
# AC-1: GET /api/concepts with filters
# ---------------------------------------------------------------------------


class TestListConcepts:
    def test_empty_store_returns_empty_list(self, client: TestClient) -> None:
        """Given no concepts, GET /api/concepts returns an empty list."""
        response = client.get("/api/concepts")
        assert response.status_code == 200
        assert response.json() == []

    def test_returns_all_concepts_when_no_filter(
        self, client: TestClient, store: _TestStore
    ) -> None:
        """Given concepts in store, GET /api/concepts returns all of them."""
        c1 = _make_concept("Alpha")
        c2 = _make_concept("Beta")
        store.create_concept(c1)
        store.create_concept(c2)

        response = client.get("/api/concepts")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2

    def test_filter_by_label_returns_matching_concepts(
        self, client: TestClient, store: _TestStore
    ) -> None:
        """Given concepts with different labels, label filter returns only matching ones."""
        verified = _make_concept("Verified", labels={"verified"})
        stale = _make_concept("Stale", labels={"stale"})
        store.create_concept(verified)
        store.create_concept(stale)

        response = client.get("/api/concepts?label=verified")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["name"] == "Verified"

    def test_filter_by_multiple_labels_returns_any_match(
        self, client: TestClient, store: _TestStore
    ) -> None:
        """Label filter with multiple values returns concepts matching any label (OR semantics)."""
        verified = _make_concept("Verified", labels={"verified"})
        stale = _make_concept("Stale", labels={"stale"})
        unrelated = _make_concept("Other", labels={"deprecated"})
        store.create_concept(verified)
        store.create_concept(stale)
        store.create_concept(unrelated)

        response = client.get("/api/concepts?label=verified&label=stale")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2
        names = {c["name"] for c in data}
        assert names == {"Verified", "Stale"}

    def test_concept_summary_contains_required_fields(
        self, client: TestClient, store: _TestStore
    ) -> None:
        """Each concept in the list response contains id, name, labels, confidence."""
        concept = _make_concept("Alpha", labels={"verified"})
        store.create_concept(concept)

        response = client.get("/api/concepts")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        item = data[0]
        assert "id" in item
        assert item["name"] == "Alpha"
        assert "labels" in item
        assert "confidence" in item


# ---------------------------------------------------------------------------
# AC-2: GET /api/concepts/{id}
# ---------------------------------------------------------------------------


class TestGetConcept:
    def test_returns_full_concept_with_edges(
        self, client: TestClient, store: _TestStore
    ) -> None:
        """Given a concept ID with outgoing edges, response includes concept and edges."""
        concept = _make_concept("Hub")
        target = _make_concept("Target")
        store.create_concept(concept)
        store.create_concept(target)
        edge = _make_edge(concept.id, target.id)
        store.create_edge(edge)

        response = client.get(f"/api/concepts/{concept.id}")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == str(concept.id)
        assert data["name"] == "Hub"
        assert "edges" in data
        assert len(data["edges"]) == 1
        assert data["edges"][0]["source_id"] == str(concept.id)

    def test_returns_impact_profile_when_present(
        self, client: TestClient, store: _TestStore
    ) -> None:
        """Given a concept with an impact profile, the full concept includes it."""
        target_id = uuid.uuid4()
        profile = ImpactProfile(
            last_computed=datetime.now(timezone.utc),
            structural_impact=[
                ImpactEntry(
                    target_concept_id=target_id,
                    confidence=0.9,
                    relationship_path=[],
                    depth=1,
                    rationale="Structural dependency.",
                )
            ],
        )
        concept = Concept(
            name="WithProfile",
            description="Has an impact profile.",
            created_by="agent",
            impact_profile=profile,
        )
        store.create_concept(concept)

        response = client.get(f"/api/concepts/{concept.id}")
        assert response.status_code == 200
        data = response.json()
        assert data["impact_profile"] is not None
        assert len(data["impact_profile"]["structural_impact"]) == 1

    def test_returns_concept_with_no_edges(
        self, client: TestClient, store: _TestStore
    ) -> None:
        """Given a concept with no edges, response includes empty edges list."""
        concept = _make_concept("Isolated")
        store.create_concept(concept)

        response = client.get(f"/api/concepts/{concept.id}")
        assert response.status_code == 200
        data = response.json()
        assert data["edges"] == []

    def test_nonexistent_concept_returns_404(self, client: TestClient) -> None:
        """Given a UUID that does not exist, GET /api/concepts/{id} returns 404."""
        missing_id = uuid.uuid4()
        response = client.get(f"/api/concepts/{missing_id}")
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# AC-3: GET /api/graph?center={id}&radius=2
# ---------------------------------------------------------------------------


class TestGetGraph:
    def test_returns_cytoscape_format(
        self, client: TestClient, store: _TestStore
    ) -> None:
        """Given a valid center ID, response is Cytoscape-format with nodes and edges."""
        center = _make_concept("Center")
        neighbor = _make_concept("Neighbor")
        store.create_concept(center)
        store.create_concept(neighbor)
        store.create_edge(_make_edge(center.id, neighbor.id))

        response = client.get(f"/api/graph?center={center.id}&radius=2")
        assert response.status_code == 200
        data = response.json()
        assert "nodes" in data
        assert "edges" in data

    def test_nodes_have_cytoscape_data_format(
        self, client: TestClient, store: _TestStore
    ) -> None:
        """Each node has {data: {id, label, type}} shape for Cytoscape compatibility."""
        concept = _make_concept("NodeConcept")
        store.create_concept(concept)

        response = client.get(f"/api/graph?center={concept.id}&radius=1")
        assert response.status_code == 200
        data = response.json()
        assert len(data["nodes"]) >= 1
        node = data["nodes"][0]
        assert "data" in node
        assert "id" in node["data"]
        assert "label" in node["data"]
        assert "type" in node["data"]

    def test_edges_have_cytoscape_data_format(
        self, client: TestClient, store: _TestStore
    ) -> None:
        """Each edge has {data: {id, source, target, weight}} shape."""
        source = _make_concept("Source")
        target = _make_concept("Target")
        store.create_concept(source)
        store.create_concept(target)
        store.create_edge(_make_edge(source.id, target.id))

        response = client.get(f"/api/graph?center={source.id}&radius=2")
        assert response.status_code == 200
        data = response.json()
        assert len(data["edges"]) == 1
        edge = data["edges"][0]
        assert "data" in edge
        assert "id" in edge["data"]
        assert "source" in edge["data"]
        assert "target" in edge["data"]
        assert "weight" in edge["data"]

    def test_missing_center_returns_422(self, client: TestClient) -> None:
        """GET /api/graph without center param returns 422 Unprocessable Entity."""
        response = client.get("/api/graph")
        assert response.status_code == 422

    def test_radius_limits_subgraph_depth(
        self, client: TestClient, store: _TestStore
    ) -> None:
        """Given radius=1, only center and direct neighbors are included."""
        center = _make_concept("Center")
        hop1 = _make_concept("Hop1")
        hop2 = _make_concept("Hop2")
        store.create_concept(center)
        store.create_concept(hop1)
        store.create_concept(hop2)
        store.create_edge(_make_edge(center.id, hop1.id))
        store.create_edge(_make_edge(hop1.id, hop2.id))

        response = client.get(f"/api/graph?center={center.id}&radius=1")
        assert response.status_code == 200
        data = response.json()
        node_ids = {n["data"]["id"] for n in data["nodes"]}
        assert str(center.id) in node_ids
        assert str(hop1.id) in node_ids
        assert str(hop2.id) not in node_ids

    def test_nonexistent_center_returns_empty_graph(
        self, client: TestClient
    ) -> None:
        """Given a non-existent center ID, response has empty nodes and edges."""
        missing = uuid.uuid4()
        response = client.get(f"/api/graph?center={missing}&radius=2")
        assert response.status_code == 200
        data = response.json()
        assert data["nodes"] == []
        assert data["edges"] == []


# ---------------------------------------------------------------------------
# AC-4: GET /api/activity?limit=20
# ---------------------------------------------------------------------------


class TestGetActivity:
    def test_empty_store_returns_empty_list(self, client: TestClient) -> None:
        """Given no work items, GET /api/activity returns an empty list."""
        response = client.get("/api/activity")
        assert response.status_code == 200
        assert response.json() == []

    def test_returns_work_items_ordered_by_created_at_desc(
        self, client: TestClient, store: _TestStore
    ) -> None:
        """Work items are returned most-recent first."""
        concept = _make_concept("C")
        store.create_concept(concept)
        wi1 = WorkItem(
            item_type="verify_concept",
            concept_id=concept.id,
            description="First",
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        wi2 = WorkItem(
            item_type="verify_concept",
            concept_id=concept.id,
            description="Second",
            created_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        )
        store.create_work_item(wi1)
        store.create_work_item(wi2)

        response = client.get("/api/activity?limit=20")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2
        assert data[0]["description"] == "Second"
        assert data[1]["description"] == "First"

    def test_limit_parameter_caps_result_count(
        self, client: TestClient, store: _TestStore
    ) -> None:
        """GET /api/activity?limit=1 returns at most 1 item."""
        concept = _make_concept("C")
        store.create_concept(concept)
        for i in range(5):
            store.create_work_item(
                WorkItem(
                    item_type="verify_concept",
                    concept_id=concept.id,
                    description=f"Item {i}",
                )
            )

        response = client.get("/api/activity?limit=1")
        assert response.status_code == 200
        assert len(response.json()) == 1

    def test_default_limit_is_20(
        self, client: TestClient, store: _TestStore
    ) -> None:
        """GET /api/activity with no limit param returns at most 20 items."""
        concept = _make_concept("C")
        store.create_concept(concept)
        for i in range(25):
            store.create_work_item(
                WorkItem(
                    item_type="verify_concept",
                    concept_id=concept.id,
                    description=f"Item {i}",
                )
            )

        response = client.get("/api/activity")
        assert response.status_code == 200
        assert len(response.json()) == 20

    def test_activity_item_contains_required_fields(
        self, client: TestClient, store: _TestStore
    ) -> None:
        """Each activity item includes id, item_type, concept_id, description, created_at."""
        concept = _make_concept("C")
        store.create_concept(concept)
        wi = _make_work_item(concept.id, "Check this concept.")
        store.create_work_item(wi)

        response = client.get("/api/activity?limit=20")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        item = data[0]
        assert "id" in item
        assert item["item_type"] == "verify_concept"
        assert item["concept_id"] == str(concept.id)
        assert "created_at" in item


# ---------------------------------------------------------------------------
# AC-5: GET /api/health
# ---------------------------------------------------------------------------


class TestGetHealth:
    def test_health_returns_200(self, client: TestClient) -> None:
        """GET /api/health returns HTTP 200."""
        response = client.get("/api/health")
        assert response.status_code == 200

    def test_health_contains_metrics(self, client: TestClient) -> None:
        """Health response contains coverage, freshness, blast_radius_completeness."""
        response = client.get("/api/health")
        data = response.json()
        assert "metrics" in data
        metrics = data["metrics"]
        assert "coverage" in metrics
        assert "freshness" in metrics
        assert "blast_radius_completeness" in metrics

    def test_health_contains_targets(self, client: TestClient) -> None:
        """Health response contains coverage_target, freshness_target, blast_radius_target."""
        response = client.get("/api/health")
        data = response.json()
        assert "targets" in data
        targets = data["targets"]
        assert "coverage_target" in targets
        assert "freshness_target" in targets
        assert "blast_radius_target" in targets

    def test_health_contains_effective_weights(self, client: TestClient) -> None:
        """Health response contains effective priority weights."""
        response = client.get("/api/health")
        data = response.json()
        assert "effective_weights" in data
        weights = data["effective_weights"]
        assert isinstance(weights, dict)
        assert len(weights) > 0

    def test_health_contains_work_queue_depth(
        self, client: TestClient, store: _TestStore
    ) -> None:
        """Health response contains work_queue_depth reflecting pending work items."""
        concept = _make_concept("C")
        store.create_concept(concept)
        wi = _make_work_item(concept.id)
        store.create_work_item(wi)

        response = client.get("/api/health")
        assert response.status_code == 200
        data = response.json()
        assert "work_queue_depth" in data
        assert data["work_queue_depth"] == 1

    def test_health_metric_values_are_floats_in_0_to_1(
        self, client: TestClient
    ) -> None:
        """All three metric values are floats in [0.0, 1.0]."""
        response = client.get("/api/health")
        data = response.json()
        for key in ("coverage", "freshness", "blast_radius_completeness"):
            value = data["metrics"][key]
            assert isinstance(value, float)
            assert 0.0 <= value <= 1.0, f"{key}={value} not in [0,1]"


# ---------------------------------------------------------------------------
# Story 11.5: Review Workflow UI
# ---------------------------------------------------------------------------


class TestReviewWorkflowUI:
    def test_concept_detail_includes_referenced_code_snippet(
        self, client: TestClient, store: _TestStore, tmp_path: Path
    ) -> None:
        """Given a concept with code refs, detail view includes inline referenced code."""
        file_path = tmp_path / "review_target.py"
        file_path.write_text("line1\nline2\nline3\nline4\n", encoding="utf-8")
        concept = Concept(
            name="ReviewedConcept",
            description="Needs human review",
            created_by="agent",
            code_references=[
                CodeReference(
                    symbol="module.fn",
                    file_path=str(file_path),
                    line_range=(2, 3),
                    content_hash="a" * 64,
                    semantic_anchor="function body",
                )
            ],
        )
        store.create_concept(concept)

        response = client.get(f"/api/concepts/{concept.id}")
        assert response.status_code == 200
        data = response.json()
        assert len(data["code_references"]) == 1
        assert data["code_references"][0]["snippet"] == "line2\nline3"

    def test_verify_marks_concept_verified_and_returns_confirmation(
        self, client: TestClient, store: _TestStore
    ) -> None:
        """Given Verify action, concept is marked verified and confirmation is returned."""
        concept = _make_concept("ToVerify")
        store.create_concept(concept)

        response = client.post(
            f"/api/concepts/{concept.id}/verify",
            json={"reviewer": "alice"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["message"] == "Concept verified successfully."
        assert data["concept"]["verified_by"] == "alice"
        assert data["review_outcome"]["action"] == "verified"

    def test_flag_creates_review_concept_work_item(
        self, client: TestClient, store: _TestStore
    ) -> None:
        """Given Flag action, concept is flagged and review_concept item is created."""
        concept = _make_concept("ToFlag")
        store.create_concept(concept)

        response = client.post(
            f"/api/concepts/{concept.id}/flag",
            json={"reviewer": "carol"},
        )
        assert response.status_code == 200
        data = response.json()
        assert "needs-review" in data["concept"]["labels"]
        assert data["review_outcome"]["action"] == "flagged"
        assert data["work_item"]["item_type"] == "review_concept"

    def test_correct_updates_concept_and_records_outcome(
        self, client: TestClient, store: _TestStore
    ) -> None:
        """Given Correct submit, concept is updated and correction outcome recorded."""
        concept = _make_concept("ToCorrect")
        store.create_concept(concept)

        response = client.post(
            f"/api/concepts/{concept.id}/correct",
            json={
                "reviewer": "bob",
                "error_type": "description_wrong",
                "description": "Updated description from reviewer.",
                "relationships": [{"edge_type": "depends-on", "target_symbol": "module.X"}],
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["concept"]["description"] == "Updated description from reviewer."
        assert data["review_outcome"]["action"] == "corrected"
        assert data["review_outcome"]["error_type"] == "description_wrong"

    def test_error_types_endpoint_returns_dropdown_options(self, client: TestClient) -> None:
        """Correction form options are available via error-type endpoint."""
        response = client.get("/api/review/error-types")
        assert response.status_code == 200
        data = response.json()
        assert "error_types" in data
        assert "description_wrong" in data["error_types"]
