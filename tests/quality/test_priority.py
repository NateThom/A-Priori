"""Tests for BasePriorityEngine — AC traceability: Story 9.2.

AC:
- Given a work item for an investigate_file with coverage_gap = 1.0 and
  default weights, when the score is computed, then the coverage_gap factor
  contributes 0.15 to the total score.
- Given a work item for a concept labeled needs-review, when the score is
  computed, then the needs_review factor contributes 0.20.
- Given a work item near recently-modified files (graph distance = 1), when
  the score is computed, then the developer_proximity factor is high.
- Given all six factors at their maximum (1.0), when the score is computed
  with default weights, then the total is 1.0.
- Given custom weights configured in apriori.config.yaml, when scores are
  computed, then the custom weights are used.
"""

from __future__ import annotations

import pytest

from apriori.config import DEFAULT_BASE_PRIORITIES, load_config
from apriori.quality.priority import BasePriorityEngine


# ---------------------------------------------------------------------------
# Helper: isolate one factor by zeroing out all others
# ---------------------------------------------------------------------------

def _zero_inputs() -> dict:
    """Return inputs that produce 0.0 for all factors."""
    return {
        "coverage_gap": 0.0,
        "concept_labels": set(),       # no needs-review
        "graph_distance": 999,          # far → proximity = 0
        "git_commit_count": 0,          # no activity
        "days_since_verified": 0.0,     # just verified → not stale
        "failure_count": 0,             # no failures
    }


# ---------------------------------------------------------------------------
# AC1: coverage_gap = 1.0 with default weights → contributes 0.15
# ---------------------------------------------------------------------------


def test_coverage_gap_factor_contributes_correct_weight() -> None:
    """Given investigate_file with coverage_gap=1.0 and default weights,
    when the score is computed, then the coverage_gap factor contributes 0.15."""
    engine = BasePriorityEngine(weights=DEFAULT_BASE_PRIORITIES.copy())
    inputs = _zero_inputs()
    inputs["coverage_gap"] = 1.0

    score = engine.compute(**inputs)

    # Only coverage_gap is non-zero → score == coverage_gap_weight * 1.0
    assert score == pytest.approx(DEFAULT_BASE_PRIORITIES["coverage_gap"], abs=1e-9)
    assert score == pytest.approx(0.15, abs=1e-9)


def test_coverage_gap_factor_is_proportional() -> None:
    """coverage_gap=0.5 contributes exactly half the weight."""
    engine = BasePriorityEngine(weights=DEFAULT_BASE_PRIORITIES.copy())
    inputs = _zero_inputs()
    inputs["coverage_gap"] = 0.5

    score = engine.compute(**inputs)

    assert score == pytest.approx(0.15 * 0.5, abs=1e-9)


def test_coverage_gap_zero_contributes_nothing() -> None:
    """coverage_gap=0.0 contributes 0 to the score."""
    engine = BasePriorityEngine(weights=DEFAULT_BASE_PRIORITIES.copy())
    score = engine.compute(**_zero_inputs())
    assert score == pytest.approx(0.0, abs=1e-9)


# ---------------------------------------------------------------------------
# AC2: needs-review label → contributes 0.20
# ---------------------------------------------------------------------------


def test_needs_review_label_contributes_correct_weight() -> None:
    """Given a concept labeled needs-review, when the score is computed,
    then the needs_review factor contributes 0.20."""
    engine = BasePriorityEngine(weights=DEFAULT_BASE_PRIORITIES.copy())
    inputs = _zero_inputs()
    inputs["concept_labels"] = {"needs-review"}

    score = engine.compute(**inputs)

    assert score == pytest.approx(DEFAULT_BASE_PRIORITIES["needs_review"], abs=1e-9)
    assert score == pytest.approx(0.20, abs=1e-9)


def test_needs_review_absent_contributes_nothing() -> None:
    """Concept without needs-review label contributes 0 for that factor."""
    engine = BasePriorityEngine(weights=DEFAULT_BASE_PRIORITIES.copy())
    inputs = _zero_inputs()
    inputs["concept_labels"] = {"verified", "stable"}

    score = engine.compute(**inputs)

    assert score == pytest.approx(0.0, abs=1e-9)


def test_needs_review_factor_is_binary() -> None:
    """needs_review factor is exactly 1.0 when label present, 0.0 otherwise."""
    engine = BasePriorityEngine(weights=DEFAULT_BASE_PRIORITIES.copy())

    with_label = engine._compute_needs_review({"needs-review", "other"})
    without_label = engine._compute_needs_review({"verified"})
    empty = engine._compute_needs_review(set())

    assert with_label == pytest.approx(1.0)
    assert without_label == pytest.approx(0.0)
    assert empty == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# AC3: graph distance = 1 → developer_proximity factor is high
# ---------------------------------------------------------------------------


def test_developer_proximity_is_high_at_distance_1() -> None:
    """Given a work item near recently-modified files (graph distance = 1),
    when the score is computed, then the developer_proximity factor is high."""
    engine = BasePriorityEngine(weights=DEFAULT_BASE_PRIORITIES.copy())

    proximity = engine._compute_developer_proximity(graph_distance=1)

    # "High" means clearly above the midpoint
    assert proximity > 0.5


def test_developer_proximity_is_max_at_distance_0() -> None:
    """Concept on a recently-modified file (distance=0) gives maximum proximity."""
    engine = BasePriorityEngine(weights=DEFAULT_BASE_PRIORITIES.copy())
    proximity = engine._compute_developer_proximity(graph_distance=0)
    assert proximity == pytest.approx(1.0)


def test_developer_proximity_decreases_with_distance() -> None:
    """Proximity decreases monotonically as graph distance increases."""
    engine = BasePriorityEngine(weights=DEFAULT_BASE_PRIORITIES.copy())
    proximities = [engine._compute_developer_proximity(d) for d in range(6)]
    for i in range(len(proximities) - 1):
        assert proximities[i] >= proximities[i + 1]


def test_developer_proximity_is_nonnegative() -> None:
    """Proximity is always ≥ 0 even for very large distances."""
    engine = BasePriorityEngine(weights=DEFAULT_BASE_PRIORITIES.copy())
    assert engine._compute_developer_proximity(100) >= 0.0


def test_developer_proximity_contributes_to_score() -> None:
    """developer_proximity factor integrates correctly into composite score."""
    engine = BasePriorityEngine(weights=DEFAULT_BASE_PRIORITIES.copy())

    # Score with distance=0 (max proximity) vs far distance (zero proximity)
    inputs_near = _zero_inputs()
    inputs_near["graph_distance"] = 0

    inputs_far = _zero_inputs()
    # graph_distance=999 already set by _zero_inputs

    score_near = engine.compute(**inputs_near)
    score_far = engine.compute(**inputs_far)

    # Near score includes the full developer_proximity weight (0.25)
    assert score_near > score_far
    assert score_near == pytest.approx(DEFAULT_BASE_PRIORITIES["developer_proximity"])


# ---------------------------------------------------------------------------
# AC4: all six factors at maximum → total is 1.0
# ---------------------------------------------------------------------------


def test_all_factors_at_maximum_total_is_1_0() -> None:
    """Given all six factors at their maximum (1.0), when the score is computed
    with default weights, then the total is 1.0."""
    engine = BasePriorityEngine(
        weights=DEFAULT_BASE_PRIORITIES.copy(),
        max_commits=10,
        max_staleness_days=30.0,
        max_failures=5,
        max_distance=5,
    )
    score = engine.compute(
        coverage_gap=1.0,
        concept_labels={"needs-review"},   # needs_review = 1.0
        graph_distance=0,                   # developer_proximity = 1.0
        git_commit_count=10,                # git_activity = 1.0 (= max_commits)
        days_since_verified=30.0,           # staleness = 1.0 (= max_staleness_days)
        failure_count=5,                    # failure_urgency = 1.0 (= max_failures)
    )
    assert score == pytest.approx(1.0, abs=1e-6)


def test_all_factors_at_zero_total_is_0() -> None:
    """Given all factors at zero, score is 0.0."""
    engine = BasePriorityEngine(weights=DEFAULT_BASE_PRIORITIES.copy())
    score = engine.compute(**_zero_inputs())
    assert score == pytest.approx(0.0, abs=1e-9)


# ---------------------------------------------------------------------------
# Individual factor normalization — each normalized to [0, 1]
# ---------------------------------------------------------------------------


class TestGitActivityNormalization:
    """git_activity is normalized commit count over a configurable window."""

    def test_zero_commits_gives_zero_activity(self) -> None:
        engine = BasePriorityEngine(weights={}, max_commits=10)
        assert engine._compute_git_activity(0) == pytest.approx(0.0)

    def test_commits_at_cap_give_max_activity(self) -> None:
        engine = BasePriorityEngine(weights={}, max_commits=10)
        assert engine._compute_git_activity(10) == pytest.approx(1.0)

    def test_commits_above_cap_are_clamped(self) -> None:
        engine = BasePriorityEngine(weights={}, max_commits=10)
        assert engine._compute_git_activity(100) == pytest.approx(1.0)

    def test_commits_proportional_below_cap(self) -> None:
        engine = BasePriorityEngine(weights={}, max_commits=10)
        assert engine._compute_git_activity(5) == pytest.approx(0.5)


class TestStalenessNormalization:
    """staleness is normalized days-since-verified over a configurable window."""

    def test_never_verified_is_maximally_stale(self) -> None:
        engine = BasePriorityEngine(weights={}, max_staleness_days=30.0)
        assert engine._compute_staleness(None) == pytest.approx(1.0)

    def test_zero_days_is_not_stale(self) -> None:
        engine = BasePriorityEngine(weights={}, max_staleness_days=30.0)
        assert engine._compute_staleness(0.0) == pytest.approx(0.0)

    def test_max_staleness_days_gives_one(self) -> None:
        engine = BasePriorityEngine(weights={}, max_staleness_days=30.0)
        assert engine._compute_staleness(30.0) == pytest.approx(1.0)

    def test_beyond_max_is_clamped(self) -> None:
        engine = BasePriorityEngine(weights={}, max_staleness_days=30.0)
        assert engine._compute_staleness(60.0) == pytest.approx(1.0)

    def test_proportional_within_window(self) -> None:
        engine = BasePriorityEngine(weights={}, max_staleness_days=30.0)
        assert engine._compute_staleness(15.0) == pytest.approx(0.5)


class TestFailureUrgencyNormalization:
    """failure_urgency is normalized failure count."""

    def test_zero_failures_gives_zero_urgency(self) -> None:
        engine = BasePriorityEngine(weights={}, max_failures=5)
        assert engine._compute_failure_urgency(0) == pytest.approx(0.0)

    def test_max_failures_gives_one(self) -> None:
        engine = BasePriorityEngine(weights={}, max_failures=5)
        assert engine._compute_failure_urgency(5) == pytest.approx(1.0)

    def test_above_max_is_clamped(self) -> None:
        engine = BasePriorityEngine(weights={}, max_failures=5)
        assert engine._compute_failure_urgency(50) == pytest.approx(1.0)

    def test_proportional_within_cap(self) -> None:
        engine = BasePriorityEngine(weights={}, max_failures=4)
        assert engine._compute_failure_urgency(2) == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# AC5: custom weights from config
# ---------------------------------------------------------------------------


def test_custom_weights_override_defaults() -> None:
    """Given custom weights, the engine uses them instead of defaults."""
    custom_weights = {
        "coverage_gap": 0.5,
        "needs_review": 0.5,
        "developer_proximity": 0.0,
        "git_activity": 0.0,
        "staleness": 0.0,
        "failure_urgency": 0.0,
    }
    engine = BasePriorityEngine(weights=custom_weights)

    score = engine.compute(
        coverage_gap=1.0,
        concept_labels={"needs-review"},
        graph_distance=999,  # proximity → 0
        git_commit_count=0,
        days_since_verified=0.0,
        failure_count=0,
    )
    # 0.5 * 1.0 + 0.5 * 1.0 = 1.0
    assert score == pytest.approx(1.0, abs=1e-6)


def test_from_config_uses_config_weights() -> None:
    """BasePriorityEngine.from_config reads base_priority_weights from Config."""
    config = load_config(None)  # default config
    engine = BasePriorityEngine.from_config(config)

    # Should produce the same result as constructing with DEFAULT_BASE_PRIORITIES
    engine_default = BasePriorityEngine(weights=DEFAULT_BASE_PRIORITIES.copy())

    inputs = dict(
        coverage_gap=0.5,
        concept_labels={"needs-review"},
        graph_distance=2,
        git_commit_count=3,
        days_since_verified=10.0,
        failure_count=1,
    )
    assert engine.compute(**inputs) == pytest.approx(engine_default.compute(**inputs))


def test_custom_weight_for_single_factor() -> None:
    """A single factor with weight 1.0 and all others 0.0 isolates that factor."""
    for factor_name in DEFAULT_BASE_PRIORITIES:
        weights = {k: 0.0 for k in DEFAULT_BASE_PRIORITIES}
        weights[factor_name] = 1.0
        engine = BasePriorityEngine(weights=weights)

        # All inputs that maximize all factors
        score = engine.compute(
            coverage_gap=1.0,
            concept_labels={"needs-review"},
            graph_distance=0,
            git_commit_count=100,
            days_since_verified=100.0,
            failure_count=100,
        )
        # With only one factor weighted, score should be the max factor value (1.0)
        assert score == pytest.approx(1.0, abs=1e-6), (
            f"With only {factor_name}=1.0 and inputs at max, score should be 1.0"
        )


# ---------------------------------------------------------------------------
# Score is bounded [0, 1]
# ---------------------------------------------------------------------------


def test_score_is_bounded_between_0_and_1_with_default_weights() -> None:
    """Score is always within [0, 1] for valid inputs with default weights."""
    engine = BasePriorityEngine(weights=DEFAULT_BASE_PRIORITIES.copy())

    test_cases = [
        # (coverage_gap, labels, dist, commits, days_verified, failures)
        (0.0, set(), 999, 0, 0.0, 0),
        (1.0, {"needs-review"}, 0, 100, 100.0, 100),
        (0.5, {"needs-review"}, 2, 5, 15.0, 2),
        (0.0, set(), 1, 0, 0.0, 1),
    ]
    for cg, labels, dist, commits, days, failures in test_cases:
        score = engine.compute(
            coverage_gap=cg,
            concept_labels=labels,
            graph_distance=dist,
            git_commit_count=commits,
            days_since_verified=days,
            failure_count=failures,
        )
        assert 0.0 <= score <= 1.0 + 1e-9, f"score {score} out of bounds for inputs {(cg, labels, dist, commits, days, failures)}"
