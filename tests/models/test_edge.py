"""Tests for Edge model and EdgeTypeVocabulary — AC traceability: Story 1.2."""

import uuid
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from apriori.config import Config, DEFAULT_EDGE_TYPES, load_config
from apriori.models.edge import EDGE_TYPE_VOCABULARY, Edge, EdgeTypeVocabulary, load_edge_vocabulary


# ---------------------------------------------------------------------------
# AC: Given valid source/target UUIDs and an edge type of "calls",
#     when an Edge is instantiated, then it succeeds with evidence_type
#     accepted as "structural", "semantic", or "historical".
# ---------------------------------------------------------------------------
class TestEdgeInstantiation:
    def test_edge_instantiation_with_structural_evidence(self):
        source = uuid.uuid4()
        target = uuid.uuid4()
        edge = Edge(
            source_id=source,
            target_id=target,
            edge_type="calls",
            evidence_type="structural",
        )
        assert edge.source_id == source
        assert edge.target_id == target
        assert edge.edge_type == "calls"
        assert edge.evidence_type == "structural"

    def test_edge_accepts_semantic_evidence_type(self):
        edge = Edge(
            source_id=uuid.uuid4(),
            target_id=uuid.uuid4(),
            edge_type="relates-to",
            evidence_type="semantic",
        )
        assert edge.evidence_type == "semantic"

    def test_edge_accepts_historical_evidence_type(self):
        edge = Edge(
            source_id=uuid.uuid4(),
            target_id=uuid.uuid4(),
            edge_type="co-changes-with",
            evidence_type="historical",
        )
        assert edge.evidence_type == "historical"

    def test_invalid_evidence_type_raises_validation_error(self):
        with pytest.raises(ValidationError):
            Edge(
                source_id=uuid.uuid4(),
                target_id=uuid.uuid4(),
                edge_type="calls",
                evidence_type="unknown",
            )


# ---------------------------------------------------------------------------
# AC (auto-fields): id auto-generates UUID4, created_at/updated_at are set.
# ---------------------------------------------------------------------------
class TestEdgeAutoFields:
    def test_id_is_auto_generated_uuid4(self):
        edge = Edge(
            source_id=uuid.uuid4(),
            target_id=uuid.uuid4(),
            edge_type="calls",
            evidence_type="structural",
        )
        assert isinstance(edge.id, uuid.UUID)
        assert edge.id.version == 4

    def test_created_at_is_set_automatically(self):
        before = datetime.now(timezone.utc)
        edge = Edge(
            source_id=uuid.uuid4(),
            target_id=uuid.uuid4(),
            edge_type="calls",
            evidence_type="structural",
        )
        after = datetime.now(timezone.utc)
        assert before <= edge.created_at <= after

    def test_updated_at_is_set_automatically(self):
        before = datetime.now(timezone.utc)
        edge = Edge(
            source_id=uuid.uuid4(),
            target_id=uuid.uuid4(),
            edge_type="calls",
            evidence_type="structural",
        )
        after = datetime.now(timezone.utc)
        assert before <= edge.updated_at <= after


# ---------------------------------------------------------------------------
# AC: Given a confidence of 0.5 and evidence_type of "structural",
#     when an Edge is serialized to JSON and back, then the round-trip is lossless.
# ---------------------------------------------------------------------------
class TestEdgeRoundTripSerialization:
    def test_json_round_trip_is_lossless(self):
        source = uuid.uuid4()
        target = uuid.uuid4()
        edge = Edge(
            source_id=source,
            target_id=target,
            edge_type="calls",
            evidence_type="structural",
            confidence=0.5,
        )
        json_str = edge.model_dump_json()
        restored = Edge.model_validate_json(json_str)
        assert restored == edge
        assert restored.confidence == 0.5
        assert restored.evidence_type == "structural"

    # AC: Given an Edge with a metadata dictionary,
    #     when serialized and deserialized, then the metadata is preserved without loss.
    def test_metadata_preserved_in_round_trip(self):
        metadata = {"source": "AST", "version": "1.0", "confidence_reason": "direct call"}
        edge = Edge(
            source_id=uuid.uuid4(),
            target_id=uuid.uuid4(),
            edge_type="calls",
            evidence_type="structural",
            metadata=metadata,
        )
        json_str = edge.model_dump_json()
        restored = Edge.model_validate_json(json_str)
        assert restored.metadata == metadata

    def test_nested_metadata_preserved_in_round_trip(self):
        metadata = {"tags": ["a", "b"], "scores": {"quality": 0.9, "relevance": 0.7}}
        edge = Edge(
            source_id=uuid.uuid4(),
            target_id=uuid.uuid4(),
            edge_type="imports",
            evidence_type="structural",
            metadata=metadata,
        )
        json_str = edge.model_dump_json()
        restored = Edge.model_validate_json(json_str)
        assert restored.metadata == metadata


# ---------------------------------------------------------------------------
# AC: Given an edge type of "made-up-type", when validated against the
#     vocabulary, then validation fails with a clear message listing valid types.
# ---------------------------------------------------------------------------
class TestEdgeTypeVocabularyValidation:
    def test_valid_type_passes_vocabulary_check(self):
        vocab = EdgeTypeVocabulary(EDGE_TYPE_VOCABULARY)
        # Should not raise
        vocab.validate("calls")
        vocab.validate("imports")
        vocab.validate("co-changes-with")

    def test_invalid_type_fails_vocabulary_check(self):
        vocab = EdgeTypeVocabulary(EDGE_TYPE_VOCABULARY)
        with pytest.raises(ValueError) as exc_info:
            vocab.validate("made-up-type")
        error_message = str(exc_info.value)
        assert "made-up-type" in error_message

    def test_error_message_lists_valid_types(self):
        vocab = EdgeTypeVocabulary(EDGE_TYPE_VOCABULARY)
        with pytest.raises(ValueError) as exc_info:
            vocab.validate("invalid-type")
        error_message = str(exc_info.value)
        # Spot-check several types appear in the error
        for edge_type in ["calls", "imports", "inherits"]:
            assert edge_type in error_message

    def test_custom_vocabulary_validates_custom_types(self):
        custom_vocab = EdgeTypeVocabulary(frozenset({"my-custom-edge", "calls"}))
        # Custom type should be valid
        custom_vocab.validate("my-custom-edge")
        # Original type still valid
        custom_vocab.validate("calls")

    def test_custom_vocabulary_rejects_standard_types_not_included(self):
        custom_vocab = EdgeTypeVocabulary(frozenset({"only-this-type"}))
        with pytest.raises(ValueError):
            custom_vocab.validate("calls")


# ---------------------------------------------------------------------------
# AC: Given the default apriori.config.yaml, when the edge type vocabulary
#     is loaded, then it contains exactly the 12 edge types defined in PRD §5.4.
# ---------------------------------------------------------------------------
class TestLoadEdgeVocabulary:
    # The 12 canonical types from PRD §5.4
    CANONICAL_TYPES = frozenset(
        {
            # Structural
            "calls",
            "imports",
            "inherits",
            "type-references",
            # Semantic
            "depends-on",
            "implements",
            "relates-to",
            "shares-assumption-about",
            "extends",
            "supersedes",
            "owned-by",
            # Historical
            "co-changes-with",
        }
    )

    def test_default_vocabulary_has_exactly_12_types(self):
        config = Config()
        vocab = load_edge_vocabulary(config)
        assert len(vocab.types) == 12

    def test_default_vocabulary_contains_all_prd_54_types(self):
        config = Config()
        vocab = load_edge_vocabulary(config)
        assert vocab.types == self.CANONICAL_TYPES

    # AC: Given a user-extended config adding a custom edge type,
    #     when the vocabulary is loaded, then the custom type is included
    #     alongside the defaults.
    def test_custom_edge_type_included_with_defaults(self):
        config = Config(edge_types=set(DEFAULT_EDGE_TYPES) | {"my-custom-edge"})
        vocab = load_edge_vocabulary(config)
        assert "my-custom-edge" in vocab.types
        # Defaults still present
        assert "calls" in vocab.types
        assert "co-changes-with" in vocab.types

    def test_load_edge_vocabulary_returns_edge_type_vocabulary_instance(self):
        config = Config()
        vocab = load_edge_vocabulary(config)
        assert isinstance(vocab, EdgeTypeVocabulary)


# ---------------------------------------------------------------------------
# Additional: EDGE_TYPE_VOCABULARY constant matches PRD §5.4
# ---------------------------------------------------------------------------
class TestEdgeTypeVocabularyConstant:
    def test_edge_type_vocabulary_has_12_entries(self):
        assert len(EDGE_TYPE_VOCABULARY) == 12

    def test_edge_type_vocabulary_contains_structural_types(self):
        for t in ["calls", "imports", "inherits", "type-references"]:
            assert t in EDGE_TYPE_VOCABULARY

    def test_edge_type_vocabulary_contains_semantic_types(self):
        for t in ["depends-on", "implements", "relates-to", "shares-assumption-about",
                  "extends", "supersedes", "owned-by"]:
            assert t in EDGE_TYPE_VOCABULARY

    def test_edge_type_vocabulary_contains_historical_types(self):
        assert "co-changes-with" in EDGE_TYPE_VOCABULARY
