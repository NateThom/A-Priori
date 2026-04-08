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

import json
import logging
import time
import uuid
from typing import Callable, Optional

from apriori.adapters.base import LLMAdapter
from apriori.config import Config
from apriori.knowledge.integrator import IntegrationDecisionTree
from apriori.models.librarian_activity import LibrarianActivity
from apriori.models.librarian_output import LibrarianOutput
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
# Prompt templates
# ---------------------------------------------------------------------------

_ANALYSIS_PROMPT_TEMPLATE = """\
Analyze the following code and identify all key concepts and relationships.

File: {file_path}

```python
{code_content}
```

Instructions:
- Identify all key concepts (classes, functions, modules) with specific, detailed descriptions.
- Descriptions must be at least 50 characters and describe THIS specific code, not generic boilerplate.
- Include specific parameter behaviors, error conditions, and return value semantics.
- Identify relationships between concepts using only these edge types: depends-on, implements, \
relates-to, shares-assumption-about, extends, supersedes, owned-by.
{failure_context}
Respond with valid JSON only (no preamble, no markdown fences):
{{
  "concepts": [
    {{
      "name": "ExactConceptName",
      "description": "Specific description with parameter behaviors and return value semantics",
      "confidence": 0.9,
      "code_references": []
    }}
  ],
  "edges": []
}}"""

_FAILURE_CONTEXT_TEMPLATE = """\

## Previous Analysis Failures (Retry Context)
Address these failures in your analysis — be specific and avoid generic descriptions:
{failures}
"""


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

    async def run(self, iterations: int) -> list[LibrarianActivity]:
        """Execute up to ``iterations`` librarian iterations.

        Stops early if the work queue empties before ``iterations`` is reached.
        Each iteration reads fresh state from the store — no state is carried
        between iterations (arch:librarian-loop).

        Args:
            iterations: Maximum number of iterations to execute.

        Returns:
            A list of :class:`LibrarianActivity` records, one per executed
            iteration (including iterations that ended in quality failures).
            Returns an empty list when the queue is immediately empty.
        """
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
        activity_records: list[LibrarianActivity] = []

        for i in range(iterations):
            # Fresh read — no state from previous iteration (AC-7)
            pending = self._store.get_pending_work_items()

            if not pending:
                logger.info("No unresolved work items")
                break

            work_item = self._select_work_item(pending)
            activity = await self._run_iteration(
                run_id=run_id, iteration=i, work_item=work_item
            )
            activity_records.append(activity)

            # Persist activity record (AC-8)
            self._store.create_librarian_activity(activity)

        return activity_records

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
    ) -> LibrarianActivity:
        """Execute one librarian iteration end-to-end.

        Returns a :class:`LibrarianActivity` record capturing the outcome. The
        record is always returned (and persisted by the caller), even on failure.
        """
        start_time = time.monotonic()
        model_info = self._adapter.get_model_info()

        # Step 1: Load code from disk
        code_content = self._load_code(work_item)

        # Step 2: Build prompt (include failure history on retry — AC-5)
        prompt = self._build_prompt(work_item, code_content)

        # Step 3: LLM analysis call
        try:
            llm_result = await self._adapter.analyze(prompt, context="")
        except Exception as exc:  # noqa: BLE001
            logger.warning("Iteration %d: LLM call failed: %s", iteration, exc)
            return LibrarianActivity(
                run_id=run_id,
                iteration=iteration,
                work_item_id=work_item.id,
                status="error",
                model_used=model_info.name,
                duration_seconds=time.monotonic() - start_time,
                failure_reason=f"LLM call failed: {exc}",
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
            return LibrarianActivity(
                run_id=run_id,
                iteration=iteration,
                work_item_id=work_item.id,
                status="level1_failure",
                model_used=model_info.name,
                duration_seconds=time.monotonic() - start_time,
                failure_reason=level1_result.failure_record.failure_reason,
            )

        # Step 6: Level 1.5 co-regulation review (AC-4)
        concept = self._store.get_concept(work_item.concept_id)
        structural_context = self._build_structural_context(concept)

        assessment = await check_level15(
            librarian_output=level1_result.adjusted_output,
            code_snippet=code_content,
            structural_context=structural_context,
            adapter=self._adapter,
            config=self._config.quality.co_regulation,
        )

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
            return LibrarianActivity(
                run_id=run_id,
                iteration=iteration,
                work_item_id=work_item.id,
                status="level15_failure",
                model_used=model_info.name,
                duration_seconds=time.monotonic() - start_time,
                failure_reason=failure_record.failure_reason,
            )

        # Step 7: Integrate output into knowledge graph
        concepts_integrated, edges_integrated = self._integrate_output(
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
        return LibrarianActivity(
            run_id=run_id,
            iteration=iteration,
            work_item_id=work_item.id,
            status="success",
            concepts_integrated=concepts_integrated,
            edges_integrated=edges_integrated,
            model_used=model_info.name,
            duration_seconds=time.monotonic() - start_time,
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

    def _build_prompt(self, work_item: WorkItem, code_content: str) -> str:
        """Build the LLM analysis prompt for a work item.

        Includes failure history when the work item has prior failure records
        so the LLM can address specific shortcomings on retry (AC-5).
        """
        failure_context = ""
        if work_item.failure_records:
            lines = []
            for i, fr in enumerate(work_item.failure_records):
                line = f"- Attempt {i + 1}: {fr.failure_reason}"
                if fr.reviewer_feedback:
                    line += f" | Reviewer feedback: {fr.reviewer_feedback}"
                lines.append(line)
            failure_context = _FAILURE_CONTEXT_TEMPLATE.format(
                failures="\n".join(lines)
            )

        return _ANALYSIS_PROMPT_TEMPLATE.format(
            file_path=work_item.file_path or "(no file)",
            code_content=code_content or "(no code available)",
            failure_context=failure_context,
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

        Strips markdown code fences if present. Returns an empty dict on JSON
        parse failure so that Level 1's schema check fails gracefully.
        """
        content = content.strip()
        # Strip markdown fences (```json ... ``` or ``` ... ```)
        if content.startswith("```"):
            lines = content.split("\n")
            if lines[-1].startswith("```"):
                content = "\n".join(lines[1:-1])
            else:
                content = "\n".join(lines[1:])
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            return {}

    def _integrate_output(self, output: LibrarianOutput) -> tuple[int, int]:
        """Integrate concepts and edges from approved librarian output.

        Returns:
            A ``(concepts_integrated, edges_integrated)`` tuple.
        """
        name_to_id: dict[str, uuid.UUID] = {}
        concepts_integrated = 0

        for cp in output.concepts:
            result = self._integration_tree.integrate_concept(cp.name, cp.description)
            name_to_id[cp.name] = result.concept.id
            concepts_integrated += 1

        edges_integrated = 0
        if output.edges:
            # Build a full name→id map for concepts already in the graph
            all_concepts = {c.name: c.id for c in self._store.list_concepts()}
            name_to_id = {**all_concepts, **name_to_id}  # batch takes priority

            for ep in output.edges:
                source_id = name_to_id.get(ep.source_name)
                target_id = name_to_id.get(ep.target_name)
                if source_id and target_id:
                    self._integration_tree.integrate_edge(
                        source_id,
                        target_id,
                        ep.edge_type,
                        ep.evidence_type,
                        ep.confidence,
                    )
                    edges_integrated += 1

        return concepts_integrated, edges_integrated
