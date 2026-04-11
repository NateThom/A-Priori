"""Tests for the TypeScript language parser (Story 3.4, AP-62).

Each test is directly traceable to an acceptance criterion:
- AC1: Exported functions extracted with name, params, return type, line range, file path
- AC2: Classes with ``extends`` have inherits relationships identified
- AC3: ``import { Foo } from './module'`` creates an import relationship
- AC4: Barrel files (``export * from``) have re-exports tracked
- AC5: TSX/JSX files with JSX: functions and components extracted correctly
- AC6: TypeScript interfaces extracted as structural entities
"""

from pathlib import Path

import pytest

from apriori.structural.languages.typescript import TypeScriptParser
from apriori.structural.models import (
    ClassEntity,
    FunctionEntity,
    ImportRelationship,
    InterfaceEntity,
    ParseResult,
    ReExport,
)
from apriori.structural.protocol import LanguageParser


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------


def test_parser_implements_language_parser_protocol() -> None:
    """TypeScriptParser satisfies the LanguageParser Protocol."""
    parser = TypeScriptParser()
    assert isinstance(parser, LanguageParser)


def test_parse_returns_parse_result(tmp_path: Path) -> None:
    """parse() returns a ParseResult instance."""
    source = b"const x = 1;\n"
    file_path = tmp_path / "app.ts"
    parser = TypeScriptParser()
    result = parser.parse(source, file_path)
    assert isinstance(result, ParseResult)


def test_parse_result_language_typescript(tmp_path: Path) -> None:
    """ParseResult for .ts file reports language='typescript'."""
    source = b"const x: number = 1;\n"
    file_path = tmp_path / "app.ts"
    result = TypeScriptParser().parse(source, file_path)
    assert result.language == "typescript"
    assert result.file_path == file_path


def test_parse_result_language_javascript(tmp_path: Path) -> None:
    """ParseResult for .js file reports language='javascript'."""
    source = b"function foo() { return 1; }\n"
    file_path = tmp_path / "app.js"
    result = TypeScriptParser().parse(source, file_path)
    assert result.language == "javascript"


# ---------------------------------------------------------------------------
# AC1: Functions extracted with name, params, return type, line range, file path
# ---------------------------------------------------------------------------


def test_exported_function_declaration_extracted(tmp_path: Path) -> None:
    """AC1: Given a TypeScript file with an exported function,
    when parsed,
    then the function is extracted with name, params, return type, and file path."""
    source = b"export function add(x: number, y: number): number { return x + y; }\n"
    file_path = tmp_path / "math.ts"
    result = TypeScriptParser().parse(source, file_path)

    assert len(result.functions) == 1
    func = result.functions[0]
    assert func.name == "add"
    assert func.is_exported is True
    assert func.file_path == file_path
    param_names = [p.name for p in func.params]
    assert "x" in param_names
    assert "y" in param_names
    param_types = {p.name: p.type_annotation for p in func.params}
    assert "number" in (param_types.get("x") or "")
    assert "number" in (param_types.get("y") or "")
    assert func.return_type is not None
    assert "number" in func.return_type


def test_non_exported_function_extracted(tmp_path: Path) -> None:
    """AC1: Non-exported functions are also extracted with is_exported=False."""
    source = b"function helper(s: string): void { console.log(s); }\n"
    file_path = tmp_path / "util.ts"
    result = TypeScriptParser().parse(source, file_path)

    assert len(result.functions) == 1
    func = result.functions[0]
    assert func.name == "helper"
    assert func.is_exported is False
    assert func.return_type is not None
    assert "void" in func.return_type


def test_arrow_function_exported_extracted(tmp_path: Path) -> None:
    """AC1: Exported const arrow functions are extracted."""
    source = b"export const double = (x: number): number => x * 2;\n"
    file_path = tmp_path / "utils.ts"
    result = TypeScriptParser().parse(source, file_path)

    names = [f.name for f in result.functions]
    assert "double" in names
    func = next(f for f in result.functions if f.name == "double")
    assert func.is_exported is True
    assert func.return_type is not None
    assert "number" in func.return_type


def test_non_exported_arrow_function_extracted(tmp_path: Path) -> None:
    """AC1: Non-exported arrow functions are extracted with is_exported=False."""
    source = b"const greet = (name: string): string => `Hello ${name}`;\n"
    file_path = tmp_path / "greet.ts"
    result = TypeScriptParser().parse(source, file_path)

    names = [f.name for f in result.functions]
    assert "greet" in names
    func = next(f for f in result.functions if f.name == "greet")
    assert func.is_exported is False


def test_function_line_range_reported(tmp_path: Path) -> None:
    """AC1: Function start_line and end_line are 1-indexed and correct."""
    source = b"const x = 1;\n\nfunction myFunc(a: string): boolean {\n  return true;\n}\n"
    file_path = tmp_path / "code.ts"
    result = TypeScriptParser().parse(source, file_path)

    func = next(f for f in result.functions if f.name == "myFunc")
    assert func.start_line == 3  # 1-indexed: third line
    assert func.end_line == 5


def test_function_file_path_embedded(tmp_path: Path) -> None:
    """AC1: file_path in FunctionEntity matches the parsed file."""
    source = b"export function foo(): void {}\n"
    file_path = tmp_path / "foo.ts"
    result = TypeScriptParser().parse(source, file_path)

    assert result.functions[0].file_path == file_path


def test_function_param_without_type(tmp_path: Path) -> None:
    """AC1: Parameters without type annotations get type_annotation=None."""
    source = b"function plain(a, b) { return a + b; }\n"
    file_path = tmp_path / "plain.js"
    result = TypeScriptParser().parse(source, file_path)

    func = result.functions[0]
    assert func.name == "plain"
    param_names = [p.name for p in func.params]
    assert "a" in param_names
    assert "b" in param_names
    for p in func.params:
        assert p.type_annotation is None


# ---------------------------------------------------------------------------
# AC2: Classes with ``extends`` have inherits relationships identified
# ---------------------------------------------------------------------------


def test_class_with_extends_has_base(tmp_path: Path) -> None:
    """AC2: Given a class with extends,
    when parsed,
    then the base class name appears in cls.bases (inherits relationship)."""
    source = b"class Dog extends Animal { bark(): void {} }\n"
    file_path = tmp_path / "animals.ts"
    result = TypeScriptParser().parse(source, file_path)

    assert len(result.classes) == 1
    cls = result.classes[0]
    assert cls.name == "Dog"
    assert "Animal" in cls.bases


def test_class_without_extends_has_empty_bases(tmp_path: Path) -> None:
    """AC2: Classes without extends have bases=[]."""
    source = b"class Standalone { method(): string { return 'hi'; } }\n"
    file_path = tmp_path / "standalone.ts"
    result = TypeScriptParser().parse(source, file_path)

    assert len(result.classes) == 1
    assert result.classes[0].bases == []


def test_exported_class_with_extends(tmp_path: Path) -> None:
    """AC2: Exported class with extends is correctly identified."""
    source = b"export class MyService extends BaseService {}\n"
    file_path = tmp_path / "service.ts"
    result = TypeScriptParser().parse(source, file_path)

    assert len(result.classes) == 1
    cls = result.classes[0]
    assert cls.name == "MyService"
    assert cls.is_exported is True
    assert "BaseService" in cls.bases


def test_class_line_range(tmp_path: Path) -> None:
    """Class start_line and end_line are 1-indexed."""
    source = b"\nclass Foo {\n  x = 1;\n}\n"
    file_path = tmp_path / "foo.ts"
    result = TypeScriptParser().parse(source, file_path)

    cls = result.classes[0]
    assert cls.start_line == 2


# ---------------------------------------------------------------------------
# AC3: ``import { Foo } from './module'`` creates an import relationship
# ---------------------------------------------------------------------------


def test_named_import_extracted(tmp_path: Path) -> None:
    """AC3: import { Foo } from './module' creates an ImportRelationship."""
    source = b"import { Foo } from './module';\n"
    file_path = tmp_path / "app.ts"
    result = TypeScriptParser().parse(source, file_path)

    assert len(result.imports) == 1
    imp = result.imports[0]
    assert "Foo" in imp.names
    assert imp.source_module == "./module"
    assert imp.file_path == file_path


def test_multiple_named_imports_all_captured(tmp_path: Path) -> None:
    """AC3: All names from import { Foo, Bar, Baz } are captured."""
    source = b"import { Foo, Bar, Baz } from './multi';\n"
    file_path = tmp_path / "app.ts"
    result = TypeScriptParser().parse(source, file_path)

    assert len(result.imports) == 1
    imp = result.imports[0]
    assert set(imp.names) == {"Foo", "Bar", "Baz"}


def test_default_import_records_source_module(tmp_path: Path) -> None:
    """AC3: Default import records source module (names may be empty)."""
    source = b"import React from 'react';\n"
    file_path = tmp_path / "app.tsx"
    result = TypeScriptParser().parse(source, file_path)

    assert len(result.imports) == 1
    assert result.imports[0].source_module == "react"


def test_import_line_number(tmp_path: Path) -> None:
    """AC3: Import start_line is correct (1-indexed)."""
    source = b"\nimport { Foo } from './mod';\n"
    file_path = tmp_path / "app.ts"
    result = TypeScriptParser().parse(source, file_path)

    assert result.imports[0].start_line == 2


# ---------------------------------------------------------------------------
# AC4: Barrel files (``export * from``) have re-exports tracked
# ---------------------------------------------------------------------------


def test_export_star_from_tracked(tmp_path: Path) -> None:
    """AC4: export * from './submodule' is tracked as a ReExport with is_all=True."""
    source = b"export * from './submodule';\n"
    file_path = tmp_path / "index.ts"
    result = TypeScriptParser().parse(source, file_path)

    assert len(result.re_exports) == 1
    re = result.re_exports[0]
    assert re.source_module == "./submodule"
    assert re.is_all is True
    assert re.names == []
    assert re.file_path == file_path


def test_named_reexport_tracked(tmp_path: Path) -> None:
    """AC4: export { Foo, Bar } from './module' is tracked as a named ReExport."""
    source = b"export { Foo, Bar } from './module';\n"
    file_path = tmp_path / "index.ts"
    result = TypeScriptParser().parse(source, file_path)

    assert len(result.re_exports) == 1
    re = result.re_exports[0]
    assert re.source_module == "./module"
    assert set(re.names) == {"Foo", "Bar"}
    assert re.is_all is False


def test_barrel_file_multiple_reexports(tmp_path: Path) -> None:
    """AC4: A barrel file with multiple re-exports tracks all of them."""
    source = (
        b"export * from './a';\n"
        b"export * from './b';\n"
        b"export { X } from './c';\n"
    )
    file_path = tmp_path / "index.ts"
    result = TypeScriptParser().parse(source, file_path)

    assert len(result.re_exports) == 3
    modules = {r.source_module for r in result.re_exports}
    assert modules == {"./a", "./b", "./c"}


def test_reexport_line_number(tmp_path: Path) -> None:
    """AC4: ReExport start_line is correct."""
    source = b"\nexport * from './sub';\n"
    file_path = tmp_path / "index.ts"
    result = TypeScriptParser().parse(source, file_path)

    assert result.re_exports[0].start_line == 2


# ---------------------------------------------------------------------------
# AC5: TSX/JSX files: functions and components extracted without JSX confusion
# ---------------------------------------------------------------------------


def test_tsx_arrow_component_extracted(tmp_path: Path) -> None:
    """AC5: TSX arrow component extracted without JSX confusing the parser."""
    source = b"export const Greeting = (props: { name: string }) => <div>{props.name}</div>;\n"
    file_path = tmp_path / "Greeting.tsx"
    result = TypeScriptParser().parse(source, file_path)

    names = [f.name for f in result.functions]
    assert "Greeting" in names
    func = next(f for f in result.functions if f.name == "Greeting")
    assert func.is_exported is True


def test_tsx_function_component_extracted(tmp_path: Path) -> None:
    """AC5: TSX function component (function keyword) extracted correctly."""
    source = (
        b"export function Button(props: { label: string }): JSX.Element {\n"
        b"  return <button>{props.label}</button>;\n"
        b"}\n"
    )
    file_path = tmp_path / "Button.tsx"
    result = TypeScriptParser().parse(source, file_path)

    assert any(f.name == "Button" for f in result.functions)


def test_tsx_file_parses_without_errors(tmp_path: Path) -> None:
    """AC5: TSX file with JSX parses without tree-sitter errors."""
    source = b"const App = () => <div><h1>Hello</h1></div>;\n"
    file_path = tmp_path / "App.tsx"
    result = TypeScriptParser().parse(source, file_path)

    assert result.is_valid is True
    assert result.parse_errors == []


def test_jsx_file_parsed_correctly(tmp_path: Path) -> None:
    """AC5: .jsx files use the TSX grammar and extract components correctly."""
    source = b"export const MyComp = () => <span>test</span>;\n"
    file_path = tmp_path / "MyComp.jsx"
    result = TypeScriptParser().parse(source, file_path)

    assert result.is_valid is True
    names = [f.name for f in result.functions]
    assert "MyComp" in names


def test_tsx_multiple_components(tmp_path: Path) -> None:
    """AC5: Multiple components in a .tsx file are all extracted."""
    source = (
        b"export const Header = () => <header>H</header>;\n"
        b"export const Footer = () => <footer>F</footer>;\n"
    )
    file_path = tmp_path / "layout.tsx"
    result = TypeScriptParser().parse(source, file_path)

    names = {f.name for f in result.functions}
    assert "Header" in names
    assert "Footer" in names


# ---------------------------------------------------------------------------
# AC6: TypeScript interfaces extracted as structural entities
# ---------------------------------------------------------------------------


def test_interface_extracted(tmp_path: Path) -> None:
    """AC6: TypeScript interface is extracted as a structural InterfaceEntity."""
    source = b"interface UserProfile { name: string; age: number; }\n"
    file_path = tmp_path / "types.ts"
    result = TypeScriptParser().parse(source, file_path)

    assert len(result.interfaces) == 1
    iface = result.interfaces[0]
    assert iface.name == "UserProfile"
    assert iface.file_path == file_path


def test_exported_interface_has_is_exported_true(tmp_path: Path) -> None:
    """AC6: Exported interface has is_exported=True."""
    source = b"export interface ApiResponse { data: unknown; error: string | null; }\n"
    file_path = tmp_path / "api.ts"
    result = TypeScriptParser().parse(source, file_path)

    assert len(result.interfaces) == 1
    iface = result.interfaces[0]
    assert iface.name == "ApiResponse"
    assert iface.is_exported is True


def test_non_exported_interface_has_is_exported_false(tmp_path: Path) -> None:
    """AC6: Non-exported interface has is_exported=False."""
    source = b"interface Internal { value: number; }\n"
    file_path = tmp_path / "internal.ts"
    result = TypeScriptParser().parse(source, file_path)

    assert result.interfaces[0].is_exported is False


def test_interface_line_range(tmp_path: Path) -> None:
    """AC6: Interface start_line is 1-indexed and correct."""
    source = b"\ninterface Foo {\n  bar: string;\n}\n"
    file_path = tmp_path / "types.ts"
    result = TypeScriptParser().parse(source, file_path)

    iface = result.interfaces[0]
    assert iface.start_line == 2  # 1-indexed: second line


def test_interface_file_path_embedded(tmp_path: Path) -> None:
    """AC6: file_path in InterfaceEntity matches the parsed file."""
    source = b"interface Foo {}\n"
    file_path = tmp_path / "foo.ts"
    result = TypeScriptParser().parse(source, file_path)

    assert result.interfaces[0].file_path == file_path


# ---------------------------------------------------------------------------
# Story 14.3: Expanded structural relationship extraction
# ---------------------------------------------------------------------------


def test_calls_relationships_extracted_for_call_and_new(tmp_path: Path) -> None:
    """Story 14.3: call_expression and new_expression produce calls relationships."""
    source = (
        b"class Service {}\n"
        b"function helper(): void {}\n"
        b"function run(): void { helper(); new Service(); }\n"
    )
    file_path = tmp_path / "calls.ts"
    result = TypeScriptParser().parse(source, file_path)

    calls = [r for r in result.relationships if r.kind == "calls" and r.source == "run"]
    targets = {r.target for r in calls}
    assert "helper" in targets
    assert "Service" in targets


def test_inherits_relationships_include_implements_and_interface_extends(tmp_path: Path) -> None:
    """Story 14.3: class implements + interface extends emit inherits relationships."""
    source = (
        b"interface Base {}\n"
        b"interface Extra {}\n"
        b"interface Derived extends Base, Extra {}\n"
        b"class Impl implements Derived {}\n"
    )
    file_path = tmp_path / "inherits.ts"
    result = TypeScriptParser().parse(source, file_path)

    inherits = [r for r in result.relationships if r.kind == "inherits"]
    pairs = {(r.source, r.target) for r in inherits}
    assert ("Derived", "Base") in pairs
    assert ("Derived", "Extra") in pairs
    assert ("Impl", "Derived") in pairs


def test_type_references_relationships_extracted_from_signatures_and_generics(
    tmp_path: Path,
) -> None:
    """Story 14.3: type annotations, return types, and generics emit type-references."""
    source = (
        b"type UserId = string;\n"
        b"interface Repo<T> {}\n"
        b"interface User {}\n"
        b"function load(repo: Repo<User>, id: UserId): Promise<User> { throw new Error('x'); }\n"
    )
    file_path = tmp_path / "types.ts"
    result = TypeScriptParser().parse(source, file_path)

    refs = [r for r in result.relationships if r.kind == "type-references" and r.source == "load"]
    targets = {r.target for r in refs}
    assert "Repo" in targets
    assert "User" in targets
    assert "UserId" in targets
    assert "Promise" in targets
