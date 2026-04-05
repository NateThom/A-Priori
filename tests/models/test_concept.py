"""Tests for Concept and CodeReference models — AC traceability: Story 1.1."""

import uuid
from datetime import datetime, timezone

import pytest
import yaml
from pydantic import ValidationError

from apriori.models.concept import CodeReference, Concept, INITIAL_LABELS


# ---------------------------------------------------------------------------
# AC: Given a valid set of Concept fields, when a Concept is instantiated,
#     then id auto-generates a UUID4 and created_at/updated_at are set to now.
# ---------------------------------------------------------------------------
class TestConceptAutoFields:
    def test_id_is_auto_generated_uuid(self):
        concept = Concept(name="parse_file", description="Parses a source file.", created_by="agent")
        assert isinstance(concept.id, uuid.UUID)
        assert concept.id.version == 4

    def test_created_at_is_set_automatically(self):
        before = datetime.now(timezone.utc)
        concept = Concept(name="parse_file", description="Parses a source file.", created_by="agent")
        after = datetime.now(timezone.utc)
        assert before <= concept.created_at <= after

    def test_updated_at_is_set_automatically(self):
        before = datetime.now(timezone.utc)
        concept = Concept(name="parse_file", description="Parses a source file.", created_by="agent")
        after = datetime.now(timezone.utc)
        assert before <= concept.updated_at <= after


# ---------------------------------------------------------------------------
# AC: Given confidence 1.5 / -0.1, when instantiated, Pydantic raises ValidationError.
# ---------------------------------------------------------------------------
class TestConceptConfidenceValidation:
    def test_confidence_above_1_raises(self):
        with pytest.raises(ValidationError) as exc_info:
            Concept(name="x", description="d", created_by="agent", confidence=1.5)
        assert "confidence" in str(exc_info.value).lower() or "1" in str(exc_info.value)

    def test_confidence_below_0_raises(self):
        with pytest.raises(ValidationError):
            Concept(name="x", description="d", created_by="agent", confidence=-0.1)

    def test_confidence_at_bounds_accepted(self):
        c_low = Concept(name="x", description="d", created_by="agent", confidence=0.0)
        c_high = Concept(name="y", description="d", created_by="agent", confidence=1.0)
        assert c_low.confidence == 0.0
        assert c_high.confidence == 1.0


# ---------------------------------------------------------------------------
# AC: Given created_by="system", Pydantic raises ValidationError (must be
#     "agent" or "human").
# ---------------------------------------------------------------------------
class TestConceptCreatedByValidation:
    def test_system_created_by_raises(self):
        with pytest.raises(ValidationError) as exc_info:
            Concept(name="x", description="d", created_by="system")
        assert "created_by" in str(exc_info.value).lower() or "agent" in str(exc_info.value).lower() or "human" in str(exc_info.value).lower()

    def test_agent_created_by_accepted(self):
        c = Concept(name="x", description="d", created_by="agent")
        assert c.created_by == "agent"

    def test_human_created_by_accepted(self):
        c = Concept(name="x", description="d", created_by="human")
        assert c.created_by == "human"


# ---------------------------------------------------------------------------
# AC: Round-trip JSON and YAML with two CodeReferences.
# ---------------------------------------------------------------------------
class TestConceptRoundTrip:
    def _make_concept_with_refs(self) -> Concept:
        ref1 = CodeReference(
            symbol="parse_file",
            file_path="src/parser.py",
            content_hash="a" * 64,
            semantic_anchor="Parses a Python source file using tree-sitter.",
        )
        ref2 = CodeReference(
            symbol="ASTNode",
            file_path="src/ast_node.py",
            line_range=(10, 42),
            content_hash="b" * 64,
            semantic_anchor="Represents an AST node in the parse tree.",
            derived_from_code_version="c" * 40,
        )
        return Concept(
            name="parse_file",
            description="Parses a source file and returns an AST.",
            created_by="agent",
            confidence=0.85,
            labels={"auto-generated", "needs-review"},
            code_references=[ref1, ref2],
            metadata={"language": "python"},
        )

    def test_json_round_trip(self):
        original = self._make_concept_with_refs()
        json_str = original.model_dump_json()
        restored = Concept.model_validate_json(json_str)
        assert restored == original

    def test_yaml_round_trip(self):
        original = self._make_concept_with_refs()
        data = original.model_dump(mode="json")
        yaml_str = yaml.dump(data)
        loaded = yaml.safe_load(yaml_str)
        restored = Concept.model_validate(loaded)
        assert restored == original


# ---------------------------------------------------------------------------
# AC: CodeReference content_hash — 64-char hex passes; non-hex fails.
# ---------------------------------------------------------------------------
class TestCodeReferenceContentHash:
    def test_valid_sha256_hex_accepted(self):
        ref = CodeReference(
            symbol="fn",
            file_path="a.py",
            content_hash="a1b2c3" + "0" * 58,
            semantic_anchor="A function.",
        )
        assert len(ref.content_hash) == 64

    def test_non_hex_content_hash_raises(self):
        with pytest.raises(ValidationError):
            CodeReference(
                symbol="fn",
                file_path="a.py",
                content_hash="z" * 64,  # 'z' is not hex
                semantic_anchor="A function.",
            )

    def test_wrong_length_content_hash_raises(self):
        with pytest.raises(ValidationError):
            CodeReference(
                symbol="fn",
                file_path="a.py",
                content_hash="a" * 32,  # SHA-1 length, not SHA-256
                semantic_anchor="A function.",
            )


# ---------------------------------------------------------------------------
# Bonus: INITIAL_LABELS constant is documented
# ---------------------------------------------------------------------------
class TestInitialLabels:
    def test_initial_labels_contains_expected(self):
        expected = {"needs-review", "auto-generated", "deprecated", "verified", "stale", "needs-human-review"}
        assert expected.issubset(INITIAL_LABELS)
