"""Domain models for the structural parsing layer (ERD §3.3)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ParseResult(BaseModel):
    """Result of parsing a single source file via tree-sitter.

    Produced by the Orchestrator (story 3.2) and consumed by language-specific
    parsers (stories 3.3, 3.4) that extract higher-level constructs from the
    raw tree.

    The ``tree`` field holds the tree-sitter Tree object, which is not
    serializable. Callers that need to persist results should work with the
    other fields only.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    file_path: Path
    language: str
    source: bytes
    tree: Any = Field(default=None, exclude=True)
    parse_errors: list[str] = Field(default_factory=list)
    is_valid: bool = True
