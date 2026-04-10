"""Tests for Story 13.2 CLI commands: librarian run/status, concept,
validate, export, doctor.

Each test is directly traceable to a Given/When/Then acceptance criterion
from ticket AP-107.
"""

from __future__ import annotations

import argparse
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from apriori.models.concept import CodeReference, Concept
from apriori.models.edge import Edge
from apriori.models.librarian_activity import LibrarianActivity
from apriori.models.run_telemetry import RunTelemetry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_concept(
    name: str = "PaymentValidator",
    description: str = "Validates payments",
    *,
    labels: set[str] | None = None,
    confidence: float = 0.9,
    concept_id: uuid.UUID | None = None,
    code_references: list[CodeReference] | None = None,
) -> Concept:
    return Concept(
        id=concept_id or uuid.uuid4(),
        name=name,
        description=description,
        labels=labels or {"auto-generated"},
        confidence=confidence,
        code_references=code_references or [],
        created_by="agent",
    )


def _make_edge(
    source_id: uuid.UUID,
    target_id: uuid.UUID,
    edge_type: str = "depends-on",
) -> Edge:
    return Edge(
        id=uuid.uuid4(),
        source_id=source_id,
        target_id=target_id,
        edge_type=edge_type,
        confidence=0.8,
        evidence_type="structural",
    )


def _make_activity(
    run_id: uuid.UUID,
    iteration: int,
    status: str = "success",
    tokens_used: int = 1000,
    failure_reason: Optional[str] = None,
    concepts_integrated: int = 1,
    edges_integrated: int = 1,
    model_used: str = "claude-opus-4-6",
    duration_seconds: float = 2.5,
) -> LibrarianActivity:
    return LibrarianActivity(
        id=uuid.uuid4(),
        run_id=run_id,
        iteration=iteration,
        status=status,  # type: ignore[arg-type]
        concepts_integrated=concepts_integrated,
        edges_integrated=edges_integrated,
        tokens_used=tokens_used,
        model_used=model_used,
        duration_seconds=duration_seconds,
        failure_reason=failure_reason,
        created_at=datetime.now(timezone.utc),
    )


def _fake_store(
    concepts: list[Concept] | None = None,
    edges: list[Edge] | None = None,
    activities: list[LibrarianActivity] | None = None,
    metrics: dict | None = None,
) -> MagicMock:
    store = MagicMock()
    store.list_concepts.return_value = concepts or []
    store.list_edges.return_value = edges or []
    store.list_librarian_activities.return_value = activities or []
    store.get_metrics.return_value = metrics or {
        "concept_count": 5,
        "edge_count": 3,
    }
    store.search_keyword.return_value = []
    store.get_concept.return_value = None
    return store


# ---------------------------------------------------------------------------
# AC 1: librarian run --iterations 10 --budget 50000
# Given `apriori librarian run --iterations 10 --budget 50000`,
# when run, then the librarian executes up to 10 iterations within
# a 50,000 token budget.
# ---------------------------------------------------------------------------


def _make_fake_librarian_loop(telemetry: RunTelemetry, call_log: list | None = None, config_log: list | None = None):
    """Return a factory that creates a fake LibrarianLoop capturing calls."""
    async def _fake_run(iterations: int) -> tuple[list, RunTelemetry]:
        if call_log is not None:
            call_log.append(iterations)
        return [], telemetry

    def _factory(*args, config=None, **kwargs):
        if config_log is not None and config is not None:
            config_log.append(config)
        fake_loop = MagicMock()
        fake_loop.run = _fake_run
        return fake_loop

    return _factory


def test_librarian_run_invokes_loop_with_correct_iterations(tmp_path: Path, monkeypatch):
    """Given librarian run --iterations 10 --budget 50000,
    when run, then LibrarianLoop.run is called with iterations=10."""
    from apriori.shells import cli

    store = _fake_store()
    telemetry = RunTelemetry(total_iterations=10, total_tokens=30000)
    call_log: list[int] = []

    monkeypatch.setattr("apriori.shells.cli._build_store_from_args", lambda args: store)
    monkeypatch.setattr("apriori.shells.cli._build_adapter_from_config", lambda config: MagicMock())
    monkeypatch.setattr(
        "apriori.librarian.loop.LibrarianLoop",
        _make_fake_librarian_loop(telemetry, call_log=call_log),
    )

    args = argparse.Namespace(db=None, iterations=10, budget=50000)
    cli._cmd_librarian_run(args)
    assert call_log == [10]


def test_librarian_run_sets_budget_in_config(tmp_path: Path, monkeypatch):
    """Given --budget 50000, when run, then config.budget.max_tokens_per_run
    is set to 50000 before LibrarianLoop is created."""
    from apriori.shells import cli

    store = _fake_store()
    telemetry = RunTelemetry()
    config_log: list = []

    monkeypatch.setattr("apriori.shells.cli._build_store_from_args", lambda args: store)
    monkeypatch.setattr("apriori.shells.cli._build_adapter_from_config", lambda config: MagicMock())
    monkeypatch.setattr(
        "apriori.librarian.loop.LibrarianLoop",
        _make_fake_librarian_loop(telemetry, config_log=config_log),
    )

    args = argparse.Namespace(db=None, iterations=5, budget=50000)
    cli._cmd_librarian_run(args)
    assert config_log[0].budget.max_tokens_per_run == 50000


def test_librarian_run_prints_summary(capsys, monkeypatch):
    """Given a successful run, when complete, then a summary with iteration
    count and token usage is printed."""
    from apriori.shells import cli

    store = _fake_store()
    telemetry = RunTelemetry(
        total_iterations=5,
        total_tokens=20000,
        work_items_resolved=4,
        work_items_failed=1,
    )

    monkeypatch.setattr("apriori.shells.cli._build_store_from_args", lambda args: store)
    monkeypatch.setattr("apriori.shells.cli._build_adapter_from_config", lambda config: MagicMock())
    monkeypatch.setattr(
        "apriori.librarian.loop.LibrarianLoop",
        _make_fake_librarian_loop(telemetry),
    )

    args = argparse.Namespace(db=None, iterations=5, budget=None)
    cli._cmd_librarian_run(args)

    out = capsys.readouterr().out
    assert "5" in out  # total iterations
    assert "20000" in out or "20,000" in out  # total tokens


# ---------------------------------------------------------------------------
# AC 2: librarian status
# Given `apriori librarian status`, when run, then it displays detailed
# iteration yield, token spend history, and failure logs for last 5 runs.
# ---------------------------------------------------------------------------


def test_librarian_status_shows_yield(capsys, monkeypatch):
    """Given activities with 8 successes out of 10 iterations across 2 runs,
    when librarian status is run, then iteration yield is displayed."""
    from apriori.shells import cli

    run1 = uuid.uuid4()
    run2 = uuid.uuid4()
    activities = (
        [_make_activity(run1, i, status="success") for i in range(5)]
        + [_make_activity(run1, 5, status="level1_failure", failure_reason="bad output")]
        + [_make_activity(run2, i, status="success") for i in range(3)]
        + [_make_activity(run2, 3, status="error", failure_reason="timeout")]
    )
    store = _fake_store(activities=activities)

    monkeypatch.setattr("apriori.shells.cli._build_store_from_args", lambda args: store)
    args = argparse.Namespace(db=None, json=False)
    cli._cmd_librarian_status(args)

    out = capsys.readouterr().out
    # Should show at least yield or success information
    assert "yield" in out.lower() or "success" in out.lower() or "%" in out


def test_librarian_status_shows_token_spend(capsys, monkeypatch):
    """Given activities with known tokens_used values, when librarian status is
    run, then token spend totals per run are displayed (AC2)."""
    from apriori.shells import cli

    run_id = uuid.uuid4()
    activities = [
        _make_activity(run_id, 0, status="success", tokens_used=1500),
        _make_activity(run_id, 1, status="success", tokens_used=2000),
        _make_activity(run_id, 2, status="level1_failure", tokens_used=800,
                       failure_reason="bad output"),
    ]
    store = _fake_store(activities=activities)

    monkeypatch.setattr("apriori.shells.cli._build_store_from_args", lambda args: store)
    args = argparse.Namespace(db=None, json=False)
    cli._cmd_librarian_status(args)

    out = capsys.readouterr().out
    # Total tokens for this run = 1500 + 2000 + 800 = 4300
    assert "4,300" in out or "4300" in out


def test_librarian_status_json_includes_total_tokens(capsys, monkeypatch):
    """Given --json flag and activities with known tokens_used, when librarian
    status is run, then JSON output includes total_tokens per run (AC2)."""
    from apriori.shells import cli

    run_id = uuid.uuid4()
    activities = [
        _make_activity(run_id, 0, status="success", tokens_used=3000),
        _make_activity(run_id, 1, status="success", tokens_used=4000),
    ]
    store = _fake_store(activities=activities)

    monkeypatch.setattr("apriori.shells.cli._build_store_from_args", lambda args: store)
    args = argparse.Namespace(db=None, json=True)
    cli._cmd_librarian_status(args)

    out = capsys.readouterr().out
    data = json.loads(out)
    assert len(data) == 1
    assert data[0]["total_tokens"] == 7000


def test_librarian_status_shows_failure_logs(capsys, monkeypatch):
    """Given activities with failure_reason, when librarian status is run,
    then failure logs for last 5 runs are shown."""
    from apriori.shells import cli

    run_ids = [uuid.uuid4() for _ in range(6)]
    activities = []
    for i, rid in enumerate(run_ids):
        activities.append(_make_activity(rid, 0, status="level1_failure",
                                          failure_reason=f"failure-{i}"))

    store = _fake_store(activities=activities)

    monkeypatch.setattr("apriori.shells.cli._build_store_from_args", lambda args: store)
    args = argparse.Namespace(db=None, json=False)
    cli._cmd_librarian_status(args)

    out = capsys.readouterr().out
    # Last 5 runs' failures should appear; first run's failure should not
    for i in range(1, 6):  # runs 1..5 (most recent 5)
        assert f"failure-{i}" in out
    # Run 0 is outside the last 5 (it's the oldest)
    assert "failure-0" not in out


def test_librarian_status_no_activities(capsys, monkeypatch):
    """Given no activities, when librarian status is run,
    then a helpful 'no runs' message is shown."""
    from apriori.shells import cli

    store = _fake_store(activities=[])
    monkeypatch.setattr("apriori.shells.cli._build_store_from_args", lambda args: store)
    args = argparse.Namespace(db=None, json=False)
    cli._cmd_librarian_status(args)

    out = capsys.readouterr().out
    assert "no" in out.lower() or "0" in out


def test_librarian_status_json_output(capsys, monkeypatch):
    """Given --json flag, when librarian status is run,
    then valid JSON with run history is printed."""
    from apriori.shells import cli

    run_id = uuid.uuid4()
    activities = [_make_activity(run_id, 0, status="success")]
    store = _fake_store(activities=activities)

    monkeypatch.setattr("apriori.shells.cli._build_store_from_args", lambda args: store)
    args = argparse.Namespace(db=None, json=True)
    cli._cmd_librarian_status(args)

    out = capsys.readouterr().out
    data = json.loads(out)
    assert isinstance(data, list)


# ---------------------------------------------------------------------------
# AC 3: concept "PaymentValidator"
# Given `apriori concept "PaymentValidator"`, when run, then the full
# concept details are displayed.
# ---------------------------------------------------------------------------


def test_concept_displays_matching_concept(capsys, monkeypatch):
    """Given concept 'PaymentValidator' in store, when `apriori concept
    PaymentValidator` is run, then name, description, confidence, labels
    are printed."""
    from apriori.shells import cli

    concept = _make_concept(
        name="PaymentValidator",
        description="Validates payment data",
        labels={"auto-generated", "verified"},
        confidence=0.95,
    )
    store = _fake_store()
    store.search_keyword.return_value = [concept]

    monkeypatch.setattr("apriori.shells.cli._build_store_from_args", lambda args: store)
    args = argparse.Namespace(db=None, name="PaymentValidator", json=False)
    cli._cmd_concept(args)

    out = capsys.readouterr().out
    assert "PaymentValidator" in out
    assert "Validates payment data" in out
    assert "0.95" in out


def test_concept_shows_code_references(capsys, monkeypatch):
    """Given concept with code references, when displayed, then
    code references are included in output."""
    from apriori.shells import cli

    ref = CodeReference(
        symbol="PaymentValidator.validate",
        file_path="src/payments/validator.py",
        content_hash="a" * 64,
        semantic_anchor="class PaymentValidator",
    )
    concept = _make_concept(code_references=[ref])
    store = _fake_store()
    store.search_keyword.return_value = [concept]

    monkeypatch.setattr("apriori.shells.cli._build_store_from_args", lambda args: store)
    args = argparse.Namespace(db=None, name="PaymentValidator", json=False)
    cli._cmd_concept(args)

    out = capsys.readouterr().out
    assert "src/payments/validator.py" in out


def test_concept_not_found_message(capsys, monkeypatch):
    """Given no matching concept, when `apriori concept Unknown` is run,
    then a 'not found' message is printed."""
    from apriori.shells import cli

    store = _fake_store()
    store.search_keyword.return_value = []

    monkeypatch.setattr("apriori.shells.cli._build_store_from_args", lambda args: store)
    args = argparse.Namespace(db=None, name="Unknown", json=False)
    cli._cmd_concept(args)

    out = capsys.readouterr().out
    assert "not found" in out.lower() or "no" in out.lower()


def test_concept_json_output(capsys, monkeypatch):
    """Given --json flag, when concept is found, then valid JSON is printed."""
    from apriori.shells import cli

    concept = _make_concept()
    store = _fake_store()
    store.search_keyword.return_value = [concept]

    monkeypatch.setattr("apriori.shells.cli._build_store_from_args", lambda args: store)
    args = argparse.Namespace(db=None, name="PaymentValidator", json=True)
    cli._cmd_concept(args)

    out = capsys.readouterr().out
    data = json.loads(out)
    assert isinstance(data, list)
    assert data[0]["name"] == "PaymentValidator"


# ---------------------------------------------------------------------------
# AC 4: validate
# Given `apriori validate`, when run, then integrity checks verify:
# all edge references point to existing concepts, all code references have
# valid file paths, no orphaned YAML files, SQLite matches YAML.
# ---------------------------------------------------------------------------


def test_validate_passes_with_clean_store(capsys, monkeypatch, tmp_path: Path):
    """Given a clean store with all edges valid, when validate is run,
    then no errors are reported and exit code is 0."""
    from apriori.shells import cli

    cid1 = uuid.uuid4()
    cid2 = uuid.uuid4()
    concept1 = _make_concept(name="A", concept_id=cid1)
    concept2 = _make_concept(name="B", concept_id=cid2)
    edge = _make_edge(cid1, cid2)
    store = _fake_store(concepts=[concept1, concept2], edges=[edge])
    store.get_concept.side_effect = lambda cid: (
        concept1 if cid == cid1 else concept2 if cid == cid2 else None
    )

    yaml_path = tmp_path / "concepts"
    yaml_path.mkdir()

    monkeypatch.setattr("apriori.shells.cli._build_store_from_args", lambda args: store)
    monkeypatch.setattr("apriori.shells.cli._resolve_yaml_backup_path", lambda args: yaml_path)
    args = argparse.Namespace(db=None, json=False)
    cli._cmd_validate(args)

    out = capsys.readouterr().out
    assert "ok" in out.lower() or "0 error" in out.lower() or "no error" in out.lower() or "pass" in out.lower()


def test_validate_detects_dangling_edge(capsys, monkeypatch, tmp_path: Path):
    """Given an edge referencing a non-existent concept, when validate is run,
    then the dangling edge is reported as an error."""
    from apriori.shells import cli

    cid1 = uuid.uuid4()
    cid_missing = uuid.uuid4()
    concept1 = _make_concept(name="A", concept_id=cid1)
    edge = _make_edge(cid1, cid_missing)

    store = _fake_store(concepts=[concept1], edges=[edge])
    store.get_concept.side_effect = lambda cid: concept1 if cid == cid1 else None

    yaml_path = tmp_path / "concepts"
    yaml_path.mkdir()

    monkeypatch.setattr("apriori.shells.cli._build_store_from_args", lambda args: store)
    monkeypatch.setattr("apriori.shells.cli._resolve_yaml_backup_path", lambda args: yaml_path)
    args = argparse.Namespace(db=None, json=False)
    with pytest.raises(SystemExit):
        cli._cmd_validate(args)

    out = capsys.readouterr().out
    assert "dang" in out.lower() or "missing" in out.lower() or "edge" in out.lower()


def test_validate_detects_missing_code_reference_file(capsys, monkeypatch, tmp_path: Path):
    """Given a concept with code reference pointing to a non-existent file,
    when validate is run, then the missing file path is reported."""
    from apriori.shells import cli

    ref = CodeReference(
        symbol="Foo.bar",
        file_path="/nonexistent/path/foo.py",
        content_hash="b" * 64,
        semantic_anchor="class Foo",
    )
    concept = _make_concept(code_references=[ref])
    store = _fake_store(concepts=[concept], edges=[])
    store.get_concept.return_value = concept

    yaml_path = tmp_path / "concepts"
    yaml_path.mkdir()

    monkeypatch.setattr("apriori.shells.cli._build_store_from_args", lambda args: store)
    monkeypatch.setattr("apriori.shells.cli._resolve_yaml_backup_path", lambda args: yaml_path)
    args = argparse.Namespace(db=None, json=False)
    with pytest.raises(SystemExit):
        cli._cmd_validate(args)

    out = capsys.readouterr().out
    assert "nonexistent" in out or "file" in out.lower() or "path" in out.lower()


def test_validate_detects_orphaned_yaml(capsys, monkeypatch, tmp_path: Path):
    """Given a YAML file in the backup dir not present in SQLite,
    when validate is run, then the orphaned YAML is reported."""
    from apriori.shells import cli

    store = _fake_store(concepts=[], edges=[])

    yaml_path = tmp_path / "concepts"
    yaml_path.mkdir()
    orphan_id = uuid.uuid4()
    (yaml_path / "orphan.yaml").write_text(
        f"id: {orphan_id}\nname: Orphan\ndescription: ''\n"
    )

    monkeypatch.setattr("apriori.shells.cli._build_store_from_args", lambda args: store)
    monkeypatch.setattr("apriori.shells.cli._resolve_yaml_backup_path", lambda args: yaml_path)
    args = argparse.Namespace(db=None, json=False)
    with pytest.raises(SystemExit):
        cli._cmd_validate(args)

    out = capsys.readouterr().out
    assert "orphan" in out.lower() or "yaml" in out.lower()


def test_validate_json_output(capsys, monkeypatch, tmp_path: Path):
    """Given --json flag, when validate is run, then valid JSON with
    error list is printed."""
    from apriori.shells import cli

    store = _fake_store(concepts=[], edges=[])
    yaml_path = tmp_path / "concepts"
    yaml_path.mkdir()

    monkeypatch.setattr("apriori.shells.cli._build_store_from_args", lambda args: store)
    monkeypatch.setattr("apriori.shells.cli._resolve_yaml_backup_path", lambda args: yaml_path)
    args = argparse.Namespace(db=None, json=True)
    cli._cmd_validate(args)

    out = capsys.readouterr().out
    data = json.loads(out)
    assert "errors" in data
    assert isinstance(data["errors"], list)


# ---------------------------------------------------------------------------
# AC 5: export --format json
# Given `apriori export --format json`, when run, then the full knowledge
# graph is exported as a single JSON file.
# ---------------------------------------------------------------------------


def test_export_json_contains_concepts_and_edges(capsys, monkeypatch):
    """Given concepts and edges in store, when export --format json is run,
    then output JSON contains both concepts and edges arrays."""
    from apriori.shells import cli

    cid1 = uuid.uuid4()
    cid2 = uuid.uuid4()
    concepts = [
        _make_concept(name="Alpha", concept_id=cid1),
        _make_concept(name="Beta", concept_id=cid2),
    ]
    edges = [_make_edge(cid1, cid2)]
    store = _fake_store(concepts=concepts, edges=edges)

    monkeypatch.setattr("apriori.shells.cli._build_store_from_args", lambda args: store)
    args = argparse.Namespace(db=None, format="json", output=None)
    cli._cmd_export(args)

    out = capsys.readouterr().out
    data = json.loads(out)
    assert "concepts" in data
    assert "edges" in data
    assert len(data["concepts"]) == 2
    assert len(data["edges"]) == 1


def test_export_json_concept_names_present(capsys, monkeypatch):
    """Given concepts in store, when export --format json, then
    concept names appear in output."""
    from apriori.shells import cli

    concepts = [
        _make_concept(name="Alpha"),
        _make_concept(name="Beta"),
    ]
    store = _fake_store(concepts=concepts, edges=[])

    monkeypatch.setattr("apriori.shells.cli._build_store_from_args", lambda args: store)
    args = argparse.Namespace(db=None, format="json", output=None)
    cli._cmd_export(args)

    out = capsys.readouterr().out
    data = json.loads(out)
    names = {c["name"] for c in data["concepts"]}
    assert names == {"Alpha", "Beta"}


def test_export_writes_to_file_when_output_given(tmp_path: Path, monkeypatch):
    """Given --output path, when export --format json is run,
    then the JSON is written to the specified file."""
    from apriori.shells import cli

    concepts = [_make_concept(name="Alpha")]
    store = _fake_store(concepts=concepts, edges=[])

    monkeypatch.setattr("apriori.shells.cli._build_store_from_args", lambda args: store)
    out_file = tmp_path / "export.json"
    args = argparse.Namespace(db=None, format="json", output=str(out_file))
    cli._cmd_export(args)

    assert out_file.exists()
    data = json.loads(out_file.read_text())
    assert len(data["concepts"]) == 1


# ---------------------------------------------------------------------------
# AC 6: doctor
# Given `apriori doctor`, when run, then it checks:
# tree-sitter, LLM connectivity, SQLite health, git integration,
# embedding model — and reports pass/fail for each with actionable guidance.
# ---------------------------------------------------------------------------


def test_doctor_reports_all_subsystems(capsys, monkeypatch):
    """Given all subsystems available, when doctor is run,
    then a check result for each subsystem is printed."""
    from apriori.shells import cli

    # Mock all subsystem checks to pass
    monkeypatch.setattr("apriori.shells.cli._check_tree_sitter", lambda: (True, ""))
    monkeypatch.setattr("apriori.shells.cli._check_llm_connectivity", lambda config: (True, ""))
    monkeypatch.setattr("apriori.shells.cli._check_sqlite_health", lambda args: (True, ""))
    monkeypatch.setattr("apriori.shells.cli._check_git_integration", lambda: (True, ""))
    monkeypatch.setattr("apriori.shells.cli._check_embedding_model", lambda: (True, ""))

    args = argparse.Namespace(db=None)
    cli._cmd_doctor(args)

    out = capsys.readouterr().out
    # Should mention each subsystem
    assert "tree-sitter" in out.lower() or "tree_sitter" in out.lower()
    assert "llm" in out.lower() or "connectivity" in out.lower()
    assert "sqlite" in out.lower()
    assert "git" in out.lower()
    assert "embed" in out.lower()


def test_doctor_reports_pass_when_all_ok(capsys, monkeypatch):
    """Given all checks pass, when doctor is run,
    then each check is reported as PASS."""
    from apriori.shells import cli

    monkeypatch.setattr("apriori.shells.cli._check_tree_sitter", lambda: (True, ""))
    monkeypatch.setattr("apriori.shells.cli._check_llm_connectivity", lambda config: (True, ""))
    monkeypatch.setattr("apriori.shells.cli._check_sqlite_health", lambda args: (True, ""))
    monkeypatch.setattr("apriori.shells.cli._check_git_integration", lambda: (True, ""))
    monkeypatch.setattr("apriori.shells.cli._check_embedding_model", lambda: (True, ""))

    args = argparse.Namespace(db=None)
    cli._cmd_doctor(args)

    out = capsys.readouterr().out
    assert "pass" in out.lower() or "ok" in out.lower() or "✓" in out


def test_doctor_reports_fail_with_guidance(capsys, monkeypatch):
    """Given tree-sitter check fails, when doctor is run,
    then FAIL is reported with actionable guidance message."""
    from apriori.shells import cli

    monkeypatch.setattr("apriori.shells.cli._check_tree_sitter",
                        lambda: (False, "Install tree-sitter: pip install tree-sitter"))
    monkeypatch.setattr("apriori.shells.cli._check_llm_connectivity", lambda config: (True, ""))
    monkeypatch.setattr("apriori.shells.cli._check_sqlite_health", lambda args: (True, ""))
    monkeypatch.setattr("apriori.shells.cli._check_git_integration", lambda: (True, ""))
    monkeypatch.setattr("apriori.shells.cli._check_embedding_model", lambda: (True, ""))

    args = argparse.Namespace(db=None)
    with pytest.raises(SystemExit):
        cli._cmd_doctor(args)

    out = capsys.readouterr().out
    assert "fail" in out.lower() or "✗" in out
    assert "tree-sitter" in out.lower() or "tree_sitter" in out.lower()
    assert "pip install" in out.lower() or "install" in out.lower()


# ---------------------------------------------------------------------------
# Parser integration: ensure all commands are registered in the CLI parser
# ---------------------------------------------------------------------------


def test_parser_has_librarian_subcommand():
    """The top-level parser must have a 'librarian' subcommand."""
    from apriori.shells.cli import _build_parser

    parser = _build_parser()
    # Parse 'librarian run --help' without exiting
    subparser_choices = parser._subparsers._group_actions[0].choices  # type: ignore[index]
    assert "librarian" in subparser_choices


def test_parser_has_concept_subcommand():
    """The top-level parser must have a 'concept' subcommand."""
    from apriori.shells.cli import _build_parser

    parser = _build_parser()
    subparser_choices = parser._subparsers._group_actions[0].choices  # type: ignore[index]
    assert "concept" in subparser_choices


def test_parser_has_validate_subcommand():
    """The top-level parser must have a 'validate' subcommand."""
    from apriori.shells.cli import _build_parser

    parser = _build_parser()
    subparser_choices = parser._subparsers._group_actions[0].choices  # type: ignore[index]
    assert "validate" in subparser_choices


def test_parser_has_export_subcommand():
    """The top-level parser must have an 'export' subcommand."""
    from apriori.shells.cli import _build_parser

    parser = _build_parser()
    subparser_choices = parser._subparsers._group_actions[0].choices  # type: ignore[index]
    assert "export" in subparser_choices


def test_parser_has_doctor_subcommand():
    """The top-level parser must have a 'doctor' subcommand."""
    from apriori.shells.cli import _build_parser

    parser = _build_parser()
    subparser_choices = parser._subparsers._group_actions[0].choices  # type: ignore[index]
    assert "doctor" in subparser_choices


def test_librarian_run_parser_accepts_iterations_and_budget():
    """librarian run must accept --iterations and --budget flags."""
    from apriori.shells.cli import _build_parser

    parser = _build_parser()
    args = parser.parse_args(["librarian", "run", "--iterations", "5", "--budget", "30000"])
    assert args.iterations == 5
    assert args.budget == 30000


def test_export_parser_accepts_format_json():
    """export must accept --format json."""
    from apriori.shells.cli import _build_parser

    parser = _build_parser()
    args = parser.parse_args(["export", "--format", "json"])
    assert args.format == "json"
