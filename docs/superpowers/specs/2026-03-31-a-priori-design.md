# A-Priori: Self-Constructing Knowledge Base

**Date:** 2026-03-31
**Status:** Draft

## Problem Statement

AI agents working with codebases waste time and tokens re-exploring systems that have already been understood. Raw code tools (file reads, grep, git history) provide data but not understanding — agents must reconstruct mental models from scratch on every task. There is no persistent, structured layer of synthesized knowledge that agents can query for pre-digested understanding.

A-Priori solves this by providing a self-constructing knowledge base that builds and maintains itself through dedicated "librarian" agents. Task agents query it for fast, precise context — turning what would be 15 tool calls of exploration into 1-2 retrievals.

## Core Principles

1. **Speed over completeness** — the primary value is fast retrieval of pre-digested knowledge. A smaller, high-quality knowledge base beats a comprehensive but slow one.
2. **Self-constructing** — librarian agents build and maintain the knowledge base autonomously. Humans steer by choosing what to track, not by writing content.
3. **Demand-driven** — the feedback loop from task agent queries tells librarians where to invest effort. Knowledge grows toward what agents actually need.
4. **Quality-gated** — deterministic metrics enforce content standards. Content must clear a scoring threshold before reaching a reviewer agent.
5. **Code-first** — designed for software codebases. The architecture does not preclude other domains but does not contort itself to accommodate them.

## Architecture Overview

```
┌─────────────┐     ┌──────────────┐
│  Task Agent  │     │   Human      │
│  (MCP tools) │     │   (CLI)      │
└──────┬───────┘     └──────┬───────┘
       │                    │
       ▼                    ▼
┌──────────────────────────────────┐
│          Core Library            │
│  ┌────────┐ ┌────────┐ ┌──────┐ │
│  │ Search │ │ Graph  │ │ Store│ │
│  └────────┘ └────────┘ └──────┘ │
└──────────────┬───────────────────┘
               │
               ▼
┌──────────────────────────────────┐
│       Storage (SQLite/Postgres)  │
│  concepts │ edges │ documents    │
│  code_anchors │ query_log        │
└──────────────────────────────────┘
               ▲
               │
┌──────────────┴───────────────────┐
│          Librarian Agent         │
│  ┌───────────┐ ┌──────────────┐  │
│  │ Priorities│ │ Quality Gate │  │
│  └───────────┘ └──────────────┘  │
│  ┌───────────┐                   │
│  │ Reviewer  │                   │
│  └───────────┘                   │
└──────────────────────────────────┘
```

Two interfaces share one core library:
- **MCP Server** — agent-facing. Exposes read tools for task agents, write tools for librarian agents.
- **CLI** — human-facing. Workspace management, librarian control, search, inspection.

## Data Model

### Graph Layer (Thin Spine)

The graph provides fast, structured navigation. Nodes are cheap index entries, not the knowledge itself.

**Concept Node:**
| Field | Type | Description |
|-------|------|-------------|
| `id` | UUID | Primary key |
| `name` | string | Unique within workspace. Human-readable. |
| `type` | string | module, pattern, subsystem, decision, utility, etc. |
| `root_id` | UUID? | Which root this concept belongs to. Null for shallow/cross-cutting concepts. |
| `code_anchors` | CodeAnchor[] | File paths + symbols that ground this concept in code. |
| `created_at` | timestamp | |
| `updated_at` | timestamp | |

**Edge:**
| Field | Type | Description |
|-------|------|-------------|
| `id` | UUID | Primary key |
| `source` | UUID | Source concept |
| `target` | UUID | Target concept |
| `edge_type` | string | From controlled vocabulary |
| `metadata` | dict? | Optional (confidence, notes) |
| `created_at` | timestamp | |

**Edge type vocabulary:**
- `depends-on` — source requires target to function
- `implements` — source is a concrete implementation of target
- `owns` — source contains or is responsible for target
- `extends` — source builds upon or specializes target
- `relates-to` — generic association (fallback when no specific type fits)
- `supersedes` — source replaces target

**CodeAnchor:**
| Field | Type | Description |
|-------|------|-------------|
| `symbol` | string | Function/class/variable name |
| `file_path` | string | Path relative to workspace root |
| `content_hash` | string | SHA256 of code at last verification |
| `line_range` | [int, int]? | Hint, not authoritative |

### Document Layer (Rich Leaves)

Documents carry the actual knowledge. They are the librarian's primary deliverable.

**Document:**
| Field | Type | Description |
|-------|------|-------------|
| `id` | UUID | Primary key |
| `concept_id` | UUID | The concept this document explains |
| `content` | string | Markdown. The knowledge itself. |
| `summary` | string | Short abstract for fast retrieval without loading full content. |
| `code_references` | CodeReference[] | Specific code locations discussed in the document. |
| `embedding` | vector | Embedding of the summary for semantic search. |
| `confidence` | float | Librarian's self-assessed confidence (0-1). |
| `staleness_score` | float | Computed from code anchor validity. |
| `created_at` | timestamp | |
| `updated_at` | timestamp | |

A concept can have multiple documents (e.g., an overview and a deep-dive on a tricky aspect).

**CodeReference:**
| Field | Type | Description |
|-------|------|-------------|
| `symbol` | string | Function/class name |
| `file_path` | string | Path relative to workspace root |
| `content_hash` | string | SHA256 of referenced code |
| `line_range` | [int, int]? | Hint |

### Feedback Layer

**QueryLog:**
| Field | Type | Description |
|-------|------|-------------|
| `id` | UUID | Primary key |
| `query` | string | What the agent searched for |
| `mode` | string | semantic, keyword, code |
| `results` | UUID[] | Concept IDs returned |
| `followed_up` | UUID[] | Which results the agent fetched documents for |
| `timestamp` | timestamp | |

Logged passively by `search` and `get_document` tools. No explicit feedback tool needed — usefulness is inferred from follow-up behavior.

### Review Queue

**ReviewItem:**
| Field | Type | Description |
|-------|------|-------------|
| `id` | UUID | Primary key |
| `type` | string | gap, ambiguous_intent, conflicting_pattern, domain_knowledge, stale_unresolvable, root_recommendation |
| `context` | string | What the librarian tried and why it's stuck |
| `suggested_action` | string | What the librarian thinks the human should do |
| `concept_id` | UUID? | Related concept if applicable |
| `resolved` | bool | |
| `created_at` | timestamp | |

Capped at 10 items. The librarian must document its attempts before escalating.

## Workspace & Root Model

**One workspace = one knowledge base = one database.**

A workspace points at a directory (e.g., `~/work/`). All tracked content within it shares a single graph — no artificial boundaries between repos.

**Roots** are directories within the workspace that librarians actively build knowledge for. They control where librarians invest effort, not what can appear in the graph.

- Roots are selected by the user via CLI (`apriori add <path>`)
- Librarians proactively crawl and build deep knowledge within roots
- Code outside roots can still appear as shallow concepts (name + edges, no document) when referenced by root code
- Users can promote a shallow concept's directory to a root at any time

**Multi-repo example:**
```
Workspace: ~/work/
Roots:
  - ~/work/api-service/        (full knowledge)
  - ~/work/auth-library/       (full knowledge)
  - ~/work/shared-sdk/         (full knowledge)
Non-root repos discovered but not tracked deeply.
```

**Monorepo example:**
```
Workspace: ~/work/monorepo/
Roots:
  - ~/work/monorepo/packages/auth/      (full knowledge)
  - ~/work/monorepo/packages/billing/   (full knowledge)
Rest of monorepo not deeply tracked.
```

## Storage Architecture

### Storage Abstraction

All data access goes through a storage protocol/interface. Two implementations planned:

1. **SQLite** (development / single-user) — default. sqlite-vec for embeddings. Zero setup.
2. **Postgres/Supabase** (production / multi-user) — added later. pgvector for embeddings.

Build against the interface from day one. Implement SQLite first.

### Data Location (XDG Base Directory)

- **Config:** `$XDG_CONFIG_HOME/a-priori/config.yaml` (defaults to `~/.config/a-priori/`)
- **Data:** `$XDG_DATA_HOME/a-priori/workspaces/<name>/apriori.db` (defaults to `~/.local/share/a-priori/`)

### Database Schema

SQLite with WAL mode for concurrent reads (MCP server) + single writer (librarian). *Note: query logging (MCP server writes) and librarian writes are both write operations. WAL allows only one writer at a time — concurrent write attempts get SQLITE_BUSY. Query log inserts should use a short retry with backoff to handle contention.*

**Tables:**
- `roots` — tracked directories within the workspace
- `concepts` — thin graph nodes with optional `root_id`
- `edges` — typed relationships, no boundary restrictions
- `documents` — markdown content + summary + embedding vector
- `code_anchors` — per concept: file path + symbol + content hash
- `code_references` — per document: file path + symbol + content hash
- `query_log` — agent search signals
- `review_queue` — librarian escalations to human
- `meta` — schema version, timestamps

### Staleness Detection

- Code anchors store content hashes of the referenced code
- When files change (detected via git diff or filesystem watch), concepts anchored to those files get flagged stale
- Stale concepts' documents become candidates for librarian review
- Priority metrics incorporate staleness into the librarian's work queue

## MCP Tool Surface

Each tool has a rich `description` field that serves as an instruction manual for agents — when to use it, what to expect, typical workflows.

### Read Tools (Task Agents)

**`search(query, mode?, filters?, limit?)`**
Unified entry point for finding knowledge. Modes:
- `semantic` — embedding similarity against document summaries. For natural language questions.
- `keyword` — FTS5 full-text search on concept names and document content. For specific terms.
- `code` — find concepts/documents anchored to a specific file or symbol.

Returns concepts with summaries (not full documents) for fast scanning. Automatically logs the query and results to the feedback system.

**`get_document(concept_id_or_name, doc_id?)`**
Fetch full document content. If concept has multiple documents, returns the primary one unless specified. Usage is logged as a follow-up signal (indicates search results were relevant).

**`traverse(start, edge_types?, max_hops?, direction?)`**
Walk the graph from a concept. Returns connected concepts with summaries. For structured queries like "what depends on auth?"

**`get_concept(name_or_id)`**
Fetch a single concept with its edges and document summaries.

### Write Tools (Librarian Agents)

- `create_concept(name, type, root_id?, code_anchors?)`
- `create_edge(source, target, edge_type, metadata?)`
- `create_document(concept_id, content, summary, code_references?)`
- `update_concept(id_or_name, changes)`
- `update_document(doc_id, content?, summary?)`
- `update_edge(id, changes)`
- `delete_concept(id_or_name)`
- `delete_document(doc_id)`
- `delete_edge(id)`
- `flag_stale(concept_id, reason)`

### Tool Description Quality

Every MCP tool description must communicate:
- **When** to reach for this tool
- **What** it returns and in what shape
- **How** to use the results effectively
- **What not** to use it for

Generic descriptions like "search the knowledge base" are not acceptable. Descriptions are the only guidance an agent gets.

## Search Strategy

Two retrieval paths, both optimized for speed:

### Semantic Search
- Document summaries and concept names are embedded at write time (librarian pays this cost)
- Vectors stored in sqlite-vec (or pgvector on Postgres)
- Query embedding compared against stored vectors, ranked by similarity
- Summaries are the primary search target — short, dense, purpose-built

### Keyword Search
- SQLite FTS5 full-text index on document content and concept names
- For specific terms, symbol names, exact phrases
- No embeddings needed, very fast

### Embedding Provider
- OpenAI `text-embedding-3-small` as default (1536 dimensions — sqlite-vec requires fixed dimension at table creation)
- Abstract interface allows swapping to local models (Ollama) or other providers
- Embeddings computed once at write time, recomputed only on document update

### Typical Agent Flow
1. `search("how does authentication work")` — semantic search
2. Scan returned summaries, pick the relevant one
3. `get_document(concept_id)` — full content
4. Two calls to get deep, synthesized context

## The Librarian

A long-running agent kicked off via `apriori deepen`. It builds and maintains the knowledge base autonomously.

### What It Has Access To
- A-Priori write tools (create/update concepts, documents, edges)
- The codebase itself (file reads, grep, git history)
- Pre-computed priority metrics from the feedback loop
- Quality gate scores and thresholds

### Work Cycle
1. Fetch priority metrics — gaps, stale concepts, high-demand areas
2. Pick the highest-priority item
3. Load local context — full concept name list, neighborhood graph, document summaries for the area
4. Research — read code, follow references, understand the subsystem
5. Produce output — create/update concepts, write/revise documents, add edges
6. Submit to quality gate → reviewer pipeline
7. Repeat

### Modes of Operation

**Bootstrap** — first run against a new root. Crawl the directory structure, identify major components, create an initial skeleton of concepts and shallow documents. Breadth over depth.

**Deepen** — ongoing runs. Priority-driven: fill gaps, refresh stale knowledge, improve documents agents use most.

**Reactive** — triggered by git changes. When files in a tracked root change, flag affected concepts as stale, prioritize those for the next deepen cycle.

### Context Management

The librarian cannot hold the entire knowledge base in context. Before working on any item:

1. **Full concept list** — names and types only. Small enough to scan for duplicates.
2. **Neighborhood graph** — 2-3 hops from the relevant concepts. Local structure, existing edges, attached document summaries.
3. **Full documents only when editing** — fetched at the point of update. Read before write, always.
4. **Deduplication** — search by name (exact + fuzzy) before creating. Check existing documents before writing new ones.

### Steering

The librarian's behavior is shaped by its system prompt, which is configurable. The prompt includes quality metric definitions and thresholds so the librarian can self-correct before submitting.

### Human Escalation

The librarian can escalate to the review queue when genuinely stuck. Escalation types:
- **gap** — agents search for knowledge that doesn't seem to exist in the code
- **ambiguous_intent** — code exists but purpose is unclear, no comments/tests/naming to guide
- **conflicting_pattern** — same problem solved differently in different places, unclear which is canonical
- **domain_knowledge** — information not in the code (team ownership, compliance requirements, roadmap)
- **stale_unresolvable** — document contradicts current code, unclear what changed and why
- **root_recommendation** — frequent references to code outside tracked roots

Constraints:
- Queue capped at 10 items
- Must document what was tried before escalating
- System prompt biases toward action: write your best understanding at low confidence rather than escalating

## Quality Gate Pipeline

```
Librarian produces content
        ↓
Deterministic metrics computed (report card)
        ↓
Minimum threshold met? ──No──▶ Back to librarian with scores
        ↓ Yes
Reviewer agent receives content + report card
        ↓
Approve / Request revision / Reject
```

### Deterministic Metrics

The librarian's system prompt includes these metric definitions so it can self-correct before submitting.

**Content quality:**
- **Conciseness ratio** — token count relative to the number of code anchors/concepts covered. Penalizes bloat.
- **Summary accuracy** — embedding similarity between summary and full document content. Ensures the summary actually compresses the document.
- **Assertion density** — ratio of concrete, specific statements vs. vague filler. Higher is better. *Implementation note: compute via heuristic (sentence-level regex patterns for vague phrases like "important part of", "helps with", "is used for" vs. specific patterns containing identifiers, file paths, or concrete behavior descriptions). Not LLM-assisted — must be deterministic.*

**Structural quality:**
- **Code grounding score** — percentage of claims backed by a code anchor or code reference. Ungrounded documents are suspicious.
- **Edge connectivity** — does the concept have edges? Do they point to existing concepts? Concept islands indicate shallow work.
- **Duplication distance** — embedding similarity against existing documents. Too close means likely redundant.

**Freshness:**
- **Anchor validity** — do code anchors still resolve? Do content hashes match current files?
- **Reference recency** — are referenced files recently modified or has the code moved on?

### Default Thresholds (Configurable)

```yaml
quality_gate:
  min_conciseness_ratio: 0.6
  min_code_grounding_score: 0.5
  min_assertion_density: 0.4
  max_duplication_similarity: 0.85
```

### Reviewer Agent

Evaluates content that clears the deterministic gate. Receives the content plus the metric report card. Focuses on what metrics cannot catch:
- Does the document accurately describe the code?
- Would this help an agent do its job?
- Does it duplicate or contradict existing knowledge?

Can approve, request revisions, or reject.

## CLI Commands

- `apriori init <path>` — create a workspace pointing at a directory
- `apriori add <path>` — add a root to track within the current workspace
- `apriori roots` — list tracked roots and their coverage status
- `apriori status` — stale concepts, librarian activity, demand metrics
- `apriori reviews` — show items in the human review queue
- `apriori deepen` — kick off a librarian run
- `apriori search <query>` — same search agents use, in the terminal
- `apriori inspect <concept>` — view concept, edges, document summaries

## Configuration

### Global Config (`$XDG_CONFIG_HOME/a-priori/config.yaml`)

```yaml
embedding:
  provider: openai
  model: text-embedding-3-small

quality_gate:
  min_conciseness_ratio: 0.6
  min_code_grounding_score: 0.5
  min_assertion_density: 0.4
  max_duplication_similarity: 0.85

librarian:
  review_queue_cap: 10
  bootstrap_depth: shallow

search:
  default_limit: 10
  semantic_weight: 0.7
  keyword_weight: 0.3
```

### Workspace Config (`$XDG_DATA_HOME/a-priori/workspaces/<name>/workspace.yaml`)

```yaml
name: work
path: ~/work
roots:
  - path: ~/work/api-service
    added: 2026-03-31
  - path: ~/work/monorepo/packages/auth
    added: 2026-03-31
  - path: ~/work/monorepo/packages/billing
    added: 2026-03-31
```

## Project Structure

```
apriori/
├── core/
│   ├── models.py          # Concept, Edge, Document, CodeAnchor, CodeReference
│   ├── config.py          # YAML config loading, workspace/root registry
│   └── metrics.py         # Deterministic quality gate scoring
├── storage/
│   ├── interface.py       # Abstract storage protocol
│   ├── sqlite.py          # SQLite + sqlite-vec implementation
│   └── schema.sql         # Table definitions
├── search/
│   ├── semantic.py        # Embedding-based search
│   ├── keyword.py         # FTS5 full-text search
│   └── engine.py          # Unified search routing
├── embedding/
│   ├── interface.py       # Abstract embedding protocol
│   └── openai.py          # OpenAI implementation
├── graph/
│   └── traversal.py       # BFS/DFS graph walking
├── librarian/
│   ├── agent.py           # Librarian orchestration
│   ├── priorities.py      # Demand metrics from query log
│   ├── quality_gate.py    # Deterministic metric scoring + threshold enforcement
│   └── reviewer.py        # Reviewer agent
├── feedback/
│   └── logger.py          # Passive query/retrieval logging + metric computation
├── cli/
│   └── main.py            # CLI commands
└── mcp/
    └── server.py          # MCP server

tests/                     # Mirrors package structure
```

**Entry points:**
- `apriori` — CLI tool
- `apriori-mcp` — MCP server

**Dependencies:**
- `pyyaml` — config and YAML handling
- `sqlite-vec` — vector search in SQLite
- `mcp` — Model Context Protocol SDK
- `openai` — embeddings API
- `click` — CLI framework
- `pytest`, `pytest-asyncio` — dev

## Key Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Knowledge structure | Hybrid: thin graph + rich documents | Graph for fast navigation, documents for depth. Two retrieval paths. |
| Primary consumer | Agents via MCP | Human UI (CLI) is secondary. Agents are the main beneficiary. |
| Knowledge construction | Dedicated librarian agents | Not passive side effects of task work. Librarians build knowledge as their primary job. |
| Feedback mechanism | Passive logging of search + follow-up | No explicit feedback tool. Usefulness inferred from behavior. |
| Quality control | Deterministic metrics → reviewer agent | Metrics enforce minimum standards cheaply. Reviewer catches what metrics can't. |
| Storage | SQLite first, Postgres later | Storage abstraction from day one. SQLite for development, Postgres when sharing with others. |
| Workspace model | One workspace = one database | No artificial boundaries between repos. Full graph power across all tracked code. |
| Roots | Scope markers, not hard boundaries | Control where librarians invest effort. Non-root code can appear as shallow concepts. |
| Data location | XDG Base Directory | Standard, cross-platform, respects user environment. |
| Librarian escalation | Capped review queue, documented attempts required | Prevents lazy escalation. Biases toward action over asking. |
| Staleness | Content hashes on code anchors + git diff | Detects when code changes under existing knowledge. |
| Embedding | OpenAI default, abstract interface | High quality, easy setup. Swappable to local models later. |
