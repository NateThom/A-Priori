"""Level 1 Automated Consistency Checks (ERD §4.4.1).

Level 1 is deterministic, requires no LLM calls, and executes in milliseconds.
It implements six checks against a LibrarianOutput before any knowledge is
allowed to enter the graph (arch:quality-invariant).

Six checks (in execution order):

1. schema_parseable       — Raw output can be parsed as LibrarianOutput.
2. description_non_empty  — No concept has an empty or whitespace-only description.
3. description_non_generic — No concept description matches a boilerplate pattern
                             or is under 50 characters (after stripping).
4. confidence_in_range    — All confidence values (concepts and edges) are in [0.0, 1.0].
5. edge_type_valid        — All edge types are from the vocabulary.
6. referential_integrity  — Every edge source/target name appears either in the
                            current batch or in the existing knowledge graph.

Soft check (non-rejecting):

structural_corroboration  — ``depends-on`` edges with evidence_type != "structural"
                            have their confidence reduced by the configured penalty
                            (default: 0.2). Confidence is clamped to 0.0.

Usage::

    from apriori.quality.level1 import check_level1

    result = check_level1(raw_llm_output, existing_concept_names=graph_names)
    if not result.passed:
        print(result.failure_record.failure_reason)
    else:
        approved_output = result.adjusted_output
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import ValidationError

from apriori.models.librarian_output import EdgeProposal, LibrarianOutput
from apriori.models.work_item import FailureRecord


# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------

VALID_EDGE_TYPES: frozenset[str] = frozenset(
    {
        "depends-on",
        "implements",
        "relates-to",
        "shares-assumption-about",
        "extends",
        "supersedes",
        "owned-by",
    }
)

#: Minimum number of non-whitespace characters a description must have to pass
#: the ``description_non_generic`` check. Descriptions shorter than this are
#: considered too vague even if they do not match a boilerplate pattern.
MIN_DESCRIPTION_LENGTH: int = 50

#: Short list of banned boilerplate patterns (compiled, case-insensitive).
#: Matched against the stripped description text via ``re.search``.
BOILERPLATE_PATTERNS: list[re.Pattern[str]] = [
    # "handles X operations and provides methods for managing Y"
    re.compile(r"handles\s+\S+\s+operations\s+and\s+provides", re.IGNORECASE),
    # "processes data and returns results"
    re.compile(r"processes\s+data\s+and\s+returns\s+results", re.IGNORECASE),
    # "takes input … performs some operations"
    re.compile(r"takes\s+input.*?performs\s+some\s+operations", re.IGNORECASE | re.DOTALL),
    # "is responsible for handling X operations"
    re.compile(r"is\s+responsible\s+for\s+handling\s+\S+\s+operations", re.IGNORECASE),
]

#: Default confidence reduction for ``depends-on`` edges without structural
#: corroboration (``evidence_type != "structural"``).
DEFAULT_CORROBORATION_PENALTY: float = 0.2


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass
class Level1Result:
    """Outcome of a Level 1 consistency check run.

    Exactly one of ``adjusted_output`` or ``failure_record`` is set:

    - ``passed=True``:  ``adjusted_output`` holds the (possibly confidence-
      adjusted) LibrarianOutput; ``failure_record`` is None.
    - ``passed=False``: ``failure_record`` describes the violation;
      ``adjusted_output`` is None.
    """

    passed: bool
    failure_record: Optional[FailureRecord] = field(default=None)
    adjusted_output: Optional[LibrarianOutput] = field(default=None)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _failure(reason: str) -> Level1Result:
    """Produce a failed Level1Result with a well-formed FailureRecord."""
    record = FailureRecord(
        attempted_at=datetime.now(timezone.utc),
        model_used="none",
        prompt_template="level1_consistency_checks",
        failure_reason=reason,
    )
    return Level1Result(passed=False, failure_record=record)


def _apply_corroboration_penalty(
    edges: list[EdgeProposal],
    penalty: float,
) -> list[EdgeProposal]:
    """Return edges with confidence reduced for unstructured ``depends-on`` edges.

    Only ``depends-on`` edges whose ``evidence_type`` is not ``"structural"``
    are adjusted. Confidence is clamped to 0.0.
    """
    result = []
    for edge in edges:
        if edge.edge_type == "depends-on" and edge.evidence_type != "structural":
            adjusted_confidence = max(0.0, edge.confidence - penalty)
            result.append(
                EdgeProposal(
                    source_name=edge.source_name,
                    target_name=edge.target_name,
                    edge_type=edge.edge_type,
                    confidence=adjusted_confidence,
                    evidence_type=edge.evidence_type,
                )
            )
        else:
            result.append(edge)
    return result


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def check_level1(
    raw_output: Any,
    existing_concept_names: frozenset[str] = frozenset(),
    corroboration_penalty: float = DEFAULT_CORROBORATION_PENALTY,
) -> Level1Result:
    """Entry point for Level 1 checks: parse raw output then run all checks.

    This function handles the ``schema_parseable`` check.  If parsing succeeds,
    it delegates to ``run_level1_checks`` for the remaining five checks.

    Args:
        raw_output: Unvalidated data from the LLM (dict, str, None, etc.).
        existing_concept_names: Names of concepts already in the knowledge graph.
            Used to validate edge referential integrity against the existing graph.
        corroboration_penalty: Confidence reduction applied to ``depends-on`` edges
            with no structural corroboration. Default: ``DEFAULT_CORROBORATION_PENALTY``.

    Returns:
        A :class:`Level1Result` with ``passed=True`` and an ``adjusted_output``,
        or ``passed=False`` and a ``failure_record`` describing the violation.
    """
    try:
        output = LibrarianOutput.model_validate(raw_output)
    except (ValidationError, TypeError, ValueError, AttributeError, KeyError) as exc:
        return _failure(f"Level 1: schema validity error ({type(exc).__name__})")

    return run_level1_checks(output, existing_concept_names, corroboration_penalty)


def run_level1_checks(
    output: LibrarianOutput,
    existing_concept_names: frozenset[str] = frozenset(),
    corroboration_penalty: float = DEFAULT_CORROBORATION_PENALTY,
) -> Level1Result:
    """Run checks 2–6 on a pre-parsed LibrarianOutput, plus the soft corroboration check.

    Assumes ``output`` has already passed the ``schema_parseable`` check.
    Checks run in order; the first failure short-circuits.

    Args:
        output: A valid LibrarianOutput instance.
        existing_concept_names: Names of concepts already in the knowledge graph.
        corroboration_penalty: Confidence reduction for unstructured depends-on edges.

    Returns:
        A :class:`Level1Result` — passed with adjusted output, or failed with
        a FailureRecord.
    """
    # ------------------------------------------------------------------
    # Check 2: description_non_empty
    # ------------------------------------------------------------------
    for concept in output.concepts:
        if not concept.description.strip():
            return _failure("Level 1: empty description")

    # ------------------------------------------------------------------
    # Check 3: description_non_generic
    # Only applied to descriptions that passed the non-empty check.
    # ------------------------------------------------------------------
    for concept in output.concepts:
        stripped = concept.description.strip()
        if len(stripped) < MIN_DESCRIPTION_LENGTH:
            return _failure(
                f"Level 1: generic description (too short: {len(stripped)} chars, "
                f"minimum {MIN_DESCRIPTION_LENGTH})"
            )
        for pattern in BOILERPLATE_PATTERNS:
            if pattern.search(stripped):
                return _failure(
                    "Level 1: generic description (matches boilerplate pattern)"
                )

    # ------------------------------------------------------------------
    # Check 4: confidence_in_range
    # ------------------------------------------------------------------
    for concept in output.concepts:
        if not (0.0 <= concept.confidence <= 1.0):
            return _failure(
                f"Level 1: confidence out of range ({concept.confidence})"
            )
    for edge in output.edges:
        if not (0.0 <= edge.confidence <= 1.0):
            return _failure(
                f"Level 1: confidence out of range ({edge.confidence})"
            )

    # ------------------------------------------------------------------
    # Check 5: edge_type_valid
    # ------------------------------------------------------------------
    for edge in output.edges:
        if edge.edge_type not in VALID_EDGE_TYPES:
            return _failure(
                f"Level 1: invalid edge type '{edge.edge_type}'"
            )

    # ------------------------------------------------------------------
    # Check 6: referential_integrity
    # Edge endpoints must reference concepts in the current batch or the
    # existing knowledge graph.
    # ------------------------------------------------------------------
    batch_names = frozenset(c.name for c in output.concepts)
    all_known_names = batch_names | existing_concept_names
    for edge in output.edges:
        for name in (edge.source_name, edge.target_name):
            if name not in all_known_names:
                return _failure(
                    f"Level 1: referential integrity error (unknown concept '{name}')"
                )

    # ------------------------------------------------------------------
    # Soft check: structural_corroboration
    # Adjusts confidence — does not reject.
    # ------------------------------------------------------------------
    adjusted_edges = _apply_corroboration_penalty(output.edges, corroboration_penalty)

    adjusted_output = LibrarianOutput(
        concepts=output.concepts,
        edges=adjusted_edges,
    )

    return Level1Result(passed=True, adjusted_output=adjusted_output)
