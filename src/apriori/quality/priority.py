"""BasePriorityEngine — six-factor weighted priority scoring (PRD §6.3; ERD §4.3.1).

Computes a composite priority score in [0, 1] for a work item by weighting six
normalized factors:

1. ``coverage_gap``        — gap in file coverage; passed directly (already [0,1])
2. ``needs_review``        — 1.0 if the concept is labeled ``needs-review``, else 0.0
3. ``developer_proximity`` — inverted, normalized graph distance from recently-modified files
4. ``git_activity``        — normalized commit count over a configurable window
5. ``staleness``           — normalized days since last verification (None → 1.0)
6. ``failure_urgency``     — normalized prior failure count

All factors are normalized to [0, 1] before weighting. The weighted sum is returned.
When all factors are at 1.0, the score equals the sum of the weights (which must be 1.0).

Usage::

    from apriori.quality.priority import BasePriorityEngine
    from apriori.config import load_config

    engine = BasePriorityEngine.from_config(load_config())
    score = engine.compute(
        coverage_gap=0.8,
        concept_labels={"needs-review"},
        graph_distance=1,
        git_commit_count=5,
        days_since_verified=14.0,
        failure_count=2,
    )
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from apriori.config import Config


class BasePriorityEngine:
    """Computes a six-factor weighted priority score for work items (PRD §6.3).

    Each of the six factors is normalized to [0, 1] before multiplication by its
    weight. The composite score is the sum of weighted factors; with default weights
    that sum to 1.0, the composite is also in [0, 1].

    Args:
        weights: Dict mapping the six factor names to their weights. The weights
            should sum to 1.0 but are not enforced here — use
            ``Config.normalize_priority_weights`` to normalize before construction.
        max_distance: Graph hops at which developer_proximity reaches 0.
            Defaults to 5.
        max_commits: Commit count treated as "maximum activity" for normalization.
            Defaults to 10.
        max_staleness_days: Days-since-verified treated as "maximally stale".
            Defaults to 30.0.
        max_failures: Failure count treated as "maximum urgency" for normalization.
            Defaults to 5.
    """

    def __init__(
        self,
        weights: dict[str, float],
        max_distance: int = 5,
        max_commits: int = 10,
        max_staleness_days: float = 30.0,
        max_failures: int = 5,
    ) -> None:
        self._weights = weights
        self._max_distance = max_distance
        self._max_commits = max_commits
        self._max_staleness_days = max_staleness_days
        self._max_failures = max_failures

    # -------------------------------------------------------------------------
    # Factory
    # -------------------------------------------------------------------------

    @classmethod
    def from_config(cls, config: "Config") -> "BasePriorityEngine":
        """Create a BasePriorityEngine using weights from a loaded Config.

        Args:
            config: A fully loaded Config object (from ``load_config()``).

        Returns:
            A BasePriorityEngine using ``config.base_priority_weights`` for scoring.
        """
        return cls(weights=dict(config.base_priority_weights))

    # -------------------------------------------------------------------------
    # Factor normalization helpers
    # -------------------------------------------------------------------------

    def _compute_needs_review(self, concept_labels: set[str]) -> float:
        """Return 1.0 if concept is labeled needs-review, else 0.0."""
        return 1.0 if "needs-review" in concept_labels else 0.0

    def _compute_developer_proximity(self, graph_distance: int) -> float:
        """Return proximity as 1 - distance/max_distance, clamped to [0, 1].

        distance=0 → 1.0 (on a recently-modified file)
        distance=max_distance → 0.0
        distance > max_distance → 0.0 (clamped)
        """
        return max(0.0, 1.0 - graph_distance / self._max_distance)

    def _compute_git_activity(self, commit_count: int) -> float:
        """Normalize commit_count to [0, 1], capped at max_commits."""
        if self._max_commits <= 0:
            return 0.0
        return min(1.0, commit_count / self._max_commits)

    def _compute_staleness(self, days_since_verified: Optional[float]) -> float:
        """Normalize days since verification to [0, 1].

        None (never verified) → 1.0 (maximally stale).
        0.0 → 0.0 (just verified, not stale).
        """
        if days_since_verified is None:
            return 1.0
        if self._max_staleness_days <= 0.0:
            return 0.0
        return min(1.0, days_since_verified / self._max_staleness_days)

    def _compute_failure_urgency(self, failure_count: int) -> float:
        """Normalize failure_count to [0, 1], capped at max_failures."""
        if self._max_failures <= 0:
            return 0.0
        return min(1.0, failure_count / self._max_failures)

    # -------------------------------------------------------------------------
    # Composite score
    # -------------------------------------------------------------------------

    def compute(
        self,
        coverage_gap: float,
        concept_labels: set[str],
        graph_distance: int,
        git_commit_count: int,
        days_since_verified: Optional[float],
        failure_count: int,
    ) -> float:
        """Compute the weighted priority score for a work item.

        Args:
            coverage_gap: Pre-normalized coverage gap for this item's file, in
                [0, 1]. 1.0 means the file is completely uncovered.
            concept_labels: The label set of the associated concept. The engine
                checks for the ``"needs-review"`` label.
            graph_distance: Shortest graph hop count from the work item's concept
                to any recently-modified concept. 0 means the concept itself was
                recently modified.
            git_commit_count: Number of commits touching the relevant file(s)
                within the configured activity window.
            days_since_verified: Days elapsed since the concept's last
                verification. ``None`` if the concept has never been verified.
            failure_count: Number of prior failed librarian attempts on this
                work item.

        Returns:
            A float in [0, 1] representing the composite priority score. Higher
            values mean higher priority.
        """
        factors = {
            "coverage_gap": coverage_gap,
            "needs_review": self._compute_needs_review(concept_labels),
            "developer_proximity": self._compute_developer_proximity(graph_distance),
            "git_activity": self._compute_git_activity(git_commit_count),
            "staleness": self._compute_staleness(days_since_verified),
            "failure_urgency": self._compute_failure_urgency(failure_count),
        }
        return sum(self._weights.get(k, 0.0) * v for k, v in factors.items())
