"""WorkItem and FailureRecord models (PRD §5.6; ERD §3.1.4, §3.1.5)."""

import uuid
from datetime import datetime, timezone
from typing import Literal, Optional

from pydantic import BaseModel, Field


VALID_ITEM_TYPES: frozenset[str] = frozenset(
    {
        "investigate_file",
        "verify_concept",
        "evaluate_relationship",
        "reported_gap",
        "review_concept",
        "analyze_impact",
    }
)

_ItemType = Literal[
    "investigate_file",
    "verify_concept",
    "evaluate_relationship",
    "reported_gap",
    "review_concept",
    "analyze_impact",
]


class FailureRecord(BaseModel):
    """Diagnostic context captured when a librarian iteration fails.

    Embedded in WorkItem.failure_records as a JSON array in SQLite.
    The four core fields are required — no partial failure records.
    reviewer_feedback carries co-regulation guidance for the next retry attempt.
    """

    attempted_at: datetime
    model_used: str
    prompt_template: str
    failure_reason: str
    quality_scores: Optional[dict] = None
    reviewer_feedback: Optional[str] = None


class WorkItem(BaseModel):
    """Transient operational state for the librarian's work queue.

    SQLite-only — not dual-written to YAML (see arch:sqlite-vec-storage).
    base_priority_score is stored here but recalculated fresh by the
    priority engine each time; treat the stored value as a cache.
    """

    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    item_type: _ItemType
    concept_id: uuid.UUID
    description: str
    file_path: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    resolved_at: Optional[datetime] = None
    failure_count: int = 0
    failure_records: list[FailureRecord] = Field(default_factory=list)
    escalated: bool = False
    resolved: bool = False
    base_priority_score: Optional[float] = None
