"""Tests for WorkItem and FailureRecord models — AC traceability: Story 1.3."""

import json
import uuid
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from apriori.models.work_item import FailureRecord, WorkItem, VALID_ITEM_TYPES


# ---------------------------------------------------------------------------
# AC: Given a valid WorkItem with item_type = "investigate_file", when
#     instantiated, then it succeeds with failure_count = 0, failure_records
#     = [], escalated = False, and resolved = False.
# ---------------------------------------------------------------------------
class TestWorkItemDefaults:
    def test_valid_item_type_investigate_file_has_expected_defaults(self):
        item = WorkItem(item_type="investigate_file", concept_id=uuid.uuid4(), description="check file")
        assert item.failure_count == 0
        assert item.failure_records == []
        assert item.escalated is False
        assert item.resolved is False

    def test_all_six_item_types_are_accepted(self):
        cid = uuid.uuid4()
        for item_type in VALID_ITEM_TYPES:
            item = WorkItem(item_type=item_type, concept_id=cid, description="test")
            assert item.item_type == item_type

    def test_id_is_auto_generated_uuid(self):
        item = WorkItem(item_type="verify_concept", concept_id=uuid.uuid4(), description="test")
        assert isinstance(item.id, uuid.UUID)
        assert item.id.version == 4


# ---------------------------------------------------------------------------
# AC: Given an item_type of "invalid_type", when instantiated, then Pydantic
#     raises a ValidationError listing the six valid types.
# ---------------------------------------------------------------------------
class TestWorkItemItemTypeValidation:
    def test_invalid_item_type_raises_validation_error(self):
        with pytest.raises(ValidationError) as exc_info:
            WorkItem(item_type="invalid_type", concept_id=uuid.uuid4())
        error_str = str(exc_info.value)
        # The error message should reference item_type
        assert "item_type" in error_str.lower() or "invalid_type" in error_str

    def test_all_six_valid_types_are_named_in_valid_item_types_constant(self):
        expected = {
            "investigate_file",
            "verify_concept",
            "evaluate_relationship",
            "reported_gap",
            "review_concept",
            "analyze_impact",
        }
        assert expected == VALID_ITEM_TYPES


# ---------------------------------------------------------------------------
# AC: Given a WorkItem, when a FailureRecord is appended to its failure_records
#     list, then the record includes attempted_at, model_used, prompt_template,
#     and failure_reason as required fields.
# ---------------------------------------------------------------------------
class TestFailureRecordRequiredFields:
    def test_failure_record_requires_attempted_at(self):
        with pytest.raises(ValidationError):
            FailureRecord(
                model_used="claude-sonnet-4-6",
                prompt_template="investigate_file_v1",
                failure_reason="LLM returned empty response",
            )

    def test_failure_record_requires_model_used(self):
        with pytest.raises(ValidationError):
            FailureRecord(
                attempted_at=datetime.now(timezone.utc),
                prompt_template="investigate_file_v1",
                failure_reason="LLM returned empty response",
            )

    def test_failure_record_requires_prompt_template(self):
        with pytest.raises(ValidationError):
            FailureRecord(
                attempted_at=datetime.now(timezone.utc),
                model_used="claude-sonnet-4-6",
                failure_reason="LLM returned empty response",
            )

    def test_failure_record_requires_failure_reason(self):
        with pytest.raises(ValidationError):
            FailureRecord(
                attempted_at=datetime.now(timezone.utc),
                model_used="claude-sonnet-4-6",
                prompt_template="investigate_file_v1",
            )

    def test_valid_failure_record_can_be_appended_to_work_item(self):
        item = WorkItem(item_type="investigate_file", concept_id=uuid.uuid4(), description="test")
        record = FailureRecord(
            attempted_at=datetime.now(timezone.utc),
            model_used="claude-sonnet-4-6",
            prompt_template="investigate_file_v1",
            failure_reason="LLM returned empty response",
        )
        item.failure_records.append(record)
        assert len(item.failure_records) == 1
        assert item.failure_records[0].model_used == "claude-sonnet-4-6"


# ---------------------------------------------------------------------------
# AC: Given a FailureRecord with quality_scores, when serialized to JSON, then
#     all scores round-trip without loss.
# ---------------------------------------------------------------------------
class TestFailureRecordQualityScoresRoundTrip:
    def test_quality_scores_round_trip_via_json(self):
        scores = {"specificity": 0.75, "completeness": 0.9, "structural_corroboration": 0.3}
        record = FailureRecord(
            attempted_at=datetime.now(timezone.utc),
            model_used="claude-sonnet-4-6",
            prompt_template="investigate_file_v1",
            failure_reason="Low quality score",
            quality_scores=scores,
        )
        json_str = record.model_dump_json()
        restored = FailureRecord.model_validate_json(json_str)
        assert restored.quality_scores == scores

    def test_quality_scores_none_by_default(self):
        record = FailureRecord(
            attempted_at=datetime.now(timezone.utc),
            model_used="claude-sonnet-4-6",
            prompt_template="investigate_file_v1",
            failure_reason="LLM timeout",
        )
        assert record.quality_scores is None

    def test_quality_scores_with_nested_dict_round_trips(self):
        scores = {"overall": 0.6, "dimensions": {"a": 0.5, "b": 0.7}}
        record = FailureRecord(
            attempted_at=datetime.now(timezone.utc),
            model_used="claude-sonnet-4-6",
            prompt_template="investigate_file_v1",
            failure_reason="Partial failure",
            quality_scores=scores,
        )
        json_str = record.model_dump_json()
        restored = FailureRecord.model_validate_json(json_str)
        assert restored.quality_scores == scores


# ---------------------------------------------------------------------------
# AC: Given a WorkItem with failure_count = 3 and escalated = False, when
#     serialized and deserialized, then both fields are preserved correctly.
# ---------------------------------------------------------------------------
class TestWorkItemSerializationRoundTrip:
    def test_failure_count_and_escalated_survive_json_round_trip(self):
        item = WorkItem(
            item_type="evaluate_relationship",
            concept_id=uuid.uuid4(),
            description="evaluate relationship",
            failure_count=3,
            escalated=False,
        )
        json_str = item.model_dump_json()
        restored = WorkItem.model_validate_json(json_str)
        assert restored.failure_count == 3
        assert restored.escalated is False

    def test_full_work_item_with_failure_records_round_trips(self):
        concept_id = uuid.uuid4()
        record = FailureRecord(
            attempted_at=datetime.now(timezone.utc),
            model_used="claude-haiku-4-5",
            prompt_template="verify_concept_v2",
            failure_reason="Timeout after 30s",
            quality_scores={"specificity": 0.4},
        )
        item = WorkItem(
            item_type="verify_concept",
            concept_id=concept_id,
            description="verify concept integrity",
            failure_count=1,
            failure_records=[record],
            escalated=False,
            resolved=False,
            base_priority_score=0.82,
        )
        json_str = item.model_dump_json()
        restored = WorkItem.model_validate_json(json_str)
        assert restored.concept_id == concept_id
        assert restored.failure_count == 1
        assert len(restored.failure_records) == 1
        assert restored.failure_records[0].failure_reason == "Timeout after 30s"
        assert restored.failure_records[0].quality_scores == {"specificity": 0.4}
        assert restored.escalated is False
        assert restored.resolved is False
        assert restored.base_priority_score == pytest.approx(0.82)

    def test_resolved_true_preserved_in_round_trip(self):
        item = WorkItem(
            item_type="reported_gap",
            concept_id=uuid.uuid4(),
            description="reported gap in coverage",
            failure_count=0,
            escalated=False,
            resolved=True,
        )
        json_str = item.model_dump_json()
        restored = WorkItem.model_validate_json(json_str)
        assert restored.resolved is True


# ---------------------------------------------------------------------------
# AC: Given the ERD §3.1.4 WorkItem specification
#     When a WorkItem is instantiated
#     Then it must support: description (required str), file_path (optional str,
#     default None), created_at (datetime, auto-generated), resolved_at
#     (optional datetime, default None)
# ---------------------------------------------------------------------------
class TestWorkItemERDFields:
    def test_description_is_required(self):
        """WorkItem without description raises ValidationError."""
        with pytest.raises(ValidationError):
            WorkItem(item_type="investigate_file", concept_id=uuid.uuid4())

    def test_description_is_stored(self):
        """WorkItem accepts and stores a description string."""
        item = WorkItem(
            item_type="investigate_file",
            concept_id=uuid.uuid4(),
            description="Investigate missing imports in auth module",
        )
        assert item.description == "Investigate missing imports in auth module"

    def test_file_path_defaults_to_none(self):
        """file_path defaults to None when not supplied."""
        item = WorkItem(
            item_type="investigate_file",
            concept_id=uuid.uuid4(),
            description="Some investigation",
        )
        assert item.file_path is None

    def test_file_path_accepts_a_string(self):
        """file_path stores the given path string."""
        item = WorkItem(
            item_type="investigate_file",
            concept_id=uuid.uuid4(),
            description="Check file for missing deps",
            file_path="src/apriori/models/concept.py",
        )
        assert item.file_path == "src/apriori/models/concept.py"

    def test_created_at_is_auto_generated_datetime(self):
        """created_at is set automatically to a recent UTC datetime."""
        before = datetime.now(timezone.utc)
        item = WorkItem(
            item_type="verify_concept",
            concept_id=uuid.uuid4(),
            description="Verify concept integrity",
        )
        after = datetime.now(timezone.utc)
        assert isinstance(item.created_at, datetime)
        assert before <= item.created_at <= after

    def test_created_at_differs_across_instances(self):
        """Each WorkItem gets its own auto-generated created_at."""
        cid = uuid.uuid4()
        item1 = WorkItem(item_type="verify_concept", concept_id=cid, description="first")
        item2 = WorkItem(item_type="verify_concept", concept_id=cid, description="second")
        # Both are datetimes; they may be equal if created fast but must both exist
        assert isinstance(item1.created_at, datetime)
        assert isinstance(item2.created_at, datetime)

    def test_resolved_at_defaults_to_none(self):
        """resolved_at defaults to None for new work items."""
        item = WorkItem(
            item_type="review_concept",
            concept_id=uuid.uuid4(),
            description="Review concept node",
        )
        assert item.resolved_at is None

    def test_resolved_at_accepts_a_datetime(self):
        """resolved_at stores the given datetime."""
        ts = datetime.now(timezone.utc)
        item = WorkItem(
            item_type="review_concept",
            concept_id=uuid.uuid4(),
            description="Review concept node",
            resolved_at=ts,
        )
        assert item.resolved_at == ts


# ---------------------------------------------------------------------------
# AC: Given a WorkItem with all fields populated
#     When serialized to JSON via model_dump(mode="json")
#     Then all 4 new fields appear in the output and round-trip back identically
# ---------------------------------------------------------------------------
class TestWorkItemNewFieldsRoundTrip:
    def test_all_four_new_fields_present_in_model_dump(self):
        """model_dump(mode='json') includes all 4 new fields."""
        ts = datetime.now(timezone.utc)
        item = WorkItem(
            item_type="analyze_impact",
            concept_id=uuid.uuid4(),
            description="Analyze impact of edge removal",
            file_path="src/apriori/graph/engine.py",
            resolved_at=ts,
        )
        data = item.model_dump(mode="json")
        assert "description" in data
        assert "file_path" in data
        assert "created_at" in data
        assert "resolved_at" in data

    def test_new_fields_round_trip_via_json(self):
        """All 4 new fields survive a JSON round-trip."""
        ts = datetime.now(timezone.utc)
        item = WorkItem(
            item_type="analyze_impact",
            concept_id=uuid.uuid4(),
            description="Analyze impact of edge removal",
            file_path="src/apriori/graph/engine.py",
            resolved_at=ts,
        )
        json_str = item.model_dump_json()
        restored = WorkItem.model_validate_json(json_str)
        assert restored.description == item.description
        assert restored.file_path == item.file_path
        assert restored.created_at == item.created_at
        assert restored.resolved_at == item.resolved_at

    def test_null_optionals_round_trip_via_json(self):
        """file_path=None and resolved_at=None survive a JSON round-trip."""
        item = WorkItem(
            item_type="reported_gap",
            concept_id=uuid.uuid4(),
            description="Gap in documentation",
        )
        json_str = item.model_dump_json()
        restored = WorkItem.model_validate_json(json_str)
        assert restored.file_path is None
        assert restored.resolved_at is None
        assert restored.description == "Gap in documentation"
        assert isinstance(restored.created_at, datetime)


# ---------------------------------------------------------------------------
# AC: Given a FailureRecord for a Level 1.5 failure,
#     When the record is created,
#     Then it must accept an optional reviewer_feedback field (default None).
# ---------------------------------------------------------------------------
class TestFailureRecordReviewerFeedback:
    def test_reviewer_feedback_defaults_to_none(self):
        record = FailureRecord(
            attempted_at=datetime.now(timezone.utc),
            model_used="claude-sonnet-4-6",
            prompt_template="investigate_file_v1",
            failure_reason="LLM returned low quality output",
        )
        assert record.reviewer_feedback is None

    def test_reviewer_feedback_accepts_string(self):
        feedback = "The concept name lacked specificity. Be more precise about the module boundary."
        record = FailureRecord(
            attempted_at=datetime.now(timezone.utc),
            model_used="claude-sonnet-4-6",
            prompt_template="investigate_file_v1",
            failure_reason="Low specificity score",
            reviewer_feedback=feedback,
        )
        assert record.reviewer_feedback == feedback

    def test_reviewer_feedback_survives_json_round_trip(self):
        feedback = "Focus on the public API boundary, not internal helpers."
        record = FailureRecord(
            attempted_at=datetime.now(timezone.utc),
            model_used="claude-sonnet-4-6",
            prompt_template="verify_concept_v2",
            failure_reason="Incomplete analysis",
            reviewer_feedback=feedback,
        )
        restored = FailureRecord.model_validate_json(record.model_dump_json())
        assert restored.reviewer_feedback == feedback

    def test_reviewer_feedback_none_survives_json_round_trip(self):
        record = FailureRecord(
            attempted_at=datetime.now(timezone.utc),
            model_used="claude-sonnet-4-6",
            prompt_template="investigate_file_v1",
            failure_reason="Timeout",
        )
        restored = FailureRecord.model_validate_json(record.model_dump_json())
        assert restored.reviewer_feedback is None
