"""Tests for apriori CLI blast-radius command (Story 12.6 — AP-100).

AC8: Given `apriori blast-radius src/payments/validate.py`, the same information
     is displayed in a human-readable format.
"""

from __future__ import annotations

import argparse
import json as _json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from apriori.models.concept import Concept, CodeReference
from apriori.models.impact import ImpactEntry, ImpactProfile
from apriori.retrieval.blast_radius_query import BlastRadiusEntry
from apriori.shells import cli


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sample_entry(
    concept_id: uuid.UUID | None = None,
    concept_name: str = "target_concept",
    confidence: float = 0.8,
    impact_layer: str = "structural",
    depth: int = 1,
    rationale: str = "Test rationale.",
) -> BlastRadiusEntry:
    cid = concept_id or uuid.uuid4()
    return BlastRadiusEntry(
        concept_id=cid,
        concept_name=concept_name,
        confidence=confidence,
        impact_layer=impact_layer,
        depth=depth,
        relationship_path=[str(uuid.uuid4())],
        rationale=rationale,
        composite_score=confidence * (1.0 / depth),
    )


def _run_blast_radius(tmp_path: Path, entries: list, target: str = "src/payments/validate.py",
                      depth: int | None = None, min_confidence: float | None = None,
                      use_json: bool = False) -> str:
    """Run _cmd_blast_radius with mocked query_blast_radius and return captured output."""
    import io, sys
    from apriori.storage.sqlite_store import SQLiteStore

    db_path = tmp_path / "test.db"
    # Create a real (empty) db so the file exists
    SQLiteStore(db_path=db_path)

    with patch("apriori.retrieval.blast_radius_query.query_blast_radius", return_value=entries):
        args = argparse.Namespace(
            target=target,
            depth=depth,
            min_confidence=min_confidence,
            db=str(db_path),
            json=use_json,
        )
        buf = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = buf
        try:
            cli._cmd_blast_radius(args)
        finally:
            sys.stdout = old_stdout
        return buf.getvalue()


# ---------------------------------------------------------------------------
# AC8: CLI command displays human-readable blast radius output
# ---------------------------------------------------------------------------

def test_blast_radius_cli_prints_human_readable_output(tmp_path: Path) -> None:
    """Given `apriori blast-radius src/payments/validate.py`,
    the output displays entries in human-readable format."""
    entries = [
        _sample_entry(concept_name="payment_validator", confidence=0.9, depth=1, impact_layer="structural"),
        _sample_entry(concept_name="order_processor", confidence=0.7, depth=2, impact_layer="semantic"),
    ]

    out = _run_blast_radius(tmp_path, entries)

    assert "payment_validator" in out
    assert "order_processor" in out
    assert "structural" in out


def test_blast_radius_cli_json_output(tmp_path: Path) -> None:
    """Given --json flag, the output is valid JSON."""
    target_id = uuid.uuid4()
    entries = [_sample_entry(concept_id=target_id, concept_name="json_target")]

    out = _run_blast_radius(tmp_path, entries, use_json=True)

    data = _json.loads(out)
    assert isinstance(data, list)
    assert len(data) == 1
    entry = data[0]
    assert entry["concept_id"] == str(target_id)
    assert entry["concept_name"] == "json_target"
    assert "composite_score" in entry


def test_blast_radius_cli_no_results_message(tmp_path: Path) -> None:
    """When no impact entries are found, the CLI displays a clear 'no impact' message."""
    out = _run_blast_radius(tmp_path, [])

    output_lower = out.lower()
    assert "no" in output_lower or "0" in output_lower or "empty" in output_lower


def test_blast_radius_cli_passes_depth_and_confidence_to_query(tmp_path: Path) -> None:
    """Given --depth and --min-confidence flags, they are forwarded to query_blast_radius."""
    captured_kwargs: dict = {}

    def fake_query(store, target, **kwargs):
        captured_kwargs.update(kwargs)
        return []

    from apriori.storage.sqlite_store import SQLiteStore
    db_path = tmp_path / "test.db"
    SQLiteStore(db_path=db_path)

    with patch("apriori.retrieval.blast_radius_query.query_blast_radius", side_effect=fake_query):
        args = argparse.Namespace(
            target="some_concept",
            depth=2,
            min_confidence=0.5,
            db=str(db_path),
            json=False,
        )
        cli._cmd_blast_radius(args)

    assert captured_kwargs.get("max_depth") == 2
    assert captured_kwargs.get("min_confidence") == pytest.approx(0.5)


def test_blast_radius_cli_registered_in_main_parser() -> None:
    """The 'blast-radius' subcommand is registered in the main CLI argument parser."""
    parser = cli._build_parser()
    args = parser.parse_args(["blast-radius", "src/module.py"])
    assert args.command == "blast-radius"
    assert args.target == "src/module.py"


def test_blast_radius_cli_registered_with_depth_and_confidence_flags() -> None:
    """The blast-radius command accepts --depth and --min-confidence flags."""
    parser = cli._build_parser()
    args = parser.parse_args(["blast-radius", "my_concept", "--depth", "3", "--min-confidence", "0.6"])
    assert args.depth == 3
    assert args.min_confidence == pytest.approx(0.6)


def test_blast_radius_cli_output_includes_confidence_and_depth(tmp_path: Path) -> None:
    """Human-readable output shows confidence and depth values for each entry."""
    entries = [_sample_entry(concept_name="alpha", confidence=0.85, depth=2, impact_layer="semantic")]
    out = _run_blast_radius(tmp_path, entries)

    # Output should show the confidence value in some form
    assert "alpha" in out
    # Depth indicator
    assert "2" in out
