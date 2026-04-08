"""AdaptiveModulator — metric-driven weight modulation for the librarian (PRD §6.3.1; ERD §4.3.2).

Automatically shifts the librarian's focus toward whichever product metric is
furthest below target by boosting the weights of factors that reduce those deficits.

Metric-to-factor mapping:
- ``coverage`` deficit → boosts ``coverage_gap`` weight
- ``freshness`` deficit → boosts ``staleness`` weight
- ``blast_radius_completeness`` deficit → direct score multiplier on ``analyze_impact`` items

Usage::

    from apriori.quality.modulation import AdaptiveModulator
    from apriori.config import DEFAULT_BASE_PRIORITIES

    modulator = AdaptiveModulator(
        base_weights=DEFAULT_BASE_PRIORITIES.copy(),
        coverage_target=0.80,
        freshness_target=0.90,
        blast_radius_target=0.80,
        modulation_strength=0.8,
    )

    # Compute effective weights from live metrics
    effective_weights, telemetry = modulator.compute_effective_weights(
        coverage=0.60,
        freshness=0.85,
        blast_radius_completeness=0.70,
    )

    # Apply per-item adjustments (blast radius boost + escalation reduction)
    final_score = modulator.apply_item_score_adjustments(
        base_score=0.55,
        item_type="analyze_impact",
        escalated=False,
        blast_radius_deficit=telemetry.blast_radius_deficit,
    )
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field


class ModulationTelemetry(BaseModel):
    """Telemetry emitted after each adaptive modulation computation (ERD §4.3.2).

    Stored as a JSON-lines record in the health dashboard telemetry file.
    All fields are present after ``AdaptiveModulator.compute_effective_weights``
    returns; ``selected_item_*`` fields are populated by the caller after
    selecting the highest-priority work item.

    Attributes:
        coverage: Current coverage metric value in [0, 1].
        freshness: Current freshness metric value in [0, 1].
        blast_radius_completeness: Current blast-radius completeness in [0, 1].
        coverage_target: Target coverage threshold (e.g. 0.80).
        freshness_target: Target freshness threshold (e.g. 0.90).
        blast_radius_target: Target blast-radius completeness (e.g. 0.80).
        coverage_deficit: max(0, coverage_target - coverage).
        freshness_deficit: max(0, freshness_target - freshness).
        blast_radius_deficit: max(0, blast_radius_target - blast_radius_completeness).
        effective_weights: Factor weights after deficit modulation is applied.
        selected_item_id: UUID of the highest-priority work item selected.
        selected_item_score: Final priority score of the selected item.
        selected_item_type: ``item_type`` of the selected work item.
        computed_at: UTC timestamp when modulation was computed.
    """

    # Metric snapshots
    coverage: float
    freshness: float
    blast_radius_completeness: float

    # Targets
    coverage_target: float
    freshness_target: float
    blast_radius_target: float

    # Deficits (always ≥ 0)
    coverage_deficit: float
    freshness_deficit: float
    blast_radius_deficit: float

    # Effective weights after modulation
    effective_weights: dict[str, float]

    # Selected work item — populated by caller after prioritization
    selected_item_id: Optional[str] = None
    selected_item_score: Optional[float] = None
    selected_item_type: Optional[str] = None

    computed_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class AdaptiveModulator:
    """Shifts librarian focus toward the metric furthest below target (PRD §6.3.1).

    Applies the modulation formula to base factor weights::

        effective_weight = base_weight * (1 + deficit * modulation_strength)

    where ``deficit = max(0, target - current_metric)``.

    Metric-to-factor mapping:
    - **coverage** deficit → ``coverage_gap`` factor weight
    - **freshness** deficit → ``staleness`` factor weight
    - **blast_radius_completeness** deficit → direct score multiplier on
      ``analyze_impact`` items (applied by ``apply_item_score_adjustments``)

    Factors not driven by a metric (e.g. ``needs_review``, ``developer_proximity``,
    ``git_activity``, ``failure_urgency``) are never modified by modulation.

    Args:
        base_weights: Mapping of factor names to their base weights. Typically
            ``DEFAULT_BASE_PRIORITIES.copy()`` from ``apriori.config``.
        coverage_target: Coverage threshold below which deficit boosts
            ``coverage_gap``. Defaults to 0.80.
        freshness_target: Freshness threshold below which deficit boosts
            ``staleness``. Defaults to 0.90.
        blast_radius_target: Blast-radius completeness threshold below which
            deficit boosts ``analyze_impact`` item scores. Defaults to 0.80.
        modulation_strength: Scalar in [0, 1] controlling how aggressively
            weights are boosted. 0.0 disables modulation entirely; 1.0 applies
            the full deficit multiplier. Defaults to 0.8.
        escalation_reduction_factor: Score multiplier applied to all escalated
            work items regardless of type. Defaults to 0.5.
    """

    def __init__(
        self,
        base_weights: dict[str, float],
        coverage_target: float = 0.80,
        freshness_target: float = 0.90,
        blast_radius_target: float = 0.80,
        modulation_strength: float = 0.8,
        escalation_reduction_factor: float = 0.5,
    ) -> None:
        self._base_weights = base_weights
        self._coverage_target = coverage_target
        self._freshness_target = freshness_target
        self._blast_radius_target = blast_radius_target
        self._modulation_strength = modulation_strength
        self._escalation_reduction_factor = escalation_reduction_factor

    # -------------------------------------------------------------------------
    # Core modulation
    # -------------------------------------------------------------------------

    def compute_effective_weights(
        self,
        coverage: float,
        freshness: float,
        blast_radius_completeness: float,
    ) -> tuple[dict[str, float], ModulationTelemetry]:
        """Compute effective factor weights after applying deficit-based modulation.

        Reads the three live metrics, computes their deficits, then boosts the
        corresponding factor weights using the modulation formula. Factors with no
        associated metric are returned unchanged.

        Args:
            coverage: Current coverage metric in [0, 1].
            freshness: Current freshness metric in [0, 1].
            blast_radius_completeness: Current blast-radius completeness in [0, 1].

        Returns:
            A ``(effective_weights, telemetry)`` tuple. ``effective_weights`` is a
            copy of the base weights with modulated values substituted for affected
            factors. ``telemetry`` captures all inputs, computed deficits, and the
            effective weights for dashboard storage.
        """
        coverage_deficit = max(0.0, self._coverage_target - coverage)
        freshness_deficit = max(0.0, self._freshness_target - freshness)
        blast_radius_deficit = max(0.0, self._blast_radius_target - blast_radius_completeness)

        # Start from a copy of base weights; only modify driven factors
        effective_weights = dict(self._base_weights)

        if "coverage_gap" in effective_weights:
            effective_weights["coverage_gap"] = self._base_weights["coverage_gap"] * (
                1 + coverage_deficit * self._modulation_strength
            )

        if "staleness" in effective_weights:
            effective_weights["staleness"] = self._base_weights["staleness"] * (
                1 + freshness_deficit * self._modulation_strength
            )

        telemetry = ModulationTelemetry(
            coverage=coverage,
            freshness=freshness,
            blast_radius_completeness=blast_radius_completeness,
            coverage_target=self._coverage_target,
            freshness_target=self._freshness_target,
            blast_radius_target=self._blast_radius_target,
            coverage_deficit=coverage_deficit,
            freshness_deficit=freshness_deficit,
            blast_radius_deficit=blast_radius_deficit,
            effective_weights=effective_weights,
        )

        return effective_weights, telemetry

    # -------------------------------------------------------------------------
    # Per-item score adjustments
    # -------------------------------------------------------------------------

    def apply_item_score_adjustments(
        self,
        base_score: float,
        item_type: str,
        escalated: bool,
        blast_radius_deficit: float,
    ) -> float:
        """Apply blast-radius boost and escalation reduction to a work item's score.

        Two adjustments are applied in order:

        1. **Blast radius boost** (``analyze_impact`` items only): the score is
           multiplied by ``1 + blast_radius_deficit * modulation_strength``.
        2. **Escalation reduction**: if the item is escalated, the score is
           further multiplied by ``escalation_reduction_factor`` (default 0.5).

        Args:
            base_score: The raw priority score before any adjustments.
            item_type: The work item's ``item_type`` (e.g. ``"analyze_impact"``).
            escalated: Whether the work item has ``escalated=True``.
            blast_radius_deficit: Pre-computed blast-radius deficit from the most
                recent ``compute_effective_weights`` call.

        Returns:
            Adjusted score with blast-radius boost and/or escalation reduction
            applied as appropriate.
        """
        score = base_score

        if item_type == "analyze_impact":
            score *= 1 + blast_radius_deficit * self._modulation_strength

        if escalated:
            score *= self._escalation_reduction_factor

        return score

    # -------------------------------------------------------------------------
    # Telemetry storage
    # -------------------------------------------------------------------------

    def store_telemetry(self, telemetry: ModulationTelemetry, path: Path) -> None:
        """Append a telemetry record to a JSON-lines file for the health dashboard.

        Each call appends one JSON-serialized ``ModulationTelemetry`` record to
        ``path``. The file is created if it does not exist. Earlier records are
        never overwritten — append-only semantics.

        Args:
            telemetry: The modulation telemetry to persist.
            path: Destination file path. Extension is conventionally ``.jsonl``.
        """
        with open(path, "a") as f:
            f.write(telemetry.model_dump_json() + "\n")
