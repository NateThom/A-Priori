# S-1: Async Architecture Decision Record

**Date:** 2026-04-03
**Status:** Decided
**Decision:** Sync core, async boundaries

---

## Context

A-Priori is a Python application with four entry points (MCP server, CLI, librarian loop, audit UI) built on top of a core library that handles storage, models, structural parsing, semantic enrichment, quality assurance, and knowledge management.

The system serves two concurrent workloads:

1. **Librarian iterations (write-heavy, slow):** N librarian agents run concurrently. Each reads from the knowledge graph, sends a prompt to an LLM (2-10 seconds latency), validates the response, and writes results back. The LLM call dominates iteration time.
2. **Agent/human queries (read-heavy, fast):** M external consumers (AI coding agents via MCP, humans via audit UI) query the knowledge graph concurrently. These are SQLite reads that should complete in under 500ms.

The question: should the `KnowledgeStore` protocol and other core interfaces use `async def` or plain `def`?

## Decision

**Sync core, async boundaries.**

- The core library (`models/`, `storage/`, `knowledge/`, `quality/`, `structural/`, `retrieval/`) is entirely synchronous.
- Async exists only at entry points and I/O boundaries:
  - **MCP server:** async handlers (required by MCP Python SDK), calling sync core via `asyncio.to_thread()`
  - **Audit UI server:** async FastAPI handlers, calling sync core via `asyncio.to_thread()`
  - **LLM adapters:** expose an async interface (`async def analyze(...)`) using `httpx.AsyncClient` for non-blocking network I/O
  - **Librarian orchestrator:** async function that manages N concurrent iterations, each of which calls sync core functions for local work and awaits the async LLM adapter for network calls

## Rationale

### Async is a property of I/O boundaries, not business logic

The core logic — priority scoring, Pydantic validation, quality checks, knowledge management, graph traversal — is pure computation on local data. Making these functions async adds `await` noise throughout the codebase for zero performance benefit. Sync code is simpler to write, debug, and test.

### The LLM adapter is where async is non-negotiable

When N librarians each have an LLM call in flight, those calls must be concurrent without N threads sitting idle. An async LLM adapter with `httpx.AsyncClient` handles this naturally: N calls in flight on one thread.

### The MCP SDK requires async, but the bridge is clean

The MCP Python SDK is async-native, built on `anyio` (not raw `asyncio`). Its high-level API (FastMCP) supports plain `def` tool handlers — it automatically bridges them to async via `anyio.to_thread.run_sync()`. We don't write bridging code ourselves; the MCP handler is a plain sync function that calls the sync core directly. (See S-6 decision record for details.)

### SQLite's concurrency model makes async storage pointless

SQLite with WAL mode supports concurrent reads (good for M queriers) but serializes writes (one writer at a time). `aiosqlite` just wraps sync SQLite in a thread pool — it's async cosmetics over sync reality. Keeping the storage layer sync is honest about what's actually happening.

Write serialization is not a practical bottleneck for N librarians because writes are millisecond operations. The bottleneck is the LLM call (seconds). N librarians have N LLM calls in flight concurrently; their writes serialize through SQLite quickly as each completes.

### Testing benefits are significant

Sync core code is tested with plain `pytest` — no `pytest-asyncio`, no `@pytest.mark.asyncio`, no async fixtures. Given that the core library is where the majority of business logic and tests live, this simplification compounds across the entire test suite.

## Consequences

### Interface Signatures

The `KnowledgeStore` protocol uses plain `def` methods:

```python
class KnowledgeStore(Protocol):
    def create_concept(self, concept: Concept) -> Concept: ...
    def get_concept(self, concept_id: UUID) -> Concept | None: ...
    def search_semantic(self, query_embedding: list[float], limit: int) -> list[Concept]: ...
    # etc.
```

The LLM adapter protocol uses `async def`:

```python
class LLMAdapter(Protocol):
    async def analyze(self, prompt: str, context: dict) -> AnalysisResult: ...
    def get_token_count(self, text: str) -> int: ...  # sync — pure computation
    def get_model_info(self) -> ModelInfo: ...          # sync — returns config
```

### Librarian Orchestrator Pattern

The orchestrator is async, managing concurrency at the iteration level:

```python
async def run_librarian(store: KnowledgeStore, adapter: LLMAdapter, max_iterations: int):
    """Run N iterations concurrently, bounded by config."""
    work_items = store.get_work_queue()  # sync call — fast
    tasks = []
    for item in work_items[:max_iterations]:
        tasks.append(run_single_iteration(store, adapter, item))
    await asyncio.gather(*tasks)

async def run_single_iteration(store: KnowledgeStore, adapter: LLMAdapter, item: WorkItem):
    context = store.load_context(item)          # sync — fast local read
    code = read_source_file(item.file_path)     # sync — fast local read
    prompt = build_prompt(item, context, code)   # sync — pure computation

    result = await adapter.analyze(prompt, context)  # ASYNC — slow network I/O

    validation = validate_level1(result, store)  # sync — fast computation
    if not validation.passed:
        store.record_failure(item, validation)   # sync — fast local write
        return

    store.integrate_knowledge(result)            # sync — fast local write
    store.resolve_work_item(item)                # sync — fast local write
```

### MCP Tool Handler Pattern

**Updated by S-6:** The MCP Python SDK uses FastMCP, which automatically bridges sync handlers to async via `anyio.to_thread.run_sync()`. We don't write the async bridging ourselves — handlers are plain `def` functions. A `safe_tool` decorator handles error translation (see S-6 for details).

```python
@mcp.tool()
@safe_tool
def search(query: str, mode: str = "keyword") -> list[dict]:
    """MCP tool — sync handler, FastMCP bridges to async automatically."""
    return retrieval.search(store, query, mode=mode)
```

### Thread Safety Requirements

Because sync core functions run in thread pool threads (via `anyio.to_thread.run_sync()` at the MCP boundary, `asyncio.to_thread()` at the audit UI boundary), SQLite connections must be per-thread. WAL mode plus per-thread connections from a connection pool provides safe concurrent access. This is well-trodden territory — no novel concurrency challenges.

## What This Decision Does NOT Cover

- **Which async framework** for the audit UI (FastAPI is assumed but confirmed in S-7)
- **Connection pooling strategy** for SQLite (implementation detail for the storage epic)
- **Whether the librarian runs in-process or as a subprocess** (orthogonal to sync/async — both work with this architecture)
