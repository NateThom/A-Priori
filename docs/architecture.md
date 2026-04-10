# Architecture Guide

A-Priori is a layered knowledge graph system. This guide explains the four-layer architecture, the quality pipeline, and the adaptive priority system.

---

## System Overview

A-Priori builds a living knowledge graph of your codebase by combining three sources of truth:

1. **Structural** — What the AST tells us (calls, imports, inheritance)
2. **Semantic** — What an LLM tells us (dependencies, responsibilities, assumptions)
3. **Historical** — What git tells us (co-change patterns, ownership)

These sources flow through a layered pipeline with strict upward-only dependencies.

---

## The Four-Layer Architecture

```
┌─────────────────────────────────────────┐
│  Layer 3: Retrieval & Querying          │  apriori.retrieval/
│  blast_radius, graph traversal, queries │
└───────────────────┬─────────────────────┘
                    │ reads from
┌───────────────────▼─────────────────────┐
│  Layer 2: Knowledge Management          │  apriori.knowledge/
│  integrate, review, maintain freshness  │
└───────────────────┬─────────────────────┘
                    │ produces input for
┌───────────────────▼─────────────────────┐
│  Quality Pipeline                       │  apriori.quality/
│  Level 1 checks → Co-regulation review │
└───────────────────┬─────────────────────┘
                    │ validates output of
┌───────────────────▼─────────────────────┐
│  Layer 1: Semantic Enrichment           │  apriori.librarian/
│  LLM-driven analysis and annotation     │
└───────────────────┬─────────────────────┘
                    │ operates on
┌───────────────────▼─────────────────────┐
│  Layer 0: Structural Analysis           │  apriori.structural/
│  Deterministic AST parsing              │
└─────────────────────────────────────────┘
```

**Dependency rule:** Each layer may only import from the layer below it and from shared modules (`models/`, `storage/`, `adapters/`, `config.py`). No layer imports from a layer above it.

---

## Layer 0: Structural Analysis (`apriori.structural/`)

**Responsibility:** Parse source files into structured entities. Deterministic — no LLM involvement.

**Key modules:**

| Module | Purpose |
|---|---|
| `orchestrator.py` | Walks the file tree, detects language, dispatches to parser |
| `languages/python_parser.py` | tree-sitter Python parser |
| `languages/typescript.py` | tree-sitter TypeScript/JavaScript parser |
| `graph_builder.py` | Converts parse results into Concept nodes and structural Edges |
| `fqn.py` | Fully-qualified name resolution |
| `change_detector.py` | Detects changed files via git diff |

**Inputs:** Source file paths (`.py`, `.ts`, `.tsx`, `.js`)

**Outputs:** `ParseResult` objects containing:
- `FunctionEntity`, `ClassEntity`, `InterfaceEntity`
- `ImportRelationship`, `Relationship`
- Symbol locations (file, line range)

**Structural edge types produced:** `calls`, `imports`, `inherits`, `type-references`

**All parsing uses tree-sitter.** No regex-based code parsing. This ensures consistent, fast, incremental parsing across all supported languages.

---

## Layer 1: Semantic Enrichment (`apriori.librarian/`)

**Responsibility:** Use an LLM to add meaning that static analysis cannot capture.

The librarian operates as an autonomous loop: it picks work items from a priority queue, constructs an analysis prompt with code context, sends it to the LLM, validates the response through the quality pipeline, and integrates valid output into the knowledge graph.

### The Librarian Loop

Each iteration:
1. **Claim** the highest-priority work item from the queue
2. **Load context**: code content, related concepts, recent git changes
3. **Call LLM** with a structured analysis prompt
4. **Parse response**: extract concepts, descriptions, semantic edges
5. **Validate** through the quality pipeline (Levels 1 and 1.5)
6. **Integrate** validated output into the knowledge graph
7. **Record telemetry**: tokens used, yield, failure reason (if any)

The loop is **stateless between iterations**: each iteration reads current state from disk, picks the best work item, does its job, and exits. No state is carried between iterations.

### Semantic Edge Types

The librarian produces:

| Type | Meaning |
|---|---|
| `depends-on` | Functional dependency |
| `implements` | Implements a contract or interface |
| `relates-to` | General semantic relationship |
| `shares-assumption-about` | Shared architectural assumption |
| `extends` | Extends behavior without inheriting |
| `supersedes` | Replaces a deprecated concept |
| `owned-by` | Ownership or responsibility |

---

## The Quality Pipeline (`apriori.quality/`)

**The quality pipeline is the system's most important invariant:** no LLM-produced knowledge enters the knowledge graph without passing through it.

### Level 1: Consistency Checks

Structural validation of the librarian's output:
- Concepts must have non-empty names and descriptions
- Edge source and target must exist
- Edge types must be in the configured vocabulary
- Confidence values must be in [0.0, 1.0]

**Result:** `Level1Result` with `passed: bool` and list of violations

### Level 1.5: Co-Regulation Review

A second-opinion review using the LLM as a co-regulator:
- The LLM's output is re-analyzed by an independent prompt
- The co-regulator assesses whether the concept description matches the code
- Produces a `CoRegulationAssessment` with a `confidence` score

**Thresholds (configurable):**
- `confidence >= 0.7` → Accept automatically
- `0.5 ≤ confidence < 0.7` → Accept with `needs-review` label
- `confidence < 0.5` → Reject; re-queue for retry

### Failure Management

Failed analysis attempts are tracked per work item:
- Each failure is recorded as a `FailureRecord` with the model used, prompt template, and failure reason
- Items with persistent failures are **escalated** (`item_type: "escalated"`) and surfaced in the audit UI
- Escalated items require human intervention to resolve

---

## Layer 2: Knowledge Management (`apriori.knowledge/`)

**Responsibility:** Curate and maintain the knowledge graph over time.

### Integration (`knowledge/integrator.py`)

After the quality pipeline, the `Integrator` merges validated librarian output:
- Creates or updates concepts in the DualWriter store
- Creates semantic edges
- Updates concept metadata (confidence, code version, timestamps)
- Maintains a `name_to_id` map for edge resolution

### Human Review (`knowledge/reviewer.py`)

The `ReviewService` handles three review actions:
- **Verify**: Confirm a concept is correct → raises confidence, adds `verified` label
- **Correct**: Submit a correction → updates description, creates review outcome
- **Flag**: Mark for re-investigation → creates a new work item

### Freshness Tracking (`knowledge/staleness.py`)

Monitors how current the knowledge is:
- Computes staleness per concept based on days since last verification
- Concepts verified against an old git SHA are marked stale when the code changes
- Stale concepts are prioritized by the work queue

### Impact Profiles (`knowledge/impact.py`)

Computes the semantic impact of changing a concept:
- BFS traversal over outgoing edges with multiplicative confidence
- Includes: `depends-on`, `implements`, `shares-assumption-about`, `extends`, `supersedes`
- Excludes: `relates-to`, `owned-by` (too weak for impact propagation)
- Result: `ImpactProfile` with `semantic_impact`, `structural_impact`, `historical_impact`

---

## Layer 3: Retrieval (`apriori.retrieval/`)

**Responsibility:** Read-only graph queries and impact computation.

### Blast Radius (`retrieval/blast_radius_query.py`)

Combines three impact sources into a ranked list:
1. **Structural impact** — direct code dependencies from Layer 0
2. **Semantic impact** — propagated confidence through semantic edges
3. **Historical impact** — co-change patterns from git history

Each impact entry has a `composite_score = confidence × (1/depth)`.

### Historical Impact (`retrieval/historical_impact.py`)

Reads git log to compute file co-change statistics:
- `compute_historical_impact_edges()` — builds co-change edges from git history
- `compute_file_cochange_confidences()` — computes frequency-weighted confidence
- Confidence formula: `(co_change_count / total_changes) × recency_weight`
- Recency decay modes: `exponential`, `linear`, `none`

---

## Shared Modules

Cross-cut all layers; may be imported by any module.

| Module | Purpose |
|---|---|
| `models/` | Pydantic v2 domain models (Concept, Edge, WorkItem, etc.) |
| `storage/` | KnowledgeStore protocol + SQLite/YAML implementations |
| `adapters/` | LLM adapter protocol + Anthropic/Ollama implementations |
| `config.py` | Configuration loading and validation |
| `embedding/` | Embedding service protocol and sentence-transformers implementation |

---

## Storage Architecture

### KnowledgeStore Protocol (`storage/protocol.py`)

All storage access goes through the `KnowledgeStore` protocol. No direct SQLite calls outside the storage layer. This ensures:
1. The dual-write invariant is always maintained
2. Storage implementations can be swapped without touching application code

### Dual-Write (`storage/dual_writer.py`)

Every write goes to both stores simultaneously:

```
Application Code
       │
       ▼
  DualWriter
  ├──► SQLiteStore  (fast queries, vector index, FTS5)
  └──► YamlStore    (human-readable, disaster recovery)
```

**SQLiteStore:** SQLite + sqlite-vec extension
- Tables: `concepts`, `edges`, `concept_embeddings`, `work_items`, `librarian_activities`, `review_outcomes`
- Indexes: FTS5 on name/description, vector index on embeddings (768-dim)

**YamlStore:** One YAML file per concept, keyed by UUID
- Authoritative source of truth for disaster recovery
- `apriori rebuild-index` reconstructs SQLite from YAML

---

## The Adaptive Priority System

The librarian's work queue uses a **6-factor weighted priority score** that adapts to the current state of the knowledge graph.

### Base Priority Factors

| Factor | Default Weight | What it measures |
|---|---|---|
| `coverage_gap` | 0.15 | Files with no concepts in the knowledge graph |
| `needs_review` | 0.20 | Concepts explicitly flagged for review |
| `developer_proximity` | 0.25 | Graph distance from recently-modified files (inverted) |
| `git_activity` | 0.20 | Normalized commit count over a window |
| `staleness` | 0.15 | Days since last concept verification |
| `failure_urgency` | 0.05 | Prior analysis failure count |

Each factor produces a normalized score [0.0, 1.0]. The priority score is the weighted sum.

### Adaptive Modulation

Static weights are good for a stable graph but suboptimal during rapid growth or drift. The `AdaptiveModulator` adjusts effective weights based on three health metrics:

| Health Metric | Poor → Effect |
|---|---|
| **Coverage** (< 50%) | Boosts `coverage_gap` + `developer_proximity` to fill gaps faster |
| **Freshness** (< 70%) | Boosts `staleness` + `needs_review` to reverify stale concepts |
| **Blast Radius Completeness** (< 80%) | Boosts `coverage_gap` to ensure impact profiles exist |

**Bootstrap Mode:** When coverage is below `bootstrap_coverage_threshold` (default 50%), `developer_proximity` weight is multiplied by `bootstrap_developer_proximity_strength` (default 2.0). This ensures the first librarian iterations concentrate on the most recently-touched code — giving you the most immediately useful knowledge first.

Modulation strength (default 0.8) controls how far effective weights can deviate from base weights. At 0.0, no modulation occurs. At 1.0, weights can shift to their theoretical maximum.

---

## Thin Shells

All user-facing interfaces are thin entry-point wrappers with no business logic:

| Shell | Module | Purpose |
|---|---|---|
| CLI | `shells/cli.py` | `apriori` command-line interface |
| MCP Server | `mcp/server.py` | Model Context Protocol server |
| Audit UI | `shells/ui/server.py` | FastAPI read-only Graph API |

Each shell imports and delegates to core library functions. No business logic lives in the shells.

---

## LLM Adapter Pattern

The LLM provider is a pluggable dependency via the adapter protocol in `adapters/base.py`:

```python
class LLMAdapter(Protocol):
    def complete(self, prompt: str, *, system: str | None = None) -> str: ...
    def count_tokens(self, text: str) -> int: ...
```

Two implementations are provided: `AnthropicAdapter` and `OllamaAdapter`. The librarian always calls the adapter protocol — never a specific provider directly. To use a different model, change `llm.provider` and `llm.model` in config.

---

## Test Structure

Tests mirror the `src/apriori/` directory structure:

```
tests/
├── models/         → tests for src/apriori/models/
├── structural/     → tests for src/apriori/structural/
├── knowledge/      → tests for src/apriori/knowledge/
├── quality/        → tests for src/apriori/quality/
├── retrieval/      → tests for src/apriori/retrieval/
├── storage/        → tests for src/apriori/storage/
├── librarian/      → tests for src/apriori/librarian/
├── mcp/            → tests for src/apriori/mcp/
└── shells/         → tests for src/apriori/shells/
```

Each test must be traceable to a specific Given/When/Then acceptance criterion. Run with:

```bash
pytest --tb=short
```
