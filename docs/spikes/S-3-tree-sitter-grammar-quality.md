# S-3: Tree-sitter Grammar Quality Decision Record

**Date:** 2026-04-07
**Status:** Done
**Verdict:** tree-sitter-python 0.25.0 and tree-sitter-typescript 0.23.2 are **fit for purpose**. Zero parse errors across 16 diverse real-world code cases. `arch:tree-sitter-only` validated.

**Versions:** tree-sitter 0.25.2, tree-sitter-python 0.25.0, tree-sitter-typescript 0.23.2

---

## Context

The Structural Engine epic (E3) requires reliable AST parsing for Python and TypeScript to extract functions, classes, modules, imports, calls, and inheritance. Tree-sitter grammars vary in quality and coverage. This spike validates extraction completeness before Story 3.2 (Parsing Orchestrator) is implemented.

**Scope:** Functions, classes, imports, call sites, inheritance, module-level constructs.

**Test harness:** 8 Python cases + 8 TypeScript/TSX cases covering real-world patterns. See `spike_tree_sitter.py` for the full harness.

---

## Python — Extraction Quality

### What Works Correctly

| Construct | Node Type | Notes |
|-----------|-----------|-------|
| Function definitions | `function_definition` | Name, params, body |
| Class definitions | `class_definition` | Name, bases (via `superclasses` field) |
| Async functions | `function_definition` | `child(0).type == "async"` to detect |
| Import statements | `import_statement` / `import_from_statement` | Full text; all import forms |
| Call sites | `call` | Function field holds callee text |
| `*args` / `**kwargs` | `list_splat_pattern` / `dictionary_splat_pattern` | In parameters node |
| Positional-only `/` | `/` child in parameters | Type is `"/"` literal |
| Metaclasses | `class_definition` → `argument_list` | `metaclass=X` appears in bases |
| Multiple inheritance | `class_definition` → `superclasses` | All bases listed |
| Nested classes | `class_definition` inside `block` | Walk recursively |
| `async for` / `async with` | `for_statement` / `with_statement` with `async` child | Detectable via AST |

### Gaps and Workarounds

**1. Decorated functions/classes — `decorated_definition` wrapper**

Tree-sitter wraps `@decorator` + target into a `decorated_definition` parent node. A naive walk over `function_definition` / `class_definition` will find the inner node, but the decorator list is NOT siblings — the parent is a `decorated_definition` with `decorator` children.

*Workaround:* When visiting `function_definition` or `class_definition`, check `node.parent.type == "decorated_definition"` and collect `decorator` children from the parent.

**2. Generators — no `generator_function` node**

Python does not have a distinct `generator_function` AST node. A generator function is a `function_definition` whose body contains a `yield_expression` or `yield` statement.

*Workaround:* After extracting a `function_definition`, walk its `body` for `yield_expression` nodes. If found, tag `is_generator=True`.

**3. Lambdas — `lambda` is not `function_definition`**

`lambda x, *args: x + sum(args)` produces a `lambda` node, not a `function_definition`. In an assignment like `fn = lambda x: x`, the `lambda` appears inside an `assignment` → value field.

*Workaround:* Visit `lambda` node type separately. Name is derived from the assignment LHS (walk up to `assignment`, read `left` field). Mark as `is_lambda=True`. Optional for MVP.

**4. Getter/setter disambiguation**

`@property` and `@value.setter` both produce `function_definition` nodes with the **same name** (e.g., `value`). The only distinction is the decorator text.

*Workaround:* For a function inside a class body with decorators, read the decorator text. If it matches `@<name>.setter`, tag `is_setter=True`. If it's `@property`, tag `is_getter=True`.

---

## TypeScript — Extraction Quality

### What Works Correctly

| Construct | Node Type | Notes |
|-----------|-----------|-------|
| Function declarations | `function_declaration` | Name field present |
| Class declarations | `class_declaration` | Name, extends, implements |
| Abstract classes | `abstract_class_declaration` | Same pattern |
| Method definitions | `method_definition` | Name field present |
| Interface declarations | `interface_declaration` | Name field present |
| Type aliases | `type_alias_declaration` | Name field present |
| Import statements | `import_declaration` | Full text capture |
| Re-exports | `export_statement` with `source` field | Text capture |
| Call expressions | `call_expression` | `function` field |
| Generic types | `type_parameters` on function/class | Child of declaration |
| TSX / JSX | parsed with `language_tsx()` | Zero parse errors |
| Class decorators | `decorator` before `class_declaration` | Sibling in parent |

### Gaps and Workarounds

**1. Arrow functions in `const` declarations — no name field**

`const myFn = (x: number) => x * 2` produces an `arrow_function` node whose `name` field is `null`. The name lives in the enclosing `variable_declarator`.

*Workaround:* When visiting `arrow_function`, if `node.child_by_field_name("name")` is null, walk up to the nearest `variable_declarator` parent and read its `name` field. This recovers the binding name.

**2. Method modifiers (get/set/static/abstract)**

A `get` accessor like `get doubled()` produces a `method_definition` where the first child is the `get` keyword, not the method name. `node.child_by_field_name("name")` returns the `property_identifier` after the keyword.

*Workaround:* Before reading the `name` field, check `node.child(0).type` for `"get"`, `"set"`, `"static"`, `"abstract"`. Tag the method accordingly. The `name` field still points to the property identifier.

**3. Type-only imports — `import type { ... }`**

`import type { Config } from './config'` and `import { type FC } from 'react'` both produce `import_declaration` nodes but contain a `type` keyword. A naive text capture works but doesn't distinguish type-only imports from value imports.

*Workaround:* Check for a `type` token as a child of the import clause or namespace import. If present, tag `is_type_only=True`. This is important because type-only imports are erased at compile time and should not be treated as runtime dependencies.

**4. Private class fields — `private_property_identifier`**

`#privateField` inside a class produces a `field_definition` where the `name` field has type `private_property_identifier`, not `identifier`. The text includes the `#` prefix.

*Workaround:* When extracting class members, accept both `identifier` and `private_property_identifier` as name node types. Strip the `#` prefix if desired, or retain it to mark the field as private.

**5. TSX files — use `language_tsx()`**

`.tsx` files containing JSX expressions parse correctly with `language_tsx()` but produce `ERROR` nodes when parsed with `language_typescript()`. The JSX angle brackets are valid TypeScript syntax only in the TSX dialect.

*Workaround:* Detect `.tsx` extension and use `language_tsx()`. For `.ts` files, use `language_typescript()`. Both grammars produce identical node types for all non-JSX constructs.

---

## Extraction Quality Matrix

| Construct | Python | TypeScript | Notes |
|-----------|--------|-----------|-------|
| Named functions | ✅ Correct | ✅ Correct | |
| Classes | ✅ Correct | ✅ Correct | |
| Imports | ✅ Correct | ✅ Correct | |
| Inheritance / implements | ✅ Correct | ✅ Correct | |
| Call sites | ✅ Correct | ✅ Correct | |
| Async functions | ✅ Correct | ✅ Correct | |
| Decorators | ⚠️ Partial | ✅ Correct | Py: `decorated_definition` wrapper |
| Generators | ⚠️ Partial | n/a | Py: walk body for `yield_expression` |
| Lambdas | ⚠️ Partial | ⚠️ Partial | Walk up to `variable_declarator` |
| Getter/setter | ⚠️ Partial | ⚠️ Partial | Read decorator / modifier token |
| `*args` / `**kwargs` | ✅ Correct | n/a | `list/dict_splat_pattern` |
| Type-only imports | n/a | ⚠️ Partial | Check for `type` token |
| Private fields | n/a | ⚠️ Partial | `private_property_identifier` |
| TSX / JSX | n/a | ✅ Correct | Use `language_tsx()` |
| Generic types | n/a | ✅ Correct | `type_parameters` child |
| Abstract classes | n/a | ✅ Correct | `abstract_class_declaration` |

---

## Story 3.2 Impact

All 9 gaps have structural AST workarounds — no regex or heuristics required. Estimated implementation cost: **~1 additional day** beyond the base parsing orchestrator.

Priority order for Story 3.2:
1. `decorated_definition` wrapper (affects all decorated Python constructs)
2. Arrow function naming (affects all TS const-arrow patterns, extremely common)
3. TSX dialect detection (prevents ERROR nodes on `.tsx` files)
4. Getter/setter modifiers (affects property accessors)
5. Type-only imports (affects dependency graph accuracy)
6. Private fields (affects class member extraction)
7. Generators (optional for MVP — tag as `is_generator`)
8. Lambdas (optional for MVP — common but not structural)
9. Positional-only params (optional — Python 3.8+ niche)
