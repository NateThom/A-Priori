"""Parsing Orchestrator for the structural layer (Story 3.2, ERD §3.3.1).

Walks a repository file tree, applies include/exclude filters and .gitignore
rules, detects language by extension, and dispatches each file to the
appropriate tree-sitter parser.  Yields ``(file_path, language, ParseResult)``
tuples for every successfully parsed file.

Language detection (arch:tree-sitter-only):
  .py               → python
  .ts / .tsx        → typescript   (tsx uses tree-sitter TSX grammar)
  .js / .jsx        → javascript   (parsed with tree-sitter TypeScript grammar)
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterator

import pathspec
import tree_sitter_python as _tspython
import tree_sitter_typescript as _tstypescript
from pydantic import BaseModel, Field
from tree_sitter import Language, Parser

from apriori.structural.models import ParseResult

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lazy-loaded tree-sitter Language / Parser singletons
# ---------------------------------------------------------------------------

_PY_LANGUAGE: Language | None = None
_TS_LANGUAGE: Language | None = None
_TSX_LANGUAGE: Language | None = None


def _py_language() -> Language:
    global _PY_LANGUAGE
    if _PY_LANGUAGE is None:
        _PY_LANGUAGE = Language(_tspython.language())
    return _PY_LANGUAGE


def _ts_language() -> Language:
    global _TS_LANGUAGE
    if _TS_LANGUAGE is None:
        _TS_LANGUAGE = Language(_tstypescript.language_typescript())
    return _TS_LANGUAGE


def _tsx_language() -> Language:
    global _TSX_LANGUAGE
    if _TSX_LANGUAGE is None:
        _TSX_LANGUAGE = Language(_tstypescript.language_tsx())
    return _TSX_LANGUAGE


# ---------------------------------------------------------------------------
# Language detection
# ---------------------------------------------------------------------------

_EXTENSION_TO_LANGUAGE: dict[str, str] = {
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
}


def detect_language(file_path: Path) -> str | None:
    """Return the language name for *file_path* based on extension, or None.

    Recognised mappings (per Technical Notes):
      .py              → "python"
      .ts / .tsx       → "typescript"
      .js / .jsx       → "javascript"

    Args:
        file_path: Any path — only the suffix is used.

    Returns:
        A language string, or ``None`` when the extension is not recognised.
    """
    return _EXTENSION_TO_LANGUAGE.get(file_path.suffix.lower())


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


class OrchestratorConfig(BaseModel):
    """Configuration for the Parsing Orchestrator.

    Attributes:
        include_patterns: Glob patterns (relative to repo root) for files to
            include.  Defaults to all Python, TypeScript, and JavaScript
            source files.
        exclude_patterns: Glob patterns for paths to exclude.  Applied *after*
            .gitignore rules.  Defaults to common generated/dependency dirs.
        max_file_size_bytes: Files larger than this are skipped with a WARNING.
            Defaults to 1 MB.
        respect_gitignore: When ``True`` (default), the orchestrator reads
            all ``.gitignore`` files found under the repo root and skips
            matched paths.
    """

    include_patterns: list[str] = Field(
        default=[
            "**/*.py",
            "**/*.ts",
            "**/*.tsx",
            "**/*.js",
            "**/*.jsx",
        ]
    )
    exclude_patterns: list[str] = Field(
        default=[
            "**/node_modules/**",
            "**/.git/**",
            "**/__pycache__/**",
            "**/.venv/**",
            "**/dist/**",
            "**/build/**",
        ]
    )
    max_file_size_bytes: int = Field(default=1_000_000, gt=0)
    respect_gitignore: bool = True


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _load_gitignore_spec(repo_root: Path) -> pathspec.PathSpec | None:
    """Collect all .gitignore files under *repo_root* and build a PathSpec.

    Only files named ``.gitignore`` are read (not ``.git/info/exclude`` or
    global gitconfig ignores) — sufficient for the acceptance criterion.

    Args:
        repo_root: Root directory of the repository.

    Returns:
        A compiled ``pathspec.PathSpec`` if any .gitignore files were found,
        otherwise ``None``.
    """
    patterns: list[str] = []
    for gitignore in repo_root.rglob(".gitignore"):
        try:
            text = gitignore.read_text(encoding="utf-8", errors="replace")
            patterns.extend(text.splitlines())
        except OSError:
            logger.debug("Could not read %s", gitignore)

    if not patterns:
        return None
    return pathspec.PathSpec.from_lines("gitignore", patterns)


def _build_exclude_spec(patterns: list[str]) -> pathspec.PathSpec | None:
    if not patterns:
        return None
    return pathspec.PathSpec.from_lines("gitignore", patterns)


def _collect_errors(node) -> list[str]:
    """Walk tree-sitter nodes and collect ERROR / MISSING node descriptions."""
    errors: list[str] = []

    def _walk(n) -> None:
        if n.type == "ERROR" or n.is_missing:
            errors.append(
                f"parse error at {n.start_point}: {n.text.decode('utf-8', errors='replace')[:60]!r}"
            )
        for child in n.children:
            _walk(child)

    _walk(node)
    return errors


def _parse_source(source: bytes, language: str, file_path: Path) -> ParseResult:
    """Parse *source* bytes for *language* and return a ParseResult."""
    if language == "python":
        parser = Parser(_py_language())
    elif language == "typescript":
        # Use TSX grammar for .tsx files so JSX is valid
        if file_path.suffix.lower() == ".tsx":
            parser = Parser(_tsx_language())
        else:
            parser = Parser(_ts_language())
    else:
        # javascript / javascript-jsx: TypeScript grammar parses JS cleanly
        if file_path.suffix.lower() == ".jsx":
            parser = Parser(_tsx_language())
        else:
            parser = Parser(_ts_language())

    tree = parser.parse(source)
    errors = _collect_errors(tree.root_node)

    return ParseResult(
        file_path=file_path,
        language=language,
        source=source,
        tree=tree,
        parse_errors=errors,
        is_valid=len(errors) == 0,
    )


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


class Orchestrator:
    """File-tree walker that dispatches source files to tree-sitter parsers.

    Given a repository root, the orchestrator:
    1. Recursively walks all files.
    2. Applies include_patterns (glob match against the file path).
    3. Skips files matching exclude_patterns or .gitignore rules.
    4. Skips files exceeding ``max_file_size_bytes`` (WARNING log).
    5. Skips files with unrecognised extensions (DEBUG log).
    6. Parses accepted files with the appropriate tree-sitter grammar.
    7. Yields ``(file_path, language, ParseResult)`` for each parsed file.

    All operations are synchronous (arch:sync-first).
    """

    def __init__(self, config: OrchestratorConfig | None = None) -> None:
        self._config = config or OrchestratorConfig()

    def walk_and_parse(
        self, repo_root: Path
    ) -> Iterator[tuple[Path, str, ParseResult]]:
        """Walk *repo_root* and yield parsed results for each matching file.

        Args:
            repo_root: Absolute path to the repository root directory.

        Yields:
            Three-tuples of ``(file_path, language, parse_result)`` where:
            - ``file_path`` is the absolute Path of the parsed file.
            - ``language`` is one of ``"python"``, ``"typescript"``,
              ``"javascript"``.
            - ``parse_result`` is a :class:`ParseResult` instance.
        """
        config = self._config
        repo_root = repo_root.resolve()

        # Build include / exclude matchers
        include_spec = pathspec.PathSpec.from_lines(
            "gitignore", config.include_patterns
        )
        exclude_spec = _build_exclude_spec(config.exclude_patterns)
        gitignore_spec = (
            _load_gitignore_spec(repo_root) if config.respect_gitignore else None
        )

        for file_path in sorted(repo_root.rglob("*")):
            if not file_path.is_file():
                continue

            # Relative path used for pattern matching
            try:
                rel = file_path.relative_to(repo_root)
            except ValueError:
                continue

            rel_str = rel.as_posix()

            # Apply include filter
            if not include_spec.match_file(rel_str):
                continue

            # Apply exclude patterns
            if exclude_spec and exclude_spec.match_file(rel_str):
                logger.debug("Excluded by pattern: %s", rel_str)
                continue

            # Apply .gitignore rules
            if gitignore_spec and gitignore_spec.match_file(rel_str):
                logger.debug("Excluded by .gitignore: %s", rel_str)
                continue

            # Language detection — skip unrecognised extensions
            language = detect_language(file_path)
            if language is None:
                logger.debug(
                    "Skipping %s: unrecognised extension %r",
                    file_path.name,
                    file_path.suffix,
                )
                continue

            # Size guard
            file_size = file_path.stat().st_size
            if file_size > config.max_file_size_bytes:
                logger.warning(
                    "Skipping %s: file size %d bytes exceeds limit %d bytes",
                    file_path.name,
                    file_size,
                    config.max_file_size_bytes,
                )
                continue

            # Read and parse
            try:
                source = file_path.read_bytes()
            except OSError as exc:
                logger.warning("Could not read %s: %s", file_path, exc)
                continue

            parse_result = _parse_source(source, language, file_path)
            yield file_path, language, parse_result
