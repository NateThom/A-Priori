"""Tests for review workflow API endpoints in shells/ui/server.py.

AC traceability: Story 11.2b migrated to the production API server factory.

AC-1 (GET /api/escalated-items): Given escalated work items exist, when called,
    then escalated items with full failure history are returned.

AC-2 (POST /api/concepts/{id}/verify): Given a concept exists, when called,
    then the concept is verified and a ReviewOutcome is recorded.

AC-3 (POST /api/concepts/{id}/correct): Given a concept exists, when called
    with error_type and correction_details, then the concept is updated and a
    ReviewOutcome is recorded.

AC-4 (POST /api/concepts/{id}/flag): Given a concept exists, when called,
    then the concept is flagged and a review_concept work item is created.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from apriori.config import Config
from apriori.models.concept import Concept
from apriori.models.work_item import FailureRecord, WorkItem
from apriori.shells.ui.server import create_app
from apriori.storage.sqlite_store import SQLiteStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_concept(**kwargs) -> Concept:
    defaults = dict(name="TestConcept", description="A test concept.", created_by="agent")
    defaults.update(kwargs)
    return Concept(**defaults)


def _make_escalated_item(store: SQLiteStore, concept_id: uuid.UUID) -> WorkItem:
    """Create an escalated work item with a failure record."""
    item = WorkItem(
        item_type="investigate_file",
        concept_id=concept_id,
        description="Escalated for human review.",
    )
    created = store.create_work_item(item)
    failure = FailureRecord(
        attempted_at=datetime.now(timezone.utc),
        model_used="claude-3",
        prompt_template="default",
        failure_reason="Repeated low quality output.",
    )
    store.record_failure(created.id, failure)
    return store.escalate_work_item(created.id)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def store(tmp_path: Path) -> SQLiteStore:
    return SQLiteStore(tmp_path / "test.db")


@pytest.fixture()
def client(store: SQLiteStore) -> TestClient:
    """Create a TestClient using the production create_app() factory."""
    app = create_app(store=store, config=Config())
    return TestClient(app)


@pytest.fixture()
def concept(store: SQLiteStore) -> Concept:
    c = _make_concept(confidence=0.5)
    return store.create_concept(c)


# ---------------------------------------------------------------------------
# AC-1: GET /api/escalated-items
# ---------------------------------------------------------------------------


class TestGetEscalatedItems:
    """AC-1: escalated endpoint returns full failure history."""

    def test_escalated_returns_200(
        self,
        client: TestClient,
        store: SQLiteStore,
        concept: Concept,
    ):
        _make_escalated_item(store, concept.id)
        response = client.get("/api/escalated-items")
        assert response.status_code == 200

    def test_escalated_returns_list(
        self,
        client: TestClient,
        store: SQLiteStore,
        concept: Concept,
    ):
        _make_escalated_item(store, concept.id)
        _make_escalated_item(store, concept.id)
        response = client.get("/api/escalated-items")
        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 2

    def test_escalated_includes_failure_history(
        self,
        client: TestClient,
        store: SQLiteStore,
        concept: Concept,
    ):
        _make_escalated_item(store, concept.id)
        response = client.get("/api/escalated-items")
        data = response.json()
        assert len(data) == 1
        item = data[0]
        assert "failure_history" in item
        assert len(item["failure_history"]) >= 1
        assert item["failure_history"][0]["failure_reason"] == "Repeated low quality output."

    def test_escalated_includes_associated_concept(
        self,
        client: TestClient,
        store: SQLiteStore,
        concept: Concept,
    ):
        _make_escalated_item(store, concept.id)
        response = client.get("/api/escalated-items")
        data = response.json()
        assert data[0]["associated_concept"]["id"] == str(concept.id)
        assert data[0]["associated_concept"]["name"] == concept.name

    def test_escalated_empty_when_no_items(self, client: TestClient):
        response = client.get("/api/escalated-items")
        assert response.status_code == 200
        assert response.json() == []

    def test_escalated_only_returns_escalated_items(
        self,
        client: TestClient,
        store: SQLiteStore,
        concept: Concept,
    ):
        normal = WorkItem(
            item_type="verify_concept",
            concept_id=concept.id,
            description="Normal work item.",
        )
        store.create_work_item(normal)
        _make_escalated_item(store, concept.id)

        response = client.get("/api/escalated-items")
        data = response.json()

        assert len(data) == 1
        assert data[0]["failure_count"] >= 1


# ---------------------------------------------------------------------------
# AC-2: POST /api/concepts/{id}/verify
# ---------------------------------------------------------------------------


class TestVerifyConcept:
    """AC-2: verify endpoint records verification outcome."""

    def test_verify_returns_200(self, client: TestClient, concept: Concept):
        response = client.post(
            f"/api/concepts/{concept.id}/verify",
            json={"reviewer": "alice"},
        )
        assert response.status_code == 200

    def test_verify_response_contains_concept_and_outcome(
        self,
        client: TestClient,
        concept: Concept,
    ):
        response = client.post(
            f"/api/concepts/{concept.id}/verify",
            json={"reviewer": "alice"},
        )
        data = response.json()
        assert "message" in data
        assert "concept" in data
        assert "review_outcome" in data

    def test_verify_concept_has_verified_by(self, client: TestClient, concept: Concept):
        response = client.post(
            f"/api/concepts/{concept.id}/verify",
            json={"reviewer": "alice"},
        )
        data = response.json()
        assert data["concept"]["verified_by"] == "alice"

    def test_verify_review_outcome_action_is_verified(
        self,
        client: TestClient,
        concept: Concept,
    ):
        response = client.post(
            f"/api/concepts/{concept.id}/verify",
            json={"reviewer": "alice"},
        )
        data = response.json()
        assert data["review_outcome"]["action"] == "verified"
        assert data["review_outcome"]["reviewer"] == "alice"

    def test_verify_boosts_confidence(self, client: TestClient, concept: Concept):
        response = client.post(
            f"/api/concepts/{concept.id}/verify",
            json={"reviewer": "alice"},
        )
        data = response.json()
        assert data["concept"]["confidence"] == pytest.approx(0.6)

    def test_verify_returns_404_for_unknown_concept(self, client: TestClient):
        response = client.post(
            f"/api/concepts/{uuid.uuid4()}/verify",
            json={"reviewer": "alice"},
        )
        assert response.status_code == 404

    def test_verify_requires_reviewer(self, client: TestClient, concept: Concept):
        response = client.post(
            f"/api/concepts/{concept.id}/verify",
            json={},
        )
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# AC-3: POST /api/concepts/{id}/correct
# ---------------------------------------------------------------------------


class TestCorrectConcept:
    """AC-3: correct endpoint updates concept and records correction outcome."""

    def test_correct_returns_200(self, client: TestClient, concept: Concept):
        response = client.post(
            f"/api/concepts/{concept.id}/correct",
            json={"reviewer": "bob", "error_type": "description_wrong"},
        )
        assert response.status_code == 200

    def test_correct_response_contains_concept_and_outcome(
        self,
        client: TestClient,
        concept: Concept,
    ):
        response = client.post(
            f"/api/concepts/{concept.id}/correct",
            json={"reviewer": "bob", "error_type": "relationship_missing"},
        )
        data = response.json()
        assert "concept" in data
        assert "review_outcome" in data

    def test_correct_review_outcome_records_error_type(
        self,
        client: TestClient,
        concept: Concept,
    ):
        response = client.post(
            f"/api/concepts/{concept.id}/correct",
            json={
                "reviewer": "bob",
                "error_type": "relationship_missing",
                "correction_details": "Edge to DatabasePool is missing.",
            },
        )
        data = response.json()
        assert data["review_outcome"]["action"] == "corrected"
        assert data["review_outcome"]["error_type"] == "relationship_missing"
        assert data["review_outcome"]["correction_details"] == "Edge to DatabasePool is missing."

    def test_correct_all_valid_error_types(self, client: TestClient, store: SQLiteStore):
        valid_types = [
            "description_wrong",
            "relationship_missing",
            "relationship_hallucinated",
            "confidence_miscalibrated",
            "other",
        ]
        for error_type in valid_types:
            c = _make_concept(name=f"Concept_{error_type}")
            created = store.create_concept(c)
            response = client.post(
                f"/api/concepts/{created.id}/correct",
                json={"reviewer": "bob", "error_type": error_type},
            )
            assert response.status_code == 200, f"Failed for error_type={error_type}"
            data = response.json()
            assert data["review_outcome"]["error_type"] == error_type

    def test_correct_accepts_description_and_relationships(
        self,
        client: TestClient,
        concept: Concept,
    ):
        relationships = [
            {
                "target_name": "DatabasePool",
                "edge_type": "depends-on",
                "confidence": 0.9,
            }
        ]
        response = client.post(
            f"/api/concepts/{concept.id}/correct",
            json={
                "reviewer": "bob",
                "error_type": "relationship_missing",
                "description": "Updated concept description",
                "relationships": relationships,
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["concept"]["description"] == "Updated concept description"
        assert data["concept"]["metadata"]["relationship_corrections"] == relationships

    def test_correct_returns_422_for_invalid_error_type(
        self,
        client: TestClient,
        concept: Concept,
    ):
        response = client.post(
            f"/api/concepts/{concept.id}/correct",
            json={"reviewer": "bob", "error_type": "invalid_type"},
        )
        assert response.status_code == 422

    def test_correct_returns_404_for_unknown_concept(self, client: TestClient):
        response = client.post(
            f"/api/concepts/{uuid.uuid4()}/correct",
            json={"reviewer": "bob", "error_type": "description_wrong"},
        )
        assert response.status_code == 404

    def test_correct_without_correction_details_is_valid(
        self,
        client: TestClient,
        concept: Concept,
    ):
        response = client.post(
            f"/api/concepts/{concept.id}/correct",
            json={"reviewer": "bob", "error_type": "other"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["review_outcome"]["correction_details"] is None


# ---------------------------------------------------------------------------
# AC-4: POST /api/concepts/{id}/flag
# ---------------------------------------------------------------------------


class TestFlagConcept:
    """AC-4: flag endpoint creates review item and applies needs-review label."""

    def test_flag_returns_200(self, client: TestClient, concept: Concept):
        response = client.post(
            f"/api/concepts/{concept.id}/flag",
            json={"reviewer": "carol"},
        )
        assert response.status_code == 200

    def test_flag_response_contains_concept_outcome_and_work_item(
        self,
        client: TestClient,
        concept: Concept,
    ):
        response = client.post(
            f"/api/concepts/{concept.id}/flag",
            json={"reviewer": "carol"},
        )
        data = response.json()
        assert "concept" in data
        assert "review_outcome" in data
        assert "work_item" in data

    def test_flag_applies_needs_review_label(self, client: TestClient, concept: Concept):
        response = client.post(
            f"/api/concepts/{concept.id}/flag",
            json={"reviewer": "carol"},
        )
        data = response.json()
        assert "needs-review" in data["concept"]["labels"]

    def test_flag_review_outcome_action_is_flagged(
        self,
        client: TestClient,
        concept: Concept,
    ):
        response = client.post(
            f"/api/concepts/{concept.id}/flag",
            json={"reviewer": "carol"},
        )
        data = response.json()
        assert data["review_outcome"]["action"] == "flagged"
        assert data["review_outcome"]["reviewer"] == "carol"

    def test_flag_creates_review_concept_work_item(
        self,
        client: TestClient,
        concept: Concept,
    ):
        response = client.post(
            f"/api/concepts/{concept.id}/flag",
            json={"reviewer": "carol"},
        )
        data = response.json()
        assert data["work_item"]["item_type"] == "review_concept"
        assert data["work_item"]["concept_id"] == str(concept.id)

    def test_flag_returns_404_for_unknown_concept(self, client: TestClient):
        response = client.post(
            f"/api/concepts/{uuid.uuid4()}/flag",
            json={"reviewer": "carol"},
        )
        assert response.status_code == 404

    def test_flag_requires_reviewer(self, client: TestClient, concept: Concept):
        response = client.post(
            f"/api/concepts/{concept.id}/flag",
            json={},
        )
        assert response.status_code == 422
