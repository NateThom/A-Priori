"""TypeScript language parser (Story 3.4, AP-62).

Implements the LanguageParser protocol for ``.ts``, ``.tsx``, ``.js``, and
``.jsx`` files.  Uses tree-sitter-typescript with the TypeScript grammar for
``.ts``/``.js`` files and the TSX grammar for ``.tsx``/``.jsx`` files
(arch:tree-sitter-only).

All operations are synchronous (arch:sync-first).
"""

from __future__ import annotations

import re
from pathlib import Path

import tree_sitter_typescript as _tstypescript
from tree_sitter import Language, Parser

from apriori.structural.models import (
    ClassEntity,
    FunctionEntity,
    FunctionParam,
    ImportRelationship,
    InterfaceEntity,
    ParseResult,
    ReExport,
    Relationship,
)

# ---------------------------------------------------------------------------
# Lazy-loaded grammar singletons
# ---------------------------------------------------------------------------

_TS_LANGUAGE: Language | None = None
_TSX_LANGUAGE: Language | None = None


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
# Helpers
# ---------------------------------------------------------------------------

_TSX_SUFFIXES = frozenset((".tsx", ".jsx"))
_TS_SUFFIXES = frozenset((".ts", ".js"))


def _select_language(file_path: Path) -> Language:
    """Return the tree-sitter Language for the given file extension."""
    if file_path.suffix.lower() in _TSX_SUFFIXES:
        return _tsx_language()
    return _ts_language()


def _detect_language_name(file_path: Path) -> str:
    """Return 'typescript' for .ts/.tsx or 'javascript' for .js/.jsx."""
    if file_path.suffix.lower() in (".ts", ".tsx"):
        return "typescript"
    return "javascript"


def _text(node) -> str:
    """Decode a tree-sitter node's text as UTF-8."""
    return node.text.decode("utf-8", errors="replace")


def _strip_type_annotation(raw: str) -> str:
    """Strip the leading colon (and whitespace) from a type_annotation text.

    Tree-sitter returns the full token including the ``:``, e.g. ``: number``.
    """
    raw = raw.strip()
    if raw.startswith(":"):
        raw = raw[1:].strip()
    return raw


def _strip_quotes(raw: str) -> str:
    """Strip surrounding quote characters from a string-literal text."""
    raw = raw.strip()
    if len(raw) >= 2 and raw[0] in ('"', "'", "`") and raw[-1] == raw[0]:
        return raw[1:-1]
    return raw.strip("\"'`")


_TS_TYPE_STOPWORDS = frozenset(
    {
        "string",
        "number",
        "boolean",
        "void",
        "unknown",
        "any",
        "never",
        "undefined",
        "null",
        "true",
        "false",
        "readonly",
        "keyof",
        "typeof",
        "infer",
        "extends",
        "implements",
        "class",
        "interface",
        "function",
        "new",
        "import",
        "export",
        "from",
        "const",
        "let",
        "var",
        "type",
        "as",
    }
)


def _extract_type_names(raw_type: str | None) -> list[str]:
    """Extract candidate type identifiers from a type string."""
    if not raw_type:
        return []

    names: list[str] = []
    for token in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", raw_type):
        if token in _TS_TYPE_STOPWORDS:
            continue
        names.append(token)
    return names


def _collect_errors(node) -> list[str]:
    """Walk the AST and collect all ERROR / MISSING nodes."""
    errors: list[str] = []

    def _walk(n) -> None:
        if n.type == "ERROR" or n.is_missing:
            errors.append(
                f"parse error at {n.start_point}: "
                f"{n.text.decode('utf-8', errors='replace')[:60]!r}"
            )
        for child in n.children:
            _walk(child)

    _walk(node)
    return errors


# ---------------------------------------------------------------------------
# TypeScriptParser
# ---------------------------------------------------------------------------


class TypeScriptParser:
    """Language parser for TypeScript, JavaScript, TSX, and JSX files.

    Implements the LanguageParser protocol (arch:protocol-first) and uses
    tree-sitter-typescript for AST construction (arch:tree-sitter-only).
    """

    def parse(self, source: bytes, file_path: Path) -> ParseResult:
        """Parse *source* bytes from *file_path* and return a :class:`ParseResult`.

        Extracts:
        - Top-level function declarations and const arrow functions
        - Class declarations with ``extends`` (inherits relationships)
        - Interface declarations
        - Import statements (named and default)
        - Re-export statements (``export *`` and ``export { … } from``

        Args:
            source: Raw UTF-8 source code bytes.
            file_path: Absolute path of the file being parsed.  Determines
                which grammar to use (TS vs TSX) and the ``language`` field.

        Returns:
            A :class:`ParseResult` with all structural entity lists populated.
        """
        grammar = _select_language(file_path)
        parser = Parser(grammar)
        tree = parser.parse(source)
        errors = _collect_errors(tree.root_node)

        functions: list[FunctionEntity] = []
        classes: list[ClassEntity] = []
        interfaces: list[InterfaceEntity] = []
        imports: list[ImportRelationship] = []
        re_exports: list[ReExport] = []
        relationships: list[Relationship] = []

        for node in tree.root_node.children:
            self._extract_top_level(
                node, file_path, functions, classes, interfaces, imports, re_exports, relationships
            )

        return ParseResult(
            file_path=file_path,
            language=_detect_language_name(file_path),
            source=source,
            tree=tree,
            parse_errors=errors,
            is_valid=len(errors) == 0,
            functions=functions,
            classes=classes,
            interfaces=interfaces,
            imports=imports,
            re_exports=re_exports,
            relationships=relationships,
        )

    # ------------------------------------------------------------------
    # Top-level dispatch
    # ------------------------------------------------------------------

    def _extract_top_level(
        self,
        node,
        file_path: Path,
        functions: list[FunctionEntity],
        classes: list[ClassEntity],
        interfaces: list[InterfaceEntity],
        imports: list[ImportRelationship],
        re_exports: list[ReExport],
        relationships: list[Relationship],
    ) -> None:
        ntype = node.type

        if ntype == "function_declaration":
            func = self._extract_function_decl(node, file_path, is_exported=False)
            if func:
                functions.append(func)
                self._collect_function_relationships(node, func, func.name, file_path, relationships)

        elif ntype == "class_declaration":
            cls = self._extract_class_decl(
                node, file_path, is_exported=False, relationships=relationships
            )
            if cls:
                classes.append(cls)

        elif ntype == "interface_declaration":
            iface = self._extract_interface_decl(
                node, file_path, is_exported=False, relationships=relationships
            )
            if iface:
                interfaces.append(iface)

        elif ntype in ("lexical_declaration", "variable_declaration"):
            for func in self._extract_arrow_funcs(
                node, file_path, is_exported=False, relationships=relationships
            ):
                functions.append(func)

        elif ntype == "export_statement":
            self._extract_export_stmt(
                node, file_path, functions, classes, interfaces, re_exports, relationships
            )

        elif ntype == "import_statement":
            imp = self._extract_import_stmt(node, file_path)
            if imp:
                imports.append(imp)

    # ------------------------------------------------------------------
    # Declaration extractors
    # ------------------------------------------------------------------

    def _extract_function_decl(
        self, node, file_path: Path, is_exported: bool
    ) -> FunctionEntity | None:
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return None
        return FunctionEntity(
            name=_text(name_node),
            params=self._extract_params(node.child_by_field_name("parameters")),
            return_type=self._extract_return_type(
                node.child_by_field_name("return_type")
            ),
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
            file_path=file_path,
            is_exported=is_exported,
        )

    def _extract_class_decl(
        self,
        node,
        file_path: Path,
        is_exported: bool,
        relationships: list[Relationship] | None = None,
    ) -> ClassEntity | None:
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return None
        class_name = _text(name_node)
        methods = self._extract_class_methods(node, file_path)

        if relationships is not None:
            self._collect_inherits_relationships(node, class_name, file_path, relationships)
            for method in methods:
                method_node = self._find_method_definition_node(node, method.name)
                if method_node is None:
                    continue
                source_name = f"{class_name}::{method.name}"
                self._collect_function_relationships(
                    method_node,
                    method,
                    source_name,
                    file_path,
                    relationships,
                )

        return ClassEntity(
            name=class_name,
            bases=self._extract_bases(node),
            methods=methods,
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
            file_path=file_path,
            is_exported=is_exported,
        )

    def _extract_interface_decl(
        self,
        node,
        file_path: Path,
        is_exported: bool,
        relationships: list[Relationship] | None = None,
    ) -> InterfaceEntity | None:
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return None
        interface_name = _text(name_node)
        if relationships is not None:
            self._collect_interface_inherits_relationships(
                node, interface_name, file_path, relationships
            )
        return InterfaceEntity(
            name=interface_name,
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
            file_path=file_path,
            is_exported=is_exported,
        )

    def _extract_arrow_funcs(
        self,
        decl_node,
        file_path: Path,
        is_exported: bool,
        relationships: list[Relationship] | None = None,
    ) -> list[FunctionEntity]:
        """Extract arrow functions from a lexical/variable_declaration node."""
        results: list[FunctionEntity] = []
        for child in decl_node.children:
            if child.type != "variable_declarator":
                continue
            name_node = child.child_by_field_name("name")
            value_node = child.child_by_field_name("value")
            if name_node is None or value_node is None:
                continue
            if value_node.type != "arrow_function":
                continue
            func = FunctionEntity(
                name=_text(name_node),
                params=self._extract_params(
                    value_node.child_by_field_name("parameters")
                ),
                return_type=self._extract_return_type(
                    value_node.child_by_field_name("return_type")
                ),
                start_line=decl_node.start_point[0] + 1,
                end_line=decl_node.end_point[0] + 1,
                file_path=file_path,
                is_exported=is_exported,
            )
            if relationships is not None:
                self._collect_function_relationships(
                    value_node,
                    func,
                    func.name,
                    file_path,
                    relationships,
                )
            results.append(func)
        return results

    # ------------------------------------------------------------------
    # Export statement dispatch
    # ------------------------------------------------------------------

    def _extract_export_stmt(
        self,
        node,
        file_path: Path,
        functions: list[FunctionEntity],
        classes: list[ClassEntity],
        interfaces: list[InterfaceEntity],
        re_exports: list[ReExport],
        relationships: list[Relationship],
    ) -> None:
        # Case 1: export declaration (export function/class/interface/const)
        decl = node.child_by_field_name("declaration")
        if decl is not None:
            ntype = decl.type
            if ntype == "function_declaration":
                func = self._extract_function_decl(decl, file_path, is_exported=True)
                if func:
                    functions.append(func)
                    self._collect_function_relationships(
                        decl,
                        func,
                        func.name,
                        file_path,
                        relationships,
                    )
            elif ntype == "class_declaration":
                cls = self._extract_class_decl(
                    decl,
                    file_path,
                    is_exported=True,
                    relationships=relationships,
                )
                if cls:
                    classes.append(cls)
            elif ntype == "interface_declaration":
                iface = self._extract_interface_decl(
                    decl,
                    file_path,
                    is_exported=True,
                    relationships=relationships,
                )
                if iface:
                    interfaces.append(iface)
            elif ntype in ("lexical_declaration", "variable_declaration"):
                for func in self._extract_arrow_funcs(
                    decl,
                    file_path,
                    is_exported=True,
                    relationships=relationships,
                ):
                    functions.append(func)
            return

        # Case 2: re-export — must have a source string
        source_node = node.child_by_field_name("source")
        if source_node is None:
            return  # local export { Foo } with no source — not a re-export

        source_module = _strip_quotes(_text(source_node))
        export_clause = next(
            (c for c in node.children if c.type == "export_clause"), None
        )

        if export_clause is not None:
            # export { Foo, Bar } from '…'
            names = self._extract_export_clause_names(export_clause)
            re_exports.append(
                ReExport(
                    source_module=source_module,
                    names=names,
                    file_path=file_path,
                    start_line=node.start_point[0] + 1,
                    is_all=False,
                )
            )
        else:
            # export * from '…'  (no export_clause, no declaration)
            re_exports.append(
                ReExport(
                    source_module=source_module,
                    names=[],
                    file_path=file_path,
                    start_line=node.start_point[0] + 1,
                    is_all=True,
                )
            )

    # ------------------------------------------------------------------
    # Import statement
    # ------------------------------------------------------------------

    def _extract_import_stmt(
        self, node, file_path: Path
    ) -> ImportRelationship | None:
        source_node = node.child_by_field_name("source")
        if source_node is None:
            return None

        source_module = _strip_quotes(_text(source_node))
        names: list[str] = []

        # import_clause is an unnamed child of import_statement
        import_clause = next(
            (c for c in node.children if c.type == "import_clause"), None
        )
        if import_clause is not None:
            named_imports = next(
                (c for c in import_clause.children if c.type == "named_imports"),
                None,
            )
            if named_imports is not None:
                for child in named_imports.children:
                    if child.type == "import_specifier":
                        name_node = child.child_by_field_name("name")
                        if name_node is not None:
                            names.append(_text(name_node))

        return ImportRelationship(
            source_module=source_module,
            names=names,
            file_path=file_path,
            start_line=node.start_point[0] + 1,
        )

    # ------------------------------------------------------------------
    # Parameter / type helpers
    # ------------------------------------------------------------------

    def _extract_params(self, params_node) -> list[FunctionParam]:
        """Extract parameters from a formal_parameters node."""
        if params_node is None:
            return []
        result: list[FunctionParam] = []
        for child in params_node.children:
            if child.type not in (
                "required_parameter",
                "optional_parameter",
                "rest_parameter",
            ):
                continue
            pattern = child.child_by_field_name("pattern")
            type_node = child.child_by_field_name("type")
            if pattern is None:
                continue
            type_ann: str | None = None
            if type_node is not None:
                type_ann = _strip_type_annotation(_text(type_node))
            result.append(FunctionParam(name=_text(pattern), type_annotation=type_ann))
        return result

    def _extract_return_type(self, return_type_node) -> str | None:
        """Extract the return type string from a type_annotation node."""
        if return_type_node is None:
            return None
        return _strip_type_annotation(_text(return_type_node))

    def _extract_bases(self, class_node) -> list[str]:
        """Extract base class names from a class_declaration node."""
        heritage = next(
            (c for c in class_node.children if c.type == "class_heritage"), None
        )
        if heritage is None:
            return []
        bases: list[str] = []
        for child in heritage.children:
            if child.type == "extends_clause":
                value = child.child_by_field_name("value")
                if value is not None:
                    bases.append(_text(value))
        return bases

    def _extract_export_clause_names(self, export_clause_node) -> list[str]:
        """Extract exported identifier names from an export_clause node."""
        names: list[str] = []
        for child in export_clause_node.children:
            if child.type == "export_specifier":
                name_node = child.child_by_field_name("name")
                if name_node is not None:
                    names.append(_text(name_node))
        return names

    def _extract_class_methods(self, class_node, file_path: Path) -> list[FunctionEntity]:
        methods: list[FunctionEntity] = []
        body = class_node.child_by_field_name("body")
        if body is None:
            return methods
        for child in body.children:
            if child.type != "method_definition":
                continue
            name_node = child.child_by_field_name("name")
            if name_node is None:
                continue
            methods.append(
                FunctionEntity(
                    name=_text(name_node),
                    params=self._extract_params(child.child_by_field_name("parameters")),
                    return_type=self._extract_return_type(
                        child.child_by_field_name("return_type")
                    ),
                    start_line=child.start_point[0] + 1,
                    end_line=child.end_point[0] + 1,
                    file_path=file_path,
                    is_exported=False,
                    is_async=any(grand.type == "async" for grand in child.children),
                )
            )
        return methods

    def _find_method_definition_node(self, class_node, method_name: str):
        body = class_node.child_by_field_name("body")
        if body is None:
            return None
        for child in body.children:
            if child.type != "method_definition":
                continue
            name_node = child.child_by_field_name("name")
            if name_node is not None and _text(name_node) == method_name:
                return child
        return None

    def _collect_function_relationships(
        self,
        function_node,
        func: FunctionEntity,
        source_name: str,
        file_path: Path,
        relationships: list[Relationship],
    ) -> None:
        self._collect_call_relationships(function_node, source_name, file_path, relationships)
        self._collect_type_reference_relationships(
            source_name, func.params, func.return_type, function_node, file_path, relationships
        )

    def _collect_call_relationships(
        self,
        node,
        source_name: str,
        file_path: Path,
        relationships: list[Relationship],
    ) -> None:
        if node.type in ("call_expression", "new_expression"):
            target_name = self._extract_invocation_target(node)
            if target_name:
                relationships.append(
                    Relationship(
                        kind="calls",
                        source=source_name,
                        target=target_name,
                        file_path=file_path,
                        line=node.start_point[0] + 1,
                    )
                )
        for child in node.children:
            self._collect_call_relationships(child, source_name, file_path, relationships)

    def _collect_inherits_relationships(
        self,
        class_node,
        class_name: str,
        file_path: Path,
        relationships: list[Relationship],
    ) -> None:
        heritage = next((c for c in class_node.children if c.type == "class_heritage"), None)
        if heritage is None:
            return

        for child in heritage.children:
            if child.type not in ("extends_clause", "implements_clause"):
                continue
            for type_name in _extract_type_names(_text(child)):
                relationships.append(
                    Relationship(
                        kind="inherits",
                        source=class_name,
                        target=type_name,
                        file_path=file_path,
                        line=child.start_point[0] + 1,
                    )
                )

    def _collect_interface_inherits_relationships(
        self,
        interface_node,
        interface_name: str,
        file_path: Path,
        relationships: list[Relationship],
    ) -> None:
        extends_clause = next(
            (c for c in interface_node.children if c.type == "extends_type_clause"),
            None,
        )
        if extends_clause is None:
            return
        for type_name in _extract_type_names(_text(extends_clause)):
            relationships.append(
                Relationship(
                    kind="inherits",
                    source=interface_name,
                    target=type_name,
                    file_path=file_path,
                    line=extends_clause.start_point[0] + 1,
                )
            )

    def _collect_type_reference_relationships(
        self,
        source_name: str,
        params: list[FunctionParam],
        return_type: str | None,
        function_node,
        file_path: Path,
        relationships: list[Relationship],
    ) -> None:
        for param in params:
            for type_name in _extract_type_names(param.type_annotation):
                relationships.append(
                    Relationship(
                        kind="type-references",
                        source=source_name,
                        target=type_name,
                        file_path=file_path,
                        line=function_node.start_point[0] + 1,
                    )
                )
        for type_name in _extract_type_names(return_type):
            relationships.append(
                Relationship(
                    kind="type-references",
                    source=source_name,
                    target=type_name,
                    file_path=file_path,
                    line=function_node.start_point[0] + 1,
                )
            )
        type_params = function_node.child_by_field_name("type_parameters")
        if type_params is not None:
            for type_name in _extract_type_names(_text(type_params)):
                relationships.append(
                    Relationship(
                        kind="type-references",
                        source=source_name,
                        target=type_name,
                        file_path=file_path,
                        line=type_params.start_point[0] + 1,
                    )
                )

    def _extract_invocation_target(self, invocation_node) -> str | None:
        target_node = (
            invocation_node.child_by_field_name("function")
            or invocation_node.child_by_field_name("constructor")
            or invocation_node.child_by_field_name("callee")
        )
        if target_node is None and invocation_node.named_children:
            target_node = invocation_node.named_children[0]
        if target_node is None:
            return None

        if target_node.type in ("identifier", "property_identifier", "type_identifier"):
            return _text(target_node)

        property_node = target_node.child_by_field_name("property")
        if property_node is not None:
            return _text(property_node)

        for child in reversed(target_node.named_children):
            if child.type in ("identifier", "property_identifier", "type_identifier"):
                return _text(child)

        candidates = _extract_type_names(_text(target_node))
        if candidates:
            return candidates[-1]
        return None
