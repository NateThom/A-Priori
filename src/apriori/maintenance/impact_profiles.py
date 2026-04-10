"""Impact profile storage/maintenance utilities for Story 12.5."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Iterable

from apriori.knowledge.impact import ImpactComputer
from apriori.models.impact import ImpactEntry
from apriori.models.work_item import WorkItem
from apriori.retrieval.structural_impact import compute_structural_impact
from apriori.storage.protocol import KnowledgeStore


def recompute_impact_profile(store: KnowledgeStore, concept_id: uuid.UUID) -> None:
    """Recompute and persist a concept's impact profile immediately."""
    concept = store.get_concept(concept_id)
    if concept is None:
        raise KeyError(f"Concept {concept_id} not found")

    structural = compute_structural_impact(store, concept_id)
    historical = _compute_historical_impact(store, concept_id)
    profile = ImpactComputer(store).compute_profile(
        concept_id,
        structural_impact=structural,
        historical_impact=historical,
    )
    updated = concept.model_copy(
        update={
            "impact_profile": profile,
            "updated_at": datetime.now(timezone.utc),
        }
    )
    store.update_concept(updated)


def recompute_profiles_for_concepts(
    store: KnowledgeStore, concept_ids: Iterable[uuid.UUID]
) -> list[uuid.UUID]:
    """Recompute profiles for each existing concept id and return updated ids."""
    updated: list[uuid.UUID] = []
    for concept_id in set(concept_ids):
        if store.get_concept(concept_id) is None:
            continue
        recompute_impact_profile(store, concept_id)
        updated.append(concept_id)
    return updated


def enqueue_stale_impact_work_items(
    store: KnowledgeStore,
    *,
    staleness_threshold: timedelta,
    now: datetime | None = None,
) -> list[uuid.UUID]:
    """Create `analyze_impact` work items for concepts with stale profiles."""
    timestamp = now or datetime.now(timezone.utc)
    cutoff = timestamp - staleness_threshold

    pending_ids = {
        wi.concept_id
        for wi in store.get_pending_work_items()
        if wi.item_type == "analyze_impact"
    }

    created: list[uuid.UUID] = []
    for concept in store.list_concepts():
        profile = concept.impact_profile
        if profile is None:
            continue
        if profile.last_computed >= cutoff:
            continue
        if concept.id in pending_ids:
            continue

        work_item = WorkItem(
            item_type="analyze_impact",
            concept_id=concept.id,
            description=(
                f"Recompute stale impact profile for concept '{concept.name}' "
                f"(last computed {profile.last_computed.isoformat()})."
            ),
        )
        store.create_work_item(work_item)
        created.append(work_item.id)
        pending_ids.add(concept.id)

    return created


def _compute_historical_impact(
    store: KnowledgeStore, concept_id: uuid.UUID
) -> list[ImpactEntry]:
    """Build one-hop historical impact entries from outgoing historical edges."""
    entries: list[ImpactEntry] = []
    for edge in store.list_edges(source_id=concept_id):
        if edge.evidence_type != "historical":
            continue
        entries.append(
            ImpactEntry(
                target_concept_id=edge.target_id,
                confidence=edge.confidence,
                relationship_path=[str(edge.id)],
                depth=1,
                rationale="Historical co-change coupling.",
            )
        )
    return entries

