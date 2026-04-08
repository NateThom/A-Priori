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
import re
from typing import Optional

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


async def resolve_code_reference(
    ref: CodeReference,
    file_content: str,
    adapter: LLMAdapter,
) -> Optional[str]:
    """Resolve a CodeReference to a code snippet using the three-step repair chain.

    Tries each resolution path in order, returning the first success:

    1. **Symbol lookup**: regex-based search for ``def <symbol>`` or
       ``class <symbol>`` definitions in ``file_content``.
    2. **Content hash**: SHA-256 hash match against logical blocks split by
       blank lines in ``file_content``.
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
    # Step 1: symbol lookup
    snippet = _find_by_symbol(ref.symbol, file_content)
    if snippet is not None:
        return snippet

    # Step 2: content hash lookup
    snippet = _find_by_content_hash(ref.content_hash, file_content)
    if snippet is not None:
        return snippet

    # Step 3: semantic anchor fallback via LLM
    return await _resolve_via_semantic_anchor(
        ref.semantic_anchor, ref.symbol, file_content, adapter
    )


def _find_by_symbol(symbol: str, content: str) -> Optional[str]:
    """Find a symbol definition (def or class) in file content by name.

    Captures the definition block from its header line to just before the next
    top-level ``def``/``class`` statement or end of file. Handles both sync and
    async function definitions.

    Args:
        symbol: The symbol name to search for (exact, case-sensitive).
        content: Full file content to search within.

    Returns:
        The matched code block as a string, or ``None`` if not found.
    """
    escaped = re.escape(symbol)
    patterns = [
        # async def / def
        rf'^(?:async\s+)?def\s+{escaped}\s*[:(].*?(?=\n(?:async\s+)?def\s|\nclass\s|\Z)',
        # class
        rf'^class\s+{escaped}\s*[:(].*?(?=\nclass\s|\n(?:async\s+)?def\s|\Z)',
    ]
    for pattern in patterns:
        match = re.search(pattern, content, re.MULTILINE | re.DOTALL)
        if match:
            return match.group(0).rstrip()
    return None


def _find_by_content_hash(content_hash: str, file_content: str) -> Optional[str]:
    """Find a code block in file content whose SHA-256 hash matches.

    Splits the file on double blank lines (paragraph-style blocks) and checks
    each block's SHA-256. Returns the first matching block.

    Args:
        content_hash: 64-character lowercase hex SHA-256 to match against.
        file_content: Full file content to search within.

    Returns:
        The matching code block, or ``None`` if no block hash matches.
    """
    blocks = re.split(r"\n\n+", file_content)
    for block in blocks:
        block = block.strip()
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
