"""Staleness detection for the knowledge graph (Story 8.2, ERD §4.5).

A concept is stale when its ``derived_from_code_version`` differs from the
current git HEAD *and* at least one of its ``code_references`` points to a
file that has changed between those two commits.

Layer 2 (knowledge/) — may import from models/, storage/, adapters/, config.py.
No imports from structural/, semantic/, retrieval/ (arch:layer-flow).
"""

from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from typing import Callable, Optional

from apriori.models.concept import Concept
from apriori.storage.protocol import KnowledgeStore


# ---------------------------------------------------------------------------
# Default git helpers
# ---------------------------------------------------------------------------


def _get_current_git_hash() -> str:
    """Return the current git HEAD commit hash (40-char hex).

    Falls back to 40 zeros if git is unavailable.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except Exception:
        return "0" * 40


def _get_changed_files(old_hash: str, new_hash: str) -> set[str]:
    """Return the set of file paths modified between two git commits.

    Uses ``git diff --name-only`` to determine which files changed.
    Returns an empty set if git is unavailable or the diff fails.
    """
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", old_hash, new_hash],
            capture_output=True,
            text=True,
            check=True,
        )
        return {line for line in result.stdout.splitlines() if line}
    except Exception:
        return set()


# ---------------------------------------------------------------------------
# StalenessDetector
# ---------------------------------------------------------------------------


class StalenessDetector:
    """Detects and labels concepts whose referenced code has changed.

    Staleness is determined by comparing ``derived_from_code_version`` on each
    concept against the current git HEAD for the files referenced by that
    concept (ERD §4.5).  A concept is stale when:

    1. It has a non-``None`` ``derived_from_code_version``.
    2. That hash differs from the current HEAD.
    3. At least one entry in ``code_references`` points to a file that has
       changed between the concept's version and HEAD.

    Concepts with no ``derived_from_code_version`` or no ``code_references``
    are never marked stale — there is nothing to compare.

    Staleness is cleared by the librarian re-verifying the concept through the
    ``IntegrationDecisionTree`` (see ``integrator.py``), which stamps the new
    HEAD hash and removes the ``stale`` label on VERIFIED and EXTENDED actions.

    Layer 2 (knowledge/) — no imports from structural/, semantic/, or
    retrieval/ (arch:layer-flow).
    """

    def __init__(
        self,
        store: KnowledgeStore,
        git_hash_provider: Optional[Callable[[], str]] = None,
        changed_files_provider: Optional[Callable[[str, str], set[str]]] = None,
    ) -> None:
        self._store = store
        self._git_hash = git_hash_provider or _get_current_git_hash
        self._changed_files = changed_files_provider or _get_changed_files

    def detect_and_mark_stale(self) -> list[Concept]:
        """Scan all concepts, label stale ones, and return the updated list.

        Returns:
            Concepts that were labeled ``stale`` in this run (including those
            that were already stale — the label is set idempotently).
        """
        current_hash = self._git_hash()
        stale: list[Concept] = []
        for concept in self._store.list_concepts():
            if self._is_stale(concept, current_hash):
                stale.append(self._mark_stale(concept))
        return stale

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _is_stale(self, concept: Concept, current_hash: str) -> bool:
        """Return True if the concept's referenced code has changed."""
        concept_hash = concept.derived_from_code_version
        if concept_hash is None:
            return False
        if concept_hash == current_hash:
            return False
        if not concept.code_references:
            return False
        changed = self._changed_files(concept_hash, current_hash)
        return any(ref.file_path in changed for ref in concept.code_references)

    def _mark_stale(self, concept: Concept) -> Concept:
        """Add the ``stale`` label and persist the concept."""
        labels = set(concept.labels) | {"stale"}
        updated = concept.model_copy(
            update={"labels": labels, "updated_at": datetime.now(timezone.utc)}
        )
        return self._store.update_concept(updated)
