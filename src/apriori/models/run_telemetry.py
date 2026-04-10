"""RunTelemetry — end-of-run summary statistics for a librarian loop run (ERD §4.8)."""

from __future__ import annotations

from pydantic import BaseModel, Field, computed_field


class RunTelemetry(BaseModel):
    """Summary statistics collected at the end of a librarian loop run.

    Fields:
        total_iterations: Total iterations executed (including failures).
        total_tokens: Cumulative tokens consumed across all iterations.
        concepts_created: Concepts newly created by the integration tree.
        concepts_updated: Existing concepts updated (extended or supplemented).
        edges_created: Edges newly created.
        edges_updated: Edges updated or confidence-adjusted.
        work_items_resolved: Iterations that fully resolved a work item.
        work_items_failed: Iterations that ended with a quality failure or error.
        work_items_escalated: Work items that were escalated during this run.
    """

    total_iterations: int = 0
    total_tokens: int = 0
    concepts_created: int = 0
    concepts_updated: int = 0
    edges_created: int = 0
    edges_updated: int = 0
    work_items_resolved: int = 0
    work_items_failed: int = 0
    work_items_escalated: int = 0

    @computed_field
    @property
    def iteration_yield(self) -> float:
        """Fraction of iterations that resolved a work item (0.0 when no iterations ran)."""
        if self.total_iterations == 0:
            return 0.0
        return self.work_items_resolved / self.total_iterations
