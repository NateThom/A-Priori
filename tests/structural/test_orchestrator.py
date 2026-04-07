"""Tests for the Parsing Orchestrator (Story 3.2).

Each test is directly traceable to an acceptance criterion:
- AC1: Only files matching include patterns are processed
- AC2: .gitignore-excluded directories are skipped
- AC3: Unrecognized extension skipped with debug log
- AC4: File larger than max size skipped with warning
- AC5: 100 source files processed in under 5 seconds
"""

import logging
import time
from pathlib import Path

import pytest

from apriori.structural.orchestrator import Orchestrator, OrchestratorConfig, detect_language


# ---------------------------------------------------------------------------
# AC1: Only files matching include patterns are processed
# ---------------------------------------------------------------------------


def test_only_include_patterns_processed(tmp_path: Path) -> None:
    """Given a repository with .py, .ts, .tsx, .js, and .md files,
    when the orchestrator runs,
    then only source files matching configured include patterns are processed."""
    (tmp_path / "main.py").write_text("def foo(): pass\n")
    (tmp_path / "app.ts").write_text("const x = 1;\n")
    (tmp_path / "component.tsx").write_text("export const C = () => null;\n")
    (tmp_path / "util.js").write_text("function bar() {}\n")
    (tmp_path / "README.md").write_text("# Hello\n")
    (tmp_path / "data.json").write_text('{"key": "value"}\n')

    config = OrchestratorConfig(
        include_patterns=["**/*.py", "**/*.ts", "**/*.tsx", "**/*.js"],
        exclude_patterns=[],
        respect_gitignore=False,
    )
    orchestrator = Orchestrator(config)
    results = list(orchestrator.walk_and_parse(tmp_path))

    processed_extensions = {r[0].suffix for r in results}
    assert ".py" in processed_extensions
    assert ".ts" in processed_extensions
    assert ".tsx" in processed_extensions
    assert ".js" in processed_extensions
    assert ".md" not in processed_extensions
    assert ".json" not in processed_extensions


def test_include_patterns_match_nested_files(tmp_path: Path) -> None:
    """Include patterns with ** match files in subdirectories."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "module.py").write_text("x = 1\n")
    (tmp_path / "top.py").write_text("y = 2\n")
    (tmp_path / "ignored.txt").write_text("text\n")

    config = OrchestratorConfig(
        include_patterns=["**/*.py"],
        exclude_patterns=[],
        respect_gitignore=False,
    )
    orchestrator = Orchestrator(config)
    results = list(orchestrator.walk_and_parse(tmp_path))

    names = {r[0].name for r in results}
    assert "module.py" in names
    assert "top.py" in names
    assert "ignored.txt" not in names


# ---------------------------------------------------------------------------
# AC2: .gitignore-excluded directories are skipped
# ---------------------------------------------------------------------------


def test_gitignore_excluded_dir_skipped(tmp_path: Path) -> None:
    """Given a .gitignore-excluded directory like node_modules/,
    when the orchestrator runs,
    then those files are skipped."""
    node_modules = tmp_path / "node_modules"
    node_modules.mkdir()
    (node_modules / "package.js").write_text("module.exports = {};\n")
    (tmp_path / "main.py").write_text("def foo(): pass\n")
    (tmp_path / ".gitignore").write_text("node_modules/\n")

    config = OrchestratorConfig(
        include_patterns=["**/*.py", "**/*.js"],
        exclude_patterns=[],
        respect_gitignore=True,
    )
    orchestrator = Orchestrator(config)
    results = list(orchestrator.walk_and_parse(tmp_path))

    file_paths = [r[0] for r in results]
    assert not any("node_modules" in str(p) for p in file_paths)
    assert any(p.name == "main.py" for p in file_paths)


def test_gitignore_excludes_multiple_patterns(tmp_path: Path) -> None:
    """Multiple .gitignore patterns are all respected."""
    (tmp_path / ".gitignore").write_text("node_modules/\n.venv/\ndist/\n")

    for excluded_dir in ("node_modules", ".venv", "dist"):
        d = tmp_path / excluded_dir
        d.mkdir()
        (d / "file.py").write_text("pass\n")

    (tmp_path / "keep.py").write_text("x = 1\n")

    config = OrchestratorConfig(
        include_patterns=["**/*.py"],
        exclude_patterns=[],
        respect_gitignore=True,
    )
    orchestrator = Orchestrator(config)
    results = list(orchestrator.walk_and_parse(tmp_path))

    names = [r[0].name for r in results]
    assert names == ["keep.py"]


def test_exclude_patterns_skip_dirs(tmp_path: Path) -> None:
    """Explicit exclude_patterns skip matching files even without .gitignore."""
    cache = tmp_path / "__pycache__"
    cache.mkdir()
    (cache / "module.cpython-311.pyc").write_bytes(b"")
    (tmp_path / "main.py").write_text("x = 1\n")

    config = OrchestratorConfig(
        include_patterns=["**/*.py", "**/*.pyc"],
        exclude_patterns=["**/__pycache__/**"],
        respect_gitignore=False,
    )
    orchestrator = Orchestrator(config)
    results = list(orchestrator.walk_and_parse(tmp_path))

    assert len(results) == 1
    assert results[0][0].name == "main.py"


# ---------------------------------------------------------------------------
# AC3: Unrecognized extension skipped with debug log
# ---------------------------------------------------------------------------


def test_unrecognized_extension_skipped_with_debug_log(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Given a file with an unrecognized extension (.xyz),
    when encountered,
    then it is skipped and a DEBUG message is emitted."""
    (tmp_path / "data.xyz").write_text("some content\n")
    (tmp_path / "main.py").write_text("def foo(): pass\n")

    config = OrchestratorConfig(
        include_patterns=["**/*.xyz", "**/*.py"],
        exclude_patterns=[],
        respect_gitignore=False,
    )
    orchestrator = Orchestrator(config)
    with caplog.at_level(logging.DEBUG, logger="apriori.structural.orchestrator"):
        results = list(orchestrator.walk_and_parse(tmp_path))

    processed_paths = [r[0] for r in results]
    assert not any(p.suffix == ".xyz" for p in processed_paths)
    assert any(p.suffix == ".py" for p in processed_paths)

    debug_messages = [
        rec.message for rec in caplog.records if rec.levelno == logging.DEBUG
    ]
    assert any("data.xyz" in msg or ".xyz" in msg for msg in debug_messages)


# ---------------------------------------------------------------------------
# AC4: File larger than max_file_size_bytes skipped with warning
# ---------------------------------------------------------------------------


def test_large_file_skipped_with_warning(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Given a file larger than the configured max file size,
    when encountered,
    then it is skipped and a WARNING is emitted."""
    large_file = tmp_path / "large.py"
    large_file.write_bytes(b"x = 1\n" * 200)  # 1200 bytes
    (tmp_path / "small.py").write_text("y = 2\n")

    config = OrchestratorConfig(
        include_patterns=["**/*.py"],
        exclude_patterns=[],
        respect_gitignore=False,
        max_file_size_bytes=100,  # 100-byte limit
    )
    orchestrator = Orchestrator(config)
    with caplog.at_level(logging.WARNING, logger="apriori.structural.orchestrator"):
        results = list(orchestrator.walk_and_parse(tmp_path))

    processed_paths = [r[0] for r in results]
    assert not any(p.name == "large.py" for p in processed_paths)
    assert any(p.name == "small.py" for p in processed_paths)

    warning_messages = [
        rec.message for rec in caplog.records if rec.levelno == logging.WARNING
    ]
    assert any("large.py" in msg for msg in warning_messages)


# ---------------------------------------------------------------------------
# AC5: Performance — 100 source files in under 5 seconds
# ---------------------------------------------------------------------------


def test_performance_100_files(tmp_path: Path) -> None:
    """Given 100 source files,
    when the orchestrator processes them,
    then total wall-clock time is under 5 seconds."""
    for i in range(50):
        (tmp_path / f"module_{i:03d}.py").write_text(
            f"def func_{i}(x, y):\n    return x + y\n\nclass Cls_{i}:\n    pass\n"
        )
    for i in range(50):
        (tmp_path / f"service_{i:03d}.ts").write_text(
            f"export function fn_{i}(x: number): number {{ return x * 2; }}\n"
        )

    config = OrchestratorConfig(
        include_patterns=["**/*.py", "**/*.ts"],
        exclude_patterns=[],
        respect_gitignore=False,
    )
    orchestrator = Orchestrator(config)

    start = time.monotonic()
    results = list(orchestrator.walk_and_parse(tmp_path))
    elapsed = time.monotonic() - start

    assert len(results) == 100
    assert elapsed < 5.0, f"Processing 100 files took {elapsed:.2f}s (limit: 5s)"


# ---------------------------------------------------------------------------
# Language detection
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "filename, expected_language",
    [
        ("foo.py", "python"),
        ("foo.ts", "typescript"),
        ("foo.tsx", "typescript"),
        ("foo.js", "javascript"),
        ("foo.jsx", "javascript"),
        ("foo.md", None),
        ("foo.json", None),
        ("foo.yaml", None),
        ("foo.txt", None),
    ],
)
def test_detect_language(filename: str, expected_language: str | None) -> None:
    """Language is correctly detected (or None) from file extension."""
    assert detect_language(Path(filename)) == expected_language


# ---------------------------------------------------------------------------
# ParseResult structure
# ---------------------------------------------------------------------------


def test_parse_result_structure_python(tmp_path: Path) -> None:
    """ParseResult for a Python file has correct fields."""
    (tmp_path / "main.py").write_text("def foo(x):\n    return x + 1\n")

    config = OrchestratorConfig(
        include_patterns=["**/*.py"],
        exclude_patterns=[],
        respect_gitignore=False,
    )
    orchestrator = Orchestrator(config)
    results = list(orchestrator.walk_and_parse(tmp_path))

    assert len(results) == 1
    file_path, language, parse_result = results[0]

    assert file_path.name == "main.py"
    assert language == "python"
    assert parse_result.file_path.name == "main.py"
    assert parse_result.language == "python"
    assert isinstance(parse_result.parse_errors, list)
    assert isinstance(parse_result.is_valid, bool)
    assert parse_result.is_valid


def test_parse_result_structure_typescript(tmp_path: Path) -> None:
    """ParseResult for a TypeScript file has correct fields and language."""
    (tmp_path / "app.ts").write_text("const x: number = 42;\n")

    config = OrchestratorConfig(
        include_patterns=["**/*.ts"],
        exclude_patterns=[],
        respect_gitignore=False,
    )
    orchestrator = Orchestrator(config)
    results = list(orchestrator.walk_and_parse(tmp_path))

    assert len(results) == 1
    _, language, parse_result = results[0]
    assert language == "typescript"
    assert parse_result.language == "typescript"


def test_parse_result_structure_tsx(tmp_path: Path) -> None:
    """ParseResult for a TSX file uses the TSX parser and reports language=typescript."""
    (tmp_path / "Component.tsx").write_text(
        "export const C = () => <div>hello</div>;\n"
    )

    config = OrchestratorConfig(
        include_patterns=["**/*.tsx"],
        exclude_patterns=[],
        respect_gitignore=False,
    )
    orchestrator = Orchestrator(config)
    results = list(orchestrator.walk_and_parse(tmp_path))

    assert len(results) == 1
    _, language, parse_result = results[0]
    assert language == "typescript"
    assert parse_result.language == "typescript"


def test_parse_result_js_uses_typescript_parser(tmp_path: Path) -> None:
    """JavaScript files (.js/.jsx) are parsed using the TypeScript parser."""
    (tmp_path / "util.js").write_text("function greet(name) { return 'hi ' + name; }\n")

    config = OrchestratorConfig(
        include_patterns=["**/*.js"],
        exclude_patterns=[],
        respect_gitignore=False,
    )
    orchestrator = Orchestrator(config)
    results = list(orchestrator.walk_and_parse(tmp_path))

    assert len(results) == 1
    _, language, parse_result = results[0]
    assert language == "javascript"
    assert parse_result.language == "javascript"
    assert parse_result.is_valid


def test_walk_and_parse_yields_tuples(tmp_path: Path) -> None:
    """walk_and_parse yields (file_path, language, parse_result) tuples."""
    (tmp_path / "a.py").write_text("pass\n")
    (tmp_path / "b.ts").write_text("const x = 1;\n")

    config = OrchestratorConfig(
        include_patterns=["**/*.py", "**/*.ts"],
        exclude_patterns=[],
        respect_gitignore=False,
    )
    orchestrator = Orchestrator(config)
    results = list(orchestrator.walk_and_parse(tmp_path))

    assert len(results) == 2
    for item in results:
        assert len(item) == 3
        file_path, language, parse_result = item
        assert isinstance(file_path, Path)
        assert isinstance(language, str)
        assert language in ("python", "typescript", "javascript")
