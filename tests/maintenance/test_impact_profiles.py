"""Tests for impact profile maintenance hooks — AC traceability: Story 12.5."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from apriori.maintenance.impact_profiles import enqueue_stale_impact_work_items
from apriori.models.concept import Concept
from apriori.models.impact import ImpactProfile
from apriori.models.work_item import WorkItem
from apriori.storage.sqlite_store import SQLiteStore


def test_stale_profile_creates_analyze_impact_work_item(tmp_path: Path) -> None:
    """AC3: stale impact profiles enqueue analyze_impact work."""
    store = SQLiteStore(tmp_path / "test.db")
    stale_at = datetime.now(timezone.utc) - timedelta(hours=49)
    concept = store.create_concept(
        Concept(
            name="StaleConcept",
            description="Needs impact refresh.",
            created_by="agent",
            impact_profile=ImpactProfile(last_computed=stale_at),
        )
    )

    created = enqueue_stale_impact_work_items(
        store, staleness_threshold=timedelta(hours=24)
    )

    assert len(created) == 1
    pending = store.get_pending_work_items()
    analyze_items = [wi for wi in pending if wi.item_type == "analyze_impact"]
    assert len(analyze_items) == 1
    assert analyze_items[0].concept_id == concept.id


def test_stale_profile_does_not_duplicate_pending_analyze_item(tmp_path: Path) -> None:
    """AC3: detector is idempotent while an unresolved analyze_impact item exists."""
    store = SQLiteStore(tmp_path / "test.db")
    stale_at = datetime.now(timezone.utc) - timedelta(hours=49)
    concept = store.create_concept(
        Concept(
            name="StaleConcept",
            description="Needs impact refresh.",
            created_by="agent",
            impact_profile=ImpactProfile(last_computed=stale_at),
        )
    )
    store.create_work_item(
        WorkItem(
            item_type="analyze_impact",
            concept_id=concept.id,
            description="Existing pending impact analysis.",
        )
    )

    created = enqueue_stale_impact_work_items(
        store, staleness_threshold=timedelta(hours=24)
    )

    assert created == []
    pending = store.get_pending_work_items()
    analyze_items = [wi for wi in pending if wi.item_type == "analyze_impact"]
    assert len(analyze_items) == 1
