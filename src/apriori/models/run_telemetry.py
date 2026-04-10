"""RunTelemetry — end-of-run summary statistics for a librarian loop run (ERD §4.8)."""

from __future__ import annotations

from pydantic import BaseModel, computed_field


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
        files_analyzed: Distinct source files analyzed in this run (progressive
            enrichment telemetry, ERD §6.1).
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
    files_analyzed: int = 0

    @computed_field
    @property
    def iteration_yield(self) -> float:
        """Fraction of iterations that resolved a work item (0.0 when no iterations ran)."""
        if self.total_iterations == 0:
            return 0.0
        return self.work_items_resolved / self.total_iterations

    def format_progress_report(
        self,
        total_source_files: int,
        cost_per_1k_tokens: float,
    ) -> str:
        """Format a human-readable progress report with cost estimation.

        Produces a message of the form::

            Analyzed 47/312 source files. Estimated remaining cost: ~$2.30 at current model pricing.

        Args:
            total_source_files: Total source files in the repository.
            cost_per_1k_tokens: USD cost per 1,000 tokens consumed.

        Returns:
            A single-line progress report string.
        """
        remaining_files = max(0, total_source_files - self.files_analyzed)

        if self.files_analyzed > 0:
            total_cost_usd = (self.total_tokens / 1000.0) * cost_per_1k_tokens
            cost_per_file = total_cost_usd / self.files_analyzed
            estimated_remaining = cost_per_file * remaining_files
        else:
            estimated_remaining = 0.0

        return (
            f"Analyzed {self.files_analyzed}/{total_source_files} source files. "
            f"Estimated remaining cost: ~${estimated_remaining:.2f} at current model pricing."
        )
