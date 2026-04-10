"""LibrarianActivity — activity record for one librarian loop iteration (ERD §4.2.1)."""

import uuid
from datetime import datetime, timezone
from typing import Literal, Optional

from pydantic import BaseModel, Field


class LibrarianActivity(BaseModel):
    """A record of a single librarian loop iteration.

    Written to the ``librarian_activity`` SQLite table at the end of each
    iteration (arch:librarian-loop). Groups all iterations from a single
    ``librarian run`` invocation by ``run_id``.

    Fields:
        id: UUID primary key.
        run_id: Groups all iterations from one ``librarian run`` invocation.
        iteration: Zero-based iteration index within the run.
        work_item_id: The work item processed in this iteration (None when
            no items were available).
        status: Outcome of the iteration.
            ``"success"``       — output integrated, work item resolved.
            ``"level1_failure"`` — Level 1 consistency check failed.
            ``"level15_failure"`` — Level 1.5 co-regulation check failed.
            ``"no_items"``      — work queue was empty (iteration not started).
            ``"error"``         — unexpected error (LLM call failed, etc.).
        concepts_integrated: Number of concepts integrated (0 on failure).
        edges_integrated: Number of edges integrated (0 on failure).
        tokens_used: Total tokens consumed by this iteration (analysis + co-regulation).
        model_used: Identifier of the LLM model used.
        duration_seconds: Wall-clock time for this iteration.
        failure_reason: Populated on failure statuses; None on success.
        created_at: UTC timestamp when this record was created.
    """

    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    run_id: uuid.UUID
    iteration: int
    work_item_id: Optional[uuid.UUID] = None
    status: Literal["success", "level1_failure", "level15_failure", "no_items", "error"]
    concepts_integrated: int = 0
    edges_integrated: int = 0
    tokens_used: int = 0
    model_used: str = ""
    duration_seconds: float = 0.0
    failure_reason: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
