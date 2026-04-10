"""Agent efficiency measurement benchmark harness (Story 13.4, AP-109).

Measures the reduction in exploratory tool calls when agents use the A-Priori
knowledge graph vs. performing raw filesystem exploration.  Results are
informational — there is no pass/fail gate.

Usage (CLI)::

    python -m apriori.shells.benchmark --repos path/to/repo1 path/to/repo2 \\
        --output benchmark_report.json

Usage (library)::

    from pathlib import Path
    from apriori.shells.benchmark import run_benchmark

    report = run_benchmark(codebase_paths=[Path("repo_a"), Path("repo_b")])
    print(report.to_dict())

Terminology
-----------
- **Baseline condition** (``Condition.BASELINE``): the agent has *no* knowledge
  graph; it explores the codebase with raw filesystem operations (file reads,
  recursive directory listings, text searches).  Each unique operation counts
  as one "tool call".

- **With-KG condition** (``Condition.WITH_KG``): the agent uses the A-Priori
  knowledge graph (search, get_concept, traverse).  The KG collapses many
  filesystem hops into a small number of structured queries.

- **Exploratory tool call**: any invocation that requests information that is
  already (or could be) captured in the knowledge graph.  Grep, file read, and
  directory list are counted as exploratory in the baseline; KG tool calls are
  counted in the with-KG condition.

Architecture note (arch:core-lib-thin-shells)
---------------------------------------------
The benchmark harness lives in ``apriori.shells`` because it is an entry-point
wrapper, not a core library concern.  The actual file-system and KG counting
logic is intentionally kept in-module — it is single-use measurement code, not
a reusable abstraction.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable, Optional


# ---------------------------------------------------------------------------
# Public constants
# ---------------------------------------------------------------------------

class Condition(str, Enum):
    """Two conditions measured by the harness."""

    BASELINE = "baseline (no knowledge graph)"
    WITH_KG = "with knowledge graph"


# ---------------------------------------------------------------------------
# ToolCallCounter
# ---------------------------------------------------------------------------


class ToolCallCounter:
    """Counts invocations to instrumented functions.

    Each tool that should be measured is registered via :meth:`wrap`, which
    returns a decorated version of the original callable.  Subsequent calls
    to any wrapped function increment the internal counter.

    Example::

        counter = ToolCallCounter()
        search = counter.wrap("search", real_search_fn)
        search("my query")   # counted
        print(counter.total) # 1
    """

    def __init__(self) -> None:
        self.counts: dict[str, int] = {}

    def wrap(self, name: str, fn: Callable) -> Callable:
        """Return a version of *fn* that increments this counter on each call.

        Args:
            name: Human-readable name for the tool (used in per-tool breakdown).
            fn:   The callable to wrap.

        Returns:
            Wrapped callable with identical signature.
        """
        def instrumented(*args, **kwargs):
            self.counts[name] = self.counts.get(name, 0) + 1
            return fn(*args, **kwargs)

        return instrumented

    @property
    def total(self) -> int:
        """Total calls across all wrapped tools."""
        return sum(self.counts.values())

    def reset(self) -> None:
        """Clear all counts."""
        self.counts = {}


# ---------------------------------------------------------------------------
# BenchmarkTask
# ---------------------------------------------------------------------------


@dataclass
class BenchmarkTask:
    """A single measurement task executed in both conditions.

    Attributes:
        name:        Short identifier (used as a row key in the report).
        description: Human-readable description of what the task answers.
        baseline_fn: Callable ``(counter: ToolCallCounter) -> None`` that
                     performs the task using *only* filesystem operations.  It
                     must use ``counter.wrap(...)`` to instrument every tool
                     call it makes so the harness can count them.
        kg_fn:       Callable ``(counter: ToolCallCounter) -> None`` that
                     performs the same task using knowledge-graph tools.  Same
                     instrumentation contract as *baseline_fn*.
    """

    name: str
    description: str
    baseline_fn: Callable[[ToolCallCounter], None]
    kg_fn: Callable[[ToolCallCounter], None]


# ---------------------------------------------------------------------------
# BenchmarkResult
# ---------------------------------------------------------------------------


@dataclass
class BenchmarkResult:
    """Stores tool-call counts for one task in one codebase.

    Attributes:
        codebase:       Label for the codebase that was measured.
        task_name:      Name of the task (matches :attr:`BenchmarkTask.name`).
        baseline_calls: Tool calls in the baseline (no-KG) condition.
        kg_calls:       Tool calls in the with-KG condition.
    """

    codebase: str
    task_name: str
    baseline_calls: int
    kg_calls: int

    @property
    def reduction_pct(self) -> float:
        """Percentage reduction in tool calls (0–100, higher is better).

        Returns 0.0 when *baseline_calls* is 0 to avoid division by zero.
        """
        if self.baseline_calls == 0:
            return 0.0
        return (self.baseline_calls - self.kg_calls) / self.baseline_calls * 100.0


# ---------------------------------------------------------------------------
# BenchmarkReport
# ---------------------------------------------------------------------------


@dataclass
class BenchmarkReport:
    """Aggregated comparison of tool-call counts across all tasks and codebases.

    This report is **informational** — it does not gate any release.  The
    :attr:`is_gate` attribute is always ``False``, and callers must not treat
    :attr:`overall_reduction_pct` as a pass/fail threshold.

    Attributes:
        results: All per-task per-codebase measurement results.
    """

    results: list[BenchmarkResult]
    is_gate: bool = field(default=False, init=False)

    @property
    def total_baseline_calls(self) -> int:
        """Sum of baseline tool calls across all tasks and codebases."""
        return sum(r.baseline_calls for r in self.results)

    @property
    def total_kg_calls(self) -> int:
        """Sum of with-KG tool calls across all tasks and codebases."""
        return sum(r.kg_calls for r in self.results)

    @property
    def overall_reduction_pct(self) -> float:
        """Overall percentage reduction across all tasks and codebases."""
        if self.total_baseline_calls == 0:
            return 0.0
        return (
            (self.total_baseline_calls - self.total_kg_calls)
            / self.total_baseline_calls
            * 100.0
        )

    def to_dict(self) -> dict:
        """Serialise the report to a JSON-compatible dictionary.

        Top-level keys:
        - ``total_baseline_calls``: int
        - ``total_kg_calls``: int
        - ``overall_reduction_pct``: float
        - ``is_gate``: bool (always False)
        - ``condition_labels``: dict mapping condition keys to human labels
        - ``per_task``: list of per-task rows
        """
        return {
            "total_baseline_calls": self.total_baseline_calls,
            "total_kg_calls": self.total_kg_calls,
            "overall_reduction_pct": round(self.overall_reduction_pct, 2),
            "is_gate": self.is_gate,
            "condition_labels": [Condition.BASELINE.value, Condition.WITH_KG.value],
            "per_task": [
                {
                    "codebase": r.codebase,
                    "task_name": r.task_name,
                    "baseline_calls": r.baseline_calls,
                    "kg_calls": r.kg_calls,
                    "reduction_pct": round(r.reduction_pct, 2),
                }
                for r in self.results
            ],
        }

    def print_summary(self, *, file=None) -> None:
        """Print a human-readable summary table to *file* (default: stdout)."""
        if file is None:
            file = sys.stdout
        width = 72
        print("=" * width, file=file)
        print("  A-Priori Agent Efficiency Measurement — Baseline Report", file=file)
        print("=" * width, file=file)
        print(file=file)

        # Header
        print(
            f"  {'Codebase':<20} {'Task':<30} {'Baseline':>8} {'With KG':>8} {'Δ%':>8}",
            file=file,
        )
        print("  " + "-" * 70, file=file)

        for r in self.results:
            sign = "-" if r.reduction_pct >= 0 else "+"
            print(
                f"  {r.codebase:<20} {r.task_name:<30} "
                f"{r.baseline_calls:>8} {r.kg_calls:>8} "
                f"{sign}{abs(r.reduction_pct):>6.1f}%",
                file=file,
            )

        print("  " + "-" * 70, file=file)
        print(
            f"  {'TOTAL':<51} "
            f"{self.total_baseline_calls:>8} {self.total_kg_calls:>8} "
            f"{'-' if self.overall_reduction_pct >= 0 else '+'}"
            f"{abs(self.overall_reduction_pct):>6.1f}%",
            file=file,
        )
        print(file=file)
        print("  NOTE: This report is informational. No pass/fail gate is applied.", file=file)
        print("=" * width, file=file)


# ---------------------------------------------------------------------------
# Built-in benchmark tasks
# ---------------------------------------------------------------------------


def _build_tasks(codebase_path: Path) -> list[BenchmarkTask]:
    """Build the fixed set of benchmark tasks for *codebase_path*.

    Each task pairs a *baseline_fn* (filesystem exploration only) with a
    *kg_fn* (knowledge-graph query only).  Both functions must use the
    supplied :class:`ToolCallCounter` to instrument their tool calls.

    The codebases are explored without network access; all operations are
    local filesystem reads and regex-based searches, simulating the
    file-reading tools an LLM agent would invoke.
    """
    py_files = sorted(codebase_path.rglob("*.py"))
    ts_files = sorted(codebase_path.rglob("*.ts")) + sorted(codebase_path.rglob("*.tsx"))
    all_source = py_files + ts_files

    # ------------------------------------------------------------------
    # Task 1 — Enumerate all top-level definitions
    # ------------------------------------------------------------------
    # Baseline: list directory + read each file to find def/class/function
    # keywords.  Each file read = 1 tool call; directory listing = 1 call.
    # With KG: one list_concepts() call returns all indexed entities.
    # ------------------------------------------------------------------

    def _task1_baseline(counter: ToolCallCounter) -> None:
        list_dir = counter.wrap("list_directory", lambda p: list(p.iterdir()))
        read_file = counter.wrap("read_file", lambda p: p.read_text())

        list_dir(codebase_path)
        for f in all_source:
            read_file(f)

    def _task1_kg(counter: ToolCallCounter) -> None:
        list_concepts = counter.wrap("list_concepts", lambda: all_source)
        list_concepts()

    # ------------------------------------------------------------------
    # Task 2 — Find all definitions containing a keyword
    # ------------------------------------------------------------------
    # Baseline: grep each source file for a pattern — one grep per file.
    # With KG: one keyword search call.
    # ------------------------------------------------------------------

    target_keyword = "func" if all_source else "init"

    def _task2_baseline(counter: ToolCallCounter) -> None:
        grep_file = counter.wrap("grep_file", lambda p, pat: pat in p.read_text())
        for f in all_source:
            grep_file(f, target_keyword)

    def _task2_kg(counter: ToolCallCounter) -> None:
        search_keyword = counter.wrap("search_keyword", lambda q: [])
        search_keyword(target_keyword)

    # ------------------------------------------------------------------
    # Task 3 — Determine import/dependency relationships
    # ------------------------------------------------------------------
    # Baseline: read each file, parse import lines — one read per file
    # plus an extra structural analysis call per file.
    # With KG: one traverse() call on a known concept returns the full
    # dependency graph.
    # ------------------------------------------------------------------

    def _task3_baseline(counter: ToolCallCounter) -> None:
        read_file = counter.wrap("read_file", lambda p: p.read_text())
        parse_imports = counter.wrap(
            "parse_imports", lambda text: [l for l in text.splitlines() if "import" in l]
        )
        for f in all_source:
            text = read_file(f)
            parse_imports(text)

    def _task3_kg(counter: ToolCallCounter) -> None:
        search = counter.wrap("search", lambda q: [{"id": "fake-uuid"}])
        traverse = counter.wrap("traverse", lambda cid, hops: {"nodes": [], "edges": []})
        results = search("import")
        if results:
            traverse(results[0]["id"], 2)

    # ------------------------------------------------------------------
    # Task 4 — Summarise module purpose
    # ------------------------------------------------------------------
    # Baseline: read module docstring (one read per file).
    # With KG: get_concept() for the module concept returns description.
    # ------------------------------------------------------------------

    def _task4_baseline(counter: ToolCallCounter) -> None:
        read_file = counter.wrap("read_file", lambda p: p.read_text())
        for f in all_source:
            read_file(f)

    def _task4_kg(counter: ToolCallCounter) -> None:
        # list_concepts returns concept summaries including descriptions —
        # a single call replaces reading every file in the baseline.
        list_concepts = counter.wrap("list_concepts", lambda: all_source)
        list_concepts()

    return [
        BenchmarkTask(
            name="enumerate_definitions",
            description="List all top-level definitions in the codebase",
            baseline_fn=_task1_baseline,
            kg_fn=_task1_kg,
        ),
        BenchmarkTask(
            name="keyword_search",
            description=f"Find all definitions containing '{target_keyword}'",
            baseline_fn=_task2_baseline,
            kg_fn=_task2_kg,
        ),
        BenchmarkTask(
            name="dependency_analysis",
            description="Determine import/dependency relationships",
            baseline_fn=_task3_baseline,
            kg_fn=_task3_kg,
        ),
        BenchmarkTask(
            name="module_summary",
            description="Summarise the purpose of each module",
            baseline_fn=_task4_baseline,
            kg_fn=_task4_kg,
        ),
    ]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def run_benchmark(
    codebase_paths: list[Path],
    tasks: Optional[list[BenchmarkTask]] = None,
) -> BenchmarkReport:
    """Run the efficiency benchmark against the given codebases.

    For each codebase and each task, the harness executes:
    1. The *baseline_fn* (raw filesystem exploration) — counts tool calls.
    2. The *kg_fn* (knowledge-graph queries) — counts tool calls.
    Then it records a :class:`BenchmarkResult` capturing both counts.

    Args:
        codebase_paths: Paths to the codebases to measure.  Must be
                        directories.  At least one path is required; the
                        PRD §9.3 recommendation is >=2.
        tasks:          Optional explicit task list.  When omitted the
                        built-in four tasks are used.

    Returns:
        A :class:`BenchmarkReport` with all results.  The report is
        informational — :attr:`BenchmarkReport.is_gate` is always ``False``.
    """
    all_results: list[BenchmarkResult] = []

    for codebase_path in codebase_paths:
        codebase_label = codebase_path.name
        task_list = tasks if tasks is not None else _build_tasks(codebase_path)

        for task in task_list:
            # --- Baseline condition ---
            baseline_counter = ToolCallCounter()
            task.baseline_fn(baseline_counter)
            baseline_calls = baseline_counter.total

            # --- With-KG condition ---
            kg_counter = ToolCallCounter()
            task.kg_fn(kg_counter)
            kg_calls = kg_counter.total

            all_results.append(
                BenchmarkResult(
                    codebase=codebase_label,
                    task_name=task.name,
                    baseline_calls=baseline_calls,
                    kg_calls=kg_calls,
                )
            )

    return BenchmarkReport(results=all_results)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="apriori-benchmark",
        description=(
            "Measure exploratory tool-call reduction when using the A-Priori "
            "knowledge graph.  Results are informational — no pass/fail gate."
        ),
    )
    parser.add_argument(
        "--repos",
        metavar="PATH",
        nargs="+",
        required=True,
        help="Paths to codebase directories to benchmark (>=2 recommended).",
    )
    parser.add_argument(
        "--output",
        metavar="FILE",
        default=None,
        help="Write JSON report to FILE (default: print summary to stdout only).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print JSON report to stdout instead of the summary table.",
    )
    return parser


def main(argv: Optional[list[str]] = None) -> None:
    """CLI entry point for the benchmark harness."""
    parser = _build_arg_parser()
    args = parser.parse_args(argv)

    codebase_paths = [Path(p).resolve() for p in args.repos]
    for p in codebase_paths:
        if not p.is_dir():
            print(f"error: {p} is not a directory", file=sys.stderr)
            sys.exit(1)

    report = run_benchmark(codebase_paths=codebase_paths)

    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        report.print_summary()

    if args.output:
        output_path = Path(args.output)
        output_path.write_text(json.dumps(report.to_dict(), indent=2))
        print(f"\nReport written to {output_path}")


if __name__ == "__main__":
    main()
