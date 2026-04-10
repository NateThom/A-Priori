"""Tests for Story 10.1: Loop Execution and Iteration Workflow.

AC traceability:
AC-1: Given unresolved work items, when run --iterations 3, then exactly 3 iterations run
      (or fewer if the queue empties).
AC-2: Given an iteration, when the 10-step sequence completes, then work item selected,
      code read, LLM called, L1+L1.5 pass, knowledge integrated, item resolved.
AC-3: Given L1 failure, when handled, then FailureRecord written and loop continues.
AC-4: Given L1.5 failure, when handled, then FailureRecord with co-regulation feedback written.
AC-5: Given prior failure records, when item selected for retry, then prompt includes
      failure history and co-regulation feedback.
AC-6: Given empty queue, when loop starts, then logs "No unresolved work items" and exits.
AC-7: Given each iteration, when it completes, then no state is carried to the next iteration.
AC-8: Given iteration completion, when iteration ends, then librarian_activity record written.
AC-9: Given librarian run start, when orchestrator initializes, then pre-run hook invoked.
AC-10: Tested in test_reference_resolver.py.
AC-11: Given old resolved items beyond retention policy, when loop initializes, items deleted.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from apriori.adapters.base import AnalysisResult, ModelInfo
from apriori.config import Config, QualityCoRegulationConfig, QualityConfig
from apriori.models.concept import Concept
from apriori.models.impact import ImpactProfile
from apriori.models.librarian_activity import LibrarianActivity
from apriori.models.work_item import FailureRecord, WorkItem
from apriori.storage.sqlite_store import SQLiteStore


# ---------------------------------------------------------------------------
# Helpers
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

_FAILING_LEVEL15_JSON = json.dumps({
    "specificity": 0.2,
    "structural_corroboration": 0.1,
    "completeness": 0.3,
    "composite_pass": False,
    "feedback": (
        "The description does not mention the UPSERT pattern or the "
        "JSON serialization of labels. The StorageError wrapping is also absent."
    ),
})


def _make_adapter(responses: list[str]) -> MagicMock:
    """Create a mock LLM adapter that returns responses in sequence."""
    adapter = MagicMock()
    adapter.get_model_info.return_value = ModelInfo(
        name="test-model",
        provider="test",
        context_window=100000,
        cost_per_token=0.0,
    )
    adapter.get_token_count.return_value = 100
    call_count = [0]

    async def _analyze(prompt: str, context: str) -> AnalysisResult:
        idx = min(call_count[0], len(responses) - 1)
        call_count[0] += 1
        return AnalysisResult(
            content=responses[idx],
            model_name="test-model",
            tokens_used=100,
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
    failure_records: Optional[list[FailureRecord]] = None,
) -> WorkItem:
    item = WorkItem(
        item_type="investigate_file",
        concept_id=concept.id,
        description=f"Investigate {concept.name}",
        file_path=file_path,
        failure_records=failure_records or [],
        failure_count=len(failure_records) if failure_records else 0,
    )
    return store.create_work_item(item)


def _make_config(co_regulation_enabled: bool = False) -> Config:
    return Config(
        quality=QualityConfig(
            co_regulation=QualityCoRegulationConfig(enabled=co_regulation_enabled)
        )
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "test_loop.db"


@pytest.fixture
def store(db_path: Path) -> SQLiteStore:
    return SQLiteStore(db_path)


@pytest.fixture
def config() -> Config:
    return _make_config(co_regulation_enabled=False)


# ---------------------------------------------------------------------------
# AC-1: Iteration count limit
# ---------------------------------------------------------------------------

class TestIterationCountLimit:
    """AC-1: Given unresolved work items, when run --iterations N, exactly N iterations
    run (or fewer if the queue empties)."""

    @pytest.mark.asyncio
    async def test_runs_exactly_n_iterations_when_queue_has_enough_items(
        self, store: SQLiteStore, config: Config
    ):
        """Given 5 work items and iterations=3, exactly 3 iterations run."""
        from apriori.librarian.loop import LibrarianLoop

        for i in range(5):
            concept = _make_concept(store, name=f"Concept{i}")
            _make_work_item(store, concept)

        adapter = _make_adapter([_VALID_ANALYSIS_JSON] * 10)
        loop = LibrarianLoop(store, adapter, config)
        records, _ = await loop.run(iterations=3)

        assert len(records) == 3

    @pytest.mark.asyncio
    async def test_run_orchestrates_iterations_via_asyncio_gather(
        self, store: SQLiteStore, config: Config
    ):
        """Technical note: run() uses asyncio.gather() for iteration orchestration."""
        from apriori.librarian.loop import LibrarianLoop
        import apriori.librarian.loop as loop_module

        for i in range(3):
            concept = _make_concept(store, name=f"GatherConcept{i}")
            _make_work_item(store, concept)

        adapter = _make_adapter([_VALID_ANALYSIS_JSON] * 3)
        loop = LibrarianLoop(store, adapter, config)

        gather_calls: list[int] = []
        original_gather = loop_module.asyncio.gather

        async def _wrapped_gather(*args, **kwargs):
            gather_calls.append(len(args))
            return await original_gather(*args, **kwargs)

        with patch.object(loop_module.asyncio, "gather", new=_wrapped_gather):
            records, _ = await loop.run(iterations=3)

        assert len(records) == 3
        assert gather_calls, "run() should invoke asyncio.gather"
        assert gather_calls[0] >= 1

    @pytest.mark.asyncio
    async def test_stops_early_when_queue_empties(
        self, store: SQLiteStore, config: Config
    ):
        """Given 2 work items and iterations=5, only 2 iterations run (queue empties)."""
        from apriori.librarian.loop import LibrarianLoop

        for i in range(2):
            concept = _make_concept(store, name=f"Concept{i}")
            _make_work_item(store, concept)

        adapter = _make_adapter([_VALID_ANALYSIS_JSON] * 10)
        loop = LibrarianLoop(store, adapter, config)
        records, _ = await loop.run(iterations=5)

        assert len(records) == 2


# ---------------------------------------------------------------------------
# AC-2: Successful iteration end-to-end
# ---------------------------------------------------------------------------

class TestSuccessfulIteration:
    """AC-2: Given a successful 10-step sequence, work item selected, code read, LLM called,
    L1+L1.5 pass, knowledge integrated, item resolved."""

    @pytest.mark.asyncio
    async def test_work_item_resolved_after_successful_iteration(
        self, store: SQLiteStore, config: Config, tmp_path: Path
    ):
        """Given a work item, when iteration succeeds, then item is resolved."""
        from apriori.librarian.loop import LibrarianLoop

        concept = _make_concept(store, name="TestConcept")
        work_item = _make_work_item(store, concept)

        adapter = _make_adapter([_VALID_ANALYSIS_JSON])
        loop = LibrarianLoop(store, adapter, config)
        await loop.run(iterations=1)

        updated = store.get_work_item(work_item.id)
        assert updated.resolved is True
        assert updated.resolved_at is not None

    @pytest.mark.asyncio
    async def test_concept_integrated_after_successful_iteration(
        self, store: SQLiteStore, config: Config
    ):
        """Given a work item, when iteration succeeds, concepts are integrated."""
        from apriori.librarian.loop import LibrarianLoop

        concept = _make_concept(store, name="OtherConcept")
        _make_work_item(store, concept)

        adapter = _make_adapter([_VALID_ANALYSIS_JSON])
        loop = LibrarianLoop(store, adapter, config)
        records, _ = await loop.run(iterations=1)

        assert len(records) == 1
        assert records[0].status == "success"
        assert records[0].concepts_integrated >= 1

    @pytest.mark.asyncio
    async def test_activity_record_has_success_status(
        self, store: SQLiteStore, config: Config
    ):
        """Given success, activity record status is 'success'."""
        from apriori.librarian.loop import LibrarianLoop

        concept = _make_concept(store)
        _make_work_item(store, concept)

        adapter = _make_adapter([_VALID_ANALYSIS_JSON])
        loop = LibrarianLoop(store, adapter, config)
        records, _ = await loop.run(iterations=1)

        assert records[0].status == "success"
        assert records[0].model_used == "test-model"

    @pytest.mark.asyncio
    async def test_llm_adapter_called_once_per_iteration(
        self, store: SQLiteStore, config: Config
    ):
        """Given co_regulation disabled, LLM is called once per iteration."""
        from apriori.librarian.loop import LibrarianLoop

        call_log: list[str] = []

        adapter = MagicMock()
        adapter.get_model_info.return_value = ModelInfo(
            name="test-model", provider="test", context_window=100000, cost_per_token=0.0
        )

        async def _analyze(prompt: str, context: str) -> AnalysisResult:
            call_log.append(prompt)
            return AnalysisResult(
                content=_VALID_ANALYSIS_JSON,
                model_name="test-model",
                tokens_used=100,
                raw_response={},
            )

        adapter.analyze = _analyze

        concept = _make_concept(store)
        _make_work_item(store, concept)

        loop = LibrarianLoop(store, adapter, config)
        await loop.run(iterations=1)

        assert len(call_log) == 1


# ---------------------------------------------------------------------------
# AC-3: Level 1 failure handling
# ---------------------------------------------------------------------------

class TestLevel1Failure:
    """AC-3: Given L1 failure, FailureRecord is written and the loop continues."""

    @pytest.mark.asyncio
    async def test_failure_record_written_on_level1_failure(
        self, store: SQLiteStore, config: Config
    ):
        """Given LLM returns invalid output, Level 1 fails and FailureRecord written."""
        from apriori.librarian.loop import LibrarianLoop

        concept = _make_concept(store)
        work_item = _make_work_item(store, concept)

        # Return unparseable / invalid JSON
        adapter = _make_adapter(["not valid json at all"])
        loop = LibrarianLoop(store, adapter, config)
        records, _ = await loop.run(iterations=1)

        assert records[0].status == "level1_failure"
        updated = store.get_work_item(work_item.id)
        assert updated.failure_count == 1
        assert len(updated.failure_records) == 1

    @pytest.mark.asyncio
    async def test_loop_continues_after_level1_failure(
        self, store: SQLiteStore, config: Config
    ):
        """Given L1 failure on first item, loop continues to process a second item."""
        from apriori.librarian.loop import LibrarianLoop

        concept1 = _make_concept(store, name="Concept1")
        concept2 = _make_concept(store, name="Concept2")
        _make_work_item(store, concept1)
        _make_work_item(store, concept2)

        # First call fails Level 1, second call succeeds
        adapter = _make_adapter(["invalid json", _VALID_ANALYSIS_JSON])
        loop = LibrarianLoop(store, adapter, config)
        records, _ = await loop.run(iterations=2)

        statuses = {r.status for r in records}
        assert "level1_failure" in statuses
        assert "success" in statuses

    @pytest.mark.asyncio
    async def test_work_item_not_resolved_after_level1_failure(
        self, store: SQLiteStore, config: Config
    ):
        """After Level 1 failure, work item remains unresolved."""
        from apriori.librarian.loop import LibrarianLoop

        concept = _make_concept(store)
        work_item = _make_work_item(store, concept)

        adapter = _make_adapter(["invalid json"])
        loop = LibrarianLoop(store, adapter, config)
        await loop.run(iterations=1)

        updated = store.get_work_item(work_item.id)
        assert updated.resolved is False


# ---------------------------------------------------------------------------
# AC-4: Level 1.5 failure handling
# ---------------------------------------------------------------------------

class TestLevel15Failure:
    """AC-4: Given L1.5 failure, FailureRecord with co-regulation feedback written."""

    @pytest.mark.asyncio
    async def test_failure_record_has_reviewer_feedback_on_level15_failure(
        self, store: SQLiteStore
    ):
        """Given L1.5 fails, FailureRecord.reviewer_feedback is populated."""
        from apriori.librarian.loop import LibrarianLoop

        # Enable co-regulation
        config = _make_config(co_regulation_enabled=True)

        concept = _make_concept(store)
        work_item = _make_work_item(store, concept)

        # First call = valid analysis, second call = failing L1.5 review
        adapter = _make_adapter([_VALID_ANALYSIS_JSON, _FAILING_LEVEL15_JSON])
        loop = LibrarianLoop(store, adapter, config)
        records, _ = await loop.run(iterations=1)

        assert records[0].status == "level15_failure"
        updated = store.get_work_item(work_item.id)
        assert updated.failure_count == 1
        fr = updated.failure_records[0]
        assert fr.reviewer_feedback is not None
        assert "UPSERT" in fr.reviewer_feedback or "description" in fr.reviewer_feedback.lower()

    @pytest.mark.asyncio
    async def test_level15_failure_populates_quality_scores(self, store: SQLiteStore):
        """Given L1.5 failure, quality_scores dict is populated in FailureRecord."""
        from apriori.librarian.loop import LibrarianLoop

        config = _make_config(co_regulation_enabled=True)

        concept = _make_concept(store)
        work_item = _make_work_item(store, concept)

        adapter = _make_adapter([_VALID_ANALYSIS_JSON, _FAILING_LEVEL15_JSON])
        loop = LibrarianLoop(store, adapter, config)
        await loop.run(iterations=1)

        updated = store.get_work_item(work_item.id)
        fr = updated.failure_records[0]
        assert fr.quality_scores is not None
        assert "specificity" in fr.quality_scores


# ---------------------------------------------------------------------------
# AC-5: Failure history included in retry prompt
# ---------------------------------------------------------------------------

class TestRetryWithFailureHistory:
    """AC-5: Given prior failure records, prompt includes failure history."""

    @pytest.mark.asyncio
    async def test_prompt_includes_failure_reason_on_retry(
        self, store: SQLiteStore, config: Config
    ):
        """Given a work item with one failure record, the LLM prompt includes it."""
        from apriori.librarian.loop import LibrarianLoop

        concept = _make_concept(store)
        prior_failure = FailureRecord(
            attempted_at=datetime.now(timezone.utc),
            model_used="test-model",
            prompt_template="level1",
            failure_reason="Level 1: empty description",
        )
        work_item = _make_work_item(
            store, concept, failure_records=[prior_failure]
        )

        captured_prompts: list[str] = []

        adapter = MagicMock()
        adapter.get_model_info.return_value = ModelInfo(
            name="test-model", provider="test", context_window=100000, cost_per_token=0.0
        )

        async def _analyze(prompt: str, context: str) -> AnalysisResult:
            captured_prompts.append(prompt)
            return AnalysisResult(
                content=_VALID_ANALYSIS_JSON,
                model_name="test-model",
                tokens_used=100,
                raw_response={},
            )

        adapter.analyze = _analyze

        loop = LibrarianLoop(store, adapter, config)
        await loop.run(iterations=1)

        assert captured_prompts, "LLM should have been called"
        assert "Level 1: empty description" in captured_prompts[0]

    @pytest.mark.asyncio
    async def test_prompt_includes_co_regulation_feedback_on_retry(
        self, store: SQLiteStore, config: Config
    ):
        """Given a prior L1.5 failure record with reviewer_feedback, prompt includes it."""
        from apriori.librarian.loop import LibrarianLoop

        concept = _make_concept(store)
        prior_failure = FailureRecord(
            attempted_at=datetime.now(timezone.utc),
            model_used="test-model",
            prompt_template="level15_co_regulation_v1",
            failure_reason="Level 1.5: co-regulation failed",
            reviewer_feedback="The description is missing the UPSERT pattern details.",
        )
        _make_work_item(store, concept, failure_records=[prior_failure])

        captured_prompts: list[str] = []
        adapter = MagicMock()
        adapter.get_model_info.return_value = ModelInfo(
            name="test-model", provider="test", context_window=100000, cost_per_token=0.0
        )

        async def _analyze(prompt: str, context: str) -> AnalysisResult:
            captured_prompts.append(prompt)
            return AnalysisResult(
                content=_VALID_ANALYSIS_JSON, model_name="test-model",
                tokens_used=100, raw_response={},
            )

        adapter.analyze = _analyze
        loop = LibrarianLoop(store, adapter, config)
        await loop.run(iterations=1)

        assert "UPSERT" in captured_prompts[0] or "feedback" in captured_prompts[0].lower()


# ---------------------------------------------------------------------------
# AC-6: Empty queue — clean exit
# ---------------------------------------------------------------------------

class TestEmptyQueue:
    """AC-6: Given empty queue, loop exits cleanly and logs the message."""

    @pytest.mark.asyncio
    async def test_empty_queue_returns_no_activity_records(
        self, store: SQLiteStore, config: Config
    ):
        """Given no pending work items, run returns an empty list."""
        from apriori.librarian.loop import LibrarianLoop

        adapter = _make_adapter([])
        loop = LibrarianLoop(store, adapter, config)
        records, _ = await loop.run(iterations=5)

        assert records == []

    @pytest.mark.asyncio
    async def test_empty_queue_logs_message(
        self, store: SQLiteStore, config: Config
    ):
        """Given no pending work items, 'No unresolved work items' is logged."""
        import logging

        from apriori.librarian.loop import LibrarianLoop

        adapter = _make_adapter([])
        loop = LibrarianLoop(store, adapter, config)

        with patch("apriori.librarian.loop.logger") as mock_logger:
            await loop.run(iterations=1)
            mock_logger.info.assert_called_once_with("No unresolved work items")


# ---------------------------------------------------------------------------
# AC-7: No state carried between iterations
# ---------------------------------------------------------------------------

class TestNoStateCarried:
    """AC-7: Given each iteration, no state is carried to the next."""

    @pytest.mark.asyncio
    async def test_each_iteration_operates_on_different_work_item(
        self, store: SQLiteStore, config: Config
    ):
        """Given 3 work items, each iteration resolves a different one."""
        from apriori.librarian.loop import LibrarianLoop

        concepts = [_make_concept(store, name=f"C{i}") for i in range(3)]
        work_items = [_make_work_item(store, c) for c in concepts]

        adapter = _make_adapter([_VALID_ANALYSIS_JSON] * 3)
        loop = LibrarianLoop(store, adapter, config)
        records, _ = await loop.run(iterations=3)

        assert len(records) == 3
        # All work items should now be resolved
        for wi in work_items:
            updated = store.get_work_item(wi.id)
            assert updated.resolved is True

    @pytest.mark.asyncio
    async def test_second_iteration_sees_updated_queue(
        self, store: SQLiteStore, config: Config
    ):
        """Given 2 work items, second iteration sees only 1 pending item."""
        from apriori.librarian.loop import LibrarianLoop

        concept1 = _make_concept(store, name="C1")
        concept2 = _make_concept(store, name="C2")
        _make_work_item(store, concept1)
        _make_work_item(store, concept2)

        adapter = _make_adapter([_VALID_ANALYSIS_JSON] * 2)
        loop = LibrarianLoop(store, adapter, config)
        await loop.run(iterations=2)

        # After 2 successful iterations, no pending work items remain
        assert store.get_pending_work_items() == []


# ---------------------------------------------------------------------------
# AC-8: Activity record written after each iteration
# ---------------------------------------------------------------------------

class TestActivityRecordWritten:
    """AC-8: After each iteration, a record is written to the librarian_activity table."""

    @pytest.mark.asyncio
    async def test_activity_record_persisted_in_store(
        self, store: SQLiteStore, config: Config
    ):
        """Given a successful iteration, a LibrarianActivity record exists in the store."""
        from apriori.librarian.loop import LibrarianLoop

        concept = _make_concept(store)
        _make_work_item(store, concept)

        adapter = _make_adapter([_VALID_ANALYSIS_JSON])
        loop = LibrarianLoop(store, adapter, config)
        records, _ = await loop.run(iterations=1)

        stored = store.list_librarian_activities()
        assert len(stored) == 1
        assert stored[0].id == records[0].id

    @pytest.mark.asyncio
    async def test_activity_record_written_even_on_failure(
        self, store: SQLiteStore, config: Config
    ):
        """Given a failed iteration, activity record is still written."""
        from apriori.librarian.loop import LibrarianLoop

        concept = _make_concept(store)
        _make_work_item(store, concept)

        adapter = _make_adapter(["invalid json"])
        loop = LibrarianLoop(store, adapter, config)
        await loop.run(iterations=1)

        stored = store.list_librarian_activities()
        assert len(stored) == 1
        assert stored[0].status == "level1_failure"

    @pytest.mark.asyncio
    async def test_activity_records_grouped_by_run_id(
        self, store: SQLiteStore, config: Config
    ):
        """Given 3 iterations in one run, all activity records share the same run_id."""
        from apriori.librarian.loop import LibrarianLoop

        for i in range(3):
            concept = _make_concept(store, name=f"C{i}")
            _make_work_item(store, concept)

        adapter = _make_adapter([_VALID_ANALYSIS_JSON] * 3)
        loop = LibrarianLoop(store, adapter, config)
        records, _ = await loop.run(iterations=3)

        run_ids = {r.run_id for r in records}
        assert len(run_ids) == 1  # all from same run

        stored = store.list_librarian_activities(run_id=records[0].run_id)
        assert len(stored) == 3


# ---------------------------------------------------------------------------
# AC-9: Pre-run hook invocation
# ---------------------------------------------------------------------------

class TestPreRunHook:
    """AC-9: Given a pre-run hook, it is invoked when the loop initializes."""

    @pytest.mark.asyncio
    async def test_pre_run_hook_called_before_iteration(
        self, store: SQLiteStore, config: Config
    ):
        """Given a pre-run hook, it is called exactly once at the start of a run."""
        from apriori.librarian.loop import LibrarianLoop

        hook_calls: list[int] = []

        def _hook() -> None:
            hook_calls.append(1)

        adapter = _make_adapter([])
        loop = LibrarianLoop(store, adapter, config, pre_run_hook=_hook)
        await loop.run(iterations=3)

        assert hook_calls == [1]

    @pytest.mark.asyncio
    async def test_pre_run_hook_not_required(
        self, store: SQLiteStore, config: Config
    ):
        """Given no pre-run hook, the loop runs without error."""
        from apriori.librarian.loop import LibrarianLoop

        adapter = _make_adapter([])
        loop = LibrarianLoop(store, adapter, config, pre_run_hook=None)
        records, _ = await loop.run(iterations=1)
        assert records == []

    @pytest.mark.asyncio
    async def test_pre_run_enqueues_analyze_impact_for_stale_profiles(
        self, store: SQLiteStore, config: Config
    ):
        """Story 12.5 AC3: pre-run staleness detection enqueues analyze_impact work."""
        from apriori.librarian.loop import LibrarianLoop

        stale_profile = ImpactProfile(
            last_computed=datetime.now(timezone.utc) - timedelta(hours=49)
        )
        store.create_concept(
            Concept(
                name="StaleImpact",
                description="Concept with stale blast-radius profile.",
                created_by="agent",
                impact_profile=stale_profile,
            )
        )

        adapter = _make_adapter([])
        loop = LibrarianLoop(store, adapter, config, pre_run_hook=None)
        await loop.run(iterations=0)

        pending = store.get_pending_work_items()
        analyze_items = [wi for wi in pending if wi.item_type == "analyze_impact"]
        assert len(analyze_items) == 1


# ---------------------------------------------------------------------------
# AC-11: Retention policy — old items deleted on initialization
# ---------------------------------------------------------------------------

class TestRetentionPolicy:
    """AC-11: Given resolved items older than retention_days, they are deleted on init."""

    @pytest.mark.asyncio
    async def test_old_resolved_items_deleted_on_run(
        self, store: SQLiteStore, config: Config
    ):
        """Given a resolved item older than retention_days, it is deleted when run starts."""
        from apriori.librarian.loop import LibrarianLoop

        # Create and resolve a work item
        concept = _make_concept(store, name="OldConcept")
        work_item = _make_work_item(store, concept)
        store.resolve_work_item(work_item.id)

        # Backdate resolved_at to be older than retention_days
        resolved_item = store.get_work_item(work_item.id)
        old_time = datetime.now(timezone.utc) - timedelta(days=config.work_queue.retention_days + 1)
        backdated = resolved_item.model_copy(update={"resolved_at": old_time})
        store.update_work_item(backdated)

        adapter = _make_adapter([])
        loop = LibrarianLoop(store, adapter, config)
        await loop.run(iterations=1)

        # Old resolved item should be gone
        assert store.get_work_item(work_item.id) is None

    @pytest.mark.asyncio
    async def test_fresh_resolved_items_not_deleted(
        self, store: SQLiteStore, config: Config
    ):
        """Given a recently resolved item, it is NOT deleted when run starts."""
        from apriori.librarian.loop import LibrarianLoop

        concept = _make_concept(store, name="FreshConcept")
        work_item = _make_work_item(store, concept)
        store.resolve_work_item(work_item.id)

        adapter = _make_adapter([])
        loop = LibrarianLoop(store, adapter, config)
        await loop.run(iterations=1)

        # Recently resolved item should still be present
        assert store.get_work_item(work_item.id) is not None
