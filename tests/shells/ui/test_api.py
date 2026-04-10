"""Tests for read-only Graph API, activity feed endpoints, and Health Dashboard (Story 11.6).

AC traceability:
- AC-1: GET /api/concepts with filters returns filtered concepts.
- AC-2: GET /api/concepts/{id} returns full concept with edges and impact profile.
- AC-3: GET /api/graph?center={id}&radius=2 returns Cytoscape-format subgraph.
- AC-4: GET /api/activity?limit=20 returns 20 most recent librarian iterations.
- AC-6: Activity entries show work item, concept, co-regulation scores (if any), pass/fail,
        and failure reason on failures.
- AC-7: Failed entries expose full FailureRecord including reviewer_feedback.
- AC-5: GET /api/health returns metrics, targets, effective weights, queue depth.
- AC-6 (Story 11.6): Health dashboard shows three metrics vs. targets (coverage 80%,
  freshness 90%, blast radius 70%), effective weights, work queue depth, and escalated
  count. Refreshing the endpoint yields updated values.
- AC-6: GET /api/escalated-items returns escalated items with associated concepts
  and full failure history for the escalated-items view.
"""

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import pytest
from fastapi.testclient import TestClient

from apriori.config import Config
from apriori.models.concept import CodeReference
from apriori.models.concept import Concept
from apriori.models.edge import Edge
from apriori.models.impact import ImpactProfile, ImpactEntry
from apriori.models.librarian_activity import LibrarianActivity
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
        self._librarian_activities: list[LibrarianActivity] = []
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

    # --- Librarian Activity operations ---

    def create_librarian_activity(self, activity: LibrarianActivity) -> LibrarianActivity:
        self._librarian_activities.append(activity)
        return activity

    def list_librarian_activities(
        self, run_id: Optional[uuid.UUID] = None
    ) -> list[LibrarianActivity]:
        activities = list(self._librarian_activities)
        if run_id is not None:
            activities = [activity for activity in activities if activity.run_id == run_id]
        return sorted(activities, key=lambda activity: activity.iteration)

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


def _make_edge(
    source_id: uuid.UUID,
    target_id: uuid.UUID,
    *,
    edge_type: str = "depends-on",
    evidence_type: str = "semantic",
    confidence: float = 1.0,
) -> Edge:
    return Edge(
        source_id=source_id,
        target_id=target_id,
        edge_type=edge_type,
        evidence_type=evidence_type,  # type: ignore[arg-type]
        confidence=confidence,
    )


def _make_work_item(concept_id: uuid.UUID, description: str = "Work item") -> WorkItem:
    return WorkItem(
        item_type="verify_concept",
        concept_id=concept_id,
        description=description,
    )


def _make_failure_record(
    *,
    attempted_at: datetime,
    model_used: str,
    failure_reason: str,
    specificity: float,
    corroboration: float,
    completeness: float,
    reviewer_feedback: str,
) -> FailureRecord:
    return FailureRecord(
        attempted_at=attempted_at,
        model_used=model_used,
        prompt_template="default",
        failure_reason=failure_reason,
        quality_scores={
            "specificity": specificity,
            "structural_corroboration": corroboration,
            "completeness": completeness,
        },
        reviewer_feedback=reviewer_feedback,
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

    def test_includes_code_references_for_click_to_inspect(
        self, client: TestClient, store: _TestStore
    ) -> None:
        """Given concept references, detail payload includes full code references."""
        concept = Concept(
            name="Inspectable",
            description="For click detail.",
            created_by="agent",
            code_references=[
                CodeReference(
                    symbol="pkg.module.inspectable",
                    file_path="src/pkg/module.py",
                    line_range=(10, 32),
                    content_hash="a" * 64,
                    semantic_anchor="function inspectable",
                )
            ],
        )
        store.create_concept(concept)

        response = client.get(f"/api/concepts/{concept.id}")
        assert response.status_code == 200
        data = response.json()
        assert "code_references" in data
        assert len(data["code_references"]) == 1
        assert data["code_references"][0]["file_path"] == "src/pkg/module.py"

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


class TestGetGraphVisualizationFilters:
    def test_filter_by_edge_type_structural_only(self, client: TestClient, store: _TestStore) -> None:
        """Edge filter keeps only structural relationships in graph payload."""
        center = _make_concept("Center")
        structural_target = _make_concept("StructuralTarget")
        semantic_target = _make_concept("SemanticTarget")
        store.create_concept(center)
        store.create_concept(structural_target)
        store.create_concept(semantic_target)
        store.create_edge(
            _make_edge(
                center.id,
                structural_target.id,
                edge_type="calls",
                evidence_type="structural",
                confidence=0.9,
            )
        )
        store.create_edge(
            _make_edge(
                center.id,
                semantic_target.id,
                edge_type="depends-on",
                evidence_type="semantic",
                confidence=0.9,
            )
        )

        response = client.get(f"/api/graph?center={center.id}&radius=2&edge_type=structural")
        assert response.status_code == 200
        data = response.json()
        assert len(data["edges"]) == 1
        assert data["edges"][0]["data"]["evidence_type"] == "structural"

    def test_filter_by_min_confidence_applies_to_nodes_and_edges(
        self, client: TestClient, store: _TestStore
    ) -> None:
        """min_confidence removes low-confidence nodes and low-confidence edges."""
        center = Concept(
            name="Center",
            description="center",
            created_by="agent",
            confidence=0.95,
        )
        high = Concept(
            name="High",
            description="high",
            created_by="agent",
            confidence=0.8,
        )
        low = Concept(
            name="Low",
            description="low",
            created_by="agent",
            confidence=0.3,
        )
        store.create_concept(center)
        store.create_concept(high)
        store.create_concept(low)
        store.create_edge(_make_edge(center.id, high.id, confidence=0.85))
        store.create_edge(_make_edge(center.id, low.id, confidence=0.65))

        response = client.get(f"/api/graph?center={center.id}&radius=2&min_confidence=0.7")
        assert response.status_code == 200
        data = response.json()
        node_ids = {n["data"]["id"] for n in data["nodes"]}
        assert str(center.id) in node_ids
        assert str(high.id) in node_ids
        assert str(low.id) not in node_ids
        assert len(data["edges"]) == 1
        assert data["edges"][0]["data"]["target"] == str(high.id)

    def test_label_filter_highlights_matching_nodes(
        self, client: TestClient, store: _TestStore
    ) -> None:
        """highlight_label marks matching concepts without removing others."""
        center = _make_concept("Center")
        needs_review = _make_concept("NeedsReview", labels={"needs-review"})
        other = _make_concept("Other", labels={"verified"})
        store.create_concept(center)
        store.create_concept(needs_review)
        store.create_concept(other)
        store.create_edge(_make_edge(center.id, needs_review.id, confidence=0.9))
        store.create_edge(_make_edge(center.id, other.id, confidence=0.9))

        response = client.get(
            f"/api/graph?center={center.id}&radius=2&highlight_label=needs-review"
        )
        assert response.status_code == 200
        data = response.json()
        highlighted = {
            n["data"]["label"]: n["data"]["highlighted"] for n in data["nodes"]
        }
        assert highlighted["NeedsReview"] is True
        assert highlighted["Other"] is False

    def test_high_and_low_confidence_are_visually_distinct(
        self, client: TestClient, store: _TestStore
    ) -> None:
        """High and low confidence nodes expose different visual styling metadata."""
        center = _make_concept("Center")
        high = Concept(name="High", description="high", created_by="agent", confidence=0.9)
        low = Concept(name="Low", description="low", created_by="agent", confidence=0.3)
        store.create_concept(center)
        store.create_concept(high)
        store.create_concept(low)
        store.create_edge(_make_edge(center.id, high.id, confidence=0.9))
        store.create_edge(_make_edge(center.id, low.id, confidence=0.3))

        response = client.get(f"/api/graph?center={center.id}&radius=2")
        assert response.status_code == 200
        data = response.json()
        nodes = {n["data"]["label"]: n["data"] for n in data["nodes"]}
        assert nodes["High"]["confidence_bucket"] != nodes["Low"]["confidence_bucket"]
        assert nodes["High"]["visual_opacity"] != nodes["Low"]["visual_opacity"]

    def test_layout_defaults_force_directed_and_supports_toggle(
        self, client: TestClient, store: _TestStore
    ) -> None:
        """Graph response declares default layout and supports explicit override."""
        center = _make_concept("Center")
        neighbor = _make_concept("Neighbor")
        store.create_concept(center)
        store.create_concept(neighbor)
        store.create_edge(_make_edge(center.id, neighbor.id))

        default_response = client.get(f"/api/graph?center={center.id}&radius=2")
        assert default_response.status_code == 200
        assert default_response.json()["layout"] == "force-directed"

        override_response = client.get(
            f"/api/graph?center={center.id}&radius=2&layout=breadthfirst"
        )
        assert override_response.status_code == 200
        assert override_response.json()["layout"] == "breadthfirst"


# ---------------------------------------------------------------------------
# AC-4: GET /api/activity?limit=20
# ---------------------------------------------------------------------------


class TestGetActivity:
    def test_empty_store_returns_empty_list(self, client: TestClient) -> None:
        """Given no work items, GET /api/activity returns an empty list."""
        response = client.get("/api/activity")
        assert response.status_code == 200
        assert response.json() == []

    def test_returns_iterations_ordered_reverse_chronological(
        self, client: TestClient, store: _TestStore
    ) -> None:
        """Iterations are returned newest-first when activity feed loads."""
        concept = _make_concept("C")
        store.create_concept(concept)
        wi = WorkItem(
            item_type="verify_concept",
            concept_id=concept.id,
            description="Analyze concept C",
        )
        store.create_work_item(wi)

        run_id = uuid.uuid4()
        older = LibrarianActivity(
            run_id=run_id,
            iteration=0,
            work_item_id=wi.id,
            status="success",
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        newer = LibrarianActivity(
            run_id=run_id,
            iteration=1,
            work_item_id=wi.id,
            status="success",
            created_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        )
        store.create_librarian_activity(older)
        store.create_librarian_activity(newer)

        response = client.get("/api/activity?limit=20")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2
        assert data[0]["iteration"] == 1
        assert data[1]["iteration"] == 0

    def test_limit_parameter_caps_result_count(
        self, client: TestClient, store: _TestStore
    ) -> None:
        """GET /api/activity?limit=1 returns at most 1 activity entry."""
        concept = _make_concept("C")
        store.create_concept(concept)
        wi = WorkItem(
            item_type="verify_concept",
            concept_id=concept.id,
            description="Analyze concept C",
        )
        store.create_work_item(wi)
        run_id = uuid.uuid4()
        for i in range(5):
            store.create_librarian_activity(
                LibrarianActivity(
                    run_id=run_id,
                    iteration=i,
                    work_item_id=wi.id,
                    status="success",
                )
            )

        response = client.get("/api/activity?limit=1")
        assert response.status_code == 200
        assert len(response.json()) == 1

    def test_default_limit_is_20(
        self, client: TestClient, store: _TestStore
    ) -> None:
        """GET /api/activity with no limit param returns at most 20 entries."""
        concept = _make_concept("C")
        store.create_concept(concept)
        wi = WorkItem(
            item_type="verify_concept",
            concept_id=concept.id,
            description="Analyze concept C",
        )
        store.create_work_item(wi)
        run_id = uuid.uuid4()
        for i in range(25):
            store.create_librarian_activity(
                LibrarianActivity(
                    run_id=run_id,
                    iteration=i,
                    work_item_id=wi.id,
                    status="success",
                )
            )

        response = client.get("/api/activity")
        assert response.status_code == 200
        assert len(response.json()) == 20

    def test_activity_entry_contains_required_display_fields(
        self, client: TestClient, store: _TestStore
    ) -> None:
        """Each entry shows work item, concept, pass/fail status, and failure reason on failure."""
        concept = _make_concept("C")
        store.create_concept(concept)
        wi = _make_work_item(concept.id, "Check this concept.")
        store.create_work_item(wi)

        failure = FailureRecord(
            attempted_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
            model_used="claude-sonnet",
            prompt_template="level15_co_regulation_v1",
            failure_reason="Specificity too low",
            quality_scores={
                "specificity": 0.2,
                "structural_corroboration": 0.6,
                "completeness": 0.4,
            },
            reviewer_feedback="Use concrete data flow details.",
        )
        wi = store.record_failure(wi.id, failure)
        store.update_work_item(wi)
        store.create_librarian_activity(
            LibrarianActivity(
                run_id=uuid.uuid4(),
                iteration=0,
                work_item_id=wi.id,
                status="level15_failure",
                failure_reason="Specificity too low",
            )
        )

        response = client.get("/api/activity?limit=20")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        item = data[0]
        assert "id" in item
        assert item["status"] == "level15_failure"
        assert item["passed"] is False
        assert item["failure_reason"] == "Specificity too low"
        assert item["work_item"]["item_type"] == "verify_concept"
        assert item["work_item"]["description"] == "Check this concept."
        assert item["concept"]["id"] == str(concept.id)
        assert item["co_regulation_scores"]["specificity"] == 0.2

    def test_failed_entry_includes_full_failure_record_for_expansion(
        self, client: TestClient, store: _TestStore
    ) -> None:
        """Failed iteration includes full FailureRecord with reviewer_feedback."""
        concept = _make_concept("C")
        store.create_concept(concept)
        wi = _make_work_item(concept.id, "Check this concept.")
        store.create_work_item(wi)

        failure = FailureRecord(
            attempted_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
            model_used="claude-sonnet",
            prompt_template="level15_co_regulation_v1",
            failure_reason="Completeness score below threshold",
            quality_scores={
                "specificity": 0.6,
                "structural_corroboration": 0.7,
                "completeness": 0.2,
            },
            reviewer_feedback="Document return-value edge cases.",
        )
        wi = store.record_failure(wi.id, failure)
        store.update_work_item(wi)
        store.create_librarian_activity(
            LibrarianActivity(
                run_id=uuid.uuid4(),
                iteration=3,
                work_item_id=wi.id,
                status="level15_failure",
                failure_reason="Completeness score below threshold",
            )
        )

        response = client.get("/api/activity?limit=20")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        record = data[0]["failure_record"]
        assert record["failure_reason"] == "Completeness score below threshold"
        assert record["model_used"] == "claude-sonnet"
        assert record["prompt_template"] == "level15_co_regulation_v1"
        assert record["quality_scores"]["completeness"] == 0.2
        assert record["reviewer_feedback"] == "Document return-value edge cases."


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
# AC-6: GET /api/escalated-items
# ---------------------------------------------------------------------------


class TestGetEscalatedItemsView:
    def test_lists_all_escalated_items_with_description_and_associated_concept(
        self, client: TestClient, store: _TestStore
    ) -> None:
        """Given 5 escalated work items, all 5 include description + concept context."""
        for i in range(5):
            concept = _make_concept(name=f"Concept {i}", labels={"needs-human-review"})
            store.create_concept(concept)
            item = store.create_work_item(
                WorkItem(
                    item_type="verify_concept",
                    concept_id=concept.id,
                    description=f"Escalated item {i}",
                    failure_count=3,
                )
            )
            store.escalate_work_item(item.id)

        response = client.get("/api/escalated-items")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 5
        for row in data:
            assert row["description"].startswith("Escalated item ")
            assert row["associated_concept"]["id"]
            assert row["associated_concept"]["name"].startswith("Concept ")

    def test_includes_full_failure_history_with_model_reason_scores_and_feedback(
        self, client: TestClient, store: _TestStore
    ) -> None:
        """Given an escalated item, response includes full per-attempt failure history."""
        concept = _make_concept(name="Payments")
        store.create_concept(concept)
        item = store.create_work_item(
            WorkItem(
                item_type="verify_concept",
                concept_id=concept.id,
                description="Escalated payments work item",
            )
        )

        first = _make_failure_record(
            attempted_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            model_used="claude-sonnet-4-20250514",
            failure_reason="Level 1.5: specificity below threshold",
            specificity=0.2,
            corroboration=0.9,
            completeness=0.6,
            reviewer_feedback="Missing concrete payment constraints from code.",
        )
        second = _make_failure_record(
            attempted_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
            model_used="claude-sonnet-4-20250514",
            failure_reason="Level 1.5: specificity below threshold",
            specificity=0.25,
            corroboration=0.85,
            completeness=0.6,
            reviewer_feedback="Still generic; include amount limits and currency logic.",
        )
        third = _make_failure_record(
            attempted_at=datetime(2026, 1, 3, tzinfo=timezone.utc),
            model_used="claude-sonnet-4-20250514",
            failure_reason="Level 1.5: specificity below threshold",
            specificity=0.28,
            corroboration=0.82,
            completeness=0.61,
            reviewer_feedback="Name exact functions and validation branches.",
        )

        store.record_failure(item.id, first)
        store.record_failure(item.id, second)
        store.record_failure(item.id, third)
        store.escalate_work_item(item.id)

        response = client.get("/api/escalated-items")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1

        history = data[0]["failure_history"]
        assert len(history) == 3
        assert history[0]["model_used"] == "claude-sonnet-4-20250514"
        assert "specificity below threshold" in history[0]["failure_reason"]
        assert history[0]["quality_scores"]["specificity"] == 0.2
        assert history[0]["reviewer_feedback"] == "Missing concrete payment constraints from code."

    def test_failure_history_preserves_attempt_variation_for_pattern_diagnosis(
        self, client: TestClient, store: _TestStore
    ) -> None:
        """Failure history retains varied attempts to support failure-pattern analysis."""
        concept = _make_concept(name="Auth")
        store.create_concept(concept)
        item = store.create_work_item(
            WorkItem(
                item_type="verify_concept",
                concept_id=concept.id,
                description="Escalated auth work item",
            )
        )
        store.record_failure(
            item.id,
            _make_failure_record(
                attempted_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
                model_used="claude-sonnet-4-20250514",
                failure_reason="Level 1.5: specificity below threshold",
                specificity=0.30,
                corroboration=0.90,
                completeness=0.72,
                reviewer_feedback="Description too generic.",
            ),
        )
        store.record_failure(
            item.id,
            _make_failure_record(
                attempted_at=datetime(2026, 2, 2, tzinfo=timezone.utc),
                model_used="qwen2.5:7b",
                failure_reason="Level 1.5: structural corroboration below threshold",
                specificity=0.75,
                corroboration=0.12,
                completeness=0.80,
                reviewer_feedback="Relationship claims not grounded in code.",
            ),
        )
        store.record_failure(
            item.id,
            _make_failure_record(
                attempted_at=datetime(2026, 2, 3, tzinfo=timezone.utc),
                model_used="claude-sonnet-4-20250514",
                failure_reason="Level 1: generic description",
                specificity=0.35,
                corroboration=0.70,
                completeness=0.50,
                reviewer_feedback="Use repository-specific terminology.",
            ),
        )
        store.escalate_work_item(item.id)

        response = client.get("/api/escalated-items")
        assert response.status_code == 200
        data = response.json()
        history = data[0]["failure_history"]
        models = {attempt["model_used"] for attempt in history}
        reasons = {attempt["failure_reason"] for attempt in history}
        assert models == {"claude-sonnet-4-20250514", "qwen2.5:7b"}
        assert len(reasons) == 3


# ---------------------------------------------------------------------------
# AC-6 (Story 11.6): Health Dashboard — metric targets, escalated count, refresh
# ---------------------------------------------------------------------------


class TestHealthDashboard:
    """Story 11.6: single-glance health dashboard for engineering leads."""

    def test_coverage_target_is_eighty_percent(self, client: TestClient) -> None:
        """AC-1: coverage target must be 0.80 (80%)."""
        response = client.get("/api/health")
        assert response.status_code == 200
        assert response.json()["targets"]["coverage_target"] == pytest.approx(0.80)

    def test_freshness_target_is_ninety_percent(self, client: TestClient) -> None:
        """AC-1: freshness target must be 0.90 (90%)."""
        response = client.get("/api/health")
        assert response.status_code == 200
        assert response.json()["targets"]["freshness_target"] == pytest.approx(0.90)

    def test_blast_radius_target_is_seventy_percent(self, client: TestClient) -> None:
        """AC-1: blast radius completeness target must be 0.70 (70%)."""
        response = client.get("/api/health")
        assert response.status_code == 200
        assert response.json()["targets"]["blast_radius_target"] == pytest.approx(0.70)

    def test_health_contains_escalated_count(self, client: TestClient) -> None:
        """AC-3: Health response contains an escalated_count field."""
        response = client.get("/api/health")
        assert response.status_code == 200
        assert "escalated_count" in response.json()

    def test_escalated_count_zero_when_no_escalations(
        self, client: TestClient, store: _TestStore
    ) -> None:
        """AC-3: escalated_count is 0 when no items are escalated."""
        concept = _make_concept("C")
        store.create_concept(concept)
        store.create_work_item(_make_work_item(concept.id))

        response = client.get("/api/health")
        assert response.status_code == 200
        assert response.json()["escalated_count"] == 0

    def test_escalated_count_reflects_escalated_items(
        self, client: TestClient, store: _TestStore
    ) -> None:
        """AC-3: escalated_count matches the actual number of escalated work items."""
        concept = _make_concept("C")
        store.create_concept(concept)
        wi1 = _make_work_item(concept.id)
        wi2 = _make_work_item(concept.id, "Second item")
        store.create_work_item(wi1)
        store.create_work_item(wi2)
        store.escalate_work_item(wi1.id)

        response = client.get("/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data["escalated_count"] == 1
        assert data["work_queue_depth"] == 2

    def test_effective_weights_include_all_six_factors(
        self, client: TestClient
    ) -> None:
        """AC-2: effective_weights contains all six priority factors."""
        response = client.get("/api/health")
        assert response.status_code == 200
        weights = response.json()["effective_weights"]
        expected_factors = {
            "coverage_gap",
            "needs_review",
            "developer_proximity",
            "git_activity",
            "staleness",
            "failure_urgency",
        }
        assert expected_factors == set(weights.keys())

    def test_refresh_shows_updated_queue_depth(
        self, client: TestClient, store: _TestStore
    ) -> None:
        """AC-4: After adding a new work item, a fresh request shows updated depth."""
        concept = _make_concept("C")
        store.create_concept(concept)

        response1 = client.get("/api/health")
        assert response1.status_code == 200
        initial_depth = response1.json()["work_queue_depth"]

        store.create_work_item(_make_work_item(concept.id))

        response2 = client.get("/api/health")
        assert response2.status_code == 200
        assert response2.json()["work_queue_depth"] == initial_depth + 1

    def test_refresh_shows_updated_escalated_count(
        self, client: TestClient, store: _TestStore
    ) -> None:
        """AC-4: After escalating a work item, a fresh request shows updated escalated_count."""
        concept = _make_concept("C")
        store.create_concept(concept)
        wi = _make_work_item(concept.id)
        store.create_work_item(wi)

        response1 = client.get("/api/health")
        assert response1.json()["escalated_count"] == 0

        store.escalate_work_item(wi.id)

        response2 = client.get("/api/health")
        assert response2.json()["escalated_count"] == 1
