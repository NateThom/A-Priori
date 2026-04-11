"""Git Change Detector — incremental re-analysis of changed files (ERD §3.3.3).

Detects which files changed since the last analysis (using ``git diff``),
re-parses them, updates the structural graph, and generates work items for
the librarian. Hash tracking ensures only genuinely-modified symbols trigger
review work items.

Layer: structural/ (Layer 0).  Imports from storage/ and models/ are permitted
per arch:layer-flow (shared modules cross-cut all layers).

All operations are synchronous (arch:sync-first).
"""

from __future__ import annotations

import json
import subprocess
import uuid
from pathlib import Path
from typing import Optional

from pydantic import BaseModel

from apriori.maintenance.impact_profiles import recompute_profiles_for_concepts
from apriori.models.concept import Concept
from apriori.models.work_item import WorkItem
from apriori.storage.protocol import KnowledgeStore
from apriori.structural.fqn import module_fqn, symbol_fqn
from apriori.structural.graph_builder import GraphBuilder
from apriori.structural.languages.python_parser import PythonParser
from apriori.structural.languages.typescript import TypeScriptParser
from apriori.structural.models import ParseResult
from apriori.structural.orchestrator import Orchestrator, OrchestratorConfig, detect_language


# ---------------------------------------------------------------------------
# Result model
# ---------------------------------------------------------------------------


class ChangeDetectionResult(BaseModel):
    """Summary returned by :meth:`ChangeDetector.run`."""

    head_commit: str
    previous_commit: Optional[str]
    files_analyzed: list[str]
    work_items_created: list[uuid.UUID]
    concepts_flagged: int


# ---------------------------------------------------------------------------
# ChangeDetector
# ---------------------------------------------------------------------------

_STATE_KEY = "last_analyzed_commit"


def _concept_path(file_path: Path, repo_root: Path | None = None) -> Path:
    """Return path used for concept naming (repo-relative when possible)."""
    if repo_root is None:
        return file_path
    try:
        return file_path.resolve().relative_to(repo_root.resolve())
    except ValueError:
        return file_path


def _symbols_from_result(result: ParseResult, repo_root: Path | None = None) -> set[str]:
    """Return the set of FQNs that the GraphBuilder would create for *result*."""
    fp = _concept_path(result.file_path, repo_root)
    fqns: set[str] = {module_fqn(fp)}
    for func in result.functions:
        fqns.add(symbol_fqn(fp, func.name))
    for cls in result.classes:
        fqns.add(symbol_fqn(fp, cls.name))
        for method in cls.methods:
            fqns.add(symbol_fqn(fp, cls.name, method.name))
    for iface in result.interfaces:
        fqns.add(symbol_fqn(fp, iface.name))
    return fqns


class ChangeDetector:
    """Detects changed files via git and drives incremental graph updates.

    Args:
        repo_root: Absolute path to the root of the git repository to monitor.
        store: The :class:`~apriori.storage.protocol.KnowledgeStore` to read
            from and write to.
        state_file: Path to a JSON file that persists the last-analyzed commit
            hash between runs. Created on the first run.
        orchestrator_config: Optional custom :class:`OrchestratorConfig` to
            control which files are included/excluded during parsing.
    """

    def __init__(
        self,
        repo_root: Path,
        store: KnowledgeStore,
        state_file: Path,
        orchestrator_config: Optional[OrchestratorConfig] = None,
    ) -> None:
        self._repo_root = repo_root.resolve()
        self._store = store
        self._state_file = state_file
        self._orchestrator_config = orchestrator_config or OrchestratorConfig()

    # -----------------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------------

    def run(self) -> ChangeDetectionResult:
        """Detect changed files and update the knowledge graph incrementally.

        1. Read the last-analyzed commit hash from the state file (first run: None).
        2. Obtain the current HEAD commit hash via ``git rev-parse HEAD``.
        3. Determine changed files via ``git diff`` (first run: use Orchestrator
           to walk all source files).
        4. Re-parse and graph-build changed/added files.
        5. Flag concepts for modified symbols (verify_concept + needs-review).
        6. Flag concepts for deleted symbols (needs-review only).
        7. Create investigate_file work items for newly added files.
        8. Persist the HEAD hash to the state file.

        Returns:
            A :class:`ChangeDetectionResult` summarising the run.
        """
        previous_commit = self._read_last_hash()
        head_commit = self._get_head_hash()

        if previous_commit is None:
            # First run: analyze all source files
            added_files: set[Path] = set()
            modified_files: set[Path] = set()
            deleted_files: set[Path] = set()

            orchestrator = Orchestrator(self._orchestrator_config)
            for file_path, _lang, _result in orchestrator.walk_and_parse(self._repo_root):
                modified_files.add(file_path)
        else:
            added_files = self._diff_files(previous_commit, head_commit, diff_filter="A")
            deleted_files = self._diff_files(previous_commit, head_commit, diff_filter="D")
            all_changed = self._diff_files(previous_commit, head_commit, diff_filter="AMDR")
            modified_files = all_changed - added_files - deleted_files

        work_item_ids: list[uuid.UUID] = []
        files_analyzed: list[str] = []
        concepts_flagged = 0

        # Process added files
        for file_path in sorted(added_files):
            result = self._parse_file(file_path)
            if result is None:
                continue
            files_analyzed.append(str(file_path))
            builder = GraphBuilder(self._store, git_head=head_commit, repo_root=self._repo_root)
            builder.build([result])
            wi = self._create_investigate_file_item(file_path, result)
            if wi is not None:
                work_item_ids.append(wi.id)

        # Process modified files
        for file_path in sorted(modified_files):
            result = self._parse_file(file_path)
            if result is None:
                continue
            files_analyzed.append(str(file_path))
            new_items, flagged = self._process_modified_file(
                file_path, result, head_commit
            )
            work_item_ids.extend(new_items)
            concepts_flagged += flagged

        # Process deleted files (concepts must exist in store)
        for file_path in sorted(deleted_files):
            flagged = self._flag_concepts_for_deleted_file(str(file_path))
            concepts_flagged += flagged

        self._write_last_hash(head_commit)

        return ChangeDetectionResult(
            head_commit=head_commit,
            previous_commit=previous_commit,
            files_analyzed=files_analyzed,
            work_items_created=work_item_ids,
            concepts_flagged=concepts_flagged,
        )

    # -----------------------------------------------------------------------
    # Git helpers
    # -----------------------------------------------------------------------

    def _get_head_hash(self) -> str:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=self._repo_root,
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()

    def _diff_files(
        self, from_hash: str, to_hash: str, diff_filter: str
    ) -> set[Path]:
        """Return the set of files matching *diff_filter* between two commits."""
        result = subprocess.run(
            [
                "git",
                "diff",
                "--name-only",
                f"--diff-filter={diff_filter}",
                f"{from_hash}..{to_hash}",
            ],
            cwd=self._repo_root,
            capture_output=True,
            text=True,
            check=True,
        )
        paths: set[Path] = set()
        for line in result.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            candidate = self._repo_root / line
            if candidate.is_file() or diff_filter == "D":
                paths.add(candidate)
        return paths

    # -----------------------------------------------------------------------
    # Parsing
    # -----------------------------------------------------------------------

    def _parse_file(self, file_path: Path) -> Optional[ParseResult]:
        """Parse a single file using the appropriate language parser.

        Uses PythonParser or TypeScriptParser (not the raw orchestrator
        ``_parse_source``) so that functions, classes, and interfaces are
        properly extracted from the tree.  Returns None on any error.
        """
        language = detect_language(file_path)
        if language is None:
            return None
        try:
            source = file_path.read_bytes()
        except OSError:
            return None
        if len(source) > self._orchestrator_config.max_file_size_bytes:
            return None
        if language == "python":
            return PythonParser().parse(source, file_path)
        else:
            return TypeScriptParser().parse(source, file_path)

    # -----------------------------------------------------------------------
    # Work item creation
    # -----------------------------------------------------------------------

    def _create_investigate_file_item(
        self, file_path: Path, result: ParseResult
    ) -> Optional[WorkItem]:
        """Create a file-level concept and an investigate_file work item for it."""
        # Create a file-level concept to anchor the work item
        file_concept = Concept(
            name=str(_concept_path(file_path, self._repo_root)),
            description=f"New file — needs investigation: {file_path.name}",
            created_by="agent",
            confidence=1.0,
        )
        self._store.create_concept(file_concept)

        work_item = WorkItem(
            item_type="investigate_file",
            concept_id=file_concept.id,
            description=f"Investigate newly added file: {file_path}",
            file_path=str(file_path),
        )
        self._store.create_work_item(work_item)
        return work_item

    def _process_modified_file(
        self,
        file_path: Path,
        result: ParseResult,
        head_commit: str,
    ) -> tuple[list[uuid.UUID], int]:
        """Re-parse a modified file, detect symbol-level changes, and emit work items.

        Returns:
            ``(work_item_ids, concepts_flagged)``
        """
        # Step 1: snapshot old content hashes and existing concept names for this file
        old_concepts: dict[str, Concept] = {}  # FQN → Concept
        for concept in self._store.search_by_file(str(file_path)):
            for ref in concept.code_references:
                if ref.file_path == str(file_path):
                    old_concepts[concept.name] = concept
        old_structural_edges = self._structural_edge_fingerprints(
            {concept.id for concept in old_concepts.values()}
        )

        # Step 2: compute expected new FQNs from the parse result
        new_fqns = _symbols_from_result(result, repo_root=self._repo_root)

        # Step 3: run GraphBuilder to update concepts/edges in the store
        builder = GraphBuilder(self._store, git_head=head_commit, repo_root=self._repo_root)
        builder.build([result])

        # Step 4: detect modified and deleted symbols
        work_item_ids: list[uuid.UUID] = []
        concepts_flagged = 0

        # Modified: concept existed before AND is still present but content changed
        for fqn, old_concept in old_concepts.items():
            if fqn not in new_fqns:
                # Symbol was deleted from the file
                self._flag_concept(old_concept)
                concepts_flagged += 1
                continue

            # Symbol still exists — check if content hash changed
            refreshed = self._store.get_concept(old_concept.id)
            if refreshed is None:
                continue
            old_hash = _get_content_hash_for_file(old_concept, str(file_path))
            new_hash = _get_content_hash_for_file(refreshed, str(file_path))
            if old_hash is not None and new_hash is not None and old_hash != new_hash:
                # Content genuinely changed
                self._flag_concept(refreshed)
                wi = WorkItem(
                    item_type="verify_concept",
                    concept_id=refreshed.id,
                    description=f"Verify concept after code change: {refreshed.name}",
                    file_path=str(file_path),
                )
                self._store.create_work_item(wi)
                work_item_ids.append(wi.id)
                concepts_flagged += 1

        self._refresh_impact_profiles_for_structural_edge_changes(
            file_path=file_path,
            old_structural_edges=old_structural_edges,
        )

        return work_item_ids, concepts_flagged

    def _flag_concept(self, concept: Concept) -> None:
        """Add the 'needs-review' label to *concept* in the store."""
        if "needs-review" not in concept.labels:
            updated = concept.model_copy(
                update={"labels": concept.labels | {"needs-review"}}
            )
            self._store.update_concept(updated)

    def _flag_concepts_for_deleted_file(self, file_path: str) -> int:
        """Flag all concepts anchored to a deleted file.  Returns count flagged."""
        flagged = 0
        for concept in self._store.search_by_file(file_path):
            self._flag_concept(concept)
            flagged += 1
        return flagged

    def _refresh_impact_profiles_for_structural_edge_changes(
        self,
        *,
        file_path: Path,
        old_structural_edges: set[tuple[uuid.UUID, uuid.UUID]],
    ) -> None:
        """Recompute affected impact profiles when structural edges changed."""
        new_concept_ids = {
            concept.id for concept in self._store.search_by_file(str(file_path))
        }
        # Always refresh profiles for concepts tied to the modified file so
        # blast-radius data stays current immediately after change detection.
        recompute_profiles_for_concepts(self._store, new_concept_ids)
        new_edges = self._structural_edge_fingerprints(new_concept_ids)
        if old_structural_edges == new_edges:
            return

        affected_ids: set[uuid.UUID] = set()
        for source_id, target_id in old_structural_edges.symmetric_difference(new_edges):
            affected_ids.add(source_id)
            affected_ids.add(target_id)

        recompute_profiles_for_concepts(self._store, affected_ids)

    def _structural_edge_fingerprints(
        self, concept_ids: set[uuid.UUID]
    ) -> set[tuple[uuid.UUID, uuid.UUID]]:
        """Return unique structural edge pairs touching any concept in concept_ids."""
        fingerprints: set[tuple[uuid.UUID, uuid.UUID]] = set()
        for concept_id in concept_ids:
            for edge in self._store.list_edges(source_id=concept_id):
                if edge.evidence_type == "structural":
                    fingerprints.add((edge.source_id, edge.target_id))
            for edge in self._store.list_edges(target_id=concept_id):
                if edge.evidence_type == "structural":
                    fingerprints.add((edge.source_id, edge.target_id))
        return fingerprints

    # -----------------------------------------------------------------------
    # State file helpers
    # -----------------------------------------------------------------------

    def _read_last_hash(self) -> Optional[str]:
        if not self._state_file.exists():
            return None
        try:
            data = json.loads(self._state_file.read_text())
            return data.get(_STATE_KEY)
        except (json.JSONDecodeError, OSError):
            return None

    def _write_last_hash(self, commit_hash: str) -> None:
        self._state_file.write_text(json.dumps({_STATE_KEY: commit_hash}))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_content_hash_for_file(concept: Concept, file_path: str) -> Optional[str]:
    """Return the content_hash from the CodeReference matching *file_path*."""
    for ref in concept.code_references:
        if ref.file_path == file_path:
            return ref.content_hash
    return None
