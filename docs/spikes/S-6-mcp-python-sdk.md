# S-6: MCP Python SDK Decision Record

**Date:** 2026-04-03
**Status:** Decided
**Decision:** FastMCP with sync tool handlers, pinned to v1.x

---

## Context

A-Priori exposes its knowledge graph to AI coding agents via 13 MCP tools (6 read, 7 write). The MCP server is a thin shell that delegates to the sync core library. S-1 decided "sync core, async boundaries" — the question here is how the MCP Python SDK shapes that boundary.

Three specific concerns motivated this spike:

1. **Async framework mandate:** Does the SDK require a specific async framework that might conflict with S-1's architecture?
2. **Tool registration ergonomics:** How much glue code is needed per tool? With 13 tools, boilerplate compounds.
3. **Error handling conventions:** How do tools report errors to MCP clients?

## Decision

**Use FastMCP (the high-level API included in the MCP Python SDK v1.x) with synchronous tool handlers. Pin to `mcp>=1.26,<2.0`.**

FastMCP is the SDK's recommended API for new servers. It was originally a separate project, merged into the official SDK, and is used by the majority of Python MCP servers in production. It provides decorator-based tool registration, automatic JSON Schema generation from type hints, automatic sync-to-async bridging, and lifespan hooks for resource management.

## Rationale

### FastMCP sync handlers align perfectly with S-1

S-1 decided the core library is synchronous. FastMCP supports plain `def` tool handlers — when it detects a non-coroutine function, it automatically wraps it with `anyio.to_thread.run_sync()` so it doesn't block the event loop. This means we don't write any async bridging code ourselves. The handler is a plain sync function that calls the sync core directly.

This is functionally equivalent to S-1's original `asyncio.to_thread()` pattern, but the framework handles it. Less code, same behavior.

### The SDK uses anyio, not raw asyncio

The MCP Python SDK's async foundation is `anyio>=4.9`, which abstracts over both asyncio and trio. In practice, anyio runs on asyncio by default, so there's no conflict with the rest of our stack (FastAPI for the audit UI, the librarian's `asyncio.gather` for concurrent iterations). But the threading primitive is `anyio.to_thread.run_sync()`, not `asyncio.to_thread()`.

This is a minor S-1 amendment: the MCP boundary uses anyio's threading, not asyncio's. The distinction is cosmetic — same behavior, different import — but the decision record should be accurate.

### FastMCP eliminates schema boilerplate

With 13 tools, the alternative (low-level `Server` API) would require manually defining JSON Schema for each tool's input, maintaining a `list_tools()` handler, and writing a match/case dispatch in `call_tool()`. FastMCP derives all of this from type hints and docstrings:

```python
@mcp.tool()
def search(query: str, mode: str = "keyword", limit: int = 10) -> list[dict]:
    """Search the knowledge graph by keyword, exact match, file, or semantic similarity."""
    return retrieval.search(store, query, mode=mode, limit=limit)
```

The decorator registers the tool, generates `{"type": "object", "properties": {"query": {"type": "string"}, ...}}` from the signature, and uses the docstring as the tool description. No Pydantic input models needed — type hints are sufficient.

### Error handling requires an explicit workaround

SDK Issue #396: exceptions raised in tool handlers are NOT properly translated to JSON-RPC errors. The SDK catches the exception and returns a *successful* response with the error message as text content. MCP clients cannot distinguish between success and failure.

Community consensus and our decision: wrap all tool handlers with a decorator that catches exceptions and returns explicit `CallToolResult(isError=True)` responses:

```python
def safe_tool(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except ValueError as e:
            return CallToolResult(
                isError=True,
                content=[TextContent(type="text", text=str(e))]
            )
        except Exception as e:
            return CallToolResult(
                isError=True,
                content=[TextContent(type="text", text=f"Internal error: {type(e).__name__}")]
            )
    return wrapper
```

Validation errors (bad input) return descriptive messages. Unexpected errors return the exception type without exposing internals.

## Consequences

### Tool Handler Pattern

Every MCP tool follows this pattern:

```python
from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult, TextContent

mcp = FastMCP("a-priori", lifespan=app_lifespan)

@mcp.tool()
@safe_tool
def search(query: str, mode: str = "keyword", limit: int = 10) -> list[dict]:
    """Search the knowledge graph by keyword, exact match, file, or semantic similarity."""
    return retrieval.search(store, query, mode=mode, limit=limit)
```

Each handler is 3–10 lines of glue: validate input (if beyond what type hints cover), call sync core, return result. All business logic lives in the core library.

### Server Lifecycle

FastMCP's lifespan context manager initializes and tears down shared resources:

```python
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from dataclasses import dataclass

@dataclass
class AppContext:
    store: KnowledgeStore

@asynccontextmanager
async def app_lifespan(server: FastMCP) -> AsyncIterator[AppContext]:
    config = load_config()
    store = SqliteStore(config.storage.db_path)
    try:
        yield AppContext(store=store)
    finally:
        store.close()

mcp = FastMCP("a-priori", lifespan=app_lifespan)
```

The `AppContext` is available to tools via `ctx.request_context.lifespan_context` if using the `Context` parameter, or via a module-level reference (simpler for sync handlers — the lifespan sets the module-level `store` variable at startup).

### Transport

stdio for MVP. This is how Claude Code, Cursor, and other MCP clients launch local servers — as a subprocess with JSON-RPC over stdin/stdout. No HTTP server, no auth, no session management.

```python
if __name__ == "__main__":
    mcp.run(transport="stdio")
```

### SDK Version Pinning

Pin to `mcp>=1.26,<2.0` in `pyproject.toml`. v2 is in pre-alpha with breaking transport changes. Our MCP surface area is ~200 lines of glue code, so migration to v2 when it stabilizes will be straightforward. No need to plan for it now.

```toml
# v2 will require a migration pass when it stabilizes — our MCP surface is thin enough that this is low-effort
"mcp>=1.26,<2.0",
```

### S-1 Amendment

S-1's MCP tool handler pattern is updated. The original pattern:

```python
# S-1 original — we write the async bridging ourselves
@mcp_server.tool()
async def search(query: str, mode: str = "keyword") -> list[dict]:
    results = await asyncio.to_thread(store.search_keyword, query)
    return format_results(results)
```

Becomes:

```python
# S-6 update — FastMCP handles the bridging
@mcp.tool()
@safe_tool
def search(query: str, mode: str = "keyword") -> list[dict]:
    """Search the knowledge graph."""
    return retrieval.search(store, query, mode=mode)
```

The librarian orchestrator and audit UI patterns from S-1 are unchanged — those are our async code, not SDK code.

## Known Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| SDK memory leaks in long-lived servers (Issues #756, #1076) | Medium | Monitor memory usage; MCP clients reconnect naturally, restarting the subprocess |
| macOS + Python 3.12 hangs at KqueueSelector (Issue #547) | Medium | Test on target Python version early in Phase 1; use 3.11 or 3.13 if affected |
| Exception handling bug (Issue #396) | High | Mitigated by `safe_tool` decorator returning explicit `CallToolResult(isError=True)` |
| Progress callbacks broken (Issue #1600) | Low | Don't depend on `ctx.report_progress()` for correctness; all A-Priori queries target <500ms anyway |
| v2 breaking changes | Low | Pinned to v1.x; thin MCP surface makes future migration straightforward |

## What This Decision Does NOT Cover

- **Which 13 tools to implement and their exact schemas** — defined in the ERD §3.4 and §8, implemented during Phase 1
- **Whether to use `Context` parameter or module-level state** — implementation detail, decided during Phase 1 storage epic
- **HTTP transport for remote deployment** — not an MVP concern; revisit if A-Priori moves beyond local-only
- **FastMCP's structured output validation** — available but not needed for MVP; tools return plain dicts
