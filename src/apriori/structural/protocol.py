"""Protocols for the structural parsing layer (arch:protocol-first)."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from apriori.structural.models import ParseResult


@runtime_checkable
class LanguageParser(Protocol):
    """Protocol for language-specific parsers.

    Implementations (Python parser, TypeScript parser) receive a ParseResult
    from the Orchestrator and extract higher-level structural information.
    The Orchestrator dispatches to the appropriate LanguageParser based on
    the detected language (arch:tree-sitter-only).
    """

    def parse(self, source: bytes, file_path: Path) -> ParseResult:
        """Parse ``source`` bytes from ``file_path`` and return a ParseResult.

        Args:
            source: Raw UTF-8 source code bytes.
            file_path: The absolute path of the file being parsed (for
                embedding in the result).

        Returns:
            A ParseResult with at minimum ``file_path``, ``language``,
            ``source``, ``tree``, ``parse_errors``, and ``is_valid`` set.
        """
        ...
