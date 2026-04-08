"""Code reference repair chain — three-step resolution (PRD §5.2, ERD §3.1.2).

Resolution order (enforced here, not in the model layer):
  1. Symbol lookup  — find concept by FQN symbol name; verify content hash.
  2. Content hash   — scan all concepts for matching SHA-256 hash; update symbol.
  3. Semantic anchor — Phase 1: dormant; always returns UNRESOLVED immediately.

When all three steps fail, the calling code reference is marked ``is_unresolved=True``
and the parent concept is labelled ``needs-review`` in the store.

Architecture notes:
- All operations are synchronous (arch:sync-first).
- All store access goes through KnowledgeStore (arch:no-raw-sql).
- No LLM calls in Phase 1 — semantic anchor is a stub that returns UNRESOLVED.
"""

from __future__ import annotations

import uuid
from enum import Enum
from typing import Optional

from pydantic import BaseModel

from apriori.models.concept import CodeReference, Concept
from apriori.storage.protocol import KnowledgeStore


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


class ResolutionMethod(str, Enum):
    """Which repair chain step resolved the code reference.

    Used for telemetry to understand how often each fallback path is exercised.
    """

    SYMBOL = "symbol"
    """Step 1: the code reference was resolved via exact FQN symbol match."""

    CONTENT_HASH = "content_hash"
    """Step 2: symbol lookup failed; resolved via SHA-256 content hash match."""

    UNRESOLVED = "unresolved"
    """All steps failed. Phase 1: semantic anchor path returns this immediately."""


class ResolutionResult(BaseModel):
    """Structured result of one code reference resolution attempt."""

    method: ResolutionMethod
    """Which step succeeded, or UNRESOLVED if all steps failed."""

    resolved_concept_id: Optional[uuid.UUID] = None
    """UUID of the concept that owns the resolved code reference (None if unresolved)."""

    symbol_updated: bool = False
    """True when the CONTENT_HASH path succeeded and the caller should update the symbol."""

    hash_verified: bool = False
    """True when the SYMBOL path also confirmed the stored content hash matches."""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def resolve_code_reference(
    code_ref: CodeReference,
    store: KnowledgeStore,
    *,
    exclude_concept_id: Optional[uuid.UUID] = None,
) -> ResolutionResult:
    """Resolve a single CodeReference via the three-step repair chain.

    Steps are attempted in order; the first successful step is returned.

    Args:
        code_ref: The CodeReference to resolve.
        store: KnowledgeStore to search for the reference.
        exclude_concept_id: Skip this concept during the content hash scan.
            Pass the parent concept's ID to prevent a concept from resolving
            against its own stale reference.

    Returns:
        A :class:`ResolutionResult` indicating which method succeeded.
        ``method=UNRESOLVED`` means the semantic anchor path was reached and
        returned early (Phase 1 behaviour).
    """
    # Step 1: Symbol lookup
    result = _try_symbol_lookup(code_ref.symbol, code_ref.content_hash, store)
    if result is not None:
        return result

    # Step 2: Content hash fallback
    result = _try_content_hash(code_ref.content_hash, store, exclude_concept_id)
    if result is not None:
        return result

    # Step 3: Semantic anchor (Phase 1: dormant — no LLM call)
    return _invoke_semantic_anchor()


def resolve_concept_references(
    concept: Concept,
    store: KnowledgeStore,
) -> list[ResolutionResult]:
    """Resolve all CodeReferences on a Concept, applying the repair chain to each.

    Side effects on store when a reference is resolved via content hash:
    - The stale symbol on the code reference is updated to the current symbol.
    - The updated concept is persisted via ``store.update_concept``.

    Side effects on store when a reference is unresolved:
    - The code reference is marked ``is_unresolved=True``.
    - The ``needs-review`` label is added to the parent concept.
    - The updated concept is persisted via ``store.update_concept``.

    Args:
        concept: The parent Concept whose CodeReferences to resolve.
        store: KnowledgeStore used for lookup and persistence.

    Returns:
        A list of :class:`ResolutionResult` objects, one per code reference,
        in the same order as ``concept.code_references``.
    """
    if not concept.code_references:
        return []

    results: list[ResolutionResult] = []
    updated_refs: list[CodeReference] = list(concept.code_references)
    needs_update = False

    for i, code_ref in enumerate(concept.code_references):
        result = resolve_code_reference(
            code_ref,
            store,
            exclude_concept_id=concept.id,
        )
        results.append(result)

        if result.method == ResolutionMethod.CONTENT_HASH and result.resolved_concept_id is not None:
            # Update the stale symbol to the current FQN found via hash.
            resolved_concept = store.get_concept(result.resolved_concept_id)
            if resolved_concept is not None:
                for rcr in resolved_concept.code_references:
                    if rcr.content_hash == code_ref.content_hash:
                        updated_refs[i] = code_ref.model_copy(
                            update={"symbol": rcr.symbol}
                        )
                        needs_update = True
                        break

        elif result.method == ResolutionMethod.UNRESOLVED:
            updated_refs[i] = code_ref.model_copy(update={"is_unresolved": True})
            needs_update = True

    if needs_update:
        any_unresolved = any(r.method == ResolutionMethod.UNRESOLVED for r in results)
        new_labels = (
            concept.labels | {"needs-review"} if any_unresolved else concept.labels
        )
        updated_concept = concept.model_copy(
            update={"code_references": updated_refs, "labels": new_labels}
        )
        store.update_concept(updated_concept)

    return results


# ---------------------------------------------------------------------------
# Internal step implementations
# ---------------------------------------------------------------------------


def _try_symbol_lookup(
    symbol: str,
    content_hash: str,
    store: KnowledgeStore,
) -> Optional[ResolutionResult]:
    """Step 1: Find a concept whose name exactly matches the FQN symbol.

    Iterates all stored concepts. The Concept name IS the FQN (graph builder
    convention), so ``concept.name == symbol`` is the correct equality check.

    Returns a ResolutionResult (SYMBOL method) if found, otherwise None.
    """
    for concept in store.list_concepts():
        if concept.name == symbol:
            hash_verified = any(
                cr.content_hash == content_hash for cr in concept.code_references
            )
            return ResolutionResult(
                method=ResolutionMethod.SYMBOL,
                resolved_concept_id=concept.id,
                hash_verified=hash_verified,
            )
    return None


def _try_content_hash(
    content_hash: str,
    store: KnowledgeStore,
    exclude_concept_id: Optional[uuid.UUID],
) -> Optional[ResolutionResult]:
    """Step 2: Find a concept with a code reference whose hash matches.

    Scans all stored concepts and their code references. Skips the concept
    identified by ``exclude_concept_id`` to prevent a concept from resolving
    against its own stale reference.

    Returns a ResolutionResult (CONTENT_HASH method, symbol_updated=True) if
    found, otherwise None.
    """
    for concept in store.list_concepts():
        if exclude_concept_id is not None and concept.id == exclude_concept_id:
            continue
        for cr in concept.code_references:
            if cr.content_hash == content_hash:
                return ResolutionResult(
                    method=ResolutionMethod.CONTENT_HASH,
                    resolved_concept_id=concept.id,
                    symbol_updated=True,
                )
    return None


def _invoke_semantic_anchor() -> ResolutionResult:
    """Step 3: Semantic anchor fallback — Phase 1 stub.

    In a future phase this would embed the ``semantic_anchor`` text and perform
    a vector similarity search to find the nearest concept. In Phase 1, the
    path is dormant: it returns UNRESOLVED immediately without any LLM call.
    """
    return ResolutionResult(method=ResolutionMethod.UNRESOLVED)
