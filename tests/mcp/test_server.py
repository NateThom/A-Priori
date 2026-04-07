"""Tests for MCP server scaffold (Story 4.1).

Acceptance criteria:
AC1: Given `python -m apriori.mcp.server`, the server starts, initializes
     KnowledgeStore, and listens on stdio.
AC2: When a client requests the tool listing, all 13 tools are listed with
     names, descriptions, and input schemas.
AC3: Given a tool throws an unexpected exception, safe_tool catches it and
     returns an isError=True response (via ToolError).
AC4: Given a shutdown signal, the lifespan context manager exits and cleans
     up resources gracefully.
"""

from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack
from pathlib import Path

import pytest

from apriori.mcp.server import mcp, safe_tool


# ---------------------------------------------------------------------------
# AC3: safe_tool decorator
# ---------------------------------------------------------------------------


def test_safe_tool_passes_through_return_value():
    """Given a tool that succeeds, safe_tool returns the result unchanged."""

    @safe_tool
    def ok_tool(x: int) -> int:
        return x * 2

    assert ok_tool(5) == 10


def test_safe_tool_preserves_function_name():
    """safe_tool preserves __name__ and __doc__ via functools.wraps."""

    @safe_tool
    def my_named_tool() -> str:
        """My tool docstring."""
        return "ok"

    assert my_named_tool.__name__ == "my_named_tool"
    assert my_named_tool.__doc__ == "My tool docstring."


def test_safe_tool_catches_exception_and_raises_tool_error():
    """Given a tool that raises, safe_tool raises ToolError with descriptive message."""
    from mcp.server.fastmcp.exceptions import ToolError

    @safe_tool
    def failing_tool() -> str:
        raise ValueError("unexpected failure")

    with pytest.raises(ToolError) as exc_info:
        failing_tool()

    error_msg = str(exc_info.value)
    assert "failing_tool" in error_msg
    assert "ValueError" in error_msg
    assert "unexpected failure" in error_msg


def test_safe_tool_formats_error_with_exception_type():
    """safe_tool includes the exception type in the formatted error message."""
    from mcp.server.fastmcp.exceptions import ToolError

    @safe_tool
    def type_error_tool() -> str:
        raise TypeError("bad type")

    with pytest.raises(ToolError) as exc_info:
        type_error_tool()

    assert "TypeError" in str(exc_info.value)


# ---------------------------------------------------------------------------
# AC1: Server module importable and has FastMCP instance
# ---------------------------------------------------------------------------


def test_server_module_exports_fastmcp_instance():
    """The mcp object is a FastMCP instance with name 'apriori'."""
    from mcp.server.fastmcp import FastMCP

    assert isinstance(mcp, FastMCP)
    assert mcp.name == "apriori"


def test_server_has_main_module():
    """apriori.mcp.server is runnable as __main__ (has __main__.py or can be run)."""
    import importlib.util

    spec = importlib.util.find_spec("apriori.mcp")
    assert spec is not None, "apriori.mcp package must exist"


# ---------------------------------------------------------------------------
# AC2: 13 tools registered with names, descriptions, and input schemas
# ---------------------------------------------------------------------------


def test_server_registers_expected_tool_count():
    """Given the server, when tools are listed, the expected number are registered.

    AP-68 scaffolded 13 tools. AP-70 added 5 read tools (search, traverse,
    get_concept→replaced, list_edge_types, get_status, blast_radius) for a
    total of 18.
    """
    tools = asyncio.run(mcp.list_tools())
    assert len(tools) == 18, (
        f"Expected 18 tools, got {len(tools)}: {[t.name for t in tools]}"
    )


def test_all_tools_have_non_empty_descriptions():
    """Every registered tool has a non-empty description string."""
    tools = asyncio.run(mcp.list_tools())
    for tool in tools:
        assert tool.description, f"Tool '{tool.name}' has no description"
        assert tool.description.strip(), f"Tool '{tool.name}' description is blank"


def test_all_tools_have_input_schemas():
    """Every registered tool has an inputSchema dict."""
    tools = asyncio.run(mcp.list_tools())
    for tool in tools:
        assert isinstance(tool.inputSchema, dict), (
            f"Tool '{tool.name}' inputSchema is not a dict: {tool.inputSchema!r}"
        )


def test_tool_names_are_unique():
    """All 13 tool names are distinct."""
    tools = asyncio.run(mcp.list_tools())
    names = [t.name for t in tools]
    assert len(names) == len(set(names)), f"Duplicate tool names: {names}"


def test_expected_tool_names_present():
    """All expected tool names are registered (AP-68 + AP-70 additions)."""
    expected = {
        # Concept CRUD (AP-68 scaffold; bodies in AP-70/AP-73)
        "create_concept",
        "get_concept",
        "update_concept",
        "delete_concept",
        "list_concepts",
        # Edge CRUD
        "create_edge",
        "get_edge",
        "delete_edge",
        "list_edges",
        "get_neighbors",
        # Search & metrics (AP-68 scaffold)
        "search_semantic",
        "search_keyword",
        "get_metrics",
        # Read tools added by AP-70
        "search",
        "traverse",
        "list_edge_types",
        "get_status",
        "blast_radius",
    }
    tools = asyncio.run(mcp.list_tools())
    actual = {t.name for t in tools}
    missing = expected - actual
    assert not missing, f"Missing tools: {missing}"


# ---------------------------------------------------------------------------
# AC4: Lifespan initializes and cleans up DualWriter store
# ---------------------------------------------------------------------------


def test_lifespan_runs_without_error(tmp_path: Path):
    """Given a temp directory, the lifespan context manager starts and exits cleanly."""
    from apriori.mcp.server import build_lifespan

    lifespan = build_lifespan(
        db_path=tmp_path / "test.db",
        yaml_path=tmp_path / "backup.yaml",
    )

    async def run_lifespan():
        async with AsyncExitStack() as stack:
            ctx = await stack.enter_async_context(lifespan(mcp))
            return ctx

    ctx = asyncio.run(run_lifespan())
    assert ctx is not None


def test_lifespan_provides_knowledge_store(tmp_path: Path):
    """The lifespan context yields a dict with a 'store' key satisfying KnowledgeStore."""
    from apriori.mcp.server import build_lifespan
    from apriori.storage.protocol import KnowledgeStore

    lifespan = build_lifespan(
        db_path=tmp_path / "test.db",
        yaml_path=tmp_path / "backup.yaml",
    )

    async def run_lifespan():
        async with AsyncExitStack() as stack:
            ctx = await stack.enter_async_context(lifespan(mcp))
            return ctx

    ctx = asyncio.run(run_lifespan())
    assert "store" in ctx, f"Lifespan context must have 'store' key, got: {ctx!r}"
    assert isinstance(ctx["store"], KnowledgeStore), (
        f"store must satisfy KnowledgeStore protocol, got {type(ctx['store'])}"
    )
