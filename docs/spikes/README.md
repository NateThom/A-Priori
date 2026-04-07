# A-Priori: Pre-Epic Spike Tracker

**Purpose:** These spikes produce decision records that unblock epic definition and implementation planning. Each spike answers a specific technical question whose answer changes how we write acceptance criteria, define interfaces, or estimate complexity.

**Status Key:** `done` | `in-progress` | `blocked` | `not-started`

---

## Spikes That Block Epic Definition

These must be resolved before epics can be written. Their answers change interface signatures, schema definitions, or architectural boundaries.

| ID | Spike | Status | Blocks | Est. Hours | Decision Record |
|----|-------|--------|--------|------------|-----------------|
| S-1 | Async Architecture | done | All epics (interface signatures) | 2-3 | [S-1-async-architecture.md](./S-1-async-architecture.md) |
| S-2 | Embedding Strategy | done | Storage layer epic (vec0 dimensions) | 3-4 | [S-2-embedding-strategy.md](./S-2-embedding-strategy.md) |
| S-6 | MCP Python SDK | done | MCP epic (may feed back into S-1) | 2 | [S-6-mcp-python-sdk.md](./S-6-mcp-python-sdk.md) |

## Spikes That Block Epic Implementation

These can be scheduled as first-stories within their parent epics. The epic can be defined without the answer, but implementation can't start until the spike resolves.

| ID | Spike | Status | Parent Epic | Est. Hours | Decision Record |
|----|-------|--------|-------------|------------|-----------------|
| S-3 | Tree-sitter Grammar Quality | done | Structural Engine | 3-4 | [S-3-tree-sitter-grammar-quality.md](./S-3-tree-sitter-grammar-quality.md) |
| S-4 | Blast Radius Validation | not-started | Phase 3: Blast Radius | 2-3 | — |
| S-5 | YAML Performance at Scale | not-started | Storage Layer | 2-3 | — |
| S-7 | Audit UI Technology | not-started | Audit UI | 4-6 | — |
| S-8 | Co-Regulation Prompt Design | not-started | Quality Pipeline | 3-4 | — |

---

## Spike Descriptions

### S-1: Async Architecture (DONE)
**Question:** Should the core library, storage protocol, and interfaces use sync or async Python?
**Why it blocks:** Async vs. sync changes every function signature in the system. Can't write epic acceptance criteria that reference interfaces without knowing this.
**Decision:** Sync core, async boundaries. See [decision record](./S-1-async-architecture.md).

### S-2: Embedding Strategy (DONE)
**Question:** Which embedding model and dimensions should we use for sqlite-vec? What's the cost/quality trade-off for local vs. API embeddings?
**Why it blocks:** The `vec0` virtual table requires a fixed embedding dimension at creation time. Can't define the storage schema without this.
**Decision:** Local `e5-base-v2` via `sentence-transformers`, 768 dimensions, cosine distance. See [decision record](./S-2-embedding-strategy.md).

### S-3: Tree-sitter Grammar Quality (DONE)
**Question:** How complete is tree-sitter's Python and TypeScript grammar coverage for our extraction needs? What structural entities does it miss?
**Why it doesn't block definition:** The structural engine epic can be defined as "extract functions, classes, modules, imports using tree-sitter." Gaps discovered here become workaround stories.
**Decision:** tree-sitter-python 0.25.0 and tree-sitter-typescript 0.23.2 are fit for purpose. Zero parse errors on 16 diverse cases. 9 extraction gaps documented with structural workarounds. `arch:tree-sitter-only` validated. See [decision record](./S-3-tree-sitter-grammar-quality.md).

### S-4: Blast Radius Validation
**Question:** How do we validate that blast radius predictions are accurate? What does the test harness look like?
**Why it doesn't block definition:** The blast radius epic can be defined in terms of the three-layer impact model. Validation methodology is an implementation detail.

### S-5: YAML Performance at Scale
**Question:** At what graph size does the dual-write YAML strategy become a bottleneck? What's the read/write performance curve?
**Why it doesn't block definition:** The storage epic is defined around the `KnowledgeStore` protocol. YAML performance only matters at scale and can be addressed with a migration path.

### S-6: MCP Python SDK (DONE)
**Question:** Does the SDK have quirks in tool registration, lifecycle management, or transport that affect our architecture? Does it mandate a specific async framework?
**Why it partially blocks:** If the SDK mandates a specific async framework or has an unexpected execution model, that feeds back into S-1. Low risk given S-1 already accounts for the SDK being async-native.
**Decision:** FastMCP with sync tool handlers, pinned to v1.x. SDK uses anyio (not raw asyncio), but this is compatible with S-1. FastMCP auto-bridges sync handlers to async. S-1 amended to reflect this. See [decision record](./S-6-mcp-python-sdk.md).

### S-7: Audit UI Technology
**Question:** FastAPI + htmx? FastAPI + React SPA? Flask? What's the right stack for a local-only audit UI?
**Why it doesn't block definition:** The audit UI epic can be defined in terms of capabilities (graph explorer, librarian monitor, review workflow). Technology selection is the first implementation decision.

### S-8: Co-Regulation Prompt Design
**Question:** Can an LLM-as-judge prompt reliably discriminate between good and bad librarian output? What does the prompt look like? What are the failure modes?
**Why it doesn't block definition:** The quality pipeline epic is defined in terms of the three-level system. Prompt design is the first implementation task.
