"""Domain models for the structural parsing layer (ERD §3.3)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Parameter(BaseModel):
    """A single function/method parameter."""

    name: str
    type_annotation: str | None = None


class FunctionDef(BaseModel):
    """A function or method definition extracted from source."""

    name: str
    parameters: list[Parameter] = Field(default_factory=list)
    return_annotation: str | None = None
    start_line: int
    end_line: int
    file_path: Path
    is_async: bool = False


class ClassDef(BaseModel):
    """A class definition extracted from source."""

    name: str
    base_classes: list[str] = Field(default_factory=list)
    methods: list[FunctionDef] = Field(default_factory=list)
    start_line: int
    end_line: int
    file_path: Path


class Relationship(BaseModel):
    """A structural relationship between two entities.

    ``kind`` is one of:
    - ``"inherits"``: class → base class
    - ``"imports"``: module or name imported by this file
    - ``"calls"``: one function calls another
    """

    kind: str
    source: str
    target: str
    file_path: Path
    line: int | None = None


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

    # Higher-level entities extracted by language-specific parsers
    functions: list[FunctionDef] = Field(default_factory=list)
    classes: list[ClassDef] = Field(default_factory=list)
    relationships: list[Relationship] = Field(default_factory=list)
