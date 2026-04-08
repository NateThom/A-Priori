"""Tests for Story 11.2a read-only Graph API."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from apriori.models.concept import Concept
from apriori.models.edge import Edge
from apriori.models.impact import ImpactEntry, ImpactProfile
from apriori.models.work_item import WorkItem
from apriori.shells.ui.server import create_app
from apriori.storage.sqlite_store import SQLiteStore


def _make_concept(name: str, labels: set[str] | None = None, impact_profile: ImpactProfile | None = None) -> Concept:
    return Concept(
        name=name,
        description=f"{name} description",
        labels=labels or set(),
        created_by="agent",
        impact_profile=impact_profile,
    )


def test_get_concepts_filters_by_label(tmp_path):
    store = SQLiteStore(tmp_path / "api.db")
    c1 = _make_concept("alpha", labels={"needs-review"})
    c2 = _make_concept("beta", labels={"verified"})
    store.create_concept(c1)
    store.create_concept(c2)

    client = TestClient(create_app(store=store, total_source_files=10))
    response = client.get("/api/concepts", params={"label": "needs-review"})

    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 1
    assert payload[0]["id"] == str(c1.id)


def test_get_concept_by_id_returns_edges_and_impact(tmp_path):
    store = SQLiteStore(tmp_path / "api.db")
    target = _make_concept("target")
    impact = ImpactProfile(
        structural_impact=[
            ImpactEntry(
                target_concept_id=target.id,
                confidence=0.9,
                relationship_path=[str(uuid.uuid4())],
                depth=1,
                rationale="Target is directly called",
            )
        ],
        last_computed=datetime.now(timezone.utc),
    )
    source = _make_concept("source", impact_profile=impact)
    store.create_concept(source)
    store.create_concept(target)

    edge = Edge(
        source_id=source.id,
        target_id=target.id,
        edge_type="calls",
        evidence_type="structural",
    )
    store.create_edge(edge)

    client = TestClient(create_app(store=store, total_source_files=10))
    response = client.get(f"/api/concepts/{source.id}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["concept"]["id"] == str(source.id)
    assert payload["edges"][0]["id"] == str(edge.id)
    assert payload["concept"]["impact_profile"] is not None


def test_get_graph_returns_cytoscape_shape(tmp_path):
    store = SQLiteStore(tmp_path / "api.db")
    center = _make_concept("center", labels={"verified"})
    child = _make_concept("child")
    store.create_concept(center)
    store.create_concept(child)
    edge = Edge(
        source_id=center.id,
        target_id=child.id,
        edge_type="depends-on",
        evidence_type="semantic",
        confidence=0.7,
    )
    store.create_edge(edge)

    client = TestClient(create_app(store=store, total_source_files=10))
    response = client.get("/api/graph", params={"center": str(center.id), "radius": 2})

    assert response.status_code == 200
    payload = response.json()
    assert {"nodes", "edges"} == set(payload.keys())
    assert payload["nodes"][0]["data"].keys() >= {"id", "label", "type"}
    assert payload["edges"][0]["data"].keys() >= {"id", "source", "target", "weight"}


def test_get_activity_returns_recent_work_items(tmp_path):
    store = SQLiteStore(tmp_path / "api.db")
    concept = _make_concept("work-source")
    store.create_concept(concept)

    older = WorkItem(
        item_type="verify_concept",
        concept_id=concept.id,
        description="older",
        created_at=datetime.now(timezone.utc).replace(microsecond=0),
    )
    newer = WorkItem(
        item_type="verify_concept",
        concept_id=concept.id,
        description="newer",
    )
    store.create_work_item(older)
    store.create_work_item(newer)

    client = TestClient(create_app(store=store, total_source_files=10))
    response = client.get("/api/activity", params={"limit": 1})

    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 1
    assert payload[0]["description"] == "newer"


def test_get_health_returns_metrics_targets_weights_and_queue_depth(tmp_path):
    store = SQLiteStore(tmp_path / "api.db")
    concept = _make_concept("health-concept")
    store.create_concept(concept)
    store.create_work_item(
        WorkItem(item_type="verify_concept", concept_id=concept.id, description="pending")
    )

    client = TestClient(create_app(store=store, total_source_files=10))
    response = client.get("/api/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["metrics"].keys() >= {"coverage", "freshness", "blast_radius_completeness"}
    assert payload["targets"].keys() >= {"coverage", "freshness", "blast_radius_completeness"}
    assert isinstance(payload["effective_weights"], dict)
    assert payload["queue_depth"] == 1
