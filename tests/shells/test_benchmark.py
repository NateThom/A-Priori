"""Tests for the agent efficiency measurement benchmark harness (Story 13.4).

Each test traces to a Given/When/Then acceptance criterion from AP-109.

AC 1: Given a small benchmark suite (>=2 representative codebases), when an
      agent performs a set of predefined tasks with and without the knowledge
      graph, then tool-call counts are recorded for both conditions.

AC 2: Given the recorded counts, when the comparison is computed, then a report
      is produced showing total tool calls per condition, per-task breakdown,
      and percentage reduction.

AC 3: Given the report, when the results are reviewed, then they are treated as
      an informational baseline — not a release gate.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable
from unittest.mock import MagicMock, patch

import pytest

from apriori.shells.benchmark import (
    BenchmarkReport,
    BenchmarkResult,
    BenchmarkTask,
    Condition,
    ToolCallCounter,
    run_benchmark,
)


# ---------------------------------------------------------------------------
# ToolCallCounter tests
# ---------------------------------------------------------------------------


class TestToolCallCounter:
    """AC 1 — tool-call counts are recorded for both conditions."""

    def test_counts_calls_to_wrapped_functions(self):
        """Given a function wrapped by the counter, when called N times,
        then count reflects N."""
        counter = ToolCallCounter()

        def fake_search(q: str) -> list:
            return [q]

        wrapped = counter.wrap("search", fake_search)
        wrapped("foo")
        wrapped("bar")
        wrapped("baz")

        assert counter.total == 3

    def test_counts_zero_before_any_calls(self):
        """Given a fresh counter, then total is 0."""
        counter = ToolCallCounter()
        assert counter.total == 0

    def test_multiple_functions_accumulate(self):
        """Given two wrapped functions, when each is called once,
        then total is 2."""
        counter = ToolCallCounter()
        counter.wrap("search", lambda q: [])(q="x")
        counter.wrap("get_concept", lambda cid: None)(cid="y")
        assert counter.total == 2

    def test_per_function_breakdown(self):
        """Given two wrapped functions called different times,
        then per-function counts are correct."""
        counter = ToolCallCounter()
        search = counter.wrap("search", lambda q: [])
        get_concept = counter.wrap("get_concept", lambda cid: None)

        search("a")
        search("b")
        get_concept("x")

        assert counter.counts == {"search": 2, "get_concept": 1}

    def test_reset_clears_counts(self):
        """Given a counter with calls, when reset(), then total is 0."""
        counter = ToolCallCounter()
        counter.wrap("search", lambda q: [])("x")
        assert counter.total == 1
        counter.reset()
        assert counter.total == 0
        assert counter.counts == {}


# ---------------------------------------------------------------------------
# BenchmarkTask tests
# ---------------------------------------------------------------------------


class TestBenchmarkTask:
    """AC 1 — benchmark tasks run in both conditions."""

    def test_task_has_name_and_description(self):
        """Given a task, then it has a human-readable name and description."""
        task = BenchmarkTask(
            name="find_concept",
            description="Locate the definition of a known concept",
            baseline_fn=lambda counter: None,
            kg_fn=lambda counter: None,
        )
        assert task.name == "find_concept"
        assert "concept" in task.description.lower()

    def test_task_baseline_fn_receives_counter(self):
        """Given a task's baseline_fn, when run, it receives a ToolCallCounter."""
        received: list[ToolCallCounter] = []

        task = BenchmarkTask(
            name="t",
            description="d",
            baseline_fn=lambda counter: received.append(counter),
            kg_fn=lambda counter: None,
        )
        counter = ToolCallCounter()
        task.baseline_fn(counter)
        assert len(received) == 1
        assert isinstance(received[0], ToolCallCounter)

    def test_task_kg_fn_receives_counter(self):
        """Given a task's kg_fn, when run, it receives a ToolCallCounter."""
        received: list[ToolCallCounter] = []

        task = BenchmarkTask(
            name="t",
            description="d",
            baseline_fn=lambda counter: None,
            kg_fn=lambda counter: received.append(counter),
        )
        counter = ToolCallCounter()
        task.kg_fn(counter)
        assert len(received) == 1


# ---------------------------------------------------------------------------
# BenchmarkResult tests
# ---------------------------------------------------------------------------


class TestBenchmarkResult:
    """AC 1 — results capture counts per task per condition."""

    def test_result_stores_task_and_counts(self):
        """Given a result, then it stores task name, baseline count, kg count."""
        result = BenchmarkResult(
            codebase="repo_a",
            task_name="find_concept",
            baseline_calls=12,
            kg_calls=3,
        )
        assert result.codebase == "repo_a"
        assert result.task_name == "find_concept"
        assert result.baseline_calls == 12
        assert result.kg_calls == 3

    def test_reduction_percentage_calculated(self):
        """Given baseline=10 and kg=6, then reduction is 40.0%."""
        result = BenchmarkResult(
            codebase="repo_a",
            task_name="t",
            baseline_calls=10,
            kg_calls=6,
        )
        assert result.reduction_pct == pytest.approx(40.0)

    def test_reduction_zero_when_no_improvement(self):
        """Given baseline=5 and kg=5, then reduction is 0%."""
        result = BenchmarkResult(
            codebase="r",
            task_name="t",
            baseline_calls=5,
            kg_calls=5,
        )
        assert result.reduction_pct == pytest.approx(0.0)

    def test_reduction_handles_zero_baseline(self):
        """Given baseline=0, then reduction is 0 (no division by zero)."""
        result = BenchmarkResult(
            codebase="r",
            task_name="t",
            baseline_calls=0,
            kg_calls=0,
        )
        assert result.reduction_pct == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# BenchmarkReport tests  — AC 2
# ---------------------------------------------------------------------------


class TestBenchmarkReport:
    """AC 2 — report shows totals, per-task breakdown, and % reduction."""

    def _make_results(self) -> list[BenchmarkResult]:
        return [
            BenchmarkResult("repo_a", "find_concept", baseline_calls=10, kg_calls=3),
            BenchmarkResult("repo_a", "list_deps", baseline_calls=8, kg_calls=4),
            BenchmarkResult("repo_b", "find_concept", baseline_calls=15, kg_calls=5),
            BenchmarkResult("repo_b", "list_deps", baseline_calls=6, kg_calls=2),
        ]

    def test_report_contains_total_calls_per_condition(self):
        """Given multiple results, when report is built,
        then total baseline and kg counts are present."""
        report = BenchmarkReport(results=self._make_results())
        assert report.total_baseline_calls == 39   # 10+8+15+6
        assert report.total_kg_calls == 14          # 3+4+5+2

    def test_report_contains_per_task_breakdown(self):
        """Given multiple tasks across codebases, when report is built,
        then per-task rows are present."""
        report = BenchmarkReport(results=self._make_results())
        assert len(report.results) == 4
        task_names = {r.task_name for r in report.results}
        assert "find_concept" in task_names
        assert "list_deps" in task_names

    def test_report_overall_reduction_percentage(self):
        """Given totals baseline=39 and kg=14, then overall reduction ≈ 64.1%."""
        report = BenchmarkReport(results=self._make_results())
        expected = (39 - 14) / 39 * 100
        assert report.overall_reduction_pct == pytest.approx(expected, abs=0.1)

    def test_report_is_informational_no_gate(self):
        """AC 3 — report has no pass/fail gate; is_gate is False."""
        report = BenchmarkReport(results=self._make_results())
        assert report.is_gate is False

    def test_report_to_dict_has_required_keys(self):
        """Given a report, when serialised to dict,
        then required top-level keys are present."""
        report = BenchmarkReport(results=self._make_results())
        d = report.to_dict()
        required_keys = {
            "total_baseline_calls",
            "total_kg_calls",
            "overall_reduction_pct",
            "is_gate",
            "per_task",
            "condition_labels",
        }
        assert required_keys.issubset(d.keys())

    def test_report_per_task_in_dict(self):
        """Given a report, when serialised, then per_task has correct structure."""
        report = BenchmarkReport(results=self._make_results())
        d = report.to_dict()
        assert isinstance(d["per_task"], list)
        first = d["per_task"][0]
        assert "codebase" in first
        assert "task_name" in first
        assert "baseline_calls" in first
        assert "kg_calls" in first
        assert "reduction_pct" in first

    def test_condition_labels(self):
        """Given a report, then condition labels describe both conditions."""
        report = BenchmarkReport(results=self._make_results())
        d = report.to_dict()
        assert Condition.BASELINE.value in d["condition_labels"]
        assert Condition.WITH_KG.value in d["condition_labels"]


# ---------------------------------------------------------------------------
# run_benchmark integration test — AC 1 + AC 2
# ---------------------------------------------------------------------------


class TestRunBenchmark:
    """Integration: run_benchmark produces a BenchmarkReport from >=2 codebases."""

    def test_run_benchmark_returns_report(self, tmp_path: Path):
        """Given two synthetic codebases, when run_benchmark is called,
        then a BenchmarkReport is returned."""
        # Create two minimal Python repos
        repo_a = tmp_path / "repo_a"
        repo_b = tmp_path / "repo_b"

        _write_minimal_py_repo(repo_a, module_name="alpha", n_functions=3)
        _write_minimal_py_repo(repo_b, module_name="beta", n_functions=5)

        report = run_benchmark(codebase_paths=[repo_a, repo_b])

        assert isinstance(report, BenchmarkReport)
        assert report.is_gate is False

    def test_run_benchmark_covers_two_or_more_codebases(self, tmp_path: Path):
        """AC 1 — at least 2 representative codebases in results."""
        repo_a = tmp_path / "repo_a"
        repo_b = tmp_path / "repo_b"
        _write_minimal_py_repo(repo_a, "alpha", 2)
        _write_minimal_py_repo(repo_b, "beta", 2)

        report = run_benchmark(codebase_paths=[repo_a, repo_b])

        codebases = {r.codebase for r in report.results}
        assert len(codebases) >= 2

    def test_run_benchmark_has_per_task_results(self, tmp_path: Path):
        """AC 2 — results include a per-task breakdown."""
        repo_a = tmp_path / "repo_a"
        repo_b = tmp_path / "repo_b"
        _write_minimal_py_repo(repo_a, "alpha", 2)
        _write_minimal_py_repo(repo_b, "beta", 2)

        report = run_benchmark(codebase_paths=[repo_a, repo_b])

        assert len(report.results) >= 2  # at least 1 task × 2 codebases

    def test_run_benchmark_baseline_exceeds_kg_calls(self, tmp_path: Path):
        """AC 2 — baseline tool calls >= kg tool calls (KG reduces exploration)."""
        repo_a = tmp_path / "repo_a"
        _write_minimal_py_repo(repo_a, "alpha", 4)

        report = run_benchmark(codebase_paths=[repo_a])

        for result in report.results:
            assert result.baseline_calls >= result.kg_calls, (
                f"Task {result.task_name}: baseline {result.baseline_calls} "
                f"< kg {result.kg_calls}"
            )

    def test_run_benchmark_writes_json_report(self, tmp_path: Path):
        """AC 2 — results can be serialised as a JSON report."""
        repo_a = tmp_path / "repo_a"
        _write_minimal_py_repo(repo_a, "alpha", 2)

        report = run_benchmark(codebase_paths=[repo_a])
        output_path = tmp_path / "benchmark_report.json"
        output_path.write_text(json.dumps(report.to_dict(), indent=2))

        loaded = json.loads(output_path.read_text())
        assert "total_baseline_calls" in loaded
        assert "total_kg_calls" in loaded
        assert "overall_reduction_pct" in loaded


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_minimal_py_repo(path: Path, module_name: str, n_functions: int) -> None:
    """Create a minimal Python repo with one module containing N functions."""
    path.mkdir(parents=True, exist_ok=True)
    lines = [f'"""Module {module_name}."""\n\n']
    for i in range(n_functions):
        lines.append(f"def {module_name}_func_{i}(x):\n    return x + {i}\n\n")
    (path / f"{module_name}.py").write_text("".join(lines))
