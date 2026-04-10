"""LibrarianLoop — autonomous loop orchestrator (ERD §4.2.1).

Each ``LibrarianLoop.run(iterations)`` call executes up to ``iterations``
isolated iterations of the 10-step sequence:

    1.  Pre-run initialisation: invoke optional hook, delete old work items.
    2.  Re-read pending work queue from store (fresh — no state carried).
    3.  Compute adaptive priority weights via AdaptiveModulator.
    4.  Score every pending item, apply per-item adjustments.
    5.  Select the highest-priority item (exit if queue is empty).
    6.  Load the associated concept and code from disk.
    7.  Build the LLM analysis prompt (include failure history on retry).
    8.  Send prompt to the LLM adapter.
    9.  Run Level 1 consistency checks.
    10. Run Level 1.5 co-regulation review.
        → Integrate approved output; resolve work item.
        → On any failure: record FailureRecord, skip integration, continue.

A ``LibrarianActivity`` record is written to the store at the end of every
iteration regardless of outcome.

Usage::

    from apriori.librarian.loop import LibrarianLoop

    loop = LibrarianLoop(store, adapter, config)
    activities = await loop.run(iterations=10)
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Callable, Optional

from apriori.adapters.base import LLMAdapter
from apriori.config import Config
from apriori.knowledge.integrator import IntegrationAction, IntegrationDecisionTree
from apriori.librarian.budget import TokenBudgetManager
from apriori.librarian.prompt_templates import (
    build_librarian_prompt,
    parse_librarian_response,
)
from apriori.models.librarian_activity import LibrarianActivity
from apriori.models.librarian_output import LibrarianOutput
from apriori.models.run_telemetry import RunTelemetry
from apriori.models.work_item import WorkItem
from apriori.quality.failure_management import (
    failure_record_from_level15,
    record_failure_and_check_escalation,
)
from apriori.quality.level1 import check_level1
from apriori.quality.level15 import check_level15
from apriori.quality.metrics import MetricsEngine
from apriori.quality.modulation import AdaptiveModulator
from apriori.quality.priority import BasePriorityEngine
from apriori.storage.protocol import KnowledgeStore

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# LibrarianLoop
# ---------------------------------------------------------------------------


class LibrarianLoop:
    """Autonomous librarian loop — connects all Phase 2 components (ERD §4.2.1).

    Orchestrates work item selection, code loading, LLM analysis, quality
    validation, and knowledge integration in isolated iterations. No state is
    carried between iterations — each iteration re-reads from the store.

    Args:
        store: KnowledgeStore providing the work queue, concept graph, and
            activity persistence.
        adapter: LLM adapter for analysis and co-regulation calls.
        config: Loaded A-Priori configuration.
        total_source_files: Total source files in the repository; used to
            compute the coverage metric for adaptive modulation. Defaults to 0
            (coverage = 0.0 when unset).
        pre_run_hook: Optional zero-argument callable invoked once at the start
            of ``run()``, before any iterations execute.
    """

    def __init__(
        self,
        store: KnowledgeStore,
        adapter: LLMAdapter,
        config: Config,
        *,
        total_source_files: int = 0,
        pre_run_hook: Optional[Callable[[], None]] = None,
    ) -> None:
        self._store = store
        self._adapter = adapter
        self._config = config
        self._total_source_files = total_source_files
        self._pre_run_hook = pre_run_hook

        self._modulator = AdaptiveModulator(
            base_weights=dict(config.base_priority_weights),
            modulation_strength=config.librarian.modulation_strength,
        )
        self._metrics_engine = MetricsEngine(store)
        self._integration_tree = IntegrationDecisionTree(store)

    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------

    async def run(self, iterations: int) -> tuple[list[LibrarianActivity], RunTelemetry]:
        """Execute up to ``iterations`` librarian iterations.

        Stops early if:
        - The work queue empties before ``iterations`` is reached.
        - The token budget would be exceeded by the next iteration (AC-1).

        Each iteration reads fresh state from the store — no state is carried
        between iterations (arch:librarian-loop).

        Args:
            iterations: Maximum number of iterations to execute.

        Returns:
            A ``(activity_records, telemetry)`` tuple. ``activity_records``
            contains one :class:`LibrarianActivity` per executed iteration
            (including iterations that ended in quality failures). ``telemetry``
            contains aggregated run statistics (AC-5).
        """
        telemetry = RunTelemetry()
        co_reg_enabled = self._config.quality.co_regulation.enabled
        budget_manager = TokenBudgetManager(
            self._config.budget,
            co_regulation_enabled=co_reg_enabled,
        )

        # Pre-run hook (AC-9)
        if self._pre_run_hook is not None:
            self._pre_run_hook()

        # Retention cleanup: delete resolved items beyond retention window (AC-11)
        deleted = self._store.delete_old_work_items(
            days=self._config.work_queue.retention_days
        )
        if deleted:
            logger.debug("Deleted %d old resolved work items", deleted)

        run_id = uuid.uuid4()
        # Quick empty-queue check to preserve the single log event semantics.
        initial_pending = self._store.get_pending_work_items()
        if not initial_pending:
            logger.info("No unresolved work items")
            return [], telemetry

        claimed: set[uuid.UUID] = set()
        lock = asyncio.Lock()
        activity_records: list[LibrarianActivity] = []
        claimed_iterations = 0
        budget_halted = False

        async def _worker() -> None:
            nonlocal claimed_iterations, budget_halted
            while True:
                # Fresh read for every iteration claim (AC-7).
                async with lock:
                    if claimed_iterations >= iterations:
                        return

                    # Budget check before starting next iteration (AC-1).
                    if budget_manager.should_halt_before_iteration():
                        budget_halted = True
                        logger.info(
                            "Token budget halt: %d tokens used, estimated next iteration "
                            "cost would exceed per-run limit of %d tokens.",
                            budget_manager.total_tokens,
                            self._config.budget.max_tokens_per_run,
                        )
                        return

                    pending = self._store.get_pending_work_items()
                    pending = [item for item in pending if item.id not in claimed]
                    if not pending:
                        return

                    work_item = self._select_work_item(pending)
                    claimed.add(work_item.id)
                    iteration = claimed_iterations
                    claimed_iterations += 1

                activity, tokens_used, detail = await self._run_iteration(
                    run_id=run_id, iteration=iteration, work_item=work_item
                )

                async with lock:
                    claimed.discard(work_item.id)
                    activity_records.append(activity)
                    # Persist activity record (AC-8)
                    self._store.create_librarian_activity(activity)
                    # Update budget tracking
                    budget_manager.record_iteration(tokens_used)
                    # Update telemetry
                    telemetry.total_tokens += tokens_used
                    telemetry.total_iterations += 1
                    if activity.status == "success":
                        telemetry.work_items_resolved += 1
                        telemetry.concepts_created += detail.get("concepts_created", 0)
                        telemetry.concepts_updated += detail.get("concepts_updated", 0)
                        telemetry.edges_created += detail.get("edges_created", 0)
                        telemetry.edges_updated += detail.get("edges_updated", 0)
                    elif activity.status in ("level1_failure", "level15_failure", "error"):
                        telemetry.work_items_failed += 1

        concurrency = min(iterations, len(initial_pending))
        tasks = [_worker() for _ in range(concurrency)]
        await asyncio.gather(*tasks)

        # Count escalations from the work items processed this run
        telemetry.work_items_escalated = sum(
            1
            for act in activity_records
            if act.work_item_id is not None
            and self._store.get_work_item(act.work_item_id) is not None
            and self._store.get_work_item(act.work_item_id).escalated
        )

        logger.info(
            "Run complete: %d iterations, %d tokens, %d resolved, %d failed, "
            "%.2f iteration yield.",
            telemetry.total_iterations,
            telemetry.total_tokens,
            telemetry.work_items_resolved,
            telemetry.work_items_failed,
            telemetry.iteration_yield,
        )

        return activity_records, telemetry

    # -------------------------------------------------------------------------
    # Work item selection
    # -------------------------------------------------------------------------

    def _select_work_item(self, pending: list[WorkItem]) -> WorkItem:
        """Score all pending items and return the highest-priority one.

        Applies adaptive modulation to the base priority weights, then scores
        each pending item using :class:`BasePriorityEngine`. Per-item
        adjustments (blast-radius boost, escalation reduction) are applied
        by :class:`AdaptiveModulator`.
        """
        coverage = self._metrics_engine.get_coverage(self._total_source_files)
        freshness = self._metrics_engine.get_freshness()
        blast_radius = self._metrics_engine.get_blast_radius_completeness()

        effective_weights, telemetry = self._modulator.compute_effective_weights(
            coverage=coverage,
            freshness=freshness,
            blast_radius_completeness=blast_radius,
        )

        priority_engine = BasePriorityEngine(weights=effective_weights)

        best_item = pending[0]
        best_score = -1.0

        for item in pending:
            concept = self._store.get_concept(item.concept_id)
            labels: set[str] = concept.labels if concept else set()

            base_score = priority_engine.compute(
                coverage_gap=0.5,
                concept_labels=labels,
                graph_distance=0,
                git_commit_count=0,
                days_since_verified=None,
                failure_count=item.failure_count,
            )
            score = self._modulator.apply_item_score_adjustments(
                base_score=base_score,
                item_type=item.item_type,
                escalated=item.escalated,
                blast_radius_deficit=telemetry.blast_radius_deficit,
            )

            if score > best_score:
                best_score = score
                best_item = item

        return best_item

    # -------------------------------------------------------------------------
    # Single iteration execution
    # -------------------------------------------------------------------------

    async def _run_iteration(
        self,
        run_id: uuid.UUID,
        iteration: int,
        work_item: WorkItem,
    ) -> tuple[LibrarianActivity, int, dict]:
        """Execute one librarian iteration end-to-end.

        Returns:
            A ``(activity, tokens_used, detail)`` tuple. ``activity`` captures
            the iteration outcome. ``tokens_used`` is the total tokens consumed
            (analysis + co-regulation). ``detail`` contains fine-grained counts
            for telemetry (concepts_created, concepts_updated, etc.).
        """
        start_time = time.monotonic()
        model_info = self._adapter.get_model_info()
        tokens_used = 0
        detail: dict = {}

        # Step 1: Load code from disk
        code_content = self._load_code(work_item)
        concept = self._store.get_concept(work_item.concept_id)
        structural_context = self._build_structural_context(concept)

        # Step 2: Build prompt (include failure history on retry — AC-5)
        # Apply per-iteration token limit: truncate graph context if needed (AC-2).
        prompt = self._build_prompt(
            work_item=work_item,
            code_content=code_content,
            structural_context=structural_context,
            provider=model_info.provider,
        )
        prompt = self._maybe_truncate_prompt(
            prompt=prompt,
            code_content=code_content,
            work_item=work_item,
            provider=model_info.provider,
            iteration=iteration,
        )

        # Step 3: LLM analysis call
        try:
            llm_result = await self._adapter.analyze(prompt, context="")
            tokens_used += llm_result.tokens_used
        except Exception as exc:  # noqa: BLE001
            logger.warning("Iteration %d: LLM call failed: %s", iteration, exc)
            return (
                LibrarianActivity(
                    run_id=run_id,
                    iteration=iteration,
                    work_item_id=work_item.id,
                    status="error",
                    model_used=model_info.name,
                    duration_seconds=time.monotonic() - start_time,
                    failure_reason=f"LLM call failed: {exc}",
                ),
                tokens_used,
                detail,
            )

        # Step 4: Parse LLM response
        raw_output = self._parse_llm_output(llm_result.content)

        # Step 5: Level 1 quality checks (AC-3)
        existing_names = frozenset(c.name for c in self._store.list_concepts())
        level1_result = check_level1(raw_output, existing_concept_names=existing_names)

        if not level1_result.passed:
            record_failure_and_check_escalation(
                self._store, work_item.id, level1_result.failure_record
            )
            logger.debug(
                "Iteration %d: Level 1 failure: %s",
                iteration,
                level1_result.failure_record.failure_reason,
            )
            return (
                LibrarianActivity(
                    run_id=run_id,
                    iteration=iteration,
                    work_item_id=work_item.id,
                    status="level1_failure",
                    model_used=model_info.name,
                    duration_seconds=time.monotonic() - start_time,
                    failure_reason=level1_result.failure_record.failure_reason,
                ),
                tokens_used,
                detail,
            )

        # Step 6: Level 1.5 co-regulation review (AC-4).
        # IMPORTANT: the review call is ALWAYS made when co-regulation is enabled,
        # even if doing so would push past the per-run token budget (arch:quality-invariant).
        assessment, coreg_tokens = await check_level15(
            librarian_output=level1_result.adjusted_output,
            code_snippet=code_content,
            structural_context=structural_context,
            adapter=self._adapter,
            config=self._config.quality.co_regulation,
        )
        # co-regulation tokens are charged regardless of outcome (AC-4)
        tokens_used += coreg_tokens

        if not assessment.composite_pass:
            failure_record = failure_record_from_level15(
                assessment=assessment,
                model_used=model_info.name,
                prompt_template="level15_co_regulation_v1",
            )
            record_failure_and_check_escalation(
                self._store, work_item.id, failure_record
            )
            logger.debug(
                "Iteration %d: Level 1.5 failure: %s",
                iteration,
                failure_record.failure_reason,
            )
            return (
                LibrarianActivity(
                    run_id=run_id,
                    iteration=iteration,
                    work_item_id=work_item.id,
                    status="level15_failure",
                    model_used=model_info.name,
                    duration_seconds=time.monotonic() - start_time,
                    failure_reason=failure_record.failure_reason,
                ),
                tokens_used,
                detail,
            )

        # Step 7: Integrate output into knowledge graph
        concepts_integrated, edges_integrated, detail = self._integrate_output(
            level1_result.adjusted_output
        )

        # Step 8: Resolve work item
        self._store.resolve_work_item(work_item.id)

        logger.debug(
            "Iteration %d: success — integrated %d concepts, %d edges",
            iteration,
            concepts_integrated,
            edges_integrated,
        )
        return (
            LibrarianActivity(
                run_id=run_id,
                iteration=iteration,
                work_item_id=work_item.id,
                status="success",
                concepts_integrated=concepts_integrated,
                edges_integrated=edges_integrated,
                model_used=model_info.name,
                duration_seconds=time.monotonic() - start_time,
            ),
            tokens_used,
            detail,
        )

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------

    def _load_code(self, work_item: WorkItem) -> str:
        """Read code content for a work item from disk.

        Returns an empty string when ``work_item.file_path`` is None or the
        file cannot be read.
        """
        if not work_item.file_path:
            return ""
        try:
            with open(work_item.file_path, encoding="utf-8") as f:
                return f.read()
        except OSError:
            return ""

    def _build_prompt(
        self,
        *,
        work_item: WorkItem,
        code_content: str,
        structural_context: str,
        provider: str,
    ) -> str:
        """Build the LLM analysis prompt for a work item.

        Includes failure history when the work item has prior failure records
        so the LLM can address specific shortcomings on retry (AC-5).
        """
        return build_librarian_prompt(
            work_item=work_item,
            code_content=code_content,
            structural_context=structural_context,
            provider=provider,
            with_failure_context=bool(work_item.failure_records),
        )

    def _build_structural_context(self, concept) -> str:
        """Build a structural context string from the concept's graph neighbourhood."""
        if concept is None:
            return ""
        neighbors = self._store.get_neighbors(concept.id)
        if not neighbors:
            return ""
        return f"Graph neighbors of {concept.name}: " + ", ".join(
            n.name for n in neighbors
        )

    @staticmethod
    def _parse_llm_output(content: str) -> dict:
        """Parse the LLM response content to a raw dict for Level 1 validation.

        Accepts plain JSON and JSON in markdown fences, normalizes provider
        response shape, and falls back to text extraction when parsing fails.
        """
        return parse_librarian_response(content)

    def _maybe_truncate_prompt(
        self,
        *,
        prompt: str,
        code_content: str,
        work_item: WorkItem,
        provider: str,
        iteration: int,
    ) -> str:
        """Truncate graph context in ``prompt`` when it exceeds the per-iteration limit.

        Code content and structural code context are preserved. Only the graph
        neighbour context (the ``## Structural context`` section) is reduced to
        fit within ``max_tokens_per_iteration`` (AC-2).

        When no per-iteration limit is configured, the prompt is returned unchanged.
        """
        limit = self._config.budget.max_tokens_per_iteration
        if limit is None:
            return prompt

        token_count = self._adapter.get_token_count(prompt)
        if token_count <= limit:
            return prompt

        # Rebuild with empty structural context to preserve code section (AC-2)
        logger.warning(
            "Iteration %d: prompt is %d tokens (limit %d) — truncating graph context.",
            iteration,
            token_count,
            limit,
        )
        truncated = self._build_prompt(
            work_item=work_item,
            code_content=code_content,
            structural_context="",  # remove graph context
            provider=provider,
        )
        return truncated

    def _integrate_output(self, output: LibrarianOutput) -> tuple[int, int, dict]:
        """Integrate concepts and edges from approved librarian output.

        Returns:
            A ``(concepts_integrated, edges_integrated, detail)`` tuple where
            ``detail`` breaks down counts for telemetry.
        """
        name_to_id: dict[str, uuid.UUID] = {}
        concepts_integrated = 0
        concepts_created = 0
        concepts_updated = 0

        for cp in output.concepts:
            result = self._integration_tree.integrate_concept(cp.name, cp.description)
            name_to_id[cp.name] = result.concept.id
            concepts_integrated += 1
            if result.action == IntegrationAction.CREATED:
                concepts_created += 1
            else:
                concepts_updated += 1

        edges_integrated = 0
        edges_created = 0
        edges_updated = 0
        if output.edges:
            # Build a full name→id map for concepts already in the graph
            all_concepts = {c.name: c.id for c in self._store.list_concepts()}
            name_to_id = {**all_concepts, **name_to_id}  # batch takes priority

            for ep in output.edges:
                source_id = name_to_id.get(ep.source_name)
                target_id = name_to_id.get(ep.target_name)
                if source_id and target_id:
                    edge_result = self._integration_tree.integrate_edge(
                        source_id,
                        target_id,
                        ep.edge_type,
                        ep.evidence_type,
                        ep.confidence,
                    )
                    edges_integrated += 1
                    if edge_result.action == IntegrationAction.EDGE_CREATED:
                        edges_created += 1
                    else:
                        edges_updated += 1

        detail = {
            "concepts_created": concepts_created,
            "concepts_updated": concepts_updated,
            "edges_created": edges_created,
            "edges_updated": edges_updated,
        }
        return concepts_integrated, edges_integrated, detail
