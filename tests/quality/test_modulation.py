"""Tests for AdaptiveModulator — AC traceability: Story 9.3.

AC:
- Given coverage at 0.50 (target 0.80, deficit 0.30) and freshness at 0.95
  (target 0.90, deficit 0.0), when modulation runs with modulation_strength=1.0,
  then the effective weight for coverage_gap is 0.15 * (1 + 0.30 * 1.0) = 0.195
  while staleness and needs_review weights are unchanged.
- Given modulation_strength=0.0, when modulation runs, then effective weights
  equal base weights exactly (modulation disabled).
- Given an escalated work item, when its final priority is computed, then it is
  multiplied by 0.5 (the configured reduction factor).
- Given the modulation computation, when telemetry is emitted, then it includes:
  current metric values, targets, deficits, effective weights, and the selected
  work item with its score.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from apriori.config import DEFAULT_BASE_PRIORITIES
from apriori.quality.modulation import AdaptiveModulator, ModulationTelemetry


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

DEFAULT_COVERAGE_TARGET = 0.80
DEFAULT_FRESHNESS_TARGET = 0.90
DEFAULT_BLAST_RADIUS_TARGET = 0.80


def _make_modulator(modulation_strength: float = 1.0) -> AdaptiveModulator:
    return AdaptiveModulator(
        base_weights=DEFAULT_BASE_PRIORITIES.copy(),
        coverage_target=DEFAULT_COVERAGE_TARGET,
        freshness_target=DEFAULT_FRESHNESS_TARGET,
        blast_radius_target=DEFAULT_BLAST_RADIUS_TARGET,
        modulation_strength=modulation_strength,
        escalation_reduction_factor=0.5,
    )


# ---------------------------------------------------------------------------
# AC1: Deficit modulation boosts coverage_gap; leaves other weights unchanged
# ---------------------------------------------------------------------------


def test_coverage_deficit_boosts_coverage_gap_weight() -> None:
    """Given coverage=0.50 (deficit=0.30) and modulation_strength=1.0,
    then effective coverage_gap weight = 0.15 * (1 + 0.30 * 1.0) = 0.195."""
    modulator = _make_modulator(modulation_strength=1.0)

    effective_weights, _ = modulator.compute_effective_weights(
        coverage=0.50,
        freshness=0.95,
        blast_radius_completeness=0.90,
    )

    assert effective_weights["coverage_gap"] == pytest.approx(0.15 * (1 + 0.30 * 1.0), abs=1e-9)
    assert effective_weights["coverage_gap"] == pytest.approx(0.195, abs=1e-9)


def test_zero_freshness_deficit_leaves_staleness_weight_unchanged() -> None:
    """Given freshness=0.95 (target=0.90, deficit=0.0), staleness weight unchanged."""
    modulator = _make_modulator(modulation_strength=1.0)

    effective_weights, _ = modulator.compute_effective_weights(
        coverage=0.50,
        freshness=0.95,
        blast_radius_completeness=0.90,
    )

    assert effective_weights["staleness"] == pytest.approx(
        DEFAULT_BASE_PRIORITIES["staleness"], abs=1e-9
    )


def test_needs_review_weight_always_unchanged_by_modulation() -> None:
    """needs_review weight is not modulated (no metric drives it)."""
    modulator = _make_modulator(modulation_strength=1.0)

    effective_weights, _ = modulator.compute_effective_weights(
        coverage=0.0,      # maximum coverage deficit
        freshness=0.0,     # maximum freshness deficit
        blast_radius_completeness=0.0,
    )

    assert effective_weights["needs_review"] == pytest.approx(
        DEFAULT_BASE_PRIORITIES["needs_review"], abs=1e-9
    )


def test_coverage_gap_modulation_uses_correct_formula() -> None:
    """effective_weight = base_weight * (1 + deficit * modulation_strength).

    Spot-check with deficit=0.40 and strength=0.5:
    expected = 0.15 * (1 + 0.40 * 0.5) = 0.15 * 1.20 = 0.18
    """
    modulator = AdaptiveModulator(
        base_weights=DEFAULT_BASE_PRIORITIES.copy(),
        coverage_target=0.80,
        freshness_target=0.90,
        blast_radius_target=0.80,
        modulation_strength=0.5,
    )

    effective_weights, _ = modulator.compute_effective_weights(
        coverage=0.40,   # deficit = 0.80 - 0.40 = 0.40
        freshness=1.0,
        blast_radius_completeness=1.0,
    )

    expected = DEFAULT_BASE_PRIORITIES["coverage_gap"] * (1 + 0.40 * 0.5)
    assert effective_weights["coverage_gap"] == pytest.approx(expected, abs=1e-9)


def test_freshness_deficit_boosts_staleness_weight() -> None:
    """Given freshness=0.70 (target=0.90, deficit=0.20), staleness boosted."""
    modulator = _make_modulator(modulation_strength=1.0)

    effective_weights, _ = modulator.compute_effective_weights(
        coverage=0.90,   # no coverage deficit
        freshness=0.70,  # deficit = 0.90 - 0.70 = 0.20
        blast_radius_completeness=0.90,
    )

    expected = DEFAULT_BASE_PRIORITIES["staleness"] * (1 + 0.20 * 1.0)
    assert effective_weights["staleness"] == pytest.approx(expected, abs=1e-9)


# ---------------------------------------------------------------------------
# AC2: modulation_strength=0.0 → effective weights == base weights exactly
# ---------------------------------------------------------------------------


def test_zero_modulation_strength_preserves_base_weights() -> None:
    """Given modulation_strength=0.0, effective weights equal base weights exactly."""
    modulator = _make_modulator(modulation_strength=0.0)

    effective_weights, _ = modulator.compute_effective_weights(
        coverage=0.0,               # maximum possible deficit
        freshness=0.0,
        blast_radius_completeness=0.0,
    )

    for factor, base_weight in DEFAULT_BASE_PRIORITIES.items():
        assert effective_weights[factor] == pytest.approx(base_weight, abs=1e-9), (
            f"Factor {factor!r} weight changed despite modulation_strength=0.0"
        )


def test_zero_modulation_returns_all_base_weights_as_dict() -> None:
    """With strength=0, returned weights contain all factors from base_weights."""
    modulator = _make_modulator(modulation_strength=0.0)

    effective_weights, _ = modulator.compute_effective_weights(
        coverage=0.5,
        freshness=0.5,
        blast_radius_completeness=0.5,
    )

    assert set(effective_weights.keys()) == set(DEFAULT_BASE_PRIORITIES.keys())


# ---------------------------------------------------------------------------
# AC3: Escalated items multiplied by 0.5 reduction factor
# ---------------------------------------------------------------------------


def test_escalated_item_score_multiplied_by_reduction_factor() -> None:
    """Given an escalated work item, final priority is multiplied by 0.5."""
    modulator = _make_modulator()

    _, telemetry = modulator.compute_effective_weights(
        coverage=0.5,
        freshness=0.9,
        blast_radius_completeness=0.8,
    )

    base_score = 0.80
    escalated_score = modulator.apply_item_score_adjustments(
        base_score=base_score,
        item_type="verify_concept",
        escalated=True,
        blast_radius_deficit=telemetry.blast_radius_deficit,
    )

    assert escalated_score == pytest.approx(base_score * 0.5, abs=1e-9)


def test_non_escalated_item_score_unaffected_by_reduction() -> None:
    """Non-escalated items are not multiplied by the reduction factor."""
    modulator = _make_modulator()

    _, telemetry = modulator.compute_effective_weights(
        coverage=0.9,
        freshness=0.9,
        blast_radius_completeness=0.9,
    )

    base_score = 0.60
    score = modulator.apply_item_score_adjustments(
        base_score=base_score,
        item_type="verify_concept",
        escalated=False,
        blast_radius_deficit=telemetry.blast_radius_deficit,
    )

    assert score == pytest.approx(base_score, abs=1e-9)


def test_escalation_reduction_factor_is_configurable() -> None:
    """The escalation reduction factor can be configured (not hardcoded to 0.5)."""
    modulator = AdaptiveModulator(
        base_weights=DEFAULT_BASE_PRIORITIES.copy(),
        escalation_reduction_factor=0.25,
    )

    score = modulator.apply_item_score_adjustments(
        base_score=0.80,
        item_type="investigate_file",
        escalated=True,
        blast_radius_deficit=0.0,
    )

    assert score == pytest.approx(0.80 * 0.25, abs=1e-9)


# ---------------------------------------------------------------------------
# AC3 (continued): analyze_impact items get blast radius score multiplier
# ---------------------------------------------------------------------------


def test_analyze_impact_item_gets_blast_radius_multiplier() -> None:
    """Blast radius completeness deficit boosts analyze_impact items via score multiplier."""
    modulator = _make_modulator(modulation_strength=1.0)

    blast_deficit = 0.30  # blast_radius_completeness=0.50, target=0.80
    base_score = 0.50

    score = modulator.apply_item_score_adjustments(
        base_score=base_score,
        item_type="analyze_impact",
        escalated=False,
        blast_radius_deficit=blast_deficit,
    )

    # multiplier = 1 + deficit * strength = 1 + 0.30 * 1.0 = 1.30
    assert score == pytest.approx(base_score * 1.30, abs=1e-9)


def test_non_analyze_impact_item_not_boosted_by_blast_radius() -> None:
    """Blast radius deficit only boosts analyze_impact items, not others."""
    modulator = _make_modulator(modulation_strength=1.0)

    blast_deficit = 0.50
    base_score = 0.50

    for item_type in ("investigate_file", "verify_concept", "evaluate_relationship",
                      "reported_gap", "review_concept"):
        score = modulator.apply_item_score_adjustments(
            base_score=base_score,
            item_type=item_type,
            escalated=False,
            blast_radius_deficit=blast_deficit,
        )
        assert score == pytest.approx(base_score, abs=1e-9), (
            f"item_type={item_type!r} should not be boosted by blast radius"
        )


def test_escalated_analyze_impact_applies_both_adjustments() -> None:
    """Escalated analyze_impact items get both the blast multiplier AND the reduction."""
    modulator = _make_modulator(modulation_strength=1.0)

    base_score = 0.60
    blast_deficit = 0.20

    score = modulator.apply_item_score_adjustments(
        base_score=base_score,
        item_type="analyze_impact",
        escalated=True,
        blast_radius_deficit=blast_deficit,
    )

    # blast multiplier = 1 + 0.20 * 1.0 = 1.20; then escalation * 0.5
    expected = base_score * 1.20 * 0.5
    assert score == pytest.approx(expected, abs=1e-9)


# ---------------------------------------------------------------------------
# AC4: Telemetry completeness
# ---------------------------------------------------------------------------


def test_telemetry_contains_metric_values() -> None:
    """Telemetry includes current metric values."""
    modulator = _make_modulator()

    _, telemetry = modulator.compute_effective_weights(
        coverage=0.50,
        freshness=0.95,
        blast_radius_completeness=0.75,
    )

    assert telemetry.coverage == pytest.approx(0.50)
    assert telemetry.freshness == pytest.approx(0.95)
    assert telemetry.blast_radius_completeness == pytest.approx(0.75)


def test_telemetry_contains_targets() -> None:
    """Telemetry includes target values."""
    modulator = _make_modulator()

    _, telemetry = modulator.compute_effective_weights(
        coverage=0.50,
        freshness=0.95,
        blast_radius_completeness=0.75,
    )

    assert telemetry.coverage_target == pytest.approx(DEFAULT_COVERAGE_TARGET)
    assert telemetry.freshness_target == pytest.approx(DEFAULT_FRESHNESS_TARGET)
    assert telemetry.blast_radius_target == pytest.approx(DEFAULT_BLAST_RADIUS_TARGET)


def test_telemetry_contains_deficits() -> None:
    """Telemetry includes computed deficits."""
    modulator = _make_modulator()

    _, telemetry = modulator.compute_effective_weights(
        coverage=0.50,
        freshness=0.95,
        blast_radius_completeness=0.75,
    )

    assert telemetry.coverage_deficit == pytest.approx(0.30, abs=1e-9)
    assert telemetry.freshness_deficit == pytest.approx(0.0, abs=1e-9)
    assert telemetry.blast_radius_deficit == pytest.approx(0.05, abs=1e-9)


def test_telemetry_contains_effective_weights() -> None:
    """Telemetry includes effective weights after modulation."""
    modulator = _make_modulator(modulation_strength=1.0)

    effective_weights, telemetry = modulator.compute_effective_weights(
        coverage=0.50,
        freshness=0.95,
        blast_radius_completeness=0.90,
    )

    assert telemetry.effective_weights == effective_weights


def test_telemetry_effective_weights_match_computed() -> None:
    """Telemetry effective_weights are identical to the returned weights dict."""
    modulator = _make_modulator(modulation_strength=1.0)

    effective_weights, telemetry = modulator.compute_effective_weights(
        coverage=0.60,
        freshness=0.80,
        blast_radius_completeness=0.70,
    )

    for factor, weight in effective_weights.items():
        assert telemetry.effective_weights[factor] == pytest.approx(weight, abs=1e-9)


def test_telemetry_selected_item_can_be_set() -> None:
    """Telemetry supports setting selected work item info post-selection."""
    _, telemetry = _make_modulator().compute_effective_weights(
        coverage=0.5, freshness=0.9, blast_radius_completeness=0.8
    )
    telemetry.selected_item_id = "abc-123"
    telemetry.selected_item_score = 0.75
    telemetry.selected_item_type = "verify_concept"

    assert telemetry.selected_item_id == "abc-123"
    assert telemetry.selected_item_score == pytest.approx(0.75)
    assert telemetry.selected_item_type == "verify_concept"


def test_telemetry_is_pydantic_model() -> None:
    """ModulationTelemetry is a Pydantic model (serializable)."""
    _, telemetry = _make_modulator().compute_effective_weights(
        coverage=0.6, freshness=0.85, blast_radius_completeness=0.72
    )

    data = json.loads(telemetry.model_dump_json())
    assert "coverage" in data
    assert "freshness" in data
    assert "blast_radius_completeness" in data
    assert "coverage_target" in data
    assert "coverage_deficit" in data
    assert "effective_weights" in data


# ---------------------------------------------------------------------------
# Telemetry storage — store_telemetry appends to JSON-lines file
# ---------------------------------------------------------------------------


def test_store_telemetry_creates_jsonl_file(tmp_path: Path) -> None:
    """store_telemetry creates the file and appends a valid JSON line."""
    modulator = _make_modulator()
    _, telemetry = modulator.compute_effective_weights(
        coverage=0.5, freshness=0.9, blast_radius_completeness=0.8
    )

    output_path = tmp_path / "modulation_telemetry.jsonl"
    modulator.store_telemetry(telemetry, output_path)

    assert output_path.exists()
    lines = output_path.read_text().strip().split("\n")
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["coverage"] == pytest.approx(0.5)
    assert "effective_weights" in record


def test_store_telemetry_appends_multiple_records(tmp_path: Path) -> None:
    """store_telemetry appends successive records without overwriting."""
    modulator = _make_modulator()
    output_path = tmp_path / "telemetry.jsonl"

    for coverage_val in (0.3, 0.5, 0.7):
        _, telemetry = modulator.compute_effective_weights(
            coverage=coverage_val, freshness=0.9, blast_radius_completeness=0.8
        )
        modulator.store_telemetry(telemetry, output_path)

    lines = output_path.read_text().strip().split("\n")
    assert len(lines) == 3
    coverages = [json.loads(line)["coverage"] for line in lines]
    assert coverages == pytest.approx([0.3, 0.5, 0.7])


# ---------------------------------------------------------------------------
# Deficit clamping — no negative deficits
# ---------------------------------------------------------------------------


def test_deficit_is_zero_when_metric_exceeds_target() -> None:
    """Deficit is clamped to 0.0 when metric is above its target (no negative boost)."""
    modulator = _make_modulator(modulation_strength=1.0)

    _, telemetry = modulator.compute_effective_weights(
        coverage=0.95,              # above target 0.80
        freshness=0.99,             # above target 0.90
        blast_radius_completeness=0.99,
    )

    assert telemetry.coverage_deficit == pytest.approx(0.0)
    assert telemetry.freshness_deficit == pytest.approx(0.0)
    assert telemetry.blast_radius_deficit == pytest.approx(0.0)


def test_above_target_weights_equal_base_weights() -> None:
    """When all metrics exceed targets, effective weights equal base weights."""
    modulator = _make_modulator(modulation_strength=1.0)

    effective_weights, _ = modulator.compute_effective_weights(
        coverage=1.0,
        freshness=1.0,
        blast_radius_completeness=1.0,
    )

    for factor, base_weight in DEFAULT_BASE_PRIORITIES.items():
        assert effective_weights[factor] == pytest.approx(base_weight, abs=1e-9), (
            f"Factor {factor!r} should equal base weight when metric exceeds target"
        )
