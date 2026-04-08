"""Domain models for the structural parsing layer (ERD §3.3)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class FunctionParam(BaseModel):
    """A single parameter in a function signature."""

    name: str
    type_annotation: str | None = None


class FunctionEntity(BaseModel):
    """A function or arrow-function extracted from source.

    Covers top-level ``function`` declarations, ``const f = () => {}``
    assignments, and Python ``def``/``async def`` definitions.
    """

    name: str
    params: list[FunctionParam] = Field(default_factory=list)
    return_type: str | None = None
    start_line: int
    end_line: int
    file_path: Path
    is_exported: bool = False
    is_async: bool = False


class ClassEntity(BaseModel):
    """A class extracted from source.

    ``bases`` records the names of extended classes, representing
    ``inherits`` relationships in the structural graph.
    ``methods`` holds method definitions for languages that nest them (Python).
    """

    name: str
    bases: list[str] = Field(default_factory=list)
    methods: list[FunctionEntity] = Field(default_factory=list)
    start_line: int
    end_line: int
    file_path: Path
    is_exported: bool = False


class InterfaceEntity(BaseModel):
    """A TypeScript interface extracted as a structural entity (ERD §3.3.1)."""

    name: str
    start_line: int
    end_line: int
    file_path: Path
    is_exported: bool = False


class ImportRelationship(BaseModel):
    """An import statement extracted from source.

    ``names`` contains the imported identifiers from ``import { Foo } from …``.
    For default or namespace imports ``names`` is empty and only
    ``source_module`` is meaningful.
    """

    source_module: str
    names: list[str] = Field(default_factory=list)
    file_path: Path
    start_line: int


class ReExport(BaseModel):
    """A re-export statement, tracking barrel-file re-exports.

    ``is_all=True``  → ``export * from '…'``
    ``is_all=False`` → ``export { Foo } from '…'``

    ``names`` lists the re-exported identifiers when ``is_all=False``.
    """

    source_module: str
    names: list[str] = Field(default_factory=list)
    file_path: Path
    start_line: int
    is_all: bool = True


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

    Produced by the Orchestrator (story 3.2) and populated with extracted
    structural entities by language-specific parsers (stories 3.3, 3.4).

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

    # Structural entities populated by language-specific parsers
    functions: list[FunctionEntity] = Field(default_factory=list)
    classes: list[ClassEntity] = Field(default_factory=list)
    interfaces: list[InterfaceEntity] = Field(default_factory=list)
    imports: list[ImportRelationship] = Field(default_factory=list)
    re_exports: list[ReExport] = Field(default_factory=list)
    relationships: list[Relationship] = Field(default_factory=list)
