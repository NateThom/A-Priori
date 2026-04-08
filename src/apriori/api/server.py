"""FastAPI REST server for the A-Priori Audit UI (Epic 11, Stories 11.2a/11.2b).

Thin shell delegating to core apriori modules (arch:core-lib-thin-shells,
arch:mcp-thin-shell). Business logic lives in knowledge/reviewer.py and
storage/protocol.py — this module handles only HTTP wiring.

Sync KnowledgeStore calls are wrapped in ``asyncio.to_thread()`` per S-1
so FastAPI's async event loop is never blocked.

Server startup:
    uvicorn apriori.api.server:app --host 127.0.0.1 --port 8391
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, field_validator

from apriori.models.review_outcome import VALID_ERROR_TYPES
from apriori.storage.protocol import KnowledgeStore

# ---------------------------------------------------------------------------
# Module-level store — injected by lifespan or tests
# ---------------------------------------------------------------------------

_store: Optional[KnowledgeStore] = None


def _get_store() -> KnowledgeStore:
    if _store is None:
        raise RuntimeError("KnowledgeStore not initialised")
    return _store


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class VerifyRequest(BaseModel):
    reviewer: str


class CorrectRequest(BaseModel):
    reviewer: str
    error_type: str
    correction_details: Optional[str] = None

    @field_validator("error_type")
    @classmethod
    def error_type_must_be_valid(cls, v: str) -> str:
        if v not in VALID_ERROR_TYPES:
            raise ValueError(
                f"error_type '{v}' is not valid; must be one of {sorted(VALID_ERROR_TYPES)}"
            )
        return v


class FlagRequest(BaseModel):
    reviewer: str


# ---------------------------------------------------------------------------
# FastAPI application
# ---------------------------------------------------------------------------

app = FastAPI(title="A-Priori Audit API")


# ---------------------------------------------------------------------------
# AC-1: GET /api/escalated
# ---------------------------------------------------------------------------


@app.get("/api/escalated")
async def get_escalated() -> list[dict[str, Any]]:
    """Return all escalated work items with full failure history.

    Returns:
        List of escalated WorkItem dicts, each including their
        ``failure_records`` array.
    """
    store = _get_store()
    items = await asyncio.to_thread(store.get_escalated_items)
    return [item.model_dump(mode="json") for item in items]


# ---------------------------------------------------------------------------
# AC-2: POST /api/concepts/{concept_id}/verify
# ---------------------------------------------------------------------------


@app.post("/api/concepts/{concept_id}/verify")
async def verify_concept(
    concept_id: uuid.UUID, body: VerifyRequest
) -> dict[str, Any]:
    """Verify a concept and record a ReviewOutcome.

    Args:
        concept_id: UUID of the concept to verify.
        body: Verify request with reviewer identifier.

    Returns:
        Dict with ``concept`` and ``review_outcome`` keys.

    Raises:
        HTTPException(404): If the concept does not exist.
    """
    from apriori.knowledge.reviewer import ReviewService

    store = _get_store()
    service = ReviewService(store)
    try:
        concept, outcome = await asyncio.to_thread(
            service.verify_concept, concept_id, body.reviewer
        )
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Concept {concept_id} not found")

    return {
        "concept": concept.model_dump(mode="json"),
        "review_outcome": outcome.model_dump(mode="json"),
    }


# ---------------------------------------------------------------------------
# AC-3: POST /api/concepts/{concept_id}/correct
# ---------------------------------------------------------------------------


@app.post("/api/concepts/{concept_id}/correct")
async def correct_concept(
    concept_id: uuid.UUID, body: CorrectRequest
) -> dict[str, Any]:
    """Record a human correction for a concept.

    Args:
        concept_id: UUID of the concept to correct.
        body: Correct request with reviewer, error_type, and optional
            correction_details.

    Returns:
        Dict with ``concept`` and ``review_outcome`` keys.

    Raises:
        HTTPException(404): If the concept does not exist.
    """
    from apriori.knowledge.reviewer import ReviewService

    store = _get_store()
    service = ReviewService(store)
    try:
        concept, outcome = await asyncio.to_thread(
            service.correct_concept,
            concept_id,
            body.reviewer,
            body.error_type,
            body.correction_details,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Concept {concept_id} not found")

    return {
        "concept": concept.model_dump(mode="json"),
        "review_outcome": outcome.model_dump(mode="json"),
    }


# ---------------------------------------------------------------------------
# AC-4: POST /api/concepts/{concept_id}/flag
# ---------------------------------------------------------------------------


@app.post("/api/concepts/{concept_id}/flag")
async def flag_concept(
    concept_id: uuid.UUID, body: FlagRequest
) -> dict[str, Any]:
    """Flag a concept for human review and create a review_concept work item.

    Args:
        concept_id: UUID of the concept to flag.
        body: Flag request with reviewer identifier.

    Returns:
        Dict with ``concept``, ``review_outcome``, and ``work_item`` keys.

    Raises:
        HTTPException(404): If the concept does not exist.
    """
    from apriori.knowledge.reviewer import ReviewService

    store = _get_store()
    service = ReviewService(store)
    try:
        concept, outcome, work_item = await asyncio.to_thread(
            service.flag_concept, concept_id, body.reviewer
        )
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Concept {concept_id} not found")

    return {
        "concept": concept.model_dump(mode="json"),
        "review_outcome": outcome.model_dump(mode="json"),
        "work_item": work_item.model_dump(mode="json"),
    }
