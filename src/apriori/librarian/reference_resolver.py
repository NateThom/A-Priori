"""Code reference resolution with semantic anchor fallback (ERD §3.1.2).

Implements the three-step repair chain for resolving a CodeReference to its
actual code snippet within a file:

    1. Symbol lookup   — find by definition name (def/class)
    2. Content hash    — find by SHA-256 hash of a code block
    3. Semantic anchor — LLM fallback using the semantic anchor description

Usage::

    from apriori.librarian.reference_resolver import resolve_code_reference

    snippet = await resolve_code_reference(ref, file_content, adapter)
    if snippet is None:
        # All three paths failed — code cannot be located
        ...
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Optional

import tree_sitter_python as _tspython
import tree_sitter_typescript as _tstypescript
from tree_sitter import Language, Node, Parser

from apriori.adapters.base import LLMAdapter
from apriori.models.concept import CodeReference


_LOCATE_PROMPT = """\
You are a code locator. Given the file content below and a semantic anchor description, \
find and extract the most relevant code block (function, class, or method) that matches \
the description.

Semantic anchor: {semantic_anchor}
Symbol hint: {symbol}

File content:
```
{file_content}
```

Return ONLY the raw code block, with no markdown fences, no explanation, and no preamble. \
If the code cannot be found, return an empty string."""

_PY_LANGUAGE: Language | None = None
_TS_LANGUAGE: Language | None = None
_TSX_LANGUAGE: Language | None = None

_PY_SYMBOL_TYPES = frozenset(
    {"function_definition", "async_function_definition", "class_definition"}
)
_TS_SYMBOL_TYPES = frozenset(
    {
        "function_declaration",
        "class_declaration",
        "method_definition",
        "generator_function_declaration",
        "interface_declaration",
    }
)


def _py_language() -> Language:
    global _PY_LANGUAGE
    if _PY_LANGUAGE is None:
        _PY_LANGUAGE = Language(_tspython.language())
    return _PY_LANGUAGE


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


def _iter_nodes(node: Node):
    yield node
    for child in node.children:
        yield from _iter_nodes(child)


def _parse_tree(file_path: str, content: str):
    suffix = Path(file_path).suffix.lower()
    source = content.encode("utf-8")

    if suffix == ".py":
        parser = Parser(_py_language())
        return "python", parser.parse(source)

    if suffix in {".tsx", ".jsx"}:
        parser = Parser(_tsx_language())
        return "typescript", parser.parse(source)

    if suffix in {".ts", ".js"}:
        parser = Parser(_ts_language())
        return "typescript", parser.parse(source)

    # Unknown extension — fall back to Python grammar first, then TypeScript.
    py_tree = Parser(_py_language()).parse(source)
    if not py_tree.root_node.has_error:
        return "python", py_tree
    ts_tree = Parser(_ts_language()).parse(source)
    return "typescript", ts_tree


def _find_named_nodes(language: str, tree) -> list[Node]:
    root = tree.root_node
    if language == "python":
        allowed = _PY_SYMBOL_TYPES
    else:
        allowed = _TS_SYMBOL_TYPES

    nodes: list[Node] = []
    for node in _iter_nodes(root):
        if node.type in allowed:
            nodes.append(node)
    return nodes


def _node_name(node: Node) -> str:
    name_node = node.child_by_field_name("name")
    if name_node is None:
        return ""
    return name_node.text.decode("utf-8")


async def resolve_code_reference(
    ref: CodeReference,
    file_content: str,
    adapter: LLMAdapter,
) -> Optional[str]:
    """Resolve a CodeReference to a code snippet using the three-step repair chain.

    Tries each resolution path in order, returning the first success:

    1. **Symbol lookup**: tree-sitter AST search for named symbol definition
       nodes (function/class/interface/method).
    2. **Content hash**: SHA-256 hash match against tree-sitter extracted
       definition blocks from the parsed AST.
    3. **Semantic anchor LLM fallback**: sends the semantic anchor and file
       content to the LLM adapter for location assistance.

    Args:
        ref: The CodeReference to resolve. Uses ``ref.symbol``,
            ``ref.content_hash``, and ``ref.semantic_anchor``.
        file_content: The full text of the file referenced by ``ref.file_path``.
        adapter: LLM adapter used for the semantic anchor fallback (Step 3).

    Returns:
        The resolved code snippet as a string, or ``None`` if all three paths
        fail (including an empty LLM response).
    """
    language, tree = _parse_tree(ref.file_path, file_content)
    symbol_nodes = _find_named_nodes(language, tree)

    # Step 1: symbol lookup
    snippet = _find_by_symbol(ref.symbol, file_content, symbol_nodes=symbol_nodes)
    if snippet is not None:
        return snippet

    # Step 2: content hash lookup
    snippet = _find_by_content_hash(
        ref.content_hash, file_content, symbol_nodes=symbol_nodes
    )
    if snippet is not None:
        return snippet

    # Step 3: semantic anchor fallback via LLM
    return await _resolve_via_semantic_anchor(
        ref.semantic_anchor, ref.symbol, file_content, adapter
    )


def _find_by_symbol(
    symbol: str, content: str, *, symbol_nodes: list[Node] | None = None
) -> Optional[str]:
    """Find a symbol definition (def or class) in file content by name.

    Uses tree-sitter to locate named definition nodes and returns the exact
    node text for the first symbol name match.

    Args:
        symbol: The symbol name to search for (exact, case-sensitive).
        content: Full file content to search within.

    Returns:
        The matched code block as a string, or ``None`` if not found.
    """
    if symbol_nodes is None:
        language, tree = _parse_tree("unknown.py", content)
        symbol_nodes = _find_named_nodes(language, tree)

    for node in symbol_nodes:
        if _node_name(node) == symbol:
            return node.text.decode("utf-8").strip()
    return None


def _find_by_content_hash(
    content_hash: str, file_content: str, *, symbol_nodes: list[Node] | None = None
) -> Optional[str]:
    """Find a code block in file content whose SHA-256 hash matches.

    Computes SHA-256 across tree-sitter extracted definition nodes and returns
    the first hash match.

    Args:
        content_hash: 64-character lowercase hex SHA-256 to match against.
        file_content: Full file content to search within.

    Returns:
        The matching code block, or ``None`` if no block hash matches.
    """
    if symbol_nodes is None:
        language, tree = _parse_tree("unknown.py", file_content)
        symbol_nodes = _find_named_nodes(language, tree)

    for node in symbol_nodes:
        block = node.text.decode("utf-8").strip()
        if not block:
            continue
        block_hash = hashlib.sha256(block.encode()).hexdigest()
        if block_hash == content_hash:
            return block
    return None


async def _resolve_via_semantic_anchor(
    semantic_anchor: str,
    symbol: str,
    file_content: str,
    adapter: LLMAdapter,
) -> Optional[str]:
    """Use the LLM adapter to locate a code block via its semantic anchor description.

    Sends the ``_LOCATE_PROMPT`` template with the semantic anchor, symbol hint,
    and file content to the adapter. Returns the stripped response, or ``None``
    if the response is empty.

    Args:
        semantic_anchor: Human-readable description of the code block to locate.
        symbol: Symbol name hint (included in the prompt for context).
        file_content: Full file content to search within.
        adapter: LLM adapter to use for the lookup call.

    Returns:
        The LLM's response as a stripped string, or ``None`` if empty.
    """
    prompt = _LOCATE_PROMPT.format(
        semantic_anchor=semantic_anchor,
        symbol=symbol,
        file_content=file_content,
    )
    result = await adapter.analyze(prompt, context="")
    resolved = result.content.strip()
    return resolved if resolved else None
