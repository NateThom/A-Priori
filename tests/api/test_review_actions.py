"""Tests for Review Action API endpoints — AC traceability: Story 11.2b.

AC-1 (GET /api/escalated): Given escalated work items exist, when called, then
    escalated work items with full failure history are returned.

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

from apriori.models.concept import Concept
from apriori.models.work_item import FailureRecord, WorkItem
from apriori.storage.sqlite_store import SQLiteStore
import apriori.api.server as api_server


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
    """Create a TestClient with a fresh store injected."""
    api_server._store = store
    yield TestClient(api_server.app)
    api_server._store = None


@pytest.fixture()
def concept(store: SQLiteStore) -> Concept:
    c = _make_concept(confidence=0.5)
    return store.create_concept(c)


# ---------------------------------------------------------------------------
# AC-1: GET /api/escalated
# ---------------------------------------------------------------------------

class TestGetEscalated:
    """AC-1: GET /api/escalated returns escalated work items with full failure history."""

    def test_escalated_returns_200(self, client: TestClient, store: SQLiteStore, concept: Concept):
        # Given: an escalated work item
        _make_escalated_item(store, concept.id)
        # When: GET /api/escalated
        response = client.get("/api/escalated")
        # Then: 200 OK
        assert response.status_code == 200

    def test_escalated_returns_list(self, client: TestClient, store: SQLiteStore, concept: Concept):
        # Given: two escalated items
        _make_escalated_item(store, concept.id)
        _make_escalated_item(store, concept.id)
        # When: GET /api/escalated
        response = client.get("/api/escalated")
        data = response.json()
        # Then: list of 2 items returned
        assert isinstance(data, list)
        assert len(data) == 2

    def test_escalated_includes_failure_history(self, client: TestClient, store: SQLiteStore, concept: Concept):
        # Given: an escalated item with a failure record
        _make_escalated_item(store, concept.id)
        # When: GET /api/escalated
        response = client.get("/api/escalated")
        data = response.json()
        # Then: failure_records are present in the response
        assert len(data) == 1
        item = data[0]
        assert "failure_records" in item
        assert len(item["failure_records"]) >= 1
        assert item["failure_records"][0]["failure_reason"] == "Repeated low quality output."

    def test_escalated_items_have_escalated_flag(self, client: TestClient, store: SQLiteStore, concept: Concept):
        # Given: an escalated item
        _make_escalated_item(store, concept.id)
        # When: GET /api/escalated
        response = client.get("/api/escalated")
        data = response.json()
        # Then: escalated=True in response
        assert data[0]["escalated"] is True

    def test_escalated_empty_when_no_items(self, client: TestClient):
        # Given: no work items in store
        # When: GET /api/escalated
        response = client.get("/api/escalated")
        # Then: empty list
        assert response.status_code == 200
        assert response.json() == []

    def test_escalated_only_returns_escalated_items(
        self, client: TestClient, store: SQLiteStore, concept: Concept
    ):
        # Given: one normal (non-escalated) work item and one escalated item
        normal = WorkItem(
            item_type="verify_concept",
            concept_id=concept.id,
            description="Normal work item.",
        )
        store.create_work_item(normal)
        _make_escalated_item(store, concept.id)
        # When: GET /api/escalated
        response = client.get("/api/escalated")
        data = response.json()
        # Then: only the escalated item is returned
        assert len(data) == 1
        assert data[0]["escalated"] is True


# ---------------------------------------------------------------------------
# AC-2: POST /api/concepts/{id}/verify
# ---------------------------------------------------------------------------

class TestVerifyConcept:
    """AC-2: POST /api/concepts/{id}/verify verifies concept and records ReviewOutcome."""

    def test_verify_returns_200(self, client: TestClient, concept: Concept):
        # When: POST verify
        response = client.post(
            f"/api/concepts/{concept.id}/verify",
            json={"reviewer": "alice"},
        )
        # Then: 200 OK
        assert response.status_code == 200

    def test_verify_response_contains_concept_and_outcome(
        self, client: TestClient, concept: Concept
    ):
        # When: POST verify
        response = client.post(
            f"/api/concepts/{concept.id}/verify",
            json={"reviewer": "alice"},
        )
        data = response.json()
        # Then: response has concept and review_outcome
        assert "concept" in data
        assert "review_outcome" in data

    def test_verify_concept_has_verified_by(self, client: TestClient, concept: Concept):
        # When: POST verify
        response = client.post(
            f"/api/concepts/{concept.id}/verify",
            json={"reviewer": "alice"},
        )
        data = response.json()
        # Then: verified_by is set
        assert data["concept"]["verified_by"] == "alice"

    def test_verify_review_outcome_action_is_verified(
        self, client: TestClient, concept: Concept
    ):
        # When: POST verify
        response = client.post(
            f"/api/concepts/{concept.id}/verify",
            json={"reviewer": "alice"},
        )
        data = response.json()
        # Then: review_outcome has action=verified
        assert data["review_outcome"]["action"] == "verified"
        assert data["review_outcome"]["reviewer"] == "alice"

    def test_verify_boosts_confidence(self, client: TestClient, concept: Concept):
        # Given: concept with confidence=0.5
        # When: POST verify
        response = client.post(
            f"/api/concepts/{concept.id}/verify",
            json={"reviewer": "alice"},
        )
        data = response.json()
        # Then: confidence boosted
        assert data["concept"]["confidence"] == pytest.approx(0.6)

    def test_verify_returns_404_for_unknown_concept(self, client: TestClient):
        # Given: non-existent concept_id
        # When: POST verify
        response = client.post(
            f"/api/concepts/{uuid.uuid4()}/verify",
            json={"reviewer": "alice"},
        )
        # Then: 404
        assert response.status_code == 404

    def test_verify_requires_reviewer(self, client: TestClient, concept: Concept):
        # When: POST verify without reviewer
        response = client.post(
            f"/api/concepts/{concept.id}/verify",
            json={},
        )
        # Then: 422 Unprocessable Entity
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# AC-3: POST /api/concepts/{id}/correct
# ---------------------------------------------------------------------------

class TestCorrectConcept:
    """AC-3: POST /api/concepts/{id}/correct with error_type updates concept and records ReviewOutcome."""

    def test_correct_returns_200(self, client: TestClient, concept: Concept):
        # When: POST correct
        response = client.post(
            f"/api/concepts/{concept.id}/correct",
            json={"reviewer": "bob", "error_type": "description_wrong"},
        )
        # Then: 200 OK
        assert response.status_code == 200

    def test_correct_response_contains_concept_and_outcome(
        self, client: TestClient, concept: Concept
    ):
        # When: POST correct
        response = client.post(
            f"/api/concepts/{concept.id}/correct",
            json={"reviewer": "bob", "error_type": "relationship_missing"},
        )
        data = response.json()
        # Then: response has concept and review_outcome
        assert "concept" in data
        assert "review_outcome" in data

    def test_correct_review_outcome_records_error_type(
        self, client: TestClient, concept: Concept
    ):
        # When: POST correct
        response = client.post(
            f"/api/concepts/{concept.id}/correct",
            json={
                "reviewer": "bob",
                "error_type": "relationship_missing",
                "correction_details": "Edge to DatabasePool is missing.",
            },
        )
        data = response.json()
        # Then: error_type recorded in review_outcome
        assert data["review_outcome"]["action"] == "corrected"
        assert data["review_outcome"]["error_type"] == "relationship_missing"
        assert data["review_outcome"]["correction_details"] == "Edge to DatabasePool is missing."

    def test_correct_all_valid_error_types(self, client: TestClient, store: SQLiteStore):
        # Given: all five valid error types
        valid_types = [
            "description_wrong",
            "relationship_missing",
            "relationship_hallucinated",
            "confidence_miscalibrated",
            "other",
        ]
        for error_type in valid_types:
            c = _make_concept(name=f"Concept_{error_type}")
            concept = store.create_concept(c)
            response = client.post(
                f"/api/concepts/{concept.id}/correct",
                json={"reviewer": "bob", "error_type": error_type},
            )
            assert response.status_code == 200, f"Failed for error_type={error_type}"
            data = response.json()
            assert data["review_outcome"]["error_type"] == error_type

    def test_correct_returns_422_for_invalid_error_type(
        self, client: TestClient, concept: Concept
    ):
        # When: POST correct with an invalid error_type
        response = client.post(
            f"/api/concepts/{concept.id}/correct",
            json={"reviewer": "bob", "error_type": "invalid_type"},
        )
        # Then: 422
        assert response.status_code == 422

    def test_correct_returns_404_for_unknown_concept(self, client: TestClient):
        # Given: non-existent concept_id
        # When: POST correct
        response = client.post(
            f"/api/concepts/{uuid.uuid4()}/correct",
            json={"reviewer": "bob", "error_type": "description_wrong"},
        )
        # Then: 404
        assert response.status_code == 404

    def test_correct_without_correction_details_is_valid(
        self, client: TestClient, concept: Concept
    ):
        # When: POST correct without correction_details
        response = client.post(
            f"/api/concepts/{concept.id}/correct",
            json={"reviewer": "bob", "error_type": "other"},
        )
        # Then: 200 OK
        assert response.status_code == 200
        data = response.json()
        assert data["review_outcome"]["correction_details"] is None


# ---------------------------------------------------------------------------
# AC-4: POST /api/concepts/{id}/flag
# ---------------------------------------------------------------------------

class TestFlagConcept:
    """AC-4: POST /api/concepts/{id}/flag flags concept and creates review_concept work item."""

    def test_flag_returns_200(self, client: TestClient, concept: Concept):
        # When: POST flag
        response = client.post(
            f"/api/concepts/{concept.id}/flag",
            json={"reviewer": "carol"},
        )
        # Then: 200 OK
        assert response.status_code == 200

    def test_flag_response_contains_concept_outcome_and_work_item(
        self, client: TestClient, concept: Concept
    ):
        # When: POST flag
        response = client.post(
            f"/api/concepts/{concept.id}/flag",
            json={"reviewer": "carol"},
        )
        data = response.json()
        # Then: response has concept, review_outcome, and work_item
        assert "concept" in data
        assert "review_outcome" in data
        assert "work_item" in data

    def test_flag_applies_needs_review_label(self, client: TestClient, concept: Concept):
        # When: POST flag
        response = client.post(
            f"/api/concepts/{concept.id}/flag",
            json={"reviewer": "carol"},
        )
        data = response.json()
        # Then: needs-review label applied to concept
        assert "needs-review" in data["concept"]["labels"]

    def test_flag_review_outcome_action_is_flagged(
        self, client: TestClient, concept: Concept
    ):
        # When: POST flag
        response = client.post(
            f"/api/concepts/{concept.id}/flag",
            json={"reviewer": "carol"},
        )
        data = response.json()
        # Then: review_outcome has action=flagged
        assert data["review_outcome"]["action"] == "flagged"
        assert data["review_outcome"]["reviewer"] == "carol"

    def test_flag_creates_review_concept_work_item(
        self, client: TestClient, concept: Concept
    ):
        # When: POST flag
        response = client.post(
            f"/api/concepts/{concept.id}/flag",
            json={"reviewer": "carol"},
        )
        data = response.json()
        # Then: work_item type is review_concept
        assert data["work_item"]["item_type"] == "review_concept"
        assert data["work_item"]["concept_id"] == str(concept.id)

    def test_flag_returns_404_for_unknown_concept(self, client: TestClient):
        # Given: non-existent concept_id
        # When: POST flag
        response = client.post(
            f"/api/concepts/{uuid.uuid4()}/flag",
            json={"reviewer": "carol"},
        )
        # Then: 404
        assert response.status_code == 404

    def test_flag_requires_reviewer(self, client: TestClient, concept: Concept):
        # When: POST flag without reviewer
        response = client.post(
            f"/api/concepts/{concept.id}/flag",
            json={},
        )
        # Then: 422 Unprocessable Entity
        assert response.status_code == 422
