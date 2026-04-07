"""MetricsEngine — coverage, freshness, and blast-radius completeness (ERD §4.6).

These three metrics serve dual purpose:
1. Health dashboard reporting
2. Driving the adaptive modulation loop (Story 9.3)

All metrics are computed via single SQL queries delegated through the
KnowledgeStore protocol (arch:no-raw-sql). Results are cached for
``cache_ttl`` seconds (default: 30) so that repeated calls before each
librarian iteration are cheap.

Usage::

    from apriori.quality.metrics import MetricsEngine
    from apriori.storage.sqlite_store import SQLiteStore

    store = SQLiteStore(Path("graph.db"))
    engine = MetricsEngine(store, cache_ttl=30.0, active_days=30)

    coverage = engine.get_coverage(total_source_files=1_200)
    freshness = engine.get_freshness()
    completeness = engine.get_blast_radius_completeness()
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from apriori.storage.protocol import KnowledgeStore


@dataclass
class _CacheEntry:
    """Single cached metric value with a monotonic expiry timestamp."""

    value: float
    expiry: float  # time.monotonic() value after which this entry is stale


class MetricsEngine:
    """Computes coverage, freshness, and blast-radius completeness metrics.

    Each metric is backed by a SQL query in the KnowledgeStore implementation
    (arch:no-raw-sql). Results are cached with a configurable TTL to avoid
    redundant queries when the engine is called repeatedly within a short
    window (e.g., before each librarian iteration).

    Cache entries are per-metric and independent: expiring one does not
    invalidate the others.

    Args:
        store: A KnowledgeStore implementation.  The SQLiteStore and
            DualWriter both satisfy the required methods.
        cache_ttl: Seconds to cache each metric before recomputing.
            Defaults to 30.
        active_days: Lookback window for "actively developed" files in the
            freshness metric.  Files whose corresponding concept ``updated_at``
            falls within this window are considered active.  Defaults to 30.
    """

    def __init__(
        self,
        store: KnowledgeStore,
        cache_ttl: float = 30.0,
        active_days: int = 30,
    ) -> None:
        self._store = store
        self._cache_ttl = cache_ttl
        self._active_days = active_days
        self._cache: dict[str, _CacheEntry] = {}

    # -------------------------------------------------------------------------
    # Internal helpers
    # -------------------------------------------------------------------------

    def _get_cached(self, key: str, compute) -> float:
        """Return a cached value if still fresh, otherwise recompute and cache it."""
        entry = self._cache.get(key)
        if entry is not None and time.monotonic() < entry.expiry:
            return entry.value
        value = compute()
        self._cache[key] = _CacheEntry(
            value=value,
            expiry=time.monotonic() + self._cache_ttl,
        )
        return value

    # -------------------------------------------------------------------------
    # Public metrics API
    # -------------------------------------------------------------------------

    def get_coverage(self, total_source_files: int) -> float:
        """Return the fraction of source files referenced by at least one Concept.

        Coverage = (distinct covered files) / total_source_files.

        Args:
            total_source_files: The total number of source files in the
                repository.  Provided by the caller because the knowledge
                store does not track uncovered files.

        Returns:
            A float in [0.0, 1.0].  Returns 0.0 if ``total_source_files``
            is zero.
        """

        def _compute() -> float:
            if total_source_files == 0:
                return 0.0
            covered = self._store.count_covered_files()
            return covered / total_source_files

        return self._get_cached("coverage", _compute)

    def get_freshness(self) -> float:
        """Return the fraction of actively-developed concepts that are verified.

        Freshness = (active concepts with last_verified > updated_at) /
                    (all active concepts).

        "Active" means ``updated_at`` is within the last ``active_days`` days.
        Returns 1.0 when there are no actively-developed concepts (vacuously
        fresh: nothing is stale if nothing is active).

        Returns:
            A float in [0.0, 1.0].
        """

        def _compute() -> float:
            fresh, active = self._store.count_fresh_active_concepts(self._active_days)
            if active == 0:
                return 1.0
            return fresh / active

        return self._get_cached("freshness", _compute)

    def get_blast_radius_completeness(self) -> float:
        """Return the fraction of concepts that have a computed impact profile.

        Blast-radius completeness = (concepts with impact_profile IS NOT NULL) /
                                    total_concepts.

        Returns 1.0 when the store contains no concepts (vacuously complete).

        Returns:
            A float in [0.0, 1.0].
        """

        def _compute() -> float:
            with_profile, total = self._store.count_blast_radius_complete()
            if total == 0:
                return 1.0
            return with_profile / total

        return self._get_cached("blast_radius", _compute)
