"""Tests for MCP blast_radius tool (Story 12.6 — AP-100).

Each test traces to a Given/When/Then acceptance criterion.

AC1: Given a concept name → returns pre-computed impact profile.
AC2: Given a file path → returns union of profiles.
AC3: Given a function symbol → identifies concept and returns profile.
AC4: Given depth=2 → only impacts within 2 hops.
AC5: Given min_confidence=0.5 → only high-confidence impacts.
AC8 (MCP side): blast_radius is no longer a placeholder — it returns real data.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

import apriori.mcp.server as mcp_server
from apriori.models.concept import Concept, CodeReference
from apriori.models.impact import ImpactEntry, ImpactProfile
from apriori.storage.sqlite_store import SQLiteStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SHA256 = "c" * 64


def _concept(
    name: str,
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
        description=f"Description of {name}",
        created_by="agent",
        code_references=refs,
        impact_profile=impact_profile,
    )


def _profile(*layers: tuple[str, float, int]) -> ImpactProfile:
    """Build a profile with entries. layers: [(layer_name, confidence, depth), ...]"""
    target_id = uuid.uuid4()
    struct = [
        ImpactEntry(
            target_concept_id=target_id,
            confidence=conf,
            relationship_path=[str(uuid.uuid4())],
            depth=depth,
            rationale=f"{layer} at depth {depth}",
        )
        for layer, conf, depth in layers
        if layer == "structural"
    ]
    sem = [
        ImpactEntry(
            target_concept_id=target_id,
            confidence=conf,
            relationship_path=[str(uuid.uuid4())],
            depth=depth,
            rationale=f"{layer} at depth {depth}",
        )
        for layer, conf, depth in layers
        if layer == "semantic"
    ]
    hist = [
        ImpactEntry(
            target_concept_id=target_id,
            confidence=conf,
            relationship_path=[str(uuid.uuid4())],
            depth=depth,
            rationale=f"{layer} at depth {depth}",
        )
        for layer, conf, depth in layers
        if layer == "historical"
    ]
    return ImpactProfile(
        structural_impact=struct,
        semantic_impact=sem,
        historical_impact=hist,
        last_computed=datetime.now(timezone.utc),
    )


@pytest.fixture
def store(tmp_path: Path) -> SQLiteStore:
    s = SQLiteStore(db_path=tmp_path / "test.db")
    mcp_server._store = s
    yield s
    mcp_server._store = None


# ---------------------------------------------------------------------------
# AC1: Concept name input
# ---------------------------------------------------------------------------

def test_blast_radius_by_concept_name_returns_entries(store: SQLiteStore) -> None:
    """Given a concept name, blast_radius returns the pre-computed impact profile."""
    target = store.create_concept(_concept("target_concept"))
    p = ImpactProfile(
        structural_impact=[
            ImpactEntry(
                target_concept_id=target.id,
                confidence=0.9,
                relationship_path=[str(uuid.uuid4())],
                depth=1,
                rationale="Direct structural dependency.",
            )
        ],
        semantic_impact=[],
        historical_impact=[],
        last_computed=datetime.now(timezone.utc),
    )
    store.create_concept(_concept("source_concept", impact_profile=p))

    results = mcp_server.blast_radius("source_concept")

    assert isinstance(results, list)
    assert len(results) == 1
    entry = results[0]
    # Check required fields
    assert "concept_id" in entry
    assert "concept_name" in entry
    assert "confidence" in entry
    assert "impact_layer" in entry
    assert "depth" in entry
    assert "relationship_path" in entry
    assert "rationale" in entry
    assert "composite_score" in entry


def test_blast_radius_returns_list_sorted_by_composite_score(store: SQLiteStore) -> None:
    """Results are sorted by composite_score descending."""
    target_a = store.create_concept(_concept("target_a"))
    target_b = store.create_concept(_concept("target_b"))

    p = ImpactProfile(
        structural_impact=[
            ImpactEntry(
                target_concept_id=target_a.id,
                confidence=0.5,
                relationship_path=[str(uuid.uuid4())],
                depth=2,  # score = 0.5/2 = 0.25
                rationale="A",
            ),
            ImpactEntry(
                target_concept_id=target_b.id,
                confidence=0.9,
                relationship_path=[str(uuid.uuid4())],
                depth=1,  # score = 0.9/1 = 0.9
                rationale="B",
            ),
        ],
        semantic_impact=[],
        historical_impact=[],
        last_computed=datetime.now(timezone.utc),
    )
    store.create_concept(_concept("multi_source", impact_profile=p))

    results = mcp_server.blast_radius("multi_source")

    assert len(results) == 2
    assert results[0]["concept_id"] == str(target_b.id)  # highest score first
    assert results[1]["concept_id"] == str(target_a.id)


# ---------------------------------------------------------------------------
# AC2: File path input → union of profiles
# ---------------------------------------------------------------------------

def test_blast_radius_by_file_path_returns_union(store: SQLiteStore) -> None:
    """Given a file path, blast_radius returns the union of all concepts' profiles."""
    target_a = store.create_concept(_concept("file_target_a"))
    target_b = store.create_concept(_concept("file_target_b"))

    p1 = ImpactProfile(
        structural_impact=[
            ImpactEntry(target_concept_id=target_a.id, confidence=0.8, relationship_path=[str(uuid.uuid4())], depth=1, rationale="A")
        ],
        semantic_impact=[], historical_impact=[],
        last_computed=datetime.now(timezone.utc),
    )
    p2 = ImpactProfile(
        structural_impact=[
            ImpactEntry(target_concept_id=target_b.id, confidence=0.7, relationship_path=[str(uuid.uuid4())], depth=1, rationale="B")
        ],
        semantic_impact=[], historical_impact=[],
        last_computed=datetime.now(timezone.utc),
    )
    store.create_concept(_concept("func_in_file_a", file_path="src/payments/validate.py", impact_profile=p1))
    store.create_concept(_concept("func_in_file_b", file_path="src/payments/validate.py", impact_profile=p2))

    results = mcp_server.blast_radius("src/payments/validate.py")

    concept_ids = {r["concept_id"] for r in results}
    assert str(target_a.id) in concept_ids
    assert str(target_b.id) in concept_ids


# ---------------------------------------------------------------------------
# AC3: Function symbol input
# ---------------------------------------------------------------------------

def test_blast_radius_by_function_symbol_returns_profile(store: SQLiteStore) -> None:
    """Given a function symbol, blast_radius identifies the concept and returns profile."""
    target = store.create_concept(_concept("symbol_target"))
    p = ImpactProfile(
        structural_impact=[
            ImpactEntry(target_concept_id=target.id, confidence=1.0, relationship_path=[str(uuid.uuid4())], depth=1, rationale="sym")
        ],
        semantic_impact=[], historical_impact=[],
        last_computed=datetime.now(timezone.utc),
    )
    store.create_concept(_concept("sym_source", symbol="validate_payment", impact_profile=p))

    results = mcp_server.blast_radius("validate_payment")

    assert len(results) >= 1
    assert any(r["concept_id"] == str(target.id) for r in results)


# ---------------------------------------------------------------------------
# AC4: depth filter
# ---------------------------------------------------------------------------

def test_blast_radius_depth_filter(store: SQLiteStore) -> None:
    """Given depth=2, only impacts within 2 hops are returned."""
    t1 = store.create_concept(_concept("depth1_target"))
    t2 = store.create_concept(_concept("depth2_target"))
    t3 = store.create_concept(_concept("depth3_target"))

    p = ImpactProfile(
        semantic_impact=[
            ImpactEntry(target_concept_id=t1.id, confidence=0.9, relationship_path=[str(uuid.uuid4())], depth=1, rationale="d1"),
            ImpactEntry(target_concept_id=t2.id, confidence=0.8, relationship_path=[str(uuid.uuid4())], depth=2, rationale="d2"),
            ImpactEntry(target_concept_id=t3.id, confidence=0.7, relationship_path=[str(uuid.uuid4())], depth=3, rationale="d3"),
        ],
        structural_impact=[], historical_impact=[],
        last_computed=datetime.now(timezone.utc),
    )
    store.create_concept(_concept("filtered_source", impact_profile=p))

    results = mcp_server.blast_radius("filtered_source", depth=2)

    result_ids = {r["concept_id"] for r in results}
    assert str(t1.id) in result_ids
    assert str(t2.id) in result_ids
    assert str(t3.id) not in result_ids


# ---------------------------------------------------------------------------
# AC5: min_confidence filter
# ---------------------------------------------------------------------------

def test_blast_radius_min_confidence_filter(store: SQLiteStore) -> None:
    """Given min_confidence=0.5, only impacts with confidence >= 0.5 are returned."""
    t_high = store.create_concept(_concept("high_conf_target"))
    t_low = store.create_concept(_concept("low_conf_target"))

    p = ImpactProfile(
        structural_impact=[
            ImpactEntry(target_concept_id=t_high.id, confidence=0.8, relationship_path=[str(uuid.uuid4())], depth=1, rationale="high"),
            ImpactEntry(target_concept_id=t_low.id, confidence=0.3, relationship_path=[str(uuid.uuid4())], depth=1, rationale="low"),
        ],
        semantic_impact=[], historical_impact=[],
        last_computed=datetime.now(timezone.utc),
    )
    store.create_concept(_concept("conf_source", impact_profile=p))

    results = mcp_server.blast_radius("conf_source", min_confidence=0.5)

    result_ids = {r["concept_id"] for r in results}
    assert str(t_high.id) in result_ids
    assert str(t_low.id) not in result_ids


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------

def test_blast_radius_returns_empty_for_unknown_target(store: SQLiteStore) -> None:
    """Given an unknown concept/file/symbol, blast_radius returns an empty list."""
    results = mcp_server.blast_radius("nonexistent_target")
    assert results == []


def test_blast_radius_returns_empty_for_concept_without_profile(store: SQLiteStore) -> None:
    """Given a concept with no impact profile, blast_radius returns an empty list."""
    store.create_concept(_concept("no_profile"))
    results = mcp_server.blast_radius("no_profile")
    assert results == []
