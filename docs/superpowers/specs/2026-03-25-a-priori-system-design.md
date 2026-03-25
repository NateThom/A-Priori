# A-Priori: System Design Specification

**Date:** 2026-03-25
**Status:** Approved
**Author:** Nate Thom + Claude

## Overview

A-Priori is an agent-first, MCP-enabled knowledge base that automatically builds and maintains a concept graph for a codebase. It ingests code, documentation, and architectural patterns, organizes them as a linked graph of concepts, and exposes precise retrieval tools for AI agents via the Model Context Protocol.

**Design principle:** Agents get the context they need, but ONLY the context they need. Precision over volume.

### Scope

**MVP (build now):**
- Knowledge graph with concept nodes, typed edges, labels, and node metadata
- Local storage (SQLite + sqlite-vec, flat YAML files as source of truth)
- Storage abstraction interface for future backend swaps
- MCP server with unified search and full CRUD tools
- Code reference system with repair chain
- Configuration file with sensible defaults and JSON schema
- Initial bootstrap crawl
- Diff-based maintenance backlog generation
- Deepening loop with advisory priority scoring

**Deferred (in priority order):**
1. Full coverage scan and semantic-graph disagreement scan
2. Human UI and RAG chat (`ask` tool)
3. Hosted/cloud storage backend
4. Federation between instances
5. Edge type governance workflow (formal vetting/migration process)

## Architecture

**Approach: Core Library + Thin Shells**

The knowledge graph logic lives in a core Python package (`apriori`). The MCP server and deepening agent are thin wrappers that import and use the core. This provides clean separation without distributed systems complexity, and naturally supports the storage abstraction and future entry points (CLI, UI server, scheduled jobs).

```
┌──────────────┐    ┌───────────────┐
│  MCP Server  │    │  Deepening    │
│   (shell)    │    │  Agent (shell)│
└──────┬───────┘    └───────┬───────┘
       │                    │
       └────────┬───────────┘
                │
  ┌─────────────┴──────────────┐
  │      apriori (core lib)    │
  │                            │
  │  ┌────────┐ ┌───────────┐  │
  │  │ Graph  │ │ Embedding │  │
  │  │ Engine │ │  Engine   │  │
  │  └───┬────┘ └─────┬─────┘  │
  │      └──────┬──────┘       │
  │      ┌──────┴──────┐       │
  │      │ Store Layer │       │
  │      │ (abstract)  │       │
  │      └──────┬──────┘       │
  └─────────────┼──────────────┘
         ┌──────┴──────┐
         │SQLite + vec │
         │+ flat files │
         └─────────────┘
```

### Package Structure

```
apriori/
├── core/
│   ├── models.py          — Concept, Edge, CodeReference, Subgraph dataclasses
│   ├── store.py           — KnowledgeStore protocol (abstract interface)
│   └── config.py          — Config loading, defaults, schema validation
│
├── graph/
│   ├── engine.py          — Graph operations: traverse, filter, subgraph extraction
│   └── query.py           — Unified search: mode routing, filter composition
│
├── embedding/
│   ├── engine.py          — Embedding protocol (abstract)
│   ├── openai.py          — OpenAI embeddings implementation
│   └── ollama.py          — Local Ollama implementation (future)
│
├── storage/
│   ├── local.py           — LocalStore: SQLite + sqlite-vec + flat files
│   └── flatfile.py        — Flat file read/write (YAML concept files)
│
├── references/
│   └── resolver.py        — Code reference repair chain: symbol → hash → semantic
│
├── maintenance/
│   ├── backlog.py         — Work item queue: creation, prioritization, scoring
│   ├── differ.py          — Git diff analysis → work item generation
│   └── bootstrap.py       — Initial repo crawl and concept generation
│
└── shells/
    ├── mcp_server.py      — MCP server (thin shell, imports core)
    └── deepening_agent.py — Deepening loop (thin shell, imports core)
```

Every major subsystem has its own module and depends on `core/` but not on sibling modules. The `storage/` module implements the protocol defined in `core/store.py`. The `embedding/` module is its own abstraction, swappable between providers.

## Data Model

### Concept Node

| Field | Type | Description |
|-------|------|-------------|
| `id` | UUID | Unique identifier |
| `name` | string | Human-readable, unique within project |
| `description` | string | Rich, markdown-compatible description |
| `labels` | set[string] | Housekeeping metadata only (e.g., `needs-review`, `auto-generated`, `deprecated`) |
| `code_references` | list[CodeReference] | Links to code (see below) |
| `created_by` | `"agent"` \| `"human"` | Provenance |
| `verified_by` | optional[`"human"`] | Whether a human has verified |
| `last_verified` | timestamp | When the agent last confirmed accuracy |
| `created_at` | timestamp | Creation time |
| `updated_at` | timestamp | Last modification time |

**Labels vs concepts:** If you can name it, it's a concept, not a label. Labels are reserved for metadata about the state of the knowledge (`needs-review`, `auto-generated`, `deprecated`), not the domain being modeled. "Payment processing" is a concept node; "stale" is a label.

### Edge

| Field | Type | Description |
|-------|------|-------------|
| `id` | UUID | Unique identifier |
| `source` | concept_id | Source concept |
| `target` | concept_id | Target concept |
| `edge_type` | string | From controlled vocabulary |
| `metadata` | optional[dict] | Notes, confidence score, etc. |
| `created_at` | timestamp | Creation time |

### CodeReference (embedded in Concept)

Code references use a **repair chain** for resilience. Resolution tries each method in order, escalating only on failure:

1. **Symbol name** (primary) — fast, free, exact. Works ~80% of the time.
2. **Content hash** (change detection) — detects code changes even when symbol resolves. Triggers `needs-review` on mismatch.
3. **Semantic anchor** (fallback) — natural language description used to re-find code after major refactors. Expensive, invoked only when symbol lookup fails.

| Field | Type | Description |
|-------|------|-------------|
| `symbol` | string | e.g., `validate_amount` — primary lookup key |
| `file_path` | string | e.g., `src/payments/validate.py` |
| `content_hash` | string | Hash of referenced code at last verification |
| `semantic_anchor` | string | Natural language description for repair fallback |
| `line_range` | optional[tuple[int, int]] | Hint, not authoritative |

### Starting Edge Type Vocabulary

| Edge Type | Description |
|-----------|-------------|
| `depends-on` | X requires Y to function |
| `implements` | X is the concrete realization of Y |
| `relates-to` | Generic association (fallback) |
| `owned-by` | Person or team responsible |
| `supersedes` | X replaced Y |
| `extends` | X builds on or specializes Y |

Six types to start. New types require a governance process (deferred). The vocabulary is defined in `apriori.config.yaml` and is the single source of truth for valid edge types.

## Storage Architecture

### Abstract Interface

```python
class KnowledgeStore(Protocol):
    # Concept CRUD
    def create_concept(concept) -> Concept
    def get_concept(id) -> Concept
    def update_concept(id, changes) -> Concept
    def delete_concept(id) -> void

    # Edge CRUD
    def create_edge(edge) -> Edge
    def get_edges(concept_id, edge_types?, direction?) -> list[Edge]
    def update_edge(id, changes) -> Edge
    def delete_edge(id) -> void

    # Traversal
    def traverse(start_id, edge_types?, max_hops?, max_nodes?,
                 strategy: "bfs"|"dfs") -> Subgraph

    # Search
    def semantic_search(query, filters?, limit?) -> list[RankedResult]

    # Maintenance
    def get_stale_concepts(threshold_seconds) -> list[Concept]
    def get_concepts_by_label(label) -> list[Concept]
    def get_concepts_by_file(file_path) -> list[Concept]

    # Index management
    def rebuild_index() -> void
```

### MVP Implementation (LocalStore)

- **SQLite** for graph structure (concepts, edges, labels, code references)
- **sqlite-vec** extension for vector embeddings (semantic search)
- **Flat YAML files** as portable source of truth in `~/.a-priori/<project>/graph/`

**Sync direction:** Flat files are authoritative. On startup, the store checks if the SQLite index is stale (comparing file modification times against a last-rebuild timestamp) and rebuilds if needed. Write operations update both the flat file and the SQLite index simultaneously.

**Concurrent access:** SQLite WAL mode — one writer, multiple readers. MCP server is primarily a reader; deepening agent is primarily a writer. SQLite handles conflicts with retry.

**Future swap:** The `KnowledgeStore` protocol allows swapping to Postgres + pgvector, Neo4j, or any other backend by writing a new implementation. No changes to the core library, MCP tools, or deepening agent.

### Flat File Format

Each concept is a YAML file. Edges are stored on the source node's file. The SQLite index handles bidirectional lookups. Filenames are slugified concept names; collisions get a short hash suffix.

```yaml
# ~/.a-priori/my-project/graph/payment-validation.yaml

id: "a1b2c3d4-..."
name: "Payment Validation"
description: |
  Validates incoming payment requests against currency-specific
  limits, merchant account status, and fraud rules before
  forwarding to the payment processor.

labels:
  - "auto-generated"

created_by: "agent"
verified_by: null
last_verified: "2026-03-25T14:30:00Z"
created_at: "2026-03-25T12:00:00Z"
updated_at: "2026-03-25T14:30:00Z"

code_references:
  - symbol: "validate_amount"
    file_path: "src/payments/validate.py"
    content_hash: "sha256:a8f3..."
    semantic_anchor: "Function that checks payment amounts against currency-specific limits"
    line_range: [45, 80]
  - symbol: "check_merchant_status"
    file_path: "src/payments/merchant.py"
    content_hash: "sha256:b7e2..."
    semantic_anchor: "Verifies the merchant account is active and in good standing"
    line_range: [12, 35]

edges:
  - target: "fraud-detection"
    edge_type: "depends-on"
  - target: "payment-processor-integration"
    edge_type: "depends-on"
  - target: "currency-handling"
    edge_type: "relates-to"
  - target: "platform-team"
    edge_type: "owned-by"
```

## MCP Tool Surface

### Read Tools

#### `search`

Unified lookup with multiple modes and composable filters.

**Modes:**
- `semantic` (default) — vector similarity search
- `keyword` — text matching against name and description
- `exact` — name or ID lookup
- `file` — concepts referencing a given file path

**Filters** (composable with any mode):

| Filter | Type | Description |
|--------|------|-------------|
| `labels` | list[string] | Concepts with these labels |
| `exclude_labels` | list[string] | Concepts without these labels |
| `created_by` | string | Provenance filter |
| `verified_by` | string \| null | Verification filter |
| `created_after` | datetime | Time filter |
| `created_before` | datetime | Time filter |
| `updated_after` | datetime | Time filter |
| `updated_before` | datetime | Time filter |
| `stale_since` | datetime | `last_verified` before this date |
| `has_edge_type` | string | Has at least one edge of this type |
| `connected_to` | string | Has an edge to this concept |
| `references_file` | string | References this file path (glob supported) |

**Returns:** Ranked list of concepts with relevance scores and summaries.

#### `traverse`

Graph traversal from a starting concept.

**Inputs:**
- `start` — concept ID or name
- `edge_types` — optional filter, only follow these edge types
- `max_hops` — maximum traversal depth
- `max_nodes` — maximum nodes to visit
- `strategy` — `"bfs"` or `"dfs"`

**Returns:** Subgraph — set of concepts and edges reachable from start, respecting filters.

#### `list_edge_types`

**Returns:** The current edge type vocabulary with descriptions, from config.

### Write Tools

| Tool | Inputs | Returns |
|------|--------|---------|
| `create_concept` | `name, description, labels?, code_references?` | Created concept |
| `update_concept` | `id_or_name, changes` | Updated concept |
| `delete_concept` | `id_or_name` | Confirmation |
| `create_edge` | `source, target, edge_type, metadata?` | Created edge |
| `update_edge` | `id, changes` | Updated edge |
| `delete_edge` | `id` | Confirmation |
| `report_gap` | `description, context?` | Created work item in maintenance backlog |

## Deepening Loop & Maintenance

### Ingestion Lifecycle

1. **Bootstrap:** Agent crawls the repo, generates `investigate_file` work items for every source file, then processes them through the normal deepening loop.
2. **Deepening loop:** Agent autonomously picks areas to study more deeply or explore new areas, based on its own assessment informed by advisory priority scores.
3. **Maintenance:** Scheduled diff checks generate work items for concepts whose referenced code has changed.
4. **Live updates:** Working agents contribute updates via MCP write tools as a side effect of their work.

### Work Items

Work items are persisted in SQLite as a separate table (not concept nodes).

**Types:**
- `investigate_file` — uncovered code, from coverage scan
- `verify_concept` — referenced code changed, from diff watcher
- `evaluate_relationship` — semantic-graph disagreement, from scan
- `reported_gap` — explicit flag from a working agent via `report_gap`
- `review_concept` — concept labeled `needs-review`

**Sources and cadences:**

| Source | Trigger | Cadence |
|--------|---------|---------|
| `report_gap` MCP tool | Event-driven | Immediate |
| Git diff watcher | Scheduled | Configurable (default: every 30 min) |
| Coverage scan | Scheduled | Deferred (future: configurable) |
| Semantic-graph scan | Scheduled | Deferred (future: configurable) |

### Advisory Priority Scoring

Each work item receives a computed priority score:

```
priority = w1 * staleness        (last_verified age vs file change recency)
         + w2 * needs_review     (1 if flagged, 0 if not)
         + w3 * coverage_gap     (unreferenced code centrality)
         + w4 * git_activity     (change frequency in related files)
         + w5 * semantic_delta   (similarity score with no edge)
```

Default weights (configurable in `apriori.config.yaml`):
- `staleness`: 0.3
- `needs_review`: 0.25
- `coverage_gap`: 0.25
- `git_activity`: 0.1
- `semantic_graph_delta`: 0.1

**The priority score is advisory, not directive.** The deepening agent sees the full backlog with scores but is free to choose what to work on based on its own judgment. The agent's behavior is steered by a configurable system prompt (`deepening_agent.system_prompt_path` in config), not by rigid queue ordering. Different prompts produce different agent personalities: maintenance-focused, exploration-focused, or responsive to reported gaps.

### Label Derivation

Labels are derived automatically, not manually applied:

| Signal | Mechanism |
|--------|-----------|
| Staleness | Computed: `file_last_modified > concept.last_verified` |
| `needs-review` | Event-driven: set by diff watcher, `report_gap`, or semantic-graph disagreement; cleared when agent reviews |
| Provenance | Set at creation: `created_by: agent\|human`, `verified_by: human` (optional) |
| `deprecated` | Proposed by agent when all code references are gone |

### Semantic-Graph Disagreement as Gap Detection

The semantic search and graph traversal are complementary sensors:
- **Graph** = what is *known* to be connected
- **Semantic search** = what *appears* to be connected
- **The delta** = knowledge gaps to investigate

When semantic search says two concepts are related but the graph has no edge between them, that's a signal — an undocumented relationship. The maintenance agent monitors for these disagreements and generates `evaluate_relationship` work items.

## Configuration

Single file at project root: `apriori.config.yaml`. Every field has a default. A JSON schema ships with the package for validation, auto-documentation, and discoverability via the `get_config_schema` MCP tool (future).

```yaml
project:
  name: "my-project"
  repo_path: "."
  store_path: "~/.a-priori/my-project"

storage:
  backend: "local"                        # local | postgres | neo4j (future)

graph:
  edge_types:
    - name: "depends-on"
      description: "X requires Y to function"
    - name: "implements"
      description: "X is the concrete realization of Y"
    - name: "relates-to"
      description: "Generic association"
    - name: "owned-by"
      description: "Person or team responsible"
    - name: "supersedes"
      description: "X replaced Y"
    - name: "extends"
      description: "X builds on or specializes Y"

embeddings:
  provider: "openai"                      # openai | ollama (future)
  model: "text-embedding-3-small"

scheduling:
  diff_check: "*/30 * * * *"
  deepening_loop: "0 */4 * * *"

priority_weights:
  staleness: 0.3
  needs_review: 0.25
  coverage_gap: 0.25
  git_activity: 0.1
  semantic_graph_delta: 0.1

deepening_agent:
  max_iterations_per_run: 10
  system_prompt_path: "prompts/deepen.md"
```

## Key Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Primary consumer | Agents (MCP-first) | Human UI deferred; agents need precise, structured context |
| MVP scope | Single repo | Federation is north star but adds complexity |
| Ingestion model | Hybrid seeded | Bootstrap crawl + diff-driven maintenance + agent side effects |
| Node granularity | Concept-level | Concepts reference code via typed edges; a piece of code can belong to multiple concepts naturally |
| Edge typing | Controlled vocabulary (6 types) | Precision for agent queries; `relates-to` as generic fallback; governance process deferred |
| Code references | Repair chain (symbol, hash, semantic) | Symbol for speed, hash for change detection, semantic for resilience |
| Storage | Local SQLite + flat YAML files | Zero cost, private, portable; abstract interface enables future cloud swap |
| Architecture | Core library + thin shells | Clean separation without distributed complexity; supports future entry points |
| Deepening agent control | Advisory scores, agent decides | LLM judgment > rigid queue; behavior steered by configurable system prompt |
| Search | Unified tool with modes + filters | One flexible tool > five specialized ones; composable filtering on all node attributes |
| Labels | Housekeeping metadata only | If you can name it, it's a concept. Labels for state (`stale`, `needs-review`), not domain knowledge |
