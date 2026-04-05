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
        item = WorkItem(item_type="investigate_file", concept_id=uuid.uuid4())
        assert item.failure_count == 0
        assert item.failure_records == []
        assert item.escalated is False
        assert item.resolved is False

    def test_all_six_item_types_are_accepted(self):
        cid = uuid.uuid4()
        for item_type in VALID_ITEM_TYPES:
            item = WorkItem(item_type=item_type, concept_id=cid)
            assert item.item_type == item_type

    def test_id_is_auto_generated_uuid(self):
        item = WorkItem(item_type="verify_concept", concept_id=uuid.uuid4())
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
        item = WorkItem(item_type="investigate_file", concept_id=uuid.uuid4())
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
            failure_count=0,
            escalated=False,
            resolved=True,
        )
        json_str = item.model_dump_json()
        restored = WorkItem.model_validate_json(json_str)
        assert restored.resolved is True
