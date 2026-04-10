"""Tests for blast_radius query module (Story 12.6 — AP-100).

Each test is directly traceable to a Given/When/Then acceptance criterion.

AC1: Given a concept name, blast_radius returns prioritised impact profile
     sorted by composite score (confidence * 1/depth).
AC2: Given a file path mapping to multiple concepts, returns union of profiles.
AC3: Given a function symbol, identifies the concept and returns its profile.
AC4: Given depth=2, returns only impacts within 2 hops.
AC5: Given min_confidence=0.5, returns only impacts with confidence >= 0.5.
AC6: Each entry includes concept name/ID, confidence, impact_layer, depth,
     relationship_path, and human-readable rationale.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from apriori.models.concept import Concept, CodeReference
from apriori.models.edge import Edge
from apriori.models.impact import ImpactEntry, ImpactProfile
from apriori.retrieval.blast_radius_query import BlastRadiusEntry, query_blast_radius
from apriori.storage.sqlite_store import SQLiteStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SHA256 = "a" * 64
_GIT_HASH = "b" * 40


def _concept(
    name: str,
    description: str = "",
    file_path: str | None = None,
    symbol: str | None = None,
    impact_profile: ImpactProfile | None = None,
) -> Concept:
    refs = []
    if file_path:
        refs.append(
            CodeReference(
                symbol=symbol or name,
                file_path=file_path,
                content_hash=_SHA256,
                semantic_anchor=name,
            )
        )
    elif symbol:
        refs.append(
            CodeReference(
                symbol=symbol,
                file_path="src/module.py",
                content_hash=_SHA256,
                semantic_anchor=symbol,
            )
        )
    return Concept(
        name=name,
        description=description or f"Description of {name}",
        created_by="agent",
        code_references=refs,
        impact_profile=impact_profile,
    )


def _impact_profile(entries_by_layer: dict[str, list[ImpactEntry]]) -> ImpactProfile:
    return ImpactProfile(
        structural_impact=entries_by_layer.get("structural", []),
        semantic_impact=entries_by_layer.get("semantic", []),
        historical_impact=entries_by_layer.get("historical", []),
        last_computed=datetime.now(timezone.utc),
    )


def _entry(target_id: uuid.UUID, confidence: float, depth: int, rationale: str = "") -> ImpactEntry:
    return ImpactEntry(
        target_concept_id=target_id,
        confidence=confidence,
        relationship_path=[str(uuid.uuid4())],
        depth=depth,
        rationale=rationale or f"Impact at depth {depth} with confidence {confidence}",
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def store(tmp_path: Path) -> SQLiteStore:
    return SQLiteStore(db_path=tmp_path / "test.db")


# ---------------------------------------------------------------------------
# AC1: Given a concept name → returns profile sorted by composite score
# ---------------------------------------------------------------------------

def test_query_by_concept_name_returns_sorted_by_composite_score(store: SQLiteStore) -> None:
    """Given a concept name, blast_radius returns the pre-computed impact profile
    as a prioritised list sorted by composite score (confidence * 1/depth)."""
    target_a = store.create_concept(_concept("target_alpha", "Alpha target concept"))
    target_b = store.create_concept(_concept("target_beta", "Beta target concept"))

    # Create impact profile with two entries of different score ordering
    # entry_a: confidence=0.8, depth=2 → composite = 0.8 * 0.5 = 0.4
    # entry_b: confidence=0.9, depth=1 → composite = 0.9 * 1.0 = 0.9
    profile = _impact_profile({
        "structural": [
            _entry(target_a.id, confidence=0.8, depth=2, rationale="Structural dep at depth 2"),
            _entry(target_b.id, confidence=0.9, depth=1, rationale="Direct structural dep"),
        ]
    })
    source = store.create_concept(_concept("payment_processor", impact_profile=profile))

    results = query_blast_radius(store, "payment_processor")

    assert isinstance(results, list)
    assert len(results) == 2
    # Sorted descending by composite_score: target_b first (0.9), then target_a (0.4)
    assert results[0].concept_id == target_b.id
    assert results[0].composite_score == pytest.approx(0.9)
    assert results[1].concept_id == target_a.id
    assert results[1].composite_score == pytest.approx(0.4)


def test_query_by_concept_id_returns_profile(store: SQLiteStore) -> None:
    """Given a concept UUID string, blast_radius returns the impact profile."""
    target = store.create_concept(_concept("target_concept"))
    profile = _impact_profile({
        "semantic": [_entry(target.id, confidence=0.7, depth=1)]
    })
    source = store.create_concept(_concept("source_concept", impact_profile=profile))

    results = query_blast_radius(store, str(source.id))

    assert len(results) == 1
    assert results[0].concept_id == target.id


def test_query_returns_empty_for_unknown_concept(store: SQLiteStore) -> None:
    """Given an unknown concept name, blast_radius returns an empty list."""
    results = query_blast_radius(store, "nonexistent_concept")
    assert results == []


def test_query_returns_empty_for_concept_without_profile(store: SQLiteStore) -> None:
    """Given a concept with no impact profile, blast_radius returns an empty list."""
    store.create_concept(_concept("no_profile_concept"))

    results = query_blast_radius(store, "no_profile_concept")
    assert results == []


# ---------------------------------------------------------------------------
# AC2: Given a file path → returns union of all impact profiles
# ---------------------------------------------------------------------------

def test_query_by_file_path_returns_union_of_profiles(store: SQLiteStore) -> None:
    """Given a file path mapping to multiple concepts, blast_radius returns
    the union of all impact profiles."""
    target_x = store.create_concept(_concept("target_x"))
    target_y = store.create_concept(_concept("target_y"))
    target_z = store.create_concept(_concept("target_z"))

    profile_a = _impact_profile({"structural": [_entry(target_x.id, 0.8, 1)]})
    profile_b = _impact_profile({"semantic": [_entry(target_y.id, 0.7, 1), _entry(target_z.id, 0.6, 2)]})

    store.create_concept(_concept("module_func_a", file_path="src/payments/validate.py", impact_profile=profile_a))
    store.create_concept(_concept("module_func_b", file_path="src/payments/validate.py", impact_profile=profile_b))

    results = query_blast_radius(store, "src/payments/validate.py")

    concept_ids = {r.concept_id for r in results}
    assert target_x.id in concept_ids
    assert target_y.id in concept_ids
    assert target_z.id in concept_ids


def test_query_by_file_path_deduplicates_entries(store: SQLiteStore) -> None:
    """Given file path with multiple concepts referencing the same target,
    the union result deduplicates by target_concept_id keeping highest score."""
    target = store.create_concept(_concept("shared_target"))

    profile_high = _impact_profile({"structural": [_entry(target.id, 0.9, 1)]})
    profile_low = _impact_profile({"semantic": [_entry(target.id, 0.4, 2)]})

    store.create_concept(_concept("func_high", file_path="src/overlap.py", impact_profile=profile_high))
    store.create_concept(_concept("func_low", file_path="src/overlap.py", impact_profile=profile_low))

    results = query_blast_radius(store, "src/overlap.py")

    # Should appear only once, with the higher composite score
    target_results = [r for r in results if r.concept_id == target.id]
    assert len(target_results) == 1
    assert target_results[0].composite_score == pytest.approx(0.9)  # 0.9 * (1/1)


# ---------------------------------------------------------------------------
# AC3: Given a function symbol → identifies concept and returns profile
# ---------------------------------------------------------------------------

def test_query_by_function_symbol_returns_profile(store: SQLiteStore) -> None:
    """Given a function symbol, blast_radius identifies the concept referencing
    that symbol and returns its impact profile."""
    target = store.create_concept(_concept("target_dep"))
    profile = _impact_profile({"structural": [_entry(target.id, 1.0, 1)]})

    store.create_concept(
        _concept(
            "payment_validator",
            symbol="validate_payment",
            impact_profile=profile,
        )
    )

    results = query_blast_radius(store, "validate_payment")

    assert len(results) >= 1
    assert any(r.concept_id == target.id for r in results)


# ---------------------------------------------------------------------------
# AC4: Given optional depth=2 → only impacts within 2 hops returned
# ---------------------------------------------------------------------------

def test_query_respects_max_depth_filter(store: SQLiteStore) -> None:
    """Given depth=2, blast_radius returns only impacts within 2 hops."""
    t1 = store.create_concept(_concept("depth_1_target"))
    t2 = store.create_concept(_concept("depth_2_target"))
    t3 = store.create_concept(_concept("depth_3_target"))

    profile = _impact_profile({
        "semantic": [
            _entry(t1.id, 0.9, 1),
            _entry(t2.id, 0.8, 2),
            _entry(t3.id, 0.7, 3),
        ]
    })
    store.create_concept(_concept("hub_concept", impact_profile=profile))

    results = query_blast_radius(store, "hub_concept", max_depth=2)

    result_ids = {r.concept_id for r in results}
    assert t1.id in result_ids
    assert t2.id in result_ids
    assert t3.id not in result_ids


# ---------------------------------------------------------------------------
# AC5: Given min_confidence=0.5 → only entries with confidence >= 0.5 returned
# ---------------------------------------------------------------------------

def test_query_respects_min_confidence_filter(store: SQLiteStore) -> None:
    """Given min_confidence=0.5, blast_radius returns only impacts with
    confidence >= 0.5."""
    high = store.create_concept(_concept("high_confidence_target"))
    low = store.create_concept(_concept("low_confidence_target"))

    profile = _impact_profile({
        "structural": [
            _entry(high.id, 0.8, 1),
            _entry(low.id, 0.3, 1),
        ]
    })
    store.create_concept(_concept("source_concept", impact_profile=profile))

    results = query_blast_radius(store, "source_concept", min_confidence=0.5)

    result_ids = {r.concept_id for r in results}
    assert high.id in result_ids
    assert low.id not in result_ids


# ---------------------------------------------------------------------------
# AC6: Each entry includes required fields
# ---------------------------------------------------------------------------

def test_entry_includes_all_required_fields(store: SQLiteStore) -> None:
    """Given each impact entry in the response, it includes: concept name/ID,
    confidence, impact_layer, depth, relationship_path, and rationale."""
    target = store.create_concept(_concept("fully_specified_target"))
    edge_id = str(uuid.uuid4())
    profile = _impact_profile({
        "semantic": [
            ImpactEntry(
                target_concept_id=target.id,
                confidence=0.75,
                relationship_path=[edge_id],
                depth=2,
                rationale="Semantic coupling via depends-on.",
            )
        ]
    })
    store.create_concept(_concept("the_source", impact_profile=profile))

    results = query_blast_radius(store, "the_source")

    assert len(results) == 1
    entry = results[0]

    # All required fields present
    assert entry.concept_id == target.id
    assert entry.concept_name == "fully_specified_target"
    assert entry.confidence == pytest.approx(0.75)
    assert entry.impact_layer == "semantic"
    assert entry.depth == 2
    assert edge_id in entry.relationship_path
    assert isinstance(entry.rationale, str)
    assert len(entry.rationale) > 0
    assert isinstance(entry.composite_score, float)


def test_entry_impact_layer_identifies_structural(store: SQLiteStore) -> None:
    """Structural entries are correctly labelled as impact_layer='structural'."""
    target = store.create_concept(_concept("structural_target"))
    profile = _impact_profile({"structural": [_entry(target.id, 1.0, 1)]})
    store.create_concept(_concept("source", impact_profile=profile))

    results = query_blast_radius(store, "source")
    assert results[0].impact_layer == "structural"


def test_entry_impact_layer_identifies_historical(store: SQLiteStore) -> None:
    """Historical entries are correctly labelled as impact_layer='historical'."""
    target = store.create_concept(_concept("historical_target"))
    profile = _impact_profile({"historical": [_entry(target.id, 0.6, 1)]})
    store.create_concept(_concept("hist_source", impact_profile=profile))

    results = query_blast_radius(store, "hist_source")
    assert results[0].impact_layer == "historical"


# ---------------------------------------------------------------------------
# Multi-layer deduplication: cross-layer de-dup by target_concept_id
# ---------------------------------------------------------------------------

def test_cross_layer_deduplication_keeps_highest_score(store: SQLiteStore) -> None:
    """When the same target appears in multiple layers, only the entry with
    the highest composite_score is kept."""
    target = store.create_concept(_concept("dup_target"))

    # structural: depth=2, conf=0.8 → score = 0.4
    # semantic:   depth=1, conf=0.5 → score = 0.5  ← winner
    profile = _impact_profile({
        "structural": [_entry(target.id, 0.8, 2)],
        "semantic": [_entry(target.id, 0.5, 1)],
    })
    store.create_concept(_concept("dup_source", impact_profile=profile))

    results = query_blast_radius(store, "dup_source")

    target_results = [r for r in results if r.concept_id == target.id]
    assert len(target_results) == 1
    assert target_results[0].composite_score == pytest.approx(0.5)
    assert target_results[0].impact_layer == "semantic"
