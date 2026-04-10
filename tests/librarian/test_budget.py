"""Tests for Story 10.3: Token Budget Management.

AC traceability:
AC-1: Given a per-run token limit of 100,000 tokens, when cumulative tokens reach 95,000
      and the estimated next iteration cost is 10,000, the loop stops with a message.
AC-2: Given a per-iteration limit of 5,000 tokens, when a prompt exceeds it, the graph
      context is truncated (not the code) to fit, and a warning is logged.
AC-3: Given co-regulation is enabled, when per-iteration cost is estimated, it accounts
      for both the analysis call and the review call.
AC-4: Given co-regulation is enabled and the analysis call completes within budget but the
      review call would exceed it, the review call is still made (never skip quality checks).
AC-5: Given the run completes, telemetry includes: total iterations, total tokens,
      concepts created/updated, edges created/updated, work items resolved/failed/escalated,
      and iteration yield.
"""

from __future__ import annotations

import json
import logging
from collections import deque
from pathlib import Path
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from apriori.adapters.base import AnalysisResult, ModelInfo
from apriori.config import BudgetConfig, Config, QualityCoRegulationConfig, QualityConfig
from apriori.librarian.budget import TokenBudgetManager
from apriori.models.concept import Concept
from apriori.models.run_telemetry import RunTelemetry
from apriori.models.work_item import WorkItem
from apriori.storage.sqlite_store import SQLiteStore


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

_VALID_ANALYSIS_JSON = json.dumps({
    "concepts": [{
        "name": "TestConcept",
        "description": (
            "This function validates user input by checking parameter types, "
            "enforcing minimum length constraints on string fields, and raising "
            "ValueError with descriptive messages when validation fails."
        ),
        "confidence": 0.9,
        "code_references": [],
    }],
    "edges": [],
})

_VALID_LEVEL15_JSON = json.dumps({
    "specificity": 0.9,
    "structural_corroboration": 0.9,
    "completeness": 0.9,
    "composite_pass": True,
    "feedback": "",
})


def _make_adapter(responses: list[str], tokens_per_call: int = 1000) -> MagicMock:
    """Create a mock LLM adapter returning responses in sequence."""
    adapter = MagicMock()
    adapter.get_model_info.return_value = ModelInfo(
        name="test-model",
        provider="test",
        context_window=200000,
        cost_per_token=0.0,
    )
    adapter.get_token_count.return_value = tokens_per_call
    call_count = [0]

    async def _analyze(prompt: str, context: str) -> AnalysisResult:
        idx = min(call_count[0], len(responses) - 1)
        call_count[0] += 1
        return AnalysisResult(
            content=responses[idx],
            model_name="test-model",
            tokens_used=tokens_per_call,
            raw_response={},
        )

    adapter.analyze = _analyze
    return adapter


def _make_concept(store: SQLiteStore, name: str = "TestConcept") -> Concept:
    concept = Concept(
        name=name,
        description=(
            "A well-described concept for testing with specific behavioral details, "
            "parameter constraints, and return value semantics."
        ),
        created_by="agent",
    )
    return store.create_concept(concept)


def _make_work_item(
    store: SQLiteStore,
    concept: Concept,
    file_path: Optional[str] = None,
) -> WorkItem:
    item = WorkItem(
        item_type="investigate_file",
        concept_id=concept.id,
        description=f"Investigate {concept.name}",
        file_path=file_path,
    )
    return store.create_work_item(item)


def _make_config(
    co_regulation_enabled: bool = False,
    max_tokens_per_run: Optional[int] = None,
    max_tokens_per_iteration: Optional[int] = None,
    token_estimation_window: int = 5,
) -> Config:
    return Config(
        quality=QualityConfig(
            co_regulation=QualityCoRegulationConfig(enabled=co_regulation_enabled)
        ),
        budget=BudgetConfig(
            max_tokens_per_run=max_tokens_per_run,
            max_tokens_per_iteration=max_tokens_per_iteration,
            token_estimation_window=token_estimation_window,
        ),
    )


@pytest.fixture
def store(tmp_path: Path) -> SQLiteStore:
    return SQLiteStore(tmp_path / "test_budget.db")


# ---------------------------------------------------------------------------
# Unit tests for TokenBudgetManager
# ---------------------------------------------------------------------------

class TestTokenBudgetManagerUnit:
    """Unit tests for TokenBudgetManager — budget logic in isolation."""

    def test_initial_total_tokens_is_zero(self):
        """A fresh manager has zero cumulative tokens."""
        mgr = TokenBudgetManager(BudgetConfig(), co_regulation_enabled=False)
        assert mgr.total_tokens == 0

    def test_record_iteration_accumulates_tokens(self):
        """Recording iterations accumulates tokens into total."""
        mgr = TokenBudgetManager(BudgetConfig(), co_regulation_enabled=False)
        mgr.record_iteration(1000)
        mgr.record_iteration(2000)
        assert mgr.total_tokens == 3000

    def test_estimate_uses_rolling_average_of_recent_iterations(self):
        """Estimate uses rolling average of the last N iterations."""
        cfg = BudgetConfig(token_estimation_window=3)
        mgr = TokenBudgetManager(cfg, co_regulation_enabled=False)
        mgr.record_iteration(1000)
        mgr.record_iteration(2000)
        mgr.record_iteration(3000)
        # Average of last 3 = 2000
        assert mgr.estimate_next_iteration_cost() == 2000

    def test_estimate_respects_window_size(self):
        """Estimate uses only the most recent N iterations, not all."""
        cfg = BudgetConfig(token_estimation_window=2)
        mgr = TokenBudgetManager(cfg, co_regulation_enabled=False)
        mgr.record_iteration(5000)
        mgr.record_iteration(5000)
        mgr.record_iteration(1000)  # new value enters window
        mgr.record_iteration(1000)  # old 5000s pushed out
        # Window: [1000, 1000], average = 1000
        assert mgr.estimate_next_iteration_cost() == 1000

    def test_estimate_returns_zero_before_any_iterations(self):
        """Before any iteration is recorded, estimate returns 0."""
        mgr = TokenBudgetManager(BudgetConfig(), co_regulation_enabled=False)
        assert mgr.estimate_next_iteration_cost() == 0

    def test_should_halt_when_cumulative_plus_estimated_exceeds_limit(self):
        """should_halt_before_iteration is True when adding estimate would exceed limit."""
        cfg = BudgetConfig(max_tokens_per_run=100000, token_estimation_window=1)
        mgr = TokenBudgetManager(cfg, co_regulation_enabled=False)
        # Seed rolling average: 10000 per iteration
        mgr.record_iteration(10000)
        # Manually advance total to 95000 (by recording more without changing window)
        mgr._total_tokens = 95000
        # estimate = 10000, total + estimate = 105000 > 100000
        assert mgr.should_halt_before_iteration() is True

    def test_should_not_halt_when_within_budget(self):
        """should_halt_before_iteration is False when budget is not exceeded."""
        cfg = BudgetConfig(max_tokens_per_run=100000, token_estimation_window=1)
        mgr = TokenBudgetManager(cfg, co_regulation_enabled=False)
        mgr.record_iteration(5000)
        mgr._total_tokens = 80000
        # estimate = 5000, total + estimate = 85000 < 100000
        assert mgr.should_halt_before_iteration() is False

    def test_should_not_halt_when_no_run_limit_configured(self):
        """should_halt_before_iteration is always False when max_tokens_per_run is None."""
        mgr = TokenBudgetManager(BudgetConfig(), co_regulation_enabled=False)
        mgr.record_iteration(100000)
        mgr._total_tokens = 999999
        assert mgr.should_halt_before_iteration() is False

    def test_co_regulation_doubles_estimate(self):
        """When co-regulation is enabled, cost estimate is doubled."""
        cfg = BudgetConfig(token_estimation_window=1)
        mgr_no_coreg = TokenBudgetManager(cfg, co_regulation_enabled=False)
        mgr_no_coreg.record_iteration(5000)

        mgr_coreg = TokenBudgetManager(cfg, co_regulation_enabled=True)
        mgr_coreg.record_iteration(5000)

        assert mgr_coreg.estimate_next_iteration_cost() == 2 * mgr_no_coreg.estimate_next_iteration_cost()

    def test_check_iteration_limit_returns_true_when_exceeded(self):
        """check_iteration_limit returns True when prompt exceeds per-iteration limit."""
        cfg = BudgetConfig(max_tokens_per_iteration=5000)
        mgr = TokenBudgetManager(cfg, co_regulation_enabled=False)
        assert mgr.check_iteration_limit(6000) is True

    def test_check_iteration_limit_returns_false_when_within_limit(self):
        """check_iteration_limit returns False when prompt is within per-iteration limit."""
        cfg = BudgetConfig(max_tokens_per_iteration=5000)
        mgr = TokenBudgetManager(cfg, co_regulation_enabled=False)
        assert mgr.check_iteration_limit(4999) is False

    def test_check_iteration_limit_always_false_when_no_limit_set(self):
        """check_iteration_limit is always False when max_tokens_per_iteration is None."""
        mgr = TokenBudgetManager(BudgetConfig(), co_regulation_enabled=False)
        assert mgr.check_iteration_limit(999999) is False


# ---------------------------------------------------------------------------
# AC-1: Per-run token limit stops the loop
# ---------------------------------------------------------------------------

class TestPerRunTokenLimit:
    """AC-1: Loop stops when cumulative tokens + estimated next cost exceeds run limit."""

    @pytest.mark.asyncio
    async def test_loop_stops_when_run_token_limit_would_be_exceeded(
        self, store: SQLiteStore
    ):
        """Given a per-run limit of 100000 and 95000 already used, loop stops before
        another iteration whose estimated cost is 10000."""
        from apriori.librarian.loop import LibrarianLoop

        # Create 5 work items — without budget limit all 5 would run
        for i in range(5):
            concept = _make_concept(store, name=f"Concept{i}")
            _make_work_item(store, concept)

        # Each LLM call uses 10000 tokens; limit is 100000
        # After 9 iterations: 90000 tokens used, next estimate = 10000 → 100000 (at limit)
        # After enough iterations to exceed, loop should stop
        config = _make_config(
            max_tokens_per_run=25000,  # after 2 iterations (20000) next estimate=10000 → 30000 > 25000
            token_estimation_window=1,
        )
        adapter = _make_adapter([_VALID_ANALYSIS_JSON] * 10, tokens_per_call=10000)
        loop = LibrarianLoop(store, adapter, config)
        records, _ = await loop.run(iterations=5)

        # Should stop before all 5 are processed
        assert len(records) < 5

    @pytest.mark.asyncio
    async def test_loop_logs_budget_halt_message(self, store: SQLiteStore):
        """Given budget is exhausted, loop logs a message describing the halt."""
        from apriori.librarian.loop import LibrarianLoop

        for i in range(5):
            concept = _make_concept(store, name=f"C{i}")
            _make_work_item(store, concept)

        config = _make_config(
            max_tokens_per_run=15000,  # stops after 1 iteration (10000), next est=10000 → 20000
            token_estimation_window=1,
        )
        adapter = _make_adapter([_VALID_ANALYSIS_JSON] * 10, tokens_per_call=10000)
        loop = LibrarianLoop(store, adapter, config)

        with patch("apriori.librarian.loop.logger") as mock_logger:
            await loop.run(iterations=5)  # noqa: discard telemetry

        # Some info/warning call should mention budget/token
        all_calls = [str(c) for c in mock_logger.info.call_args_list + mock_logger.warning.call_args_list]
        budget_mentions = [c for c in all_calls if "token" in c.lower() or "budget" in c.lower()]
        assert budget_mentions, "Expected a budget-related log message"

    @pytest.mark.asyncio
    async def test_loop_runs_normally_when_no_run_limit_configured(
        self, store: SQLiteStore
    ):
        """Given no per-run token limit, loop runs all requested iterations."""
        from apriori.librarian.loop import LibrarianLoop

        for i in range(3):
            concept = _make_concept(store, name=f"C{i}")
            _make_work_item(store, concept)

        config = _make_config()  # no budget limits
        adapter = _make_adapter([_VALID_ANALYSIS_JSON] * 3, tokens_per_call=100000)
        loop = LibrarianLoop(store, adapter, config)
        records, _ = await loop.run(iterations=3)

        assert len(records) == 3


# ---------------------------------------------------------------------------
# AC-2: Per-iteration truncation
# ---------------------------------------------------------------------------

class TestPerIterationTruncation:
    """AC-2: When prompt exceeds per-iteration limit, graph context is truncated."""

    @pytest.mark.asyncio
    async def test_iteration_runs_with_truncated_context_when_over_limit(
        self, store: SQLiteStore
    ):
        """Given per-iteration limit of 5000 tokens and prompt exceeds it,
        iteration still completes successfully (code not truncated)."""
        from apriori.librarian.loop import LibrarianLoop

        concept = _make_concept(store, name="TestConcept")
        _make_work_item(store, concept)

        # get_token_count returns 6000 (over 5000 limit) for full prompt
        config = _make_config(max_tokens_per_iteration=5000)
        adapter = _make_adapter([_VALID_ANALYSIS_JSON], tokens_per_call=100)
        adapter.get_token_count.side_effect = lambda text: (
            6000 if len(text) > 200 else 100
        )

        loop = LibrarianLoop(store, adapter, config)
        records, _ = await loop.run(iterations=1)

        # Loop should complete despite over-limit prompt
        assert len(records) == 1

    @pytest.mark.asyncio
    async def test_warning_logged_when_prompt_truncated(self, store: SQLiteStore):
        """Given prompt exceeds per-iteration limit, a warning is logged."""
        from apriori.librarian.loop import LibrarianLoop

        concept = _make_concept(store, name="TestConcept")
        _make_work_item(store, concept)

        config = _make_config(max_tokens_per_iteration=5000)
        adapter = _make_adapter([_VALID_ANALYSIS_JSON], tokens_per_call=100)
        adapter.get_token_count.side_effect = lambda text: (
            6000 if len(text) > 200 else 100
        )

        loop = LibrarianLoop(store, adapter, config)

        with patch("apriori.librarian.loop.logger") as mock_logger:
            await loop.run(iterations=1)

        warning_calls = [str(c) for c in mock_logger.warning.call_args_list]
        truncation_warnings = [
            c for c in warning_calls
            if "truncat" in c.lower() or "context" in c.lower() or "token" in c.lower()
        ]
        assert truncation_warnings, "Expected a truncation warning logged"

    @pytest.mark.asyncio
    async def test_code_section_preserved_after_truncation(self, store: SQLiteStore, tmp_path: Path):
        """Given truncation occurs, the code section is preserved in the sent prompt."""
        from apriori.librarian.loop import LibrarianLoop

        concept = _make_concept(store, name="TestConcept")
        code_file = tmp_path / "code.py"
        code_file.write_text("def foo():\n    return 42\n")
        _make_work_item(store, concept, file_path=str(code_file))

        config = _make_config(max_tokens_per_iteration=5000)
        captured_prompts: list[str] = []

        adapter = MagicMock()
        adapter.get_model_info.return_value = ModelInfo(
            name="test-model", provider="test", context_window=200000, cost_per_token=0.0
        )
        call_count = [0]

        def _get_token_count(text: str) -> int:
            # Return large count for full prompt, small for truncated
            return 6000 if "Graph neighbors" in text else 100

        adapter.get_token_count.side_effect = _get_token_count

        async def _analyze(prompt: str, context: str) -> AnalysisResult:
            captured_prompts.append(prompt)
            return AnalysisResult(
                content=_VALID_ANALYSIS_JSON,
                model_name="test-model",
                tokens_used=100,
                raw_response={},
            )

        adapter.analyze = _analyze

        # Create neighbors so structural context is non-empty
        neighbor = _make_concept(store, name="Neighbor")
        from apriori.models.edge import Edge
        edge = Edge(source_id=concept.id, target_id=neighbor.id, edge_type="depends-on", evidence_type="semantic")
        store.create_edge(edge)

        loop = LibrarianLoop(store, adapter, config)
        await loop.run(iterations=1)

        if captured_prompts:
            # Code content must appear in the prompt
            assert "def foo" in captured_prompts[-1] or "return 42" in captured_prompts[-1]


# ---------------------------------------------------------------------------
# AC-3: Co-regulation cost accounting
# ---------------------------------------------------------------------------

class TestCoRegulationCostAccounting:
    """AC-3: When co-regulation is enabled, per-iteration estimate is doubled."""

    def test_co_regulation_doubles_rolling_average_estimate(self):
        """Given co-regulation enabled, estimate_next_iteration_cost is 2x the raw average."""
        cfg = BudgetConfig(token_estimation_window=3)
        mgr_no_coreg = TokenBudgetManager(cfg, co_regulation_enabled=False)
        mgr_coreg = TokenBudgetManager(cfg, co_regulation_enabled=True)

        for tokens in [3000, 4000, 5000]:
            mgr_no_coreg.record_iteration(tokens)
            mgr_coreg.record_iteration(tokens)

        raw_avg = mgr_no_coreg.estimate_next_iteration_cost()
        coreg_est = mgr_coreg.estimate_next_iteration_cost()

        assert coreg_est == raw_avg * 2

    @pytest.mark.asyncio
    async def test_co_regulation_budget_check_uses_doubled_estimate(
        self, store: SQLiteStore
    ):
        """Given co-regulation enabled, budget check uses 2x single-call estimate.
        This means loop stops sooner than without co-regulation."""
        from apriori.librarian.loop import LibrarianLoop

        for i in range(5):
            concept = _make_concept(store, name=f"C{i}")
            _make_work_item(store, concept)

        # Without co-reg: 10000/iter, limit=25000 → stops after 2 iters
        # With co-reg: 20000 estimated/iter, limit=25000 → stops after 1 iter
        config_coreg = _make_config(
            co_regulation_enabled=True,
            max_tokens_per_run=25000,
            token_estimation_window=1,
        )
        config_no_coreg = _make_config(
            co_regulation_enabled=False,
            max_tokens_per_run=25000,
            token_estimation_window=1,
        )

        adapter_coreg = _make_adapter(
            [_VALID_ANALYSIS_JSON, _VALID_LEVEL15_JSON] * 10,
            tokens_per_call=10000,
        )
        adapter_no_coreg = _make_adapter(
            [_VALID_ANALYSIS_JSON] * 10,
            tokens_per_call=10000,
        )

        loop_coreg = LibrarianLoop(store, adapter_coreg, config_coreg)
        records_coreg, _ = await loop_coreg.run(iterations=5)

        # Reset store
        store2 = SQLiteStore(store._db_path.parent / "budget2.db")
        for i in range(5):
            concept = _make_concept(store2, name=f"C{i}")
            _make_work_item(store2, concept)

        loop_no_coreg = LibrarianLoop(store2, adapter_no_coreg, config_no_coreg)
        records_no_coreg, _ = await loop_no_coreg.run(iterations=5)

        # Co-reg loop should stop equal or sooner than non-co-reg
        assert len(records_coreg) <= len(records_no_coreg)


# ---------------------------------------------------------------------------
# AC-4: Co-regulation never skipped to save tokens
# ---------------------------------------------------------------------------

class TestCoRegulationNeverSkipped:
    """AC-4: Review call is always made even if it would push past the budget."""

    @pytest.mark.asyncio
    async def test_review_call_made_even_when_budget_nearly_exhausted(
        self, store: SQLiteStore
    ):
        """Given budget is almost exceeded, the co-regulation review call is still made."""
        from apriori.librarian.loop import LibrarianLoop

        concept = _make_concept(store, name="TestConcept")
        _make_work_item(store, concept)

        # Set budget so analysis call fits but review call would exceed
        # Each call = 10000 tokens, limit = 12000 (analysis ok, review would push to 20000)
        config = _make_config(
            co_regulation_enabled=True,
            max_tokens_per_run=12000,
            token_estimation_window=1,
        )

        review_call_made = [False]

        adapter = MagicMock()
        adapter.get_model_info.return_value = ModelInfo(
            name="test-model", provider="test", context_window=200000, cost_per_token=0.0
        )
        adapter.get_token_count.return_value = 100
        call_count = [0]

        async def _analyze(prompt: str, context: str) -> AnalysisResult:
            call_count[0] += 1
            if call_count[0] == 1:
                # First call: analysis → valid output
                return AnalysisResult(
                    content=_VALID_ANALYSIS_JSON,
                    model_name="test-model",
                    tokens_used=10000,
                    raw_response={},
                )
            else:
                # Second call: co-regulation review
                review_call_made[0] = True
                return AnalysisResult(
                    content=_VALID_LEVEL15_JSON,
                    model_name="test-model",
                    tokens_used=10000,
                    raw_response={},
                )

        adapter.analyze = _analyze

        loop = LibrarianLoop(store, adapter, config)
        await loop.run(iterations=1)

        assert review_call_made[0], (
            "Co-regulation review call must be made even if it would exceed budget"
        )


# ---------------------------------------------------------------------------
# AC-5: End-of-run telemetry
# ---------------------------------------------------------------------------

class TestRunTelemetry:
    """AC-5: When run completes, telemetry includes all required fields."""

    def test_run_telemetry_model_has_required_fields(self):
        """RunTelemetry model has all required AC-5 fields."""
        t = RunTelemetry()
        assert hasattr(t, "total_iterations")
        assert hasattr(t, "total_tokens")
        assert hasattr(t, "concepts_created")
        assert hasattr(t, "concepts_updated")
        assert hasattr(t, "edges_created")
        assert hasattr(t, "edges_updated")
        assert hasattr(t, "work_items_resolved")
        assert hasattr(t, "work_items_failed")
        assert hasattr(t, "work_items_escalated")
        assert hasattr(t, "iteration_yield")

    def test_iteration_yield_is_zero_when_no_iterations(self):
        """iteration_yield is 0.0 when no iterations ran."""
        t = RunTelemetry()
        assert t.iteration_yield == 0.0

    def test_iteration_yield_is_ratio_of_resolved_to_total(self):
        """iteration_yield = work_items_resolved / total_iterations."""
        t = RunTelemetry(total_iterations=4, work_items_resolved=3)
        assert t.iteration_yield == pytest.approx(0.75)

    def test_iteration_yield_is_1_when_all_resolved(self):
        """iteration_yield is 1.0 when all iterations resolved successfully."""
        t = RunTelemetry(total_iterations=5, work_items_resolved=5)
        assert t.iteration_yield == pytest.approx(1.0)

    @pytest.mark.asyncio
    async def test_loop_returns_telemetry_with_correct_totals(
        self, store: SQLiteStore
    ):
        """Given 3 successful iterations, telemetry shows correct counts."""
        from apriori.librarian.loop import LibrarianLoop

        for i in range(3):
            concept = _make_concept(store, name=f"C{i}")
            _make_work_item(store, concept)

        config = _make_config()
        adapter = _make_adapter([_VALID_ANALYSIS_JSON] * 3, tokens_per_call=500)
        loop = LibrarianLoop(store, adapter, config)
        records, telemetry = await loop.run(iterations=3)

        assert isinstance(telemetry, RunTelemetry)
        assert telemetry.total_iterations == 3
        assert telemetry.total_tokens == 3 * 500
        assert telemetry.work_items_resolved == 3
        assert telemetry.work_items_failed == 0
        assert telemetry.iteration_yield == pytest.approx(1.0)

    @pytest.mark.asyncio
    async def test_telemetry_counts_failed_iterations(self, store: SQLiteStore):
        """Given mixed success/failure, telemetry counts failures correctly."""
        from apriori.librarian.loop import LibrarianLoop

        concept1 = _make_concept(store, name="C1")
        concept2 = _make_concept(store, name="C2")
        _make_work_item(store, concept1)
        _make_work_item(store, concept2)

        config = _make_config()
        # First call fails L1, second succeeds
        adapter = _make_adapter(["invalid json", _VALID_ANALYSIS_JSON], tokens_per_call=500)
        loop = LibrarianLoop(store, adapter, config)
        records, telemetry = await loop.run(iterations=2)

        assert telemetry.total_iterations == 2
        assert telemetry.work_items_resolved == 1
        assert telemetry.work_items_failed == 1
        assert telemetry.iteration_yield == pytest.approx(0.5)

    @pytest.mark.asyncio
    async def test_telemetry_counts_concepts_created(self, store: SQLiteStore):
        """Given a successful iteration, telemetry.concepts_created >= 1."""
        from apriori.librarian.loop import LibrarianLoop

        concept = _make_concept(store, name="OtherConcept")
        _make_work_item(store, concept)

        config = _make_config()
        adapter = _make_adapter([_VALID_ANALYSIS_JSON], tokens_per_call=100)
        loop = LibrarianLoop(store, adapter, config)
        records, telemetry = await loop.run(iterations=1)

        assert telemetry.concepts_created >= 1

    @pytest.mark.asyncio
    async def test_telemetry_logged_at_end_of_run(self, store: SQLiteStore):
        """Given run completes, telemetry summary is logged at INFO level."""
        from apriori.librarian.loop import LibrarianLoop

        concept = _make_concept(store, name="C1")
        _make_work_item(store, concept)

        config = _make_config()
        adapter = _make_adapter([_VALID_ANALYSIS_JSON], tokens_per_call=100)
        loop = LibrarianLoop(store, adapter, config)

        with patch("apriori.librarian.loop.logger") as mock_logger:
            await loop.run(iterations=1)

        all_info = [str(c) for c in mock_logger.info.call_args_list]
        telemetry_logs = [
            c for c in all_info
            if "token" in c.lower() or "telemetry" in c.lower() or "iteration" in c.lower()
        ]
        assert telemetry_logs, "Expected telemetry logged at INFO level at end of run"

    @pytest.mark.asyncio
    async def test_empty_run_returns_telemetry(self, store: SQLiteStore):
        """Given no work items, run returns empty records and zero-telemetry."""
        from apriori.librarian.loop import LibrarianLoop

        config = _make_config()
        adapter = _make_adapter([])
        loop = LibrarianLoop(store, adapter, config)
        result = await loop.run(iterations=1)

        # run() should return (records, telemetry) tuple
        assert isinstance(result, tuple)
        records, telemetry = result
        assert records == []
        assert isinstance(telemetry, RunTelemetry)
        assert telemetry.total_iterations == 0
        assert telemetry.total_tokens == 0
