"""
Tree-sitter Grammar Quality Spike — AP-65
Tests extraction completeness for Python and TypeScript across edge cases.
"""

import textwrap
from dataclasses import dataclass, field
from typing import Any

import tree_sitter_python as tspython
import tree_sitter_typescript as tstypescript
from tree_sitter import Language, Parser, Node

# ─── Language setup ───────────────────────────────────────────────────────────

PY_LANG = Language(tspython.language())
TS_LANG = Language(tstypescript.language_typescript())
TSX_LANG = Language(tstypescript.language_tsx())


def make_parser(lang: Language) -> Parser:
    p = Parser(lang)
    return p


# ─── Result types ─────────────────────────────────────────────────────────────

@dataclass
class Extraction:
    kind: str           # function, class, import, call, etc.
    name: str
    node_type: str
    start: tuple[int, int]
    end: tuple[int, int]
    extra: dict = field(default_factory=dict)


@dataclass
class CaseResult:
    label: str
    code: str
    extractions: list[Extraction] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


# ─── Extraction helpers ───────────────────────────────────────────────────────

def first_child_text(node: Node, field_name: str) -> str:
    child = node.child_by_field_name(field_name)
    if child:
        return child.text.decode()
    return ""


def children_of_type(node: Node, *types: str) -> list[Node]:
    return [c for c in node.children if c.type in types]


def walk(node: Node, callback, depth=0):
    callback(node, depth)
    for child in node.children:
        walk(child, callback, depth + 1)


# ─── Python extraction ────────────────────────────────────────────────────────

def extract_python(source: str) -> tuple[list[Extraction], list[str]]:
    parser = make_parser(PY_LANG)
    tree = parser.parse(source.encode())
    extractions: list[Extraction] = []
    issues: list[str] = []

    def visit(node: Node, _depth: int):
        t = node.type

        if t == "function_definition":
            name = first_child_text(node, "name")
            params = node.child_by_field_name("parameters")
            param_names = []
            has_args = False
            has_kwargs = False
            decorators = []
            # Decorators are siblings BEFORE this node in parent
            for sib in (node.parent.children if node.parent else []):
                if sib.type == "decorator" and sib.end_point < node.start_point:
                    decorators.append(sib.text.decode().strip())
            if params:
                for p in params.children:
                    if p.type == "list_splat_pattern":
                        has_args = True
                    elif p.type == "dictionary_splat_pattern":
                        has_kwargs = True
                    elif p.type == "identifier":
                        param_names.append(p.text.decode())
            extractions.append(Extraction(
                kind="function",
                name=name,
                node_type=t,
                start=node.start_point,
                end=node.end_point,
                extra={
                    "params": param_names,
                    "has_args": has_args,
                    "has_kwargs": has_kwargs,
                    "decorators": decorators,
                    "is_async": node.child(0) and node.child(0).type == "async",
                },
            ))

        elif t == "class_definition":
            name = first_child_text(node, "name")
            bases = []
            arg_list = node.child_by_field_name("superclasses")
            if arg_list:
                for c in arg_list.children:
                    if c.type not in ("(", ")", ","):
                        bases.append(c.text.decode())
            decorators = []
            for sib in (node.parent.children if node.parent else []):
                if sib.type == "decorator" and sib.end_point < node.start_point:
                    decorators.append(sib.text.decode().strip())
            extractions.append(Extraction(
                kind="class",
                name=name,
                node_type=t,
                start=node.start_point,
                end=node.end_point,
                extra={"bases": bases, "decorators": decorators},
            ))

        elif t in ("import_statement", "import_from_statement"):
            extractions.append(Extraction(
                kind="import",
                name=node.text.decode().strip(),
                node_type=t,
                start=node.start_point,
                end=node.end_point,
            ))

        elif t == "call":
            fn = node.child_by_field_name("function")
            if fn:
                extractions.append(Extraction(
                    kind="call",
                    name=fn.text.decode(),
                    node_type=t,
                    start=node.start_point,
                    end=node.end_point,
                ))

    walk(tree.root_node, visit)

    # Check parse errors
    def find_errors(node: Node, _):
        if node.type == "ERROR" or node.is_missing:
            issues.append(f"Parse error at {node.start_point}: {node.text.decode()[:50]!r}")

    walk(tree.root_node, find_errors)
    return extractions, issues


# ─── TypeScript extraction ────────────────────────────────────────────────────

def extract_typescript(source: str, tsx: bool = False) -> tuple[list[Extraction], list[str]]:
    lang = TSX_LANG if tsx else TS_LANG
    parser = make_parser(lang)
    tree = parser.parse(source.encode())
    extractions: list[Extraction] = []
    issues: list[str] = []

    def visit(node: Node, _depth: int):
        t = node.type

        if t in ("function_declaration", "function_expression", "arrow_function"):
            name_node = node.child_by_field_name("name")
            name = name_node.text.decode() if name_node else "<anonymous>"
            extractions.append(Extraction(
                kind="function",
                name=name,
                node_type=t,
                start=node.start_point,
                end=node.end_point,
            ))

        elif t == "method_definition":
            name_node = node.child_by_field_name("name")
            name = name_node.text.decode() if name_node else "<unknown>"
            extractions.append(Extraction(
                kind="method",
                name=name,
                node_type=t,
                start=node.start_point,
                end=node.end_point,
            ))

        elif t in ("class_declaration", "abstract_class_declaration"):
            name_node = node.child_by_field_name("name")
            name = name_node.text.decode() if name_node else "<anonymous>"
            heritage = node.child_by_field_name("body")  # not the right field
            # Get heritage clause
            extends = []
            implements = []
            for c in node.children:
                if c.type == "class_heritage":
                    for cc in c.children:
                        if cc.type == "extends_clause":
                            for e in cc.children:
                                if e.type not in ("extends",):
                                    extends.append(e.text.decode())
                        elif cc.type == "implements_clause":
                            for e in cc.children:
                                if e.type not in ("implements",):
                                    implements.append(e.text.decode())
            extractions.append(Extraction(
                kind="class",
                name=name,
                node_type=t,
                start=node.start_point,
                end=node.end_point,
                extra={"extends": extends, "implements": implements},
            ))

        elif t in ("import_statement", "import_declaration"):
            extractions.append(Extraction(
                kind="import",
                name=node.text.decode().strip()[:80],
                node_type=t,
                start=node.start_point,
                end=node.end_point,
            ))

        elif t == "export_statement":
            # Re-exports: export { X } from 'y'
            source_node = node.child_by_field_name("source")
            if source_node:
                extractions.append(Extraction(
                    kind="re-export",
                    name=node.text.decode().strip()[:80],
                    node_type=t,
                    start=node.start_point,
                    end=node.end_point,
                ))

        elif t == "call_expression":
            fn = node.child_by_field_name("function")
            if fn:
                extractions.append(Extraction(
                    kind="call",
                    name=fn.text.decode()[:40],
                    node_type=t,
                    start=node.start_point,
                    end=node.end_point,
                ))

        elif t in ("type_alias_declaration", "interface_declaration"):
            name_node = node.child_by_field_name("name")
            name = name_node.text.decode() if name_node else "<unknown>"
            extractions.append(Extraction(
                kind="type" if t == "type_alias_declaration" else "interface",
                name=name,
                node_type=t,
                start=node.start_point,
                end=node.end_point,
            ))

    walk(tree.root_node, visit)

    def find_errors(node: Node, _):
        if node.type == "ERROR" or node.is_missing:
            issues.append(f"Parse error at {node.start_point}: {node.text.decode()[:60]!r}")

    walk(tree.root_node, find_errors)
    return extractions, issues


# ─── Test cases ───────────────────────────────────────────────────────────────

PY_CASES = [
    CaseResult(
        label="Python: Basic functions and classes",
        code=textwrap.dedent("""
            def simple(x, y):
                return x + y

            class Animal:
                def speak(self):
                    pass

            class Dog(Animal):
                def speak(self):
                    return "woof"
        """),
    ),
    CaseResult(
        label="Python: Decorators",
        code=textwrap.dedent("""
            import functools

            def my_decorator(func):
                @functools.wraps(func)
                def wrapper(*args, **kwargs):
                    return func(*args, **kwargs)
                return wrapper

            @my_decorator
            def decorated_fn(x):
                return x

            class MyClass:
                @staticmethod
                def static_method():
                    pass

                @classmethod
                def class_method(cls):
                    pass

                @property
                def value(self):
                    return self._value

                @value.setter
                def value(self, v):
                    self._value = v
        """),
    ),
    CaseResult(
        label="Python: Nested classes",
        code=textwrap.dedent("""
            class Outer:
                class Inner:
                    class DeepInner:
                        def method(self):
                            pass

                def outer_method(self):
                    class LocalClass:
                        pass
                    return LocalClass()
        """),
    ),
    CaseResult(
        label="Python: Async functions and generators",
        code=textwrap.dedent("""
            import asyncio

            async def fetch(url: str) -> str:
                async with asyncio.timeout(5):
                    return ""

            async def stream():
                for i in range(10):
                    yield i

            def sync_generator():
                yield from range(100)

            async def main():
                async for item in stream():
                    print(item)
                result = await fetch("http://example.com")
        """),
    ),
    CaseResult(
        label="Python: *args/**kwargs and complex signatures",
        code=textwrap.dedent("""
            def complex_sig(a, b=1, *args, keyword_only=True, **kwargs):
                pass

            def positional_only(x, y, /, z):
                pass

            def type_annotated(x: int, y: str = "default") -> bool:
                return True

            lambda_fn = lambda x, *args: x + sum(args)
        """),
    ),
    CaseResult(
        label="Python: Import variants",
        code=textwrap.dedent("""
            import os
            import os.path
            from os import path, getcwd
            from os.path import (
                join,
                exists,
                dirname,
            )
            from . import sibling
            from .. import parent_module
            from .submodule import helper
            import numpy as np
            from typing import Optional, Union, TYPE_CHECKING
            if TYPE_CHECKING:
                from heavy_module import HeavyClass
        """),
    ),
    CaseResult(
        label="Python: Metaclasses and complex inheritance",
        code=textwrap.dedent("""
            class Meta(type):
                def __new__(mcs, name, bases, namespace):
                    return super().__new__(mcs, name, bases, namespace)

            class Abstract(metaclass=Meta):
                pass

            class MultiInherit(Abstract, dict, list):
                pass
        """),
    ),
    CaseResult(
        label="Python: Dataclasses and Pydantic",
        code=textwrap.dedent("""
            from dataclasses import dataclass, field
            from pydantic import BaseModel, field_validator

            @dataclass
            class Point:
                x: float
                y: float
                tags: list[str] = field(default_factory=list)

            class User(BaseModel):
                name: str
                age: int

                @field_validator("age")
                @classmethod
                def validate_age(cls, v):
                    assert v > 0
                    return v
        """),
    ),
]


TS_CASES = [
    CaseResult(
        label="TypeScript: Basic classes and interfaces",
        code=textwrap.dedent("""
            interface Animal {
              name: string;
              speak(): string;
            }

            class Dog implements Animal {
              constructor(public name: string) {}
              speak(): string { return "woof"; }
            }

            abstract class Vehicle {
              abstract drive(): void;
            }
        """),
    ),
    CaseResult(
        label="TypeScript: Generic types",
        code=textwrap.dedent("""
            type Result<T, E extends Error = Error> = { ok: true; value: T } | { ok: false; error: E };
            type Nullable<T> = T | null;
            type Fn<TArgs extends unknown[], TReturn> = (...args: TArgs) => TReturn;

            interface Repository<T> {
              findById(id: string): Promise<T | null>;
              save(entity: T): Promise<void>;
            }

            function identity<T>(x: T): T { return x; }
            const map = <T, U>(arr: T[], fn: (x: T) => U): U[] => arr.map(fn);
        """),
    ),
    CaseResult(
        label="TypeScript: Decorators",
        code=textwrap.dedent("""
            function Injectable(): ClassDecorator {
              return (target) => {};
            }

            function Log(target: any, key: string, desc: PropertyDescriptor) {
              const orig = desc.value;
              desc.value = function(...args: any[]) {
                console.log(`Calling ${key}`);
                return orig.apply(this, args);
              };
            }

            @Injectable()
            class Service {
              @Log
              doWork(x: number): number { return x * 2; }
            }
        """),
    ),
    CaseResult(
        label="TypeScript: Re-exports and barrel files",
        code=textwrap.dedent("""
            export { default as Button } from './Button';
            export { Input, type InputProps } from './Input';
            export * from './utils';
            export * as Icons from './icons';
            export type { Theme } from './theme';

            // Named re-export with rename
            export { OriginalName as AliasName } from './original';
        """),
    ),
    CaseResult(
        label="TypeScript: Namespace imports and side effects",
        code=textwrap.dedent("""
            import React, { useState, useEffect, type FC } from 'react';
            import * as _ from 'lodash';
            import type { Config } from './config';
            import './styles.css';  // side-effect import

            const MyComponent: FC = () => {
              const [count, setCount] = useState(0);
              useEffect(() => { document.title = String(count); }, [count]);
              return null;
            };
        """),
    ),
    CaseResult(
        label="TypeScript: Complex class hierarchy",
        code=textwrap.dedent("""
            class Base {
              protected value: number = 0;
              get doubled() { return this.value * 2; }
              set doubled(v: number) { this.value = v / 2; }
            }

            interface Serializable {
              serialize(): string;
            }

            interface Cloneable<T> {
              clone(): T;
            }

            class Child extends Base implements Serializable, Cloneable<Child> {
              serialize() { return JSON.stringify(this); }
              clone() { return new Child(); }
              static create() { return new Child(); }
              #privateField = "private";
            }
        """),
    ),
    CaseResult(
        label="TypeScript/TSX: JSX components",
        code=textwrap.dedent("""
            import React from 'react';

            interface Props {
              title: string;
              children?: React.ReactNode;
            }

            const Layout: React.FC<Props> = ({ title, children }) => (
              <div className="layout">
                <h1>{title}</h1>
                <main>{children}</main>
              </div>
            );

            export default function App() {
              return <Layout title="App"><p>Hello</p></Layout>;
            }
        """),
        notes=["Parsed with TSX language"],
    ),
    CaseResult(
        label="TypeScript: Conditional and mapped types",
        code=textwrap.dedent("""
            type IsString<T> = T extends string ? true : false;
            type DeepPartial<T> = { [K in keyof T]?: T[K] extends object ? DeepPartial<T[K]> : T[K] };
            type Awaited<T> = T extends Promise<infer U> ? U : T;

            type UnionToIntersection<U> =
              (U extends any ? (x: U) => void : never) extends (x: infer I) => void
                ? I
                : never;

            const createProxy = <T extends object>(target: T): T =>
              new Proxy(target, {
                get(obj, key) { return Reflect.get(obj, key); }
              });
        """),
    ),
]


# ─── Runner ───────────────────────────────────────────────────────────────────

def run_python_cases() -> list[CaseResult]:
    results = []
    for case in PY_CASES:
        extractions, issues = extract_python(case.code)
        case.extractions = extractions
        case.issues = issues
        results.append(case)
    return results


def run_ts_cases() -> list[CaseResult]:
    results = []
    for case in TS_CASES:
        tsx = "TSX" in case.label or "JSX" in case.label
        extractions, issues = extract_typescript(case.code, tsx=tsx)
        case.extractions = extractions
        case.issues = issues
        results.append(case)
    return results


def print_report(cases: list[CaseResult], lang: str):
    print(f"\n{'='*70}")
    print(f"  {lang} EXTRACTION RESULTS")
    print(f"{'='*70}")

    for case in cases:
        print(f"\n--- {case.label} ---")
        by_kind: dict[str, list[Extraction]] = {}
        for e in case.extractions:
            by_kind.setdefault(e.kind, []).append(e)

        for kind, items in sorted(by_kind.items()):
            names = [e.name for e in items]
            print(f"  {kind:12s} ({len(items):2d}): {', '.join(names[:8])}")

        if case.issues:
            for issue in case.issues:
                print(f"  [ISSUE] {issue}")
        else:
            print("  [OK] No parse errors")

        if case.notes:
            for note in case.notes:
                print(f"  [NOTE] {note}")


if __name__ == "__main__":
    py_results = run_python_cases()
    ts_results = run_ts_cases()

    print_report(py_results, "PYTHON")
    print_report(ts_results, "TYPESCRIPT")

    # Summarize key gaps
    print(f"\n{'='*70}")
    print("  KEY FINDINGS SUMMARY")
    print(f"{'='*70}")

    # Check specific things
    parser = make_parser(PY_LANG)

    # Test 1: async detection
    tree = parser.parse(b"async def foo(): pass")
    root = tree.root_node
    fn = root.children[0] if root.children else None
    async_detected = fn and fn.child(0) and fn.child(0).type == "async"
    print(f"\nPy: async detected via child(0).type='async': {async_detected}")
    if fn:
        print(f"    node children types: {[c.type for c in fn.children[:5]]}")

    # Test 2: positional-only params
    tree = parser.parse(b"def f(x, y, /, z): pass")
    params_node = tree.root_node.children[0].child_by_field_name("parameters") if tree.root_node.children else None
    if params_node:
        param_types = [c.type for c in params_node.children]
        print(f"\nPy: positional-only '/' param types: {param_types}")
        has_pos_only = "/" in param_types
        print(f"    positional_only_separator detected: {has_pos_only}")

    # Test 3: decorator association in Python
    tree = parser.parse(b"@decorator\ndef foo(): pass")
    root = tree.root_node
    print(f"\nPy: decorator + function - root children types: {[c.type for c in root.children]}")
    print(f"    Decorators appear as siblings BEFORE function, not children")
    decorated = root.children[0] if root.children else None
    if decorated:
        print(f"    decorated_definition node type: {decorated.type}")
        # Check if there's a decorated_definition wrapper
        for c in root.children:
            print(f"    child type={c.type}: {c.text.decode()[:50]!r}")

    # Test 4: TS private fields (#)
    ts_parser = make_parser(TS_LANG)
    tree = ts_parser.parse(b"class X { #private = 1; }")
    def find_field_def(node):
        if node.type == "field_definition":
            name = node.child_by_field_name("name")
            print(f"\nTS: private field '#private' - name node type: {name.type if name else None}, text: {name.text.decode() if name else None}")
        for c in node.children:
            find_field_def(c)
    find_field_def(tree.root_node)

    # Test 5: TS re-exports
    tree = ts_parser.parse(b"export { Foo } from './foo';")
    def show_export(node):
        if node.type == "export_statement":
            print(f"\nTS: re-export node type={node.type}")
            print(f"    source field: {node.child_by_field_name('source')}")
            print(f"    children types: {[c.type for c in node.children]}")
        for c in node.children:
            show_export(c)
    show_export(tree.root_node)

    # Test 6: TSX JSX expression parse
    tsx_parser = make_parser(TSX_LANG)
    tree = tsx_parser.parse(b"const el = <div className='x'>{val}</div>;")
    def show_jsx(node, depth=0):
        if "jsx" in node.type:
            print(f"    {'  '*depth}jsx node: {node.type}")
        for c in node.children:
            show_jsx(c, depth+1)
    print(f"\nTSX: JSX element node types:")
    show_jsx(tree.root_node)

    # Test 7: Lambda / arrow function naming
    tree = ts_parser.parse(b"const myFn = (x: number) => x * 2;")
    def show_arrow(node):
        if node.type == "lexical_declaration":
            print(f"\nTS: arrow function in const - lexical_declaration children:")
            for c in node.children:
                print(f"    {c.type}: {c.text.decode()[:40]!r}")
                if c.type == "variable_declarator":
                    name = c.child_by_field_name("name")
                    val = c.child_by_field_name("value")
                    print(f"      name: {name.text.decode() if name else None}, value_type: {val.type if val else None}")
        for c in node.children:
            show_arrow(c)
    show_arrow(tree.root_node)

    print("\n")
