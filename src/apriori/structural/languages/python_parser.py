"""Python language parser (Story 3.3, ERD §3.3.1).

Implements the LanguageParser Protocol for .py files. Uses tree-sitter-python
to extract functions, classes, imports, and relationships from Python source.

Architecture constraints (arch:tree-sitter-only, arch:protocol-first,
arch:sync-first).
"""

from __future__ import annotations

from pathlib import Path

import tree_sitter_python as _tspython
from tree_sitter import Language, Node, Parser

from apriori.structural.models import (
    ClassDef,
    FunctionDef,
    Parameter,
    ParseResult,
    Relationship,
)

_PY_LANGUAGE: Language | None = None

_FUNC_NODE_TYPES = frozenset({"function_definition", "async_function_definition"})


def _py_language() -> Language:
    global _PY_LANGUAGE
    if _PY_LANGUAGE is None:
        _PY_LANGUAGE = Language(_tspython.language())
    return _PY_LANGUAGE


def _collect_parse_errors(node: Node) -> list[str]:
    errors: list[str] = []

    def _walk(n: Node) -> None:
        if n.type == "ERROR" or n.is_missing:
            errors.append(
                f"parse error at {n.start_point}: {n.text.decode('utf-8', errors='replace')[:60]!r}"
            )
        for child in n.children:
            _walk(child)

    _walk(node)
    return errors


# ---------------------------------------------------------------------------
# Parameter extraction
# ---------------------------------------------------------------------------


def _extract_parameters(params_node: Node) -> list[Parameter]:
    """Extract parameters from a tree-sitter ``parameters`` node."""
    result: list[Parameter] = []
    for child in params_node.named_children:
        if child.type == "identifier":
            # Simple untyped parameter (incl. `self`, `cls`)
            result.append(Parameter(name=child.text.decode("utf-8")))
        elif child.type == "typed_parameter":
            # typed_parameter: first identifier child is the name;
            # child_by_field_name("type") gives the type annotation.
            name_node = next(
                (c for c in child.children if c.type == "identifier"), None
            )
            type_node = child.child_by_field_name("type")
            if name_node:
                result.append(
                    Parameter(
                        name=name_node.text.decode("utf-8"),
                        type_annotation=(
                            type_node.text.decode("utf-8") if type_node else None
                        ),
                    )
                )
        elif child.type in ("default_parameter", "typed_default_parameter"):
            name_node = child.child_by_field_name("name")
            type_node = child.child_by_field_name("type")
            if name_node:
                result.append(
                    Parameter(
                        name=name_node.text.decode("utf-8"),
                        type_annotation=(
                            type_node.text.decode("utf-8") if type_node else None
                        ),
                    )
                )
        elif child.type in ("list_splat_pattern", "dictionary_splat_pattern"):
            # *args / **kwargs — extract the inner identifier
            inner = next(
                (c for c in child.children if c.type == "identifier"), None
            )
            if inner:
                result.append(Parameter(name=child.text.decode("utf-8")))
    return result


# ---------------------------------------------------------------------------
# Function extraction
# ---------------------------------------------------------------------------


def _extract_function(node: Node, file_path: Path) -> FunctionDef:
    """Extract a FunctionDef from a function_definition or
    async_function_definition node."""
    name_node = node.child_by_field_name("name")
    params_node = node.child_by_field_name("parameters")
    return_node = node.child_by_field_name("return_type")

    name = name_node.text.decode("utf-8") if name_node else "<unknown>"
    is_async = node.type == "async_function_definition"
    parameters = _extract_parameters(params_node) if params_node else []
    return_annotation = (
        return_node.text.decode("utf-8") if return_node else None
    )

    return FunctionDef(
        name=name,
        parameters=parameters,
        return_annotation=return_annotation,
        start_line=node.start_point.row + 1,  # 1-based
        end_line=node.end_point.row + 1,
        file_path=file_path,
        is_async=is_async,
    )


# ---------------------------------------------------------------------------
# Class extraction
# ---------------------------------------------------------------------------


def _extract_class(
    node: Node, file_path: Path
) -> tuple[ClassDef, list[Relationship]]:
    """Extract a ClassDef and its inherits Relationships from a
    class_definition node."""
    name_node = node.child_by_field_name("name")
    class_name = name_node.text.decode("utf-8") if name_node else "<unknown>"

    # Base classes live in an argument_list node (field "superclasses")
    base_classes: list[str] = []
    superclasses_node = node.child_by_field_name("superclasses")
    if superclasses_node:
        for child in superclasses_node.named_children:
            if child.type in ("identifier", "dotted_name"):
                base_classes.append(child.text.decode("utf-8"))

    # Methods in the class body
    methods: list[FunctionDef] = []
    body_node = node.child_by_field_name("body")
    if body_node:
        for child in body_node.children:
            if child.type in _FUNC_NODE_TYPES:
                methods.append(_extract_function(child, file_path))
            elif child.type == "decorated_definition":
                definition = child.child_by_field_name("definition")
                if definition and definition.type in _FUNC_NODE_TYPES:
                    methods.append(_extract_function(definition, file_path))

    cls = ClassDef(
        name=class_name,
        base_classes=base_classes,
        methods=methods,
        start_line=node.start_point.row + 1,
        end_line=node.end_point.row + 1,
        file_path=file_path,
    )

    relationships = [
        Relationship(
            kind="inherits",
            source=class_name,
            target=base,
            file_path=file_path,
            line=node.start_point.row + 1,
        )
        for base in base_classes
    ]

    return cls, relationships


# ---------------------------------------------------------------------------
# Import extraction
# ---------------------------------------------------------------------------


def _extract_imports(node: Node, file_path: Path) -> list[Relationship]:
    """Extract import Relationships from import_statement or
    import_from_statement nodes."""
    relationships: list[Relationship] = []
    line = node.start_point.row + 1

    if node.type == "import_statement":
        # `import os`, `import os.path`, `import a as b`
        for name_node in node.children_by_field_name("name"):
            # aliased_import: child_by_field_name("name") gives the real name
            if name_node.type == "aliased_import":
                real_name = name_node.child_by_field_name("name")
                module = real_name.text.decode("utf-8") if real_name else ""
            else:
                module = name_node.text.decode("utf-8")
            if module:
                relationships.append(
                    Relationship(
                        kind="imports",
                        source="",  # file-level import; source is the file itself
                        target=module,
                        file_path=file_path,
                        line=line,
                    )
                )

    elif node.type == "import_from_statement":
        # `from os.path import join, exists`
        module_node = node.child_by_field_name("module_name")
        module = module_node.text.decode("utf-8") if module_node else ""

        imported_names = node.children_by_field_name("name")
        for name_node in imported_names:
            if name_node.type == "dotted_name":
                target = name_node.text.decode("utf-8")
            elif name_node.type == "aliased_import":
                real = name_node.child_by_field_name("name")
                target = real.text.decode("utf-8") if real else ""
            elif name_node.type == "wildcard_import":
                target = "*"
            else:
                target = name_node.text.decode("utf-8")

            if target:
                relationships.append(
                    Relationship(
                        kind="imports",
                        source=module,
                        target=target,
                        file_path=file_path,
                        line=line,
                    )
                )

    return relationships


# ---------------------------------------------------------------------------
# Call relationship extraction
# ---------------------------------------------------------------------------


def _collect_calls(node: Node, file_path: Path, relationships: list[Relationship]) -> None:
    """Recursively walk *node* and collect attribute-call relationships."""
    if node.type == "call":
        func_node = node.child_by_field_name("function")
        if func_node and func_node.type == "attribute":
            target = func_node.text.decode("utf-8")
            relationships.append(
                Relationship(
                    kind="calls",
                    source="",
                    target=target,
                    file_path=file_path,
                    line=node.start_point.row + 1,
                )
            )
    for child in node.children:
        _collect_calls(child, file_path, relationships)


# ---------------------------------------------------------------------------
# Top-level module walk
# ---------------------------------------------------------------------------


def _walk_module(
    module_node: Node,
    file_path: Path,
    functions: list[FunctionDef],
    classes: list[ClassDef],
    relationships: list[Relationship],
) -> None:
    """Walk top-level children for functions/classes; collect imports/calls from
    the full tree."""
    for child in module_node.children:
        if child.type in _FUNC_NODE_TYPES:
            functions.append(_extract_function(child, file_path))
        elif child.type == "class_definition":
            cls, inherits = _extract_class(child, file_path)
            classes.append(cls)
            relationships.extend(inherits)
        elif child.type in ("import_statement", "import_from_statement"):
            relationships.extend(_extract_imports(child, file_path))
        elif child.type == "decorated_definition":
            definition = child.child_by_field_name("definition")
            if definition is None:
                # Fall back to last named child
                definition = child.named_children[-1] if child.named_children else None
            if definition and definition.type in _FUNC_NODE_TYPES:
                functions.append(_extract_function(definition, file_path))
            elif definition and definition.type == "class_definition":
                cls, inherits = _extract_class(definition, file_path)
                classes.append(cls)
                relationships.extend(inherits)

    # Walk full tree for call relationships
    _collect_calls(module_node, file_path, relationships)


# ---------------------------------------------------------------------------
# PythonParser
# ---------------------------------------------------------------------------


class PythonParser:
    """Language parser for Python (.py) files.

    Implements the LanguageParser Protocol (arch:protocol-first).
    All operations are synchronous (arch:sync-first).
    Parsing uses tree-sitter exclusively (arch:tree-sitter-only).
    """

    def parse(self, source: bytes, file_path: Path) -> ParseResult:
        """Parse Python *source* bytes from *file_path*.

        Args:
            source: Raw UTF-8 Python source code.
            file_path: Absolute path of the source file (embedded in result).

        Returns:
            A ``ParseResult`` with ``functions``, ``classes``, and
            ``relationships`` populated in addition to the standard fields.
        """
        parser = Parser(_py_language())
        tree = parser.parse(source)
        errors = _collect_parse_errors(tree.root_node)

        functions: list[FunctionDef] = []
        classes: list[ClassDef] = []
        relationships: list[Relationship] = []

        _walk_module(tree.root_node, file_path, functions, classes, relationships)

        return ParseResult(
            file_path=file_path,
            language="python",
            source=source,
            tree=tree,
            parse_errors=errors,
            is_valid=len(errors) == 0,
            functions=functions,
            classes=classes,
            relationships=relationships,
        )
