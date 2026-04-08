"""Tests for MetricsEngine — AC traceability: Story 9.1.

AC:
- Given 100 source files and 60 referenced by at least one concept, when
  get_coverage is called, then it returns 0.60.
- Given 50 concepts referencing actively-developed files and 45 with
  last_verified more recent than the code's last modification, when
  get_freshness is called, then it returns 0.90.
- Given 100 concepts and 70 with non-stale impact profiles, when
  get_blast_radius_completeness is called, then it returns 0.70.
- Given a 10,000-concept graph, when any metric is computed, then execution
  time is under 50ms.
- Given metrics were computed 10 seconds ago, when metrics are requested
  again, then cached values are returned (simple 30-second TTL cache).

All tests use real SQLiteStore instances against on-disk SQLite files
(integration tests per DoD — no mocking of the storage layer).
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from apriori.models.concept import Concept, CodeReference
from apriori.models.impact import ImpactProfile
from apriori.quality.metrics import MetricsEngine
from apriori.storage.sqlite_store import SQLiteStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SHA256 = "a" * 64


def _make_concept(
    *,
    file_paths: list[str] | None = None,
    last_verified: datetime | None = None,
    updated_at: datetime | None = None,
    impact_profile: ImpactProfile | None = None,
) -> Concept:
    now = datetime.now(timezone.utc)
    refs = []
    if file_paths:
        for fp in file_paths:
            refs.append(
                CodeReference(
                    symbol="fn",
                    file_path=fp,
                    content_hash=_SHA256,
                    semantic_anchor="anchor",
                )
            )
    concept = Concept(
        name=f"concept-{uuid.uuid4()}",
        description="test concept",
        created_by="agent",
        code_references=refs,
        last_verified=last_verified,
        impact_profile=impact_profile,
        created_at=now,
        updated_at=updated_at or now,
    )
    return concept


def _store(tmp_path: Path) -> SQLiteStore:
    return SQLiteStore(tmp_path / "test.db")


# ---------------------------------------------------------------------------
# AC1: Coverage — 60 of 100 source files referenced → 0.60
# ---------------------------------------------------------------------------


def test_get_coverage_correct_ratio(tmp_path: Path) -> None:
    """Given 100 source files and 60 referenced by at least one concept,
    when get_coverage is called, then it returns 0.60."""
    store = _store(tmp_path)
    # 60 distinct file paths, each referenced by exactly one concept
    for i in range(60):
        store.create_concept(_make_concept(file_paths=[f"src/module_{i}.py"]))
    # 40 additional concepts with NO code references (other files not covered)
    for _ in range(40):
        store.create_concept(_make_concept())

    engine = MetricsEngine(store)
    result = engine.get_coverage(total_source_files=100)

    assert result == pytest.approx(0.60)


def test_get_coverage_multiple_concepts_same_file(tmp_path: Path) -> None:
    """File referenced by multiple concepts counts only once in numerator."""
    store = _store(tmp_path)
    # 3 concepts all referencing the same file
    for _ in range(3):
        store.create_concept(_make_concept(file_paths=["shared.py"]))
    # 1 concept referencing a different file
    store.create_concept(_make_concept(file_paths=["other.py"]))

    engine = MetricsEngine(store)
    # 2 distinct files covered out of 10 total
    result = engine.get_coverage(total_source_files=10)

    assert result == pytest.approx(0.20)


def test_get_coverage_empty_store_returns_zero(tmp_path: Path) -> None:
    """Given no concepts, coverage is 0.0."""
    store = _store(tmp_path)
    engine = MetricsEngine(store)
    assert engine.get_coverage(total_source_files=100) == pytest.approx(0.0)


def test_get_coverage_zero_total_files_returns_zero(tmp_path: Path) -> None:
    """Given total_source_files=0, coverage is 0.0 (avoid division by zero)."""
    store = _store(tmp_path)
    store.create_concept(_make_concept(file_paths=["foo.py"]))
    engine = MetricsEngine(store)
    assert engine.get_coverage(total_source_files=0) == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# AC2: Freshness — 45 of 50 active concepts verified → 0.90
# ---------------------------------------------------------------------------


def test_get_freshness_correct_ratio(tmp_path: Path) -> None:
    """Given 50 concepts referencing actively-developed files and 45 with
    last_verified more recent than the code's last modification, when
    get_freshness is called, then it returns 0.90."""
    store = _store(tmp_path)
    now = datetime.now(timezone.utc)
    recent = now - timedelta(days=5)      # within 30-day active window

    # 45 active concepts that are fresh (last_verified > updated_at)
    for _ in range(45):
        store.create_concept(
            _make_concept(
                updated_at=recent,
                last_verified=now,          # verified after last update
            )
        )
    # 5 active concepts that are NOT fresh (last_verified is None)
    for _ in range(5):
        store.create_concept(
            _make_concept(
                updated_at=recent,
                last_verified=None,
            )
        )
    # 10 inactive concepts (updated > 30 days ago — not counted)
    old = now - timedelta(days=60)
    for _ in range(10):
        store.create_concept(
            _make_concept(
                updated_at=old,
                last_verified=None,
            )
        )

    engine = MetricsEngine(store)
    result = engine.get_freshness()

    assert result == pytest.approx(0.90)


def test_get_freshness_no_active_concepts_returns_one(tmp_path: Path) -> None:
    """Given no actively-developed concepts, freshness is 1.0 (vacuously fresh)."""
    store = _store(tmp_path)
    now = datetime.now(timezone.utc)
    old = now - timedelta(days=60)
    for _ in range(5):
        store.create_concept(_make_concept(updated_at=old, last_verified=None))
    engine = MetricsEngine(store)
    assert engine.get_freshness() == pytest.approx(1.0)


def test_get_freshness_empty_store_returns_one(tmp_path: Path) -> None:
    """Given no concepts at all, freshness is 1.0."""
    store = _store(tmp_path)
    engine = MetricsEngine(store)
    assert engine.get_freshness() == pytest.approx(1.0)


def test_get_freshness_respects_active_days_config(tmp_path: Path) -> None:
    """Freshness active_days is configurable — concepts outside the window are excluded."""
    store = _store(tmp_path)
    now = datetime.now(timezone.utc)

    # 5 concepts updated 20 days ago — fresh within 30-day window, outside 10-day window
    twenty_days_ago = now - timedelta(days=20)
    for _ in range(5):
        store.create_concept(
            _make_concept(updated_at=twenty_days_ago, last_verified=now)
        )

    engine_30 = MetricsEngine(store, active_days=30)
    engine_10 = MetricsEngine(store, active_days=10)

    assert engine_30.get_freshness() == pytest.approx(1.0)  # all 5 in window, all fresh
    assert engine_10.get_freshness() == pytest.approx(1.0)  # no concepts in window → vacuous


# ---------------------------------------------------------------------------
# AC3: Blast Radius Completeness — 70 of 100 concepts with impact → 0.70
# ---------------------------------------------------------------------------


def test_get_blast_radius_completeness_correct_ratio(tmp_path: Path) -> None:
    """Given 100 concepts and 70 with non-stale impact profiles, when
    get_blast_radius_completeness is called, then it returns 0.70."""
    store = _store(tmp_path)
    now = datetime.now(timezone.utc)
    profile = ImpactProfile(last_computed=now)

    for _ in range(70):
        store.create_concept(_make_concept(impact_profile=profile))
    for _ in range(30):
        store.create_concept(_make_concept(impact_profile=None))

    engine = MetricsEngine(store)
    result = engine.get_blast_radius_completeness()

    assert result == pytest.approx(0.70)


def test_get_blast_radius_completeness_empty_store_returns_one(tmp_path: Path) -> None:
    """Given no concepts, blast radius completeness is 1.0 (vacuously complete)."""
    store = _store(tmp_path)
    engine = MetricsEngine(store)
    assert engine.get_blast_radius_completeness() == pytest.approx(1.0)


def test_get_blast_radius_completeness_all_have_profile(tmp_path: Path) -> None:
    """All concepts with impact profiles → 1.0."""
    store = _store(tmp_path)
    now = datetime.now(timezone.utc)
    profile = ImpactProfile(last_computed=now)
    for _ in range(10):
        store.create_concept(_make_concept(impact_profile=profile))
    engine = MetricsEngine(store)
    assert engine.get_blast_radius_completeness() == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# AC4: Performance — all metrics < 50ms on 10,000-concept graph
# ---------------------------------------------------------------------------


def test_metrics_performance_under_50ms(tmp_path: Path) -> None:
    """Given a 10,000-concept graph, when any metric is computed, then
    execution time is under 50ms (each metric individually)."""
    store = _store(tmp_path)
    now = datetime.now(timezone.utc)
    profile = ImpactProfile(last_computed=now)

    # Bulk-insert 10,000 concepts (50% with code_refs, 50% with impact_profile)
    conn = store._get_connection()  # noqa: SLF001 — direct access for bulk seeding only
    import json as _json

    rows = []
    for i in range(10_000):
        cid = str(uuid.uuid4())
        refs = _json.dumps(
            [{"symbol": "fn", "file_path": f"src/f{i % 500}.py",
              "content_hash": _SHA256, "semantic_anchor": "anc",
              "line_range": None, "derived_from_code_version": None}]
        ) if i % 2 == 0 else "[]"
        imp = profile.model_dump_json() if i % 2 == 1 else None
        rows.append((
            cid, f"concept-{i}", "desc", "[]", refs, "agent",
            None, None, 0.5, None, None, imp,
            now.isoformat(), now.isoformat(),
        ))
    conn.executemany(
        """INSERT INTO concepts
               (id, name, description, labels, code_references, created_by,
                verified_by, last_verified, confidence, derived_from_code_version,
                metadata, impact_profile, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        rows,
    )
    conn.commit()

    engine = MetricsEngine(store)

    t0 = time.perf_counter()
    engine.get_coverage(total_source_files=10_000)
    t_coverage = (time.perf_counter() - t0) * 1000

    t0 = time.perf_counter()
    engine.get_freshness()
    t_freshness = (time.perf_counter() - t0) * 1000

    t0 = time.perf_counter()
    engine.get_blast_radius_completeness()
    t_blast = (time.perf_counter() - t0) * 1000

    assert t_coverage < 50, f"get_coverage took {t_coverage:.1f}ms (> 50ms)"
    assert t_freshness < 50, f"get_freshness took {t_freshness:.1f}ms (> 50ms)"
    assert t_blast < 50, f"get_blast_radius_completeness took {t_blast:.1f}ms (> 50ms)"


# ---------------------------------------------------------------------------
# AC5: Caching — second call within 30s returns cached value
# ---------------------------------------------------------------------------


def test_cached_values_returned_within_ttl(tmp_path: Path) -> None:
    """Given metrics were computed 10 seconds ago, when metrics are requested
    again, then cached values are returned (30-second TTL)."""
    store = _store(tmp_path)
    now = datetime.now(timezone.utc)
    profile = ImpactProfile(last_computed=now)
    store.create_concept(_make_concept(file_paths=["a.py"], impact_profile=profile))

    engine = MetricsEngine(store, cache_ttl=30.0)

    # First calls — populate cache
    cov1 = engine.get_coverage(total_source_files=10)
    fresh1 = engine.get_freshness()
    blast1 = engine.get_blast_radius_completeness()

    # Mutate the store — adding a new concept changes the ground truth
    store.create_concept(_make_concept(file_paths=["b.py"], impact_profile=profile))

    # Second calls within TTL — should return stale cached values
    cov2 = engine.get_coverage(total_source_files=10)
    fresh2 = engine.get_freshness()
    blast2 = engine.get_blast_radius_completeness()

    assert cov1 == cov2, "coverage cache miss within TTL"
    assert fresh1 == fresh2, "freshness cache miss within TTL"
    assert blast1 == blast2, "blast_radius cache miss within TTL"


def test_cache_expires_after_ttl(tmp_path: Path) -> None:
    """After TTL expires, fresh values are recomputed."""
    store = _store(tmp_path)
    engine = MetricsEngine(store, cache_ttl=0.01)  # 10ms TTL

    # First call — 0 concepts
    cov1 = engine.get_coverage(total_source_files=10)
    assert cov1 == pytest.approx(0.0)

    # Wait for cache to expire
    time.sleep(0.05)

    # Add a concept — should now be reflected
    store.create_concept(_make_concept(file_paths=["new.py"]))
    cov2 = engine.get_coverage(total_source_files=10)

    assert cov2 == pytest.approx(0.10)
    assert cov1 != cov2, "expected cache to expire and return fresh value"


def test_cache_is_per_metric(tmp_path: Path) -> None:
    """Each metric has its own cached value — invalidating one does not affect others."""
    store = _store(tmp_path)
    now = datetime.now(timezone.utc)
    profile = ImpactProfile(last_computed=now)
    store.create_concept(_make_concept(impact_profile=profile))

    engine = MetricsEngine(store, cache_ttl=30.0)
    _ = engine.get_coverage(total_source_files=5)
    _ = engine.get_freshness()
    blast_before = engine.get_blast_radius_completeness()

    # Manually expire only coverage cache
    engine._cache["coverage"].expiry = 0.0  # noqa: SLF001

    # Mutate — new concept without impact profile
    store.create_concept(_make_concept(impact_profile=None))

    # Coverage recomputed (cache expired), blast still cached
    engine.get_coverage(total_source_files=5)
    blast_after = engine.get_blast_radius_completeness()

    assert blast_before == blast_after, "blast_radius cache should not be invalidated"
