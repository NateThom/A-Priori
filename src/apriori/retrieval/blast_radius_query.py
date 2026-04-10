"""Blast radius query — Story 12.6 (AP-100).

Resolves a target (concept name, concept UUID, file path, or function symbol)
to one or more concepts and returns their pre-computed impact profiles as a
sorted, filtered, and enriched list.

Layer: retrieval/ (Layer 3). Reads from KnowledgeStore; never writes.

Input resolution priority:
1. Valid UUID string → direct concept lookup by ID.
2. Contains path separator or ends with a file extension → file-path lookup
   via ``store.search_by_file()``.
3. Try exact name match via ``list_concepts()`` iteration.
4. Try function symbol lookup via ``code_references[*].symbol``.
5. If nothing resolves, return an empty list.
"""

from __future__ import annotations

import uuid
from typing import Optional

from pydantic import BaseModel

from apriori.models.concept import Concept
from apriori.models.impact import ImpactEntry
from apriori.storage.protocol import KnowledgeStore


# ---------------------------------------------------------------------------
# Response model
# ---------------------------------------------------------------------------

class BlastRadiusEntry(BaseModel):
    """A single enriched entry in the blast-radius response."""

    concept_id: uuid.UUID
    concept_name: str
    confidence: float
    impact_layer: str  # "structural" | "semantic" | "historical"
    depth: int
    relationship_path: list[str]  # ordered edge UUID strings
    rationale: str
    composite_score: float  # confidence * (1 / depth)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def query_blast_radius(
    store: KnowledgeStore,
    target: str,
    *,
    max_depth: Optional[int] = None,
    min_confidence: Optional[float] = None,
) -> list[BlastRadiusEntry]:
    """Return the blast-radius impact entries for *target*.

    Resolves *target* to one or more concepts (by UUID, name, file path, or
    function symbol), collects all impact entries from their pre-computed
    profiles, applies optional filters, de-duplicates by target concept, and
    returns a list sorted by composite score descending.

    Args:
        store: KnowledgeStore to query (read-only).
        target: Concept name, UUID string, file path, or function symbol.
        max_depth: When provided, exclude entries with ``depth > max_depth``.
        min_confidence: When provided, exclude entries with ``confidence < min_confidence``.

    Returns:
        A list of :class:`BlastRadiusEntry` objects sorted by
        ``composite_score`` descending.  Returns an empty list when
        *target* cannot be resolved or no impact entries exist.
    """
    source_concepts = _resolve_target(store, target)
    if not source_concepts:
        return []

    # Collect all entries across all source concepts, tracking the best score
    # per target concept.  Key: target_concept_id → best BlastRadiusEntry.
    best: dict[uuid.UUID, BlastRadiusEntry] = {}

    for source in source_concepts:
        if source.impact_profile is None:
            continue

        for layer_name, layer_entries in _iter_layers(source.impact_profile):
            for entry in layer_entries:
                if max_depth is not None and entry.depth > max_depth:
                    continue
                if min_confidence is not None and entry.confidence < min_confidence:
                    continue

                target_concept = store.get_concept(entry.target_concept_id)
                if target_concept is None:
                    continue

                composite_score = entry.confidence * (1.0 / entry.depth)
                candidate = BlastRadiusEntry(
                    concept_id=entry.target_concept_id,
                    concept_name=target_concept.name,
                    confidence=entry.confidence,
                    impact_layer=layer_name,
                    depth=entry.depth,
                    relationship_path=entry.relationship_path,
                    rationale=entry.rationale,
                    composite_score=composite_score,
                )

                existing = best.get(entry.target_concept_id)
                if existing is None or composite_score > existing.composite_score:
                    best[entry.target_concept_id] = candidate

    return sorted(best.values(), key=lambda e: e.composite_score, reverse=True)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _resolve_target(store: KnowledgeStore, target: str) -> list[Concept]:
    """Resolve *target* string to a list of source Concepts.

    Resolution order:
    1. Valid UUID → direct concept lookup.
    2. Looks like a file path → ``store.search_by_file()``.
    3. Exact name match.
    4. Symbol match in ``code_references``.
    5. Fall back to empty list.
    """
    # 1. UUID lookup
    try:
        cid = uuid.UUID(target)
        concept = store.get_concept(cid)
        if concept is not None:
            return [concept]
        return []
    except (ValueError, AttributeError):
        pass

    # 2. File path: contains OS separator OR has a dot-extension that looks like a file
    if _looks_like_file_path(target):
        return store.search_by_file(target)

    # 3. Exact name match
    name_matches = [c for c in store.list_concepts() if c.name == target]
    if name_matches:
        return name_matches

    # 4. Symbol lookup in code_references
    symbol_matches = [
        c
        for c in store.list_concepts()
        if any(ref.symbol == target for ref in c.code_references)
    ]
    return symbol_matches


def _looks_like_file_path(target: str) -> bool:
    """Return True when *target* resembles a file path (not a concept name).

    Heuristics:
    - Contains a forward slash or backslash.
    - Ends with a recognised source file extension.
    """
    if "/" in target or "\\" in target:
        return True
    _FILE_EXTENSIONS = {
        ".py", ".ts", ".tsx", ".js", ".jsx", ".rs", ".go", ".java",
        ".c", ".cpp", ".h", ".hpp", ".cs", ".rb", ".swift", ".kt",
    }
    dot_idx = target.rfind(".")
    if dot_idx != -1:
        return target[dot_idx:].lower() in _FILE_EXTENSIONS
    return False


def _iter_layers(
    profile,
) -> list[tuple[str, list[ImpactEntry]]]:
    """Return (layer_name, entries) pairs for all non-empty profile layers."""
    return [
        ("structural", profile.structural_impact),
        ("semantic", profile.semantic_impact),
        ("historical", profile.historical_impact),
    ]
