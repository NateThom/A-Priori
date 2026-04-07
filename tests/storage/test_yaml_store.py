"""Tests for YamlStore — AC traceability: Story 2.6.

AC:
- AC1: Given a concept named "Payment Validation", when saved, then a file
  `.apriori/concepts/payment-validation.yaml` is created with all concept fields.
- AC2: Given two concepts with names that would slugify identically, when both
  are saved, then the second receives a numeric suffix.
- AC3: Given an edge, when saved, then a file `.apriori/edges/{uuid}.yaml` is
  created.
- AC4: Given a WorkItem, when a save is attempted to YAML, then the operation
  is skipped (work items are SQLite-only).
- AC5: Given a concept YAML file, when read and deserialized, then the
  resulting Concept object is identical to the original.
- AC6: Given the directory layout decision from S-5, when the YAML store is
  initialized, then it creates the directory structure accordingly.
"""

import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from apriori.models.concept import Concept
from apriori.models.edge import Edge
from apriori.models.work_item import WorkItem
from apriori.storage.yaml_store import YamlStore, slugify


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_concept(name: str = "Payment Validation") -> Concept:
    return Concept(
        name=name,
        description="Validates payment data before processing.",
        created_by="agent",
        confidence=0.9,
        labels={"auto-generated", "needs-review"},
    )


def _make_edge() -> Edge:
    return Edge(
        source_id=uuid.uuid4(),
        target_id=uuid.uuid4(),
        edge_type="depends-on",
        evidence_type="semantic",
        confidence=0.85,
    )


def _make_work_item() -> WorkItem:
    concept_id = uuid.uuid4()
    return WorkItem(
        item_type="verify_concept",
        concept_id=concept_id,
        description="Verify this concept is accurate.",
    )


# ---------------------------------------------------------------------------
# AC6: Directory structure created on initialization
# ---------------------------------------------------------------------------
class TestDirectoryInitialization:
    def test_concepts_directory_created(self, tmp_path: Path):
        """Given S-5 layout decision, when YamlStore initializes, concepts/ dir exists."""
        store = YamlStore(base_dir=tmp_path)
        assert (tmp_path / "concepts").is_dir()

    def test_edges_directory_created(self, tmp_path: Path):
        """Given S-5 layout decision, when YamlStore initializes, edges/ dir exists."""
        store = YamlStore(base_dir=tmp_path)
        assert (tmp_path / "edges").is_dir()

    def test_init_is_idempotent(self, tmp_path: Path):
        """Initializing twice does not raise an error."""
        YamlStore(base_dir=tmp_path)
        YamlStore(base_dir=tmp_path)  # must not raise


# ---------------------------------------------------------------------------
# Slugification helpers
# ---------------------------------------------------------------------------
class TestSlugify:
    def test_lowercase(self):
        assert slugify("Payment Validation") == "payment-validation"

    def test_hyphens_for_spaces(self):
        assert slugify("hello world") == "hello-world"

    def test_strips_special_characters(self):
        assert slugify("foo/bar!baz") == "foobarbaz"

    def test_multiple_spaces_collapse(self):
        assert slugify("a  b") == "a-b"

    def test_leading_trailing_stripped(self):
        assert slugify("  hello  ") == "hello"

    def test_deterministic(self):
        assert slugify("Payment Validation") == slugify("Payment Validation")

    def test_unicode_letters_preserved(self):
        # Non-special unicode letters should be preserved (or at least not crash)
        result = slugify("café")
        assert isinstance(result, str)
        assert len(result) > 0


# ---------------------------------------------------------------------------
# AC1: Concept file creation
# ---------------------------------------------------------------------------
class TestWriteConcept:
    def test_concept_file_created_at_expected_path(self, tmp_path: Path):
        """AC1: concept named 'Payment Validation' → .apriori/concepts/payment-validation.yaml"""
        store = YamlStore(base_dir=tmp_path)
        concept = _make_concept("Payment Validation")
        path = store.write_concept(concept)

        assert path == tmp_path / "concepts" / "payment-validation.yaml"
        assert path.exists()

    def test_concept_file_contains_all_fields(self, tmp_path: Path):
        """AC1: file contains all concept fields."""
        import yaml as _yaml
        store = YamlStore(base_dir=tmp_path)
        concept = _make_concept("Payment Validation")
        path = store.write_concept(concept)

        data = _yaml.safe_load(path.read_text())
        assert data["id"] == str(concept.id)
        assert data["name"] == concept.name
        assert data["description"] == concept.description
        assert data["created_by"] == concept.created_by

    def test_write_concept_returns_path(self, tmp_path: Path):
        store = YamlStore(base_dir=tmp_path)
        concept = _make_concept()
        result = store.write_concept(concept)
        assert isinstance(result, Path)


# ---------------------------------------------------------------------------
# AC2: Slug collision handling
# ---------------------------------------------------------------------------
class TestSlugCollision:
    def test_second_concept_gets_numeric_suffix(self, tmp_path: Path):
        """AC2: two concepts with identical slugs → second gets -2 suffix."""
        store = YamlStore(base_dir=tmp_path)
        c1 = _make_concept("Payment Validation")
        c2 = Concept(
            name="Payment Validation",
            description="A different concept with the same name.",
            created_by="human",
        )
        path1 = store.write_concept(c1)
        path2 = store.write_concept(c2)

        assert path1 == tmp_path / "concepts" / "payment-validation.yaml"
        assert path2 == tmp_path / "concepts" / "payment-validation-2.yaml"
        assert path1.exists()
        assert path2.exists()

    def test_third_collision_gets_suffix_3(self, tmp_path: Path):
        """Three concepts with identical slugs get -2 and -3 suffixes."""
        store = YamlStore(base_dir=tmp_path)
        for _ in range(3):
            c = Concept(
                name="Duplicate Name",
                description="Same name.",
                created_by="agent",
            )
            store.write_concept(c)

        assert (tmp_path / "concepts" / "duplicate-name.yaml").exists()
        assert (tmp_path / "concepts" / "duplicate-name-2.yaml").exists()
        assert (tmp_path / "concepts" / "duplicate-name-3.yaml").exists()

    def test_collision_checks_stored_id(self, tmp_path: Path):
        """Overwriting the same concept (same id) uses the original slug."""
        store = YamlStore(base_dir=tmp_path)
        concept = _make_concept("Payment Validation")
        path1 = store.write_concept(concept)
        # Write again with same id (update scenario) — should reuse same path
        path2 = store.write_concept(concept)
        assert path1 == path2
        # No -2 file should exist
        assert not (tmp_path / "concepts" / "payment-validation-2.yaml").exists()


# ---------------------------------------------------------------------------
# AC3: Edge file creation
# ---------------------------------------------------------------------------
class TestWriteEdge:
    def test_edge_file_created_at_uuid_path(self, tmp_path: Path):
        """AC3: edge saved to .apriori/edges/{uuid}.yaml"""
        store = YamlStore(base_dir=tmp_path)
        edge = _make_edge()
        path = store.write_edge(edge)

        expected = tmp_path / "edges" / f"{edge.id}.yaml"
        assert path == expected
        assert path.exists()

    def test_edge_file_contains_all_fields(self, tmp_path: Path):
        """AC3: edge YAML file contains edge fields."""
        import yaml as _yaml
        store = YamlStore(base_dir=tmp_path)
        edge = _make_edge()
        path = store.write_edge(edge)

        data = _yaml.safe_load(path.read_text())
        assert data["id"] == str(edge.id)
        assert data["source_id"] == str(edge.source_id)
        assert data["target_id"] == str(edge.target_id)
        assert data["edge_type"] == edge.edge_type
        assert data["evidence_type"] == edge.evidence_type

    def test_write_edge_returns_path(self, tmp_path: Path):
        store = YamlStore(base_dir=tmp_path)
        edge = _make_edge()
        result = store.write_edge(edge)
        assert isinstance(result, Path)


# ---------------------------------------------------------------------------
# AC4: WorkItem save is skipped
# ---------------------------------------------------------------------------
class TestWorkItemSkip:
    def test_write_work_item_raises_type_error(self, tmp_path: Path):
        """AC4: WorkItem save attempt raises TypeError — SQLite-only entity."""
        store = YamlStore(base_dir=tmp_path)
        wi = _make_work_item()
        with pytest.raises(TypeError, match="WorkItem"):
            store.write_work_item(wi)

    def test_no_yaml_file_created_for_work_item(self, tmp_path: Path):
        """AC4: no YAML file is created when WorkItem save is attempted."""
        store = YamlStore(base_dir=tmp_path)
        wi = _make_work_item()
        try:
            store.write_work_item(wi)
        except TypeError:
            pass
        # No YAML files should exist after failed write
        yaml_files = list(tmp_path.rglob("*.yaml"))
        assert len(yaml_files) == 0


# ---------------------------------------------------------------------------
# AC5: Round-trip serialization
# ---------------------------------------------------------------------------
class TestRoundTrip:
    def test_concept_round_trip(self, tmp_path: Path):
        """AC5: read-back of a concept YAML equals the original Concept."""
        store = YamlStore(base_dir=tmp_path)
        original = _make_concept("Round Trip Test")
        store.write_concept(original)
        recovered = store.read_concept(original.id)
        assert recovered == original

    def test_edge_round_trip(self, tmp_path: Path):
        """AC5: read-back of an edge YAML equals the original Edge."""
        store = YamlStore(base_dir=tmp_path)
        original = _make_edge()
        store.write_edge(original)
        recovered = store.read_edge(original.id)
        assert recovered == original

    def test_concept_with_optional_fields_round_trip(self, tmp_path: Path):
        """AC5: Concept with optional datetime and nested fields survives round-trip."""
        store = YamlStore(base_dir=tmp_path)
        original = Concept(
            name="Complex Concept",
            description="Has many optional fields.",
            created_by="human",
            verified_by="alice",
            last_verified=datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc),
            confidence=0.95,
            derived_from_code_version="a" * 40,
            metadata={"source": "manual", "priority": 1},
        )
        store.write_concept(original)
        recovered = store.read_concept(original.id)
        assert recovered == original

    def test_read_concept_returns_none_for_missing(self, tmp_path: Path):
        """Reading a non-existent concept returns None."""
        store = YamlStore(base_dir=tmp_path)
        result = store.read_concept(uuid.uuid4())
        assert result is None

    def test_read_edge_returns_none_for_missing(self, tmp_path: Path):
        """Reading a non-existent edge returns None."""
        store = YamlStore(base_dir=tmp_path)
        result = store.read_edge(uuid.uuid4())
        assert result is None

    def test_delete_concept_removes_file(self, tmp_path: Path):
        """Deleting a concept removes its YAML file."""
        store = YamlStore(base_dir=tmp_path)
        concept = _make_concept("Deletable Concept")
        path = store.write_concept(concept)
        assert path.exists()
        store.delete_concept(concept.id)
        assert not path.exists()

    def test_delete_edge_removes_file(self, tmp_path: Path):
        """Deleting an edge removes its YAML file."""
        store = YamlStore(base_dir=tmp_path)
        edge = _make_edge()
        path = store.write_edge(edge)
        assert path.exists()
        store.delete_edge(edge.id)
        assert not path.exists()
