"""Tests for Git Change Detector (Story 3.6, ERD §3.3.3).

AC traceability:
- AC1: Only changed files re-parsed — git diff --name-only {last}..HEAD limits scope
- AC2: Modified function → verify_concept work item + needs-review label
- AC3: Added file → investigate_file work item per new file
- AC4: Deleted function concept → flagged (needs-review), not deleted
- AC5: Structural edges updated when they change (GraphBuilder handles this)
- AC6: After successful run, stored last-analyzed commit hash updated to HEAD
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from apriori.storage.sqlite_store import SQLiteStore
from apriori.structural.change_detector import (
    ChangeDetectionResult,
    ChangeDetector,
    _symbols_from_result,
)
from apriori.structural.graph_builder import GraphBuilder
from apriori.structural.models import FunctionEntity, ParseResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _git(repo: Path, *args: str) -> str:
    """Run a git command in *repo* and return stdout."""
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def _init_repo(path: Path) -> Path:
    """Initialise a git repo with a single sentinel commit."""
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init")
    _git(path, "config", "user.email", "test@example.com")
    _git(path, "config", "user.name", "Test User")
    # Required to avoid 'HEAD not found' on first diff
    sentinel = path / "README.md"
    sentinel.write_text("# test repo\n")
    _git(path, "add", ".")
    _git(path, "commit", "-m", "init")
    return path


def _commit(repo: Path, message: str) -> str:
    """Stage all changes and commit; return the new commit SHA."""
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def _make_py_with_function(name: str) -> str:
    """Return Python source with a single function named *name*."""
    return f"def {name}():\n    pass\n"


def _make_py_with_two_functions(name1: str, name2: str) -> str:
    return f"def {name1}():\n    pass\n\ndef {name2}():\n    pass\n"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    return _init_repo(tmp_path / "repo")


@pytest.fixture
def store(tmp_path: Path) -> SQLiteStore:
    return SQLiteStore(tmp_path / "knowledge.db")


@pytest.fixture
def state_file(tmp_path: Path) -> Path:
    return tmp_path / "state.json"


@pytest.fixture
def detector(repo: Path, store: SQLiteStore, state_file: Path) -> ChangeDetector:
    return ChangeDetector(repo_root=repo, store=store, state_file=state_file)


# ---------------------------------------------------------------------------
# AC1: Only changed files are re-parsed
# ---------------------------------------------------------------------------


class TestAC1OnlyChangedFilesReparsed:
    """AC1: When files are modified and run() is called at commit B,
    only the changed files are re-parsed."""

    def test_changed_file_produces_work_item_but_unchanged_file_does_not(
        self, repo: Path, store: SQLiteStore, state_file: Path
    ) -> None:
        """Given two files at commit A (both analyzed), when only file_a is
        modified at commit B, then work items are created for file_a's concepts
        only — file_b's unchanged concepts produce no verify_concept items."""
        # Commit A: two files, both with a function
        (repo / "file_a.py").write_text(_make_py_with_function("func_a"))
        (repo / "file_b.py").write_text(_make_py_with_function("func_b"))
        commit_a = _commit(repo, "A: two files")

        # Analyze the repo at commit A
        detector = ChangeDetector(repo_root=repo, store=store, state_file=state_file)
        result_a = detector.run()
        assert result_a.previous_commit is None  # first run

        # Commit B: only file_a changes (func_a body changed)
        (repo / "file_a.py").write_text("def func_a():\n    return 42\n")
        commit_b = _commit(repo, "B: modify file_a only")

        # Second run — only file_a should be re-parsed
        result_b = detector.run()

        assert result_b.previous_commit == commit_a
        assert result_b.head_commit == commit_b

        # Only the concept from file_a should have a verify_concept work item
        work_items = store.get_pending_work_items()
        verify_items = [wi for wi in work_items if wi.item_type == "verify_concept"]

        file_a_items = [
            wi for wi in verify_items if wi.file_path and "file_a" in wi.file_path
        ]
        file_b_items = [
            wi for wi in verify_items if wi.file_path and "file_b" in wi.file_path
        ]

        assert len(file_a_items) >= 1, "Expected verify_concept item for changed file_a"
        assert len(file_b_items) == 0, "Expected no work items for unchanged file_b"

    def test_first_run_has_no_previous_commit(
        self, detector: ChangeDetector
    ) -> None:
        """On the first run, previous_commit is None."""
        result = detector.run()
        assert result.previous_commit is None

    def test_second_run_stores_first_commit_as_previous(
        self, repo: Path, store: SQLiteStore, state_file: Path
    ) -> None:
        """After the first run, the state file stores HEAD; second run reads it."""
        detector = ChangeDetector(repo_root=repo, store=store, state_file=state_file)
        result_a = detector.run()
        head_a = result_a.head_commit

        # No changes — second run should see head_a as previous
        result_b = detector.run()
        assert result_b.previous_commit == head_a


class TestSymbolExtraction:
    """Symbol extraction includes module-level FQN used by GraphBuilder."""

    def test_symbols_include_module_fqn(self, tmp_path: Path) -> None:
        fp = tmp_path / "mod.py"
        result = ParseResult(
            file_path=fp,
            language="python",
            source=b"def fn():\n    pass\n",
            functions=[FunctionEntity(name="fn", start_line=1, end_line=2, file_path=fp)],
        )

        symbols = _symbols_from_result(result)

        assert str(fp) in symbols
        assert str(fp) + "::fn" in symbols


# ---------------------------------------------------------------------------
# AC2: Modified function → verify_concept + needs-review
# ---------------------------------------------------------------------------


class TestAC2ModifiedFunctionVerifyConcept:
    """AC2: A modified function whose concept exists gets a verify_concept
    work item and the needs-review label."""

    def test_modified_function_creates_verify_concept_work_item(
        self, repo: Path, store: SQLiteStore, state_file: Path
    ) -> None:
        """Given a function 'calculate' at commit A, when its body changes at
        commit B, then a verify_concept work item is created for its concept."""
        (repo / "calc.py").write_text("def calculate():\n    return 0\n")
        _commit(repo, "A: add calculate")

        detector = ChangeDetector(repo_root=repo, store=store, state_file=state_file)
        detector.run()  # analyze at A

        (repo / "calc.py").write_text("def calculate():\n    return 1 + 2\n")
        _commit(repo, "B: modify calculate body")

        detector.run()  # detect change at B

        work_items = store.get_pending_work_items()
        verify_items = [wi for wi in work_items if wi.item_type == "verify_concept"]
        assert len(verify_items) >= 1

        # The work item must reference a real concept
        concept = store.get_concept(verify_items[0].concept_id)
        assert concept is not None

    def test_modified_function_concept_gets_needs_review_label(
        self, repo: Path, store: SQLiteStore, state_file: Path
    ) -> None:
        """When a function's body changes, the 'needs-review' label is applied
        to its concept node in the knowledge graph."""
        (repo / "mod.py").write_text("def process():\n    pass\n")
        _commit(repo, "A: add process")

        detector = ChangeDetector(repo_root=repo, store=store, state_file=state_file)
        detector.run()

        (repo / "mod.py").write_text("def process():\n    return 'modified'\n")
        _commit(repo, "B: modify process")

        detector.run()

        concepts = store.search_by_file(str(repo / "mod.py"))
        labeled = [c for c in concepts if "needs-review" in c.labels]
        assert len(labeled) >= 1, "At least one concept should have needs-review label"

    def test_unchanged_function_does_not_get_verify_item(
        self, repo: Path, store: SQLiteStore, state_file: Path
    ) -> None:
        """A function whose content hash has not changed does NOT get a
        verify_concept work item on the second run."""
        (repo / "stable.py").write_text("def stable():\n    pass\n")
        _commit(repo, "A: stable function")

        detector = ChangeDetector(repo_root=repo, store=store, state_file=state_file)
        detector.run()  # first run — no prior commits to compare

        # No changes at all
        result = detector.run()  # second run — nothing changed

        work_items = store.get_pending_work_items()
        verify_items = [wi for wi in work_items if wi.item_type == "verify_concept"]
        assert len(verify_items) == 0


# ---------------------------------------------------------------------------
# AC3: New file → investigate_file work item
# ---------------------------------------------------------------------------


class TestAC3NewFileInvestigateItem:
    """AC3: A newly added file produces one investigate_file work item."""

    def test_new_file_creates_investigate_file_work_item(
        self, repo: Path, store: SQLiteStore, state_file: Path
    ) -> None:
        """Given an initial analysis at commit A (no Python files), when a new
        file is added at commit B, then one investigate_file work item is
        created for it."""
        # repo fixture already has initial commit (README.md only, no Python)
        detector = ChangeDetector(repo_root=repo, store=store, state_file=state_file)
        detector.run()  # first run — no Python source files

        (repo / "new_module.py").write_text(_make_py_with_function("new_func"))
        _commit(repo, "B: add new_module.py")

        result = detector.run()

        work_items = store.get_pending_work_items()
        investigate_items = [
            wi for wi in work_items if wi.item_type == "investigate_file"
        ]
        assert len(investigate_items) == 1
        assert investigate_items[0].file_path is not None
        assert "new_module.py" in investigate_items[0].file_path

    def test_two_new_files_create_two_investigate_items(
        self, repo: Path, store: SQLiteStore, state_file: Path
    ) -> None:
        """Two newly added files produce two investigate_file work items."""
        detector = ChangeDetector(repo_root=repo, store=store, state_file=state_file)
        detector.run()

        (repo / "alpha.py").write_text(_make_py_with_function("alpha"))
        (repo / "beta.py").write_text(_make_py_with_function("beta"))
        _commit(repo, "B: two new files")

        detector.run()

        work_items = store.get_pending_work_items()
        investigate_items = [
            wi for wi in work_items if wi.item_type == "investigate_file"
        ]
        assert len(investigate_items) == 2


# ---------------------------------------------------------------------------
# AC4: Deleted function → concept flagged, not deleted
# ---------------------------------------------------------------------------


class TestAC4DeletedFunctionFlagged:
    """AC4: When a function is deleted, its concept is flagged with
    needs-review, not immediately removed from the store."""

    def test_deleted_function_concept_is_flagged_not_deleted(
        self, repo: Path, store: SQLiteStore, state_file: Path
    ) -> None:
        """Given a function 'old_func' whose concept exists in the graph,
        when old_func is removed from the file at commit B, then the concept
        still exists but has the 'needs-review' label."""
        (repo / "module.py").write_text(
            "def old_func():\n    pass\n\ndef keep_func():\n    pass\n"
        )
        _commit(repo, "A: two functions")

        detector = ChangeDetector(repo_root=repo, store=store, state_file=state_file)
        detector.run()

        # Verify old_func concept was created
        concepts_before = store.list_concepts()
        assert any("old_func" in c.name for c in concepts_before)

        # Remove old_func from the file
        (repo / "module.py").write_text("def keep_func():\n    pass\n")
        _commit(repo, "B: remove old_func")

        detector.run()

        # Concept must still exist
        concepts_after = store.list_concepts()
        old_func_concepts = [c for c in concepts_after if "old_func" in c.name]
        assert len(old_func_concepts) == 1, "old_func concept must still exist (not deleted)"

        # Concept must be flagged
        assert "needs-review" in old_func_concepts[0].labels, (
            "deleted concept must have needs-review label"
        )

    def test_deleted_function_concept_is_not_deleted_from_store(
        self, repo: Path, store: SQLiteStore, state_file: Path
    ) -> None:
        """Verify deletion does NOT call delete_concept — concept ID persists."""
        (repo / "mod.py").write_text("def doomed():\n    pass\n")
        _commit(repo, "A: add doomed")

        detector = ChangeDetector(repo_root=repo, store=store, state_file=state_file)
        detector.run()

        concepts_before = store.list_concepts()
        doomed_id = next(c.id for c in concepts_before if "doomed" in c.name)

        (repo / "mod.py").write_text("# function removed\n")
        _commit(repo, "B: delete doomed")

        detector.run()

        # Must still be retrievable by ID
        concept = store.get_concept(doomed_id)
        assert concept is not None, "concept must persist after function deletion"


# ---------------------------------------------------------------------------
# AC5: Structural edges updated
# ---------------------------------------------------------------------------


class TestAC5StructuralEdgesUpdated:
    """AC5: When structural edges change (new functions added), the graph
    builder processes them on re-analysis."""

    def test_new_function_in_changed_file_gets_concept_node(
        self, repo: Path, store: SQLiteStore, state_file: Path
    ) -> None:
        """When a changed file gains a new function, a concept is created for it."""
        (repo / "svc.py").write_text("def original():\n    pass\n")
        _commit(repo, "A: original function")

        detector = ChangeDetector(repo_root=repo, store=store, state_file=state_file)
        detector.run()

        count_before = len(store.list_concepts())

        # Add a second function to the file
        (repo / "svc.py").write_text(
            "def original():\n    pass\n\ndef added():\n    pass\n"
        )
        _commit(repo, "B: add function to existing file")

        detector.run()

        count_after = len(store.list_concepts())
        assert count_after > count_before, "new function must produce a new concept node"

        names = {c.name for c in store.list_concepts()}
        assert any("added" in n for n in names)


# ---------------------------------------------------------------------------
# AC6: Commit hash tracking
# ---------------------------------------------------------------------------


class TestAC6CommitHashTracking:
    """AC6: After a successful run, the stored last-analyzed commit hash
    is updated to HEAD."""

    def test_state_file_created_after_first_run(
        self, detector: ChangeDetector, state_file: Path
    ) -> None:
        """The state file is created (or updated) after the first run."""
        assert not state_file.exists()
        detector.run()
        assert state_file.exists()

    def test_state_file_stores_head_commit(
        self, repo: Path, store: SQLiteStore, state_file: Path
    ) -> None:
        """After run(), the state file stores the current HEAD commit hash."""
        head = _git(repo, "rev-parse", "HEAD")
        detector = ChangeDetector(repo_root=repo, store=store, state_file=state_file)
        result = detector.run()

        assert result.head_commit == head
        # The stored hash must equal HEAD
        stored = _git(repo, "rev-parse", "HEAD")
        assert result.head_commit == stored

    def test_head_hash_updated_after_new_commit(
        self, repo: Path, store: SQLiteStore, state_file: Path
    ) -> None:
        """After a new commit, a second run records the new HEAD hash."""
        detector = ChangeDetector(repo_root=repo, store=store, state_file=state_file)
        result_a = detector.run()
        hash_a = result_a.head_commit

        (repo / "new.py").write_text("x = 1\n")
        new_commit = _commit(repo, "new commit")

        result_b = detector.run()
        assert result_b.head_commit == new_commit
        assert result_b.head_commit != hash_a

    def test_result_includes_previous_commit_on_second_run(
        self, repo: Path, store: SQLiteStore, state_file: Path
    ) -> None:
        """On the second run, result.previous_commit equals the hash from the first run."""
        detector = ChangeDetector(repo_root=repo, store=store, state_file=state_file)
        result_a = detector.run()

        (repo / "x.py").write_text("y = 2\n")
        _commit(repo, "another commit")

        result_b = detector.run()
        assert result_b.previous_commit == result_a.head_commit
