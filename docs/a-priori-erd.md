# A-Priori: Engineering Requirements Document

**Date:** 2026-04-03
**Status:** Draft v2
**Source PRD:** `a-priori-prd.md` (2026-04-03, revision with §6.3.1, §6.4, §8A additions)
**Authors:** Engineering (via Claude), Nate Thom

---

## 1. Purpose of This Document

This Engineering Requirements Document translates the A-Priori PRD into implementation-level technical specifications. It is intended for the engineers and technical stakeholders who will build the system. It answers how each PRD requirement will be realized, identifies areas of technical risk that require investigation before implementation can begin, defines the schemas and interfaces at a level sufficient to write code against, and maps every implementation component back to its originating PRD section.

This document is a blueprint, not a ticket backlog. It provides the architectural scaffolding and technical decisions that inform epic and story creation. Individual task breakdown is a downstream activity that should happen collaboratively between engineering leads and the developers doing the work.

### 1.1 MVP Functionality Summary

The MVP delivers a locally-running Python application that automatically constructs and maintains a hybrid structural-semantic knowledge graph for a git-managed codebase. It is consumed primarily via MCP by AI coding agents and secondarily by engineers through a local web-based audit UI. Its flagship capability is pre-computed blast radius analysis.

At the end of MVP, a user can:

1. Point A-Priori at any git repository and receive a structural knowledge graph (functions, classes, modules, files, and their call/import/inheritance relationships) within 60 seconds, queryable via MCP — no LLM required.
2. Configure their own LLM provider (Anthropic API or Ollama) and run autonomous librarian agents that progressively build semantic understanding on top of the structural graph, with each iteration's output verified by an automated consistency check and an LLM-as-judge co-regulation review before entering the graph.
3. Query "what breaks if I change this?" via the `blast_radius` MCP tool and receive a pre-computed, confidence-scored impact assessment in under 500ms.
4. Interact with the knowledge graph through 13 MCP tools (6 read, 7 write) covering search, traversal, concept management, edge management, and gap reporting.
5. Open a local web-based audit UI to visually explore the knowledge graph, monitor the librarian's activity, review and verify concepts, inspect escalated failures, and view health metrics alongside adaptive priority weights.
6. Trust that the librarian self-corrects: work items that fail quality checks retain structured diagnostic context for smarter retries, and items that fail repeatedly escalate to human attention rather than burning tokens indefinitely.
7. Trust that the librarian self-prioritizes: an adaptive feedback loop automatically shifts the librarian's focus toward whichever product metric (coverage, freshness, blast radius completeness) is furthest below its configured target.

---

## 2. Architecture: Implementation View

The PRD defines four logical layers. This section translates those layers into concrete Python packages, modules, and their responsibilities. The entire system is a single Python package (`apriori`) with thin entry-point shells for the MCP server, librarian loop, and audit UI server.

### 2.1 Package Structure

```
apriori/
├── __init__.py
├── config.py                  # Configuration loading, defaults, validation
├── models/                    # Data model definitions
│   ├── concept.py             # Concept, CodeReference
│   ├── edge.py                # Edge, EdgeType vocabulary
│   ├── impact.py              # ImpactProfile, ImpactEntry
│   ├── work_item.py           # WorkItem, WorkItemType, FailureRecord
│   └── review.py              # ReviewOutcome, CoRegulationAssessment
├── structural/                # Layer 0 — Structural Engine
│   ├── parser.py              # Tree-sitter AST parsing orchestration
│   ├── graph_builder.py       # Structural graph construction from parse results
│   ├── languages/             # Language-specific parsing configs
│   │   ├── python.py
│   │   ├── typescript.py
│   │   └── ...
│   └── change_detector.py     # Git-diff integration, work queue population
├── semantic/                  # Layer 1 — Semantic Enrichment Engine
│   ├── librarian.py           # Ralph-Wiggum loop orchestrator
│   ├── prompt_templates/      # Model-specific prompt templates
│   │   ├── base.py            # Shared prompt construction logic
│   │   ├── anthropic.py
│   │   └── ollama.py
│   ├── response_parser.py     # LLM response → knowledge graph mutations
│   └── priority.py            # Priority scoring + adaptive modulation engine
├── quality/                   # Quality assurance pipeline
│   ├── level1.py              # Automated consistency checks
│   ├── level15.py             # Co-regulation LLM-as-judge review
│   ├── failure.py             # Failure record management + escalation logic
│   └── review_outcomes.py     # Human review outcome tracking + error profiling
├── knowledge/                 # Layer 2 — Knowledge Management
│   ├── manager.py             # Update, merge, contradict, expire logic
│   ├── temporal.py            # Staleness detection, version tracking
│   ├── confidence.py          # Confidence scoring and propagation
│   └── metrics.py             # Coverage, freshness, blast radius completeness computation
├── retrieval/                 # Layer 3 — Retrieval Interface
│   ├── query_router.py        # Graph traversal vs. vector search routing
│   ├── context_assembler.py   # Subgraph extraction and formatting
│   ├── blast_radius.py        # Impact profile queries and formatting
│   └── formatters.py          # Response formatting (MCP, CLI, human)
├── storage/                   # Storage abstraction + implementations
│   ├── protocol.py            # KnowledgeStore abstract protocol
│   ├── sqlite_store.py        # SQLite + sqlite-vec implementation
│   ├── yaml_store.py          # Flat YAML file read/write
│   └── dual_writer.py         # Coordinated dual-write (SQLite + YAML)
├── adapters/                  # LLM provider adapters
│   ├── base.py                # Adapter protocol/interface
│   ├── anthropic.py           # Anthropic API adapter
│   └── ollama.py              # Ollama adapter
├── git/                       # Git integration
│   ├── diff.py                # Diff parsing, change detection
│   └── history.py             # Co-change analysis for historical impact
├── mcp/                       # MCP server shell (thin wrapper)
│   ├── server.py              # MCP server setup and tool registration
│   └── tools.py               # Tool definitions mapping to core library
├── ui/                        # Audit UI (local web application)
│   ├── server.py              # HTTP server (Flask/FastAPI) serving SPA
│   ├── api.py                 # REST API endpoints for the frontend
│   └── frontend/              # Static SPA assets (built artifact)
│       ├── index.html
│       └── ...
└── cli/                       # CLI entry point (thin wrapper)
    └── main.py                # Click/Typer CLI commands
```

Two changes from the previous architecture are worth calling out. First, the quality assurance logic is now its own top-level module (`quality/`) rather than a single file inside `knowledge/`. This reflects the fact that the quality pipeline is now a multi-stage system with its own data models, LLM calls, failure tracking, and escalation logic — it has grown into a subsystem, not a utility function. Second, the `ui/` module is new and represents a significant addition to the engineering surface area.

### 2.2 Dependency Flow

Dependencies flow strictly downward. No layer may import from a layer above it.

```
CLI / MCP Server / Audit UI Server  (entry points — thin shells)
         │
         ▼
Layer 3: Retrieval Interface
         │
         ▼
Quality Assurance Pipeline  ──► LLM Adapters (for co-regulation review)
         │
         ▼
Layer 2: Knowledge Management
         │
         ▼
Layer 1: Semantic Enrichment  ──► LLM Adapters (for analysis)
         │
         ▼
Layer 0: Structural Engine  ──► Tree-sitter, Git
         │
         ▼
Storage Layer (protocol + implementations)
         │
         ▼
Data Models (shared across all layers)
```

The quality pipeline sits between the semantic engine and the knowledge manager. The librarian (Layer 1) produces raw analysis output. The quality pipeline validates it. Only validated output reaches the knowledge manager (Layer 2) for integration. This is the critical architectural invariant: no LLM-produced knowledge enters the graph without passing through the quality pipeline first.

### 2.3 Configuration System

A single `apriori.config.yaml` file in the project root governs all configurable behavior. The configuration module (`config.py`) loads this file, merges with sensible defaults, validates all values, and exposes a typed configuration object that other modules consume.

The configuration schema must cover:

**LLM provider settings:** provider name, API key reference (environment variable name, never stored in config), model name, max tokens per request, temperature. Optional separate review model for co-regulation (defaults to same as analysis model).

**Librarian settings:** max iterations per run, max tokens per iteration (must account for co-regulation cost when enabled), base priority weights (the six weights from PRD §6.3; must sum to 1.0 — if user-configured weights do not sum to 1.0, the configuration system shall normalize them proportionally and log a warning), developer proximity window (how many recent git commits to consider).

**Adaptive modulation settings:** `modulation_strength` (default: 1.0, 0.0 disables), `coverage_target` (default: 0.80), `freshness_target` (default: 0.90), `blast_radius_completeness_target` (default: 0.70).

**Quality assurance settings:** co-regulation review enabled/disabled (`quality.co_regulation.enabled`, default: `true`), structural corroboration confidence penalty (default: 0.2), failure escalation threshold (default: 3), escalation priority reduction factor (default: 0.5).

**Storage settings:** SQLite database path, YAML directory path, sqlite-vec index dimensions.

**Structural engine settings:** languages to parse (auto-detect vs. explicit list), file glob patterns to include/exclude, max file size to parse.

**Edge type vocabulary:** the controlled vocabulary from PRD §5.4, extensible by the user.

**Impact profile settings:** staleness threshold for flagging profiles (default: 7 days), max traversal depth for blast radius (default: 5), default minimum confidence filter (default: 0.1).

**Audit UI settings:** host (default: `127.0.0.1`), port (default: `8391`).

All settings must have defaults that produce a working system with zero configuration beyond the LLM API key.

---

## 3. Phase 1: Foundation

Phase 1 delivers Layer 0 (Structural Engine), the core data model, the storage layer, basic MCP read/write tools, git change detection, the configuration system, and the CLI skeleton. At the end of this phase, a user gets a structural knowledge graph with no LLM required.

**PRD Sections Covered:** §4.1 (Layer 0), §4.2, §4.3, §5.1–5.4, §5.6 (work item schema only — failure records are exercised in Phase 2), §8.1–8.2 (subset), §10.1 (structural subset)

### 3.1 Data Model Implementation

**Module:** `apriori/models/`

All data models should be implemented as Pydantic models with strict validation. Pydantic is recommended over plain dataclasses because the quality pipeline and co-regulation review in Phase 2 depend heavily on runtime validation of LLM output, and Pydantic's validation error messages are clear enough to include in failure records. Every model must be serializable to JSON (for SQLite storage) and YAML (for flat file storage) without loss.

#### 3.1.1 Concept Node (`models/concept.py`)

Implements the schema from PRD §5.1.

`id` is a UUID4, auto-generated on creation via `uuid.uuid4()`. `name` must be unique within a project; enforce at the storage layer with a unique index. `description` is markdown-compatible with no enforced length limit, but the librarian's prompt templates should guide output length. `labels` is a `set[str]` reserved for housekeeping metadata only — not domain knowledge. The initial label vocabulary is: `needs-review`, `auto-generated`, `deprecated`, `verified`, `stale`, `needs-human-review` (new — used by the escalation system). Labels are not validated against a vocabulary at the model level (they're extensible), but the initial set should be documented. `created_by` is a string enum: `"agent"` or `"human"`. `confidence` is a float clamped to `[0.0, 1.0]`. The model layer must enforce this range via Pydantic validator. `derived_from_code_version` is a git commit hash (40-character hex string), nullable for human-created concepts that aren't derived from specific code.

#### 3.1.2 Code Reference (`models/concept.py`, embedded)

Implements the repair chain from PRD §5.2. Embedded in the Concept model, not a standalone entity. The repair chain resolution order (symbol → content_hash → semantic_anchor) is not enforced in the model but in the retrieval layer that resolves references. `content_hash` should use SHA-256 of the referenced code block, stored as a hex string. `semantic_anchor` is a natural language description written by the librarian; resolution via semantic anchor requires an LLM call and is the expensive fallback. `line_range` is advisory, not authoritative.

#### 3.1.3 Edge (`models/edge.py`)

Implements PRD §5.3. `source` and `target` are concept UUIDs with referential integrity enforced at the storage layer. `edge_type` is validated against the controlled vocabulary in configuration. `evidence_type` is an enum: `structural`, `semantic`, `historical`. Edges are directed; the retrieval layer must support both forward and reverse traversal.

#### 3.1.4 Work Item (`models/work_item.py`)

Implements PRD §5.6 in full, including the new failure tracking fields. This is one of the models that changed most significantly in the updated PRD and warrants careful attention.

Work items live in SQLite only, not in YAML flat files — they are transient operational state, not durable knowledge. `item_type` is an enum with six values from PRD §5.6: `investigate_file`, `verify_concept`, `evaluate_relationship`, `reported_gap`, `review_concept`, `analyze_impact`.

The new failure tracking fields are:

`failure_count` is an integer, initialized to 0. Incremented each time the work item is attempted and fails either the Level 1 automated check or the Level 1.5 co-regulation review. This counter drives the escalation logic.

`failure_records` is a `list[FailureRecord]`, stored as a JSON array in SQLite. Each record captures the full diagnostic context of a failed attempt.

`escalated` is a boolean, initially `False`. Set to `True` when `failure_count` reaches the configured escalation threshold (default: 3). Once escalated, the work item's effective priority is reduced and it is flagged for human attention.

`priority_score` is a computed float, recalculated fresh on each librarian iteration start. For escalated items, the computed score is multiplied by the configured reduction factor (default: 0.5).

Resolved items should be retained for telemetry but excluded from the active work queue. A configurable retention policy (e.g., delete resolved items older than 30 days) should be implemented.

#### 3.1.5 Failure Record (`models/work_item.py`, embedded)

New in this PRD revision. The `FailureRecord` is embedded in a work item's `failure_records` list and captures everything a retry attempt needs to do better.

`attempted_at` is an ISO 8601 timestamp. `model_used` is the model name string (e.g., `"claude-sonnet-4-20250514"`, `"qwen2.5:7b"`). `prompt_template` identifies which prompt template was used. `failure_reason` is a human-readable string identifying which quality check failed and why (e.g., `"Level 1: empty description"`, `"Level 1.5: specificity score 0.2 below threshold 0.5"`). `quality_scores` is an optional dict containing the co-regulation review's dimensional scores (specificity, structural_corroboration, completeness) — only populated when the failure came from Level 1.5. `reviewer_feedback` is an optional string containing the co-regulation agent's specific actionable feedback (e.g., "The description is generic. The code contains payment validation logic including amount limits and currency checks that should be described.").

The key design constraint: failure records must contain enough information that a prompt template can construct a retry prompt that meaningfully differs from the original attempt. The `reviewer_feedback` field is the primary mechanism for this — it gives the librarian specific guidance on what to do differently.

#### 3.1.6 Co-Regulation Assessment (`models/review.py`)

New model. Captures the structured output of the Level 1.5 co-regulation review.

`specificity_score` is a float in `[0.0, 1.0]`. `structural_corroboration_score` is a float in `[0.0, 1.0]`. `completeness_score` is a float in `[0.0, 1.0]`. `composite_pass` is a boolean — `True` if the assessment passes the configured thresholds on all three dimensions. `feedback` is a string — on failure, this contains specific, actionable guidance for the librarian's next attempt; on pass, this may be empty or contain minor notes. `raw_response` is the full text of the co-regulation LLM's response, retained for debugging.

The composite pass/fail threshold for each dimension should be configurable, with defaults of 0.5 for specificity, 0.3 for structural corroboration (intentionally lower — semantic-only relationships are legitimate), and 0.4 for completeness.

#### 3.1.7 Review Outcome (`models/review.py`)

New model. Captures a human reviewer's assessment from the Level 2 review workflow in the audit UI.

`concept_id` is the concept being reviewed. `reviewer` is a string identifier (could be a name or "anonymous"). `action` is an enum: `verified`, `corrected`, `flagged`. `error_type` is an optional enum populated when `action == corrected`: `description_wrong`, `relationship_missing`, `relationship_hallucinated`, `confidence_miscalibrated`, `other`. `correction_details` is an optional string describing the correction. `created_at` is a timestamp.

Review outcomes are stored in their own SQLite table (not on the concept) because they are telemetry data used for error profiling, not knowledge graph content.

### 3.2 Storage Layer

**Module:** `apriori/storage/`

#### 3.2.1 KnowledgeStore Protocol (`storage/protocol.py`)

Define a Python `Protocol` that specifies the complete interface for knowledge storage. This protocol is the contract that enables future backend swaps.

The protocol must include operations for: **Concept CRUD** (`create_concept`, `get_concept` by ID or name, `update_concept`, `delete_concept`, `list_concepts` with filtering). **Edge CRUD** (`create_edge`, `get_edge`, `update_edge`, `delete_edge`, `get_edges_for_concept` both inbound and outbound, `get_edges_by_type`). **Work Item operations** (`create_work_item`, `get_work_queue` unresolved sorted by priority, `resolve_work_item`, `record_failure` to append a FailureRecord and increment failure_count, `escalate_work_item`, `get_escalated_items`, `get_work_item_stats`). **Review Outcome operations** (`record_review_outcome`, `get_review_outcomes` with filtering by concept/reviewer/action/time range, `get_error_profile` aggregated summary of error types over time). **Search** (`search_semantic` vector similarity, `search_keyword` text matching, `search_by_file` concepts referencing a given file path). **Graph traversal** (`traverse` BFS or DFS from a starting concept, with edge type filters, max hops, max nodes). **Metrics** (`get_coverage`, `get_freshness`, `get_blast_radius_completeness`, `get_status` overall graph health). **Bulk operations** (`rebuild_index` reconstruct SQLite from YAML files).

Every write method must return the created/updated entity. The work item operations `record_failure` and `escalate_work_item` are new relative to the prior version and critical for the quality pipeline.

#### 3.2.2 SQLite + sqlite-vec Implementation (`storage/sqlite_store.py`)

**Schema:**

```sql
CREATE TABLE concepts (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    description TEXT NOT NULL,
    labels TEXT,                       -- JSON array of strings
    code_references TEXT,              -- JSON array of CodeReference objects
    created_by TEXT NOT NULL CHECK (created_by IN ('agent', 'human')),
    verified_by TEXT,
    last_verified TEXT,                -- ISO 8601
    confidence REAL NOT NULL CHECK (confidence >= 0.0 AND confidence <= 1.0),
    derived_from_code_version TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    impact_profile TEXT               -- JSON serialized ImpactProfile
);

CREATE VIRTUAL TABLE concepts_fts USING fts5(
    name, description, content='concepts', content_rowid='rowid'
);

-- Dimensions: 768 per S-2 decision (e5-base-v2 via sentence-transformers)
CREATE VIRTUAL TABLE concept_embeddings USING vec0(
    concept_id TEXT PRIMARY KEY,
    embedding FLOAT[768]
);

CREATE TABLE edges (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL REFERENCES concepts(id) ON DELETE CASCADE,
    target TEXT NOT NULL REFERENCES concepts(id) ON DELETE CASCADE,
    edge_type TEXT NOT NULL,
    confidence REAL NOT NULL CHECK (confidence >= 0.0 AND confidence <= 1.0),
    evidence_type TEXT NOT NULL CHECK (evidence_type IN ('structural', 'semantic', 'historical')),
    metadata TEXT,
    derived_from_code_version TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (source, target, edge_type)
);

CREATE INDEX idx_edges_source ON edges(source);
CREATE INDEX idx_edges_target ON edges(target);
CREATE INDEX idx_edges_type ON edges(edge_type);

CREATE TABLE work_items (
    id TEXT PRIMARY KEY,
    item_type TEXT NOT NULL,
    description TEXT NOT NULL,
    concept_id TEXT REFERENCES concepts(id) ON DELETE SET NULL,
    file_path TEXT,
    priority_score REAL NOT NULL DEFAULT 0.0,
    resolved INTEGER NOT NULL DEFAULT 0,
    failure_count INTEGER NOT NULL DEFAULT 0,
    failure_records TEXT NOT NULL DEFAULT '[]',   -- JSON array of FailureRecord objects
    escalated INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    resolved_at TEXT
);

CREATE INDEX idx_work_items_resolved ON work_items(resolved);
CREATE INDEX idx_work_items_priority ON work_items(priority_score DESC);
CREATE INDEX idx_work_items_escalated ON work_items(escalated);

-- New: Review outcomes table for Level 2 human review tracking
CREATE TABLE review_outcomes (
    id TEXT PRIMARY KEY,
    concept_id TEXT NOT NULL REFERENCES concepts(id) ON DELETE CASCADE,
    reviewer TEXT NOT NULL,
    action TEXT NOT NULL CHECK (action IN ('verified', 'corrected', 'flagged')),
    error_type TEXT,
    correction_details TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX idx_review_outcomes_concept ON review_outcomes(concept_id);
CREATE INDEX idx_review_outcomes_action ON review_outcomes(action);
```

Key implementation decisions: All timestamps are ISO 8601 text strings. Foreign key enforcement is explicitly enabled per connection (`PRAGMA foreign_keys = ON`). WAL mode is enabled for concurrent read access while the librarian writes (`PRAGMA journal_mode = WAL`). The `UNIQUE` constraint on edges prevents duplicate relationships. The `failure_records` column is a JSON array that can grow — at escalation threshold (default 3 records), the array contains roughly 1–3KB of JSON, which is well within SQLite's practical limits. After escalation, failure records are retained for diagnostic purposes. Failure records are cleaned up alongside their parent work item when the work item retention policy runs (see §3.1.4).

#### 3.2.3 YAML Flat File Store (`storage/yaml_store.py`)

Authoritative source of truth. Directory structure:

```
.apriori/
├── config.yaml
├── concepts/
│   ├── payment-validation.yaml    # One file per concept, named by slug
│   └── ...
├── edges/
│   ├── {uuid}.yaml                # One file per edge, named by ID
│   └── ...
└── index.db                       # SQLite database (derived, rebuildable)
```

Work items, review outcomes, and failure records are not serialized to YAML — they are operational state that lives exclusively in SQLite. Only concepts and edges (the durable knowledge) are dual-written.

Concept filenames are derived from the concept name by slugifying (lowercase, hyphens for spaces, strip special characters). Collisions are resolved by appending a numeric suffix. The mapping must be deterministic.

#### 3.2.4 Dual Writer (`storage/dual_writer.py`)

Coordinates writes between SQLite and YAML. Implements the `KnowledgeStore` protocol. Write strategy: (1) Write to YAML first (authoritative). (2) Write to SQLite second (acceleration layer). (3) If SQLite write fails, log warning but do not roll back YAML — SQLite can be rebuilt. (4) Reads served from SQLite for performance. (5) Work item operations, review outcome operations, and metrics queries are SQLite-only (not dual-written).

The `rebuild_index` operation is idempotent and must be invocable via CLI and triggered automatically on first run.

### 3.3 Structural Engine (Layer 0)

**Module:** `apriori/structural/`

#### 3.3.1 AST Parser (`structural/parser.py`)

Orchestrates tree-sitter parsing across a repository. Walks the file tree respecting include/exclude globs, determines language by extension, loads the appropriate grammar, parses to AST, and extracts structural entities: functions (name, parameters, return type, line range, file path), classes (name, base classes, methods, line range, file path), modules (file path, top-level exports), and imports (source module, imported symbols).

Language-specific logic lives in `languages/` subdirectory. Each language module implements a common interface. MVP must support Python and TypeScript/JavaScript. Additional languages are added by implementing the interface without changes to the orchestrator.

Performance requirement (PRD §4.1): sub-second per file.

#### 3.3.2 Graph Builder (`structural/graph_builder.py`)

Transforms parse results into concept nodes and structural edges. Each function/method, class, and module becomes a concept node. Structural edges are created for `calls`, `imports`, `inherits`, and `type-references` relationships, all with `evidence_type = "structural"` and `confidence = 1.0`.

The graph builder must be idempotent: running it twice on the same codebase produces the same graph state, upserting by fully-qualified symbol name.

#### 3.3.3 Change Detector (`structural/change_detector.py`)

Integrates with git to detect code changes and populate the work queue. On invocation: (1) Determine changed files since last known analysis point (stored as git hash in config state; on first run, all files are "changed"). (2) Re-run structural parser and graph builder on changed files. (3) For each concept whose code references have mismatched content hashes, generate a `verify_concept` work item and add `needs-review` label. (4) For each new file, generate an `investigate_file` work item. (5) For each concept whose structural edges changed, generate an `analyze_impact` work item. (6) Update stored analysis point to current HEAD.

Uses `git diff --name-only {last_hash}..HEAD` or equivalent. Must not re-parse unchanged files.

### 3.4 MCP Server Shell (Phase 1 Subset)

**Module:** `apriori/mcp/`

Thin wrapper that registers tools and delegates to the core library. Uses the MCP Python SDK. Each tool function should be 10–20 lines of glue code: parse input, call core library, format and return result. All validation and business logic lives in the core library.

**Phase 1 read tools:** `search` (full implementation with `keyword`, `exact`, `file`, and `semantic` modes; `semantic` mode uses local embeddings via e5-base-v2 per S-2 decision), `traverse` (full), `get_concept` (full), `list_edge_types` (full), `get_status` (full).

**Deferred to Phase 3:** `blast_radius`.

**Phase 1 write tools:** `create_concept`, `update_concept`, `delete_concept`, `create_edge`, `update_edge`, `delete_edge`, `report_gap` (all full implementation with edge type validation).

### 3.5 CLI Skeleton

**Module:** `apriori/cli/`

Phase 1 commands: `apriori init` (initialize project, create `.apriori/`, generate default config, run structural parser, build initial graph), `apriori status` (print graph health metrics and work queue depth), `apriori search <query>` (CLI wrapper around search tool), `apriori rebuild-index` (reconstruct SQLite from YAML), `apriori config` (print or modify configuration values).

### 3.6 Phase 1 Acceptance Criteria

Phase 1 is complete when: (1) `apriori init` successfully parses a Python or TypeScript repository and produces a structural knowledge graph with concept nodes and structural edges. (2) The MCP server starts and all Phase 1 tools respond correctly. (3) The knowledge graph is persisted in both SQLite and YAML, and `rebuild-index` reconstructs SQLite with no data loss. (4) `apriori status` reports accurate coverage metrics. (5) Running `init` a second time after code changes correctly detects changed files, updates the structural graph, and populates appropriate work items. (6) Structural parsing processes files at sub-second speed per file; full `init` of a 10,000-file repository completes within 60 seconds. (7) All MCP read tool queries on a graph with up to 10,000 concepts complete in under 500ms at p95.

---

## 4. Phase 2: Semantic Intelligence & Audit

Phase 2 delivers Layer 1 (Semantic Enrichment), Layer 2 (Knowledge Management), the model-agnostic adapter layer, the three-level quality assurance pipeline, the adaptive priority modulation system, and the human audit UI. This phase has grown substantially compared to the prior version of the PRD — it is now the largest and most complex phase.

**PRD Sections Covered:** §4.1 (Layer 1, Layer 2), §4.4, §6.1–6.5, §8A, §9 (metrics as control system)

### 4.1 LLM Adapter Layer

**Module:** `apriori/adapters/`

#### 4.1.1 Adapter Protocol (`adapters/base.py`)

Protocol for LLM adapters. The interface must support: `async analyze(prompt: str, context: dict) -> AnalysisResult` (send prompt, return parsed result; handles retries, rate limiting, and provider-specific errors internally), `get_token_count(text: str) -> int` (estimate token count for budget management), `get_model_info() -> ModelInfo` (metadata about model name, context window, cost per token for telemetry).

The adapter must return the model name as a string in the response metadata — this value is written into failure records so that retry attempts can be distinguished from the original.

#### 4.1.2 Anthropic Adapter and Ollama Adapter

Anthropic adapter wraps the Anthropic Python SDK. Ollama adapter wraps the Ollama HTTP API (typically `localhost:11434`). Ollama adapter must handle the case where Ollama is not running with a clear error message.

Both adapters are used in two contexts: (1) the librarian's primary analysis call, and (2) the co-regulation review call. The co-regulation review may use the same model or a different one, determined by configuration. The adapter does not need to know which context it's being called from — the caller provides the prompt and the adapter executes it.

### 4.2 Librarian Orchestrator

**Module:** `apriori/semantic/librarian.py`

#### 4.2.1 Loop Execution

The librarian implements the Ralph-Wiggum loop from PRD §6.1. Invoked via `apriori librarian run`. Each invocation runs a configurable number of iterations.

A single iteration follows this exact sequence, updated from PRD §6.2:

1. **Read work queue.** Load unresolved work items from storage, with priority scores computed fresh by the adaptive priority engine (§4.3).
2. **Select work item.** Pick the highest-priority unresolved item. If the queue is empty, log and exit cleanly. If the selected item has previous failure records, those records are loaded for inclusion in the prompt context.
3. **Load context.** Based on work item type, load the minimum relevant subgraph from storage. For `investigate_file`: the file's structural concepts and immediate neighbors. For `verify_concept`: the concept, its code references, edges, and neighbors. For `evaluate_relationship`: both endpoint concepts and their neighborhoods.
4. **Read code.** For work items referencing a file or concept with code references, read the source code from disk.
5. **Formulate prompt.** Use model-specific prompt templates. The prompt includes the code, structural context, existing semantic knowledge about related concepts, instructions for what knowledge to extract, and — critically — any failure feedback from previous attempts on this work item. If the work item has failure records, the prompt must instruct the librarian to consider the previous failure feedback and adjust its approach.
6. **Call LLM.** Send the prompt to the configured LLM via the adapter. Track token consumption.
7. **Level 1: Automated consistency check.** Run the output through `quality/level1.py`. If it fails: write a FailureRecord to the work item (with `failure_reason` identifying the specific check), increment `failure_count`, check if escalation threshold is reached (if so, escalate), and exit.
8. **Level 1.5: Co-regulation review (if enabled).** Run the output through `quality/level15.py`, which makes a second LLM call. If it fails: write a FailureRecord with the co-regulation assessment's dimensional scores and feedback, increment `failure_count`, check for escalation, and exit.
9. **Integrate knowledge.** Pass the validated output to the Knowledge Manager (§4.4) for graph integration.
10. **Mark resolved.** Mark the work item as resolved with a timestamp and exit.

Each iteration is isolated. No state is carried between iterations except through the knowledge graph and work queue on disk.

#### 4.2.2 Prompt Templates

**Module:** `apriori/semantic/prompt_templates/`

Prompt templates must support a `with_failure_context` mode. When a work item has failure records, the template must include a section like:

```
Previous attempts to analyze this code failed quality review. Here is the feedback from those attempts:

Attempt 1 (model: claude-sonnet-4-20250514):
- Failed check: Level 1.5 co-regulation review
- Specificity score: 0.2 (threshold: 0.5)
- Feedback: "The description is generic. The code contains payment validation logic including amount limits, currency format checks, and merchant category restrictions that should be described specifically."

Please incorporate this feedback into your analysis. Be specific about the actual logic and behavior in this code.
```

The output schema the LLM is instructed to produce must include: a list of concepts (each with name, description, confidence, code references), a list of relationships (each with source, target, edge type, confidence, rationale), and any labels to apply. The output should be requested as structured JSON, with fallback text parsing for models that don't support structured output.

### 4.3 Priority Scoring & Adaptive Modulation

**Module:** `apriori/semantic/priority.py`

This module now has two responsibilities: computing base priority scores and modulating them via the metrics feedback loop. This is a significant change from the prior PRD.

#### 4.3.1 Base Priority Computation

For each unresolved work item, compute each factor: `staleness` (ratio of knowledge age to code age, clamped to `[0, 1]`), `needs_review` (binary `1.0` if the concept has the label, else `0.0`), `coverage_gap` (binary for `investigate_file` items), `git_activity` (normalized commit count in configured window), `semantic_delta` (binary for `evaluate_relationship` items), `developer_proximity` (graph distance from recent developer activity, inverted and normalized).

#### 4.3.2 Adaptive Modulation (PRD §6.3.1)

Before applying the weighted sum, the engine runs a health check by computing current metric values via `knowledge/metrics.py`:

`current_coverage = files_with_concepts / total_source_files`
`current_freshness = concepts_verified_after_code_change / total_active_concepts`
`current_blast_radius_completeness = concepts_with_nonstale_impact_profile / total_concepts`

For each metric, compute the deficit: `deficit = max(0, target - current_value)`. A deficit of 0 means the metric is at or above target.

Then apply modulation to the base weights:

```python
# Mapping from metrics to the weights they boost
metric_weight_map = {
    "coverage":   ["coverage_gap"],
    "freshness":  ["staleness", "needs_review"],
    "blast_radius_completeness": []  # boosts analyze_impact items directly (see below)
}

for weight_name in metric_weight_map[metric]:
    effective_weight[weight_name] = base_weight[weight_name] * (
        1 + deficit * modulation_strength
    )
```

For blast radius completeness, the modulation is applied differently: rather than boosting a weight factor, the engine directly boosts the priority score of all work items with `item_type == "analyze_impact"` by `(1 + blast_deficit * modulation_strength)`. This is because blast radius completeness doesn't map cleanly to one of the six weight factors — it maps to a work item type.

For escalated items, after computing the modulated priority, multiply by the configured reduction factor (default: 0.5).

The telemetry output of each priority computation cycle must include: the current metric values, their targets, the computed deficits, the resulting effective weights (before and after modulation), and the work item selected and its score. This feeds the health dashboard in the audit UI.

### 4.4 Quality Assurance Pipeline

**Module:** `apriori/quality/`

This is the most architecturally novel component in the updated PRD. It implements a three-level quality assurance system where each level catches a different class of error.

#### 4.4.1 Level 1: Automated Consistency Check (`quality/level1.py`)

Deterministic, no LLM calls, executes in milliseconds. Checks:

1. **Non-empty, non-generic description.** The description must be non-empty and must not match a set of known boilerplate patterns (e.g., "this module handles data processing", "this function performs operations"). This check can use a short list of banned patterns plus a minimum character length (e.g., 50 characters). It's intentionally a low bar — Level 1.5 catches subtler quality issues.
2. **Referential integrity.** Any relationship that references a concept by name must reference a concept that already exists in the graph or is being created in the same batch.
3. **Confidence range.** All confidence scores must be in `[0.0, 1.0]`.
4. **Schema validity.** The parsed output must conform to the expected Pydantic models (all required fields present, correct types). This is where Pydantic's validation shines — malformed LLM output produces clear, loggable validation errors.
5. **Edge type validity.** All asserted edge types must be in the controlled vocabulary.
6. **Structural corroboration (soft check).** If the librarian asserts a dependency relationship (edge types: `depends-on`, `implements`, `extends`), the structural graph is checked for corroborating evidence (an import, call, or type reference between the relevant code entities). If no structural corroboration is found, the confidence score is reduced by the configurable factor (default: 0.2) and a metadata note is attached. This does not fail the check — it's a confidence adjustment.

If any check (1–5) fails, the entire iteration's output is rejected. A FailureRecord is created with the specific check that failed and the reason.

#### 4.4.2 Level 1.5: Co-Regulation Review (`quality/level15.py`)

LLM-as-judge. Makes a second LLM call after Level 1 passes. This is the component that approximately doubles LLM cost per iteration when enabled.

The co-regulation review prompt must provide: the librarian's full output (concepts, relationships, confidence scores), the original code that was analyzed, and the structural context (the structural graph neighborhood). The prompt instructs the judge model to evaluate on three dimensions:

**Specificity** — Is the description specific to this actual code, or could it describe any module? Score 0.0–1.0.

**Structural corroboration** — Do the asserted relationships make sense given the code's structure? This is a deeper, LLM-powered reasoning about whether relationships are plausible, beyond the rule-based check in Level 1. Score 0.0–1.0.

**Completeness** — Did the analysis cover the main entities and behaviors in the code, or did it miss obvious aspects? Score 0.0–1.0.

The judge model must return a structured response: the three scores, a composite pass/fail verdict, and on failure, specific feedback identifying what was insufficient and how it could be improved. This feedback is the key input to the retry mechanism — it must be actionable, not vague.

Implementation detail: the co-regulation prompt template must be carefully designed to avoid the judge simply agreeing with the analysis. Adversarial framing ("find the weaknesses in this analysis") tends to produce better reviews than confirmatory framing ("evaluate whether this analysis is good"). This should be validated during development and refined iteratively.

The co-regulation review is configurable: it can use the same model as the primary analysis or a different model. It is enabled by default but can be disabled via `quality.co_regulation.enabled = false` in config. When disabled, the librarian runs with Level 1 only.

#### 4.4.3 Failure Management and Escalation (`quality/failure.py`)

When a work item fails (at either Level 1 or Level 1.5): (1) Create a `FailureRecord` with full diagnostic context (timestamp, model, prompt template, failure reason, quality scores if Level 1.5, reviewer feedback if Level 1.5). (2) Append the record to the work item's `failure_records`. (3) Increment `failure_count`. (4) If `failure_count >= escalation_threshold` (default: 3): set `escalated = True`, add `needs-human-review` label to the associated concept (if any), and log the escalation. (5) The work item remains unresolved in the queue.

The escalation logic is in this module. The priority reduction (0.5x multiplier on escalated items) is applied in the priority scoring module, not here — this module just flips the flag.

#### 4.4.4 Human Review Outcome Tracking (`quality/review_outcomes.py`)

Manages the `review_outcomes` table. When a human reviewer takes an action in the audit UI (verify, correct, or flag a concept), this module records the outcome and updates the concept accordingly.

For `verified`: set `verified_by` and `last_verified` on the concept, boost confidence by a configurable increment (default: +0.1, capped at 1.0).

For `corrected`: update the concept's description/relationships as specified, record the error type (description_wrong, relationship_missing, relationship_hallucinated, confidence_miscalibrated, other), and log the full correction for the error profile.

For `flagged`: add `needs-review` label to the concept, generate a `review_concept` work item.

The error profiling capability aggregates review outcomes over time to surface the librarian's systematic weaknesses: "In the last 30 days, 40% of human corrections were for missing relationships" tells you the prompt templates need to ask more explicitly about relationships.

### 4.5 Knowledge Manager

**Module:** `apriori/knowledge/manager.py`

Implements the "never just append" philosophy from PRD §4.1 (Layer 2). When the librarian produces validated knowledge (i.e., knowledge that has passed the quality pipeline), the manager decides how to integrate it.

Integration decision tree for each concept the librarian produces:

**Does a concept with this name already exist?** If no: create a new concept node with `created_by = "agent"` and the librarian's confidence. If yes and existing concept was created by a human: do not overwrite. Append the librarian's analysis as supplementary context, or create relationship edges only. Human-created knowledge has provenance priority. If yes and existing concept was created by an agent: does the new description agree? Update `last_verified` and potentially increase confidence. Does it contradict? Store both with a `needs-review` label. Log the contradiction. Does it extend? Merge descriptions (append new information, preserve existing). Update `updated_at`.

For each relationship the librarian asserts: if the edge already exists, update confidence (take the higher value or average). If it doesn't exist, create it. If the librarian asserts something contradicting an existing edge, flag both with `needs-review`.

Temporal stamping: every write stamps the current git HEAD hash as `derived_from_code_version`.

### 4.6 Metrics Engine

**Module:** `apriori/knowledge/metrics.py`

New module. Computes the three core product metrics from PRD §9.1 that serve dual purpose: reporting and driving adaptive modulation.

**Coverage:** `count(distinct files referenced by at least one concept) / count(total source files)`. "Total source files" is determined by the same glob patterns the structural parser uses. Files excluded from parsing are excluded from the denominator.

**Freshness:** `count(concepts where last_verified > last_code_modification) / count(concepts referencing actively-developed files)`. "Actively-developed files" means files modified in the last 30 days (configurable). Concepts referencing only inactive files are excluded from this metric. Concepts with `last_verified = NULL` (never verified) are excluded from the freshness denominator — they are "unverified," not "stale." Freshness measures how current the verified knowledge is, not how much of the codebase has been verified (see coverage metric).

**Blast radius completeness:** `count(concepts with non-stale impact profile) / count(total concepts)`. A profile is "stale" if its `last_computed` timestamp is older than the configurable staleness threshold.

These computations must be efficient — they run before every librarian iteration (for adaptive modulation) and on every audit UI dashboard load (for display). They should be SQL queries against the SQLite database, not full-table scans through Python. Pre-computing and caching the results with a short TTL (e.g., 30 seconds) is acceptable.

### 4.7 Human Audit UI

**Module:** `apriori/ui/`

**PRD Section:** §8A

This is a new deliverable in this PRD revision and represents a full frontend component. The audit UI is a locally-served single-page web application started via `apriori ui` (or `apriori-ui` as a standalone command). It runs on localhost, reads from the same SQLite database the MCP server and librarian use, requires no authentication or internet connectivity, and transmits no data externally.

#### 4.7.1 Technology Selection (Spike Required — see S-7)

The frontend technology must be decided via spike. The key constraint is that the UI must be self-contained — no external CDN dependencies, no build step required at install time, no Node.js dependency for the end user. Options to evaluate: (a) a pre-built React SPA bundled as static assets within the Python package, (b) a server-rendered approach using Jinja2 templates with HTMX for interactivity, (c) a lightweight framework like Alpine.js served as static files. The backend should be Flask or FastAPI serving both the REST API endpoints and the static frontend assets.

#### 4.7.2 Backend API (`ui/api.py`)

The REST API serves the frontend and is read-only except for review actions. Endpoints:

**Graph data:** `GET /api/concepts` (with filters for labels, confidence, recency, provenance), `GET /api/concepts/{id}` (full concept with edges and impact profile), `GET /api/edges` (with filters for type, confidence), `GET /api/graph` (subgraph for visualization, with a center concept and configurable radius).

**Librarian activity:** `GET /api/activity` (chronological feed of recent librarian iterations — what was processed, what was created/updated, pass/fail, co-regulation scores).

**Review workflow:** `POST /api/concepts/{id}/verify` (mark as verified), `POST /api/concepts/{id}/correct` (submit correction with error type), `POST /api/concepts/{id}/flag` (flag for re-review). These three endpoints are the only write operations the UI performs. They delegate to the review outcomes module and knowledge manager.

**Health metrics:** `GET /api/health` (current values for coverage, freshness, blast radius completeness, their targets, the effective priority weights including modulation, and the work queue depth).

**Escalated items:** `GET /api/escalated` (work items that have exceeded the failure threshold, with full failure history).

#### 4.7.3 Frontend Capabilities (PRD §8A.3)

The frontend must implement five capabilities from the PRD:

**Knowledge Graph Visualization.** An interactive node-and-edge view. Concepts are nodes, edges are connections. Clicking a concept shows its full details. Supports filtering by edge type, confidence threshold, label, and recency. Visually distinguishes high-confidence from low-confidence knowledge (opacity, color, or line style).

**Librarian Activity Feed.** A chronological list of recent iterations. Each entry shows: work item processed, concept created/updated, co-regulation scores (if applicable), pass/fail status, and on failure the failure reason. This is the primary mechanism for casual monitoring of librarian quality.

**Review Workflow.** View a concept alongside its referenced code (shown inline or as a link to the file). Mark as verified. Flag for correction with inline editing of description and relationships. Submit corrections that log review outcomes.

**Health Dashboard.** Displays current metric values alongside targets (coverage: X% vs. 80% target). Shows current effective priority weights (including adaptive modulation). Shows work queue depth. This gives the user a single-glance understanding of the graph's state and the librarian's focus.

**Escalated Items View.** Dedicated view for work items past the failure threshold. Shows full failure history per item: each attempt's model, failure reason, co-regulation scores, and feedback. Enables the developer to assess whether the failure is due to model limitations, ambiguous code, or prompt template issues.

### 4.8 Token Budget Management

**Phase: Phase 2 for token budget enforcement; progressive enrichment is deferred to Phase 4 per PRD §6.5 and §12.**

Implements PRD §6.5. The librarian must enforce: per-iteration token limit (if prompt plus response exceeds the limit, truncate graph context — not the code — to fit; log warning on truncation), per-run iteration limit, per-run token limit (stop if cumulative total would exceed budget on next iteration, estimated from running average).

Critical new consideration: when co-regulation review is enabled, the per-iteration cost is approximately doubled (one call for analysis, one for review). The budget management system must account for this by estimating per-iteration cost as `analysis_tokens + review_tokens` and enforcing the budget against the combined cost. If only the analysis call completes before the budget would be exceeded by the review call, the iteration should proceed (you don't want to skip the quality check to save tokens — that defeats the purpose).

Telemetry output at end of each run: total iterations, total tokens consumed (broken down by analysis vs. review), concepts created/updated, edges created/updated, work items resolved, work items failed, work items escalated.

### 4.9 Phase 2 Acceptance Criteria

Phase 2 is complete when:

1. `apriori librarian run` executes iterations against a real codebase using both the Anthropic adapter and the Ollama adapter, with the quality pipeline processing each iteration's output.
2. The Level 1 automated consistency check correctly rejects malformed output (empty descriptions, invalid confidence ranges, bad edge types) and writes structured failure records.
3. The Level 1.5 co-regulation review evaluates output on specificity, structural corroboration, and completeness, and correctly rejects low-quality analysis with actionable feedback.
4. When a work item has failure records, the librarian's retry prompt includes the failure history and feedback, and the retry attempt produces measurably different output.
5. When a work item's failure count reaches the escalation threshold, it is correctly escalated: priority reduced, `needs-human-review` label applied, item appears in the audit UI's escalated items view.
6. The adaptive priority modulation correctly shifts weights based on metric deficits — when coverage is low, the librarian demonstrably prioritizes `investigate_file` items; when freshness drops, it prioritizes `verify_concept` items.
7. The audit UI starts via `apriori ui`, displays the knowledge graph visualization, shows the librarian activity feed, supports the verify/correct/flag review workflow, and displays the health dashboard with accurate metrics and effective weights.
8. Review outcomes from the audit UI are correctly recorded and the error profile can be queried.
9. Token budget limits are enforced, with co-regulation cost correctly accounted for when enabled.
10. The `semantic` mode of the `search` MCP tool returns relevant results via vector similarity.

---

## 5. Phase 3: Blast Radius

Phase 3 delivers the impact profile data model, three-layer impact computation, the `blast_radius` MCP tool, and impact profile maintenance. This phase is unchanged from the prior PRD revision.

**PRD Sections Covered:** §5.5, §7.1–7.4, §8.1 (`blast_radius`)

### 5.1 Impact Profile Computation

**Module:** `apriori/retrieval/blast_radius.py`

**Structural impact:** BFS traversal of structural edges (`calls`, `imports`, `inherits`, `type-references`) from the target concept. Each hop increments depth. All entries have `confidence = 1.0`. Deterministic and fast. Recomputed when structural graph changes.

**Semantic impact:** BFS traversal of semantic edges (`depends-on`, `implements`, `shares-assumption-about`, `extends`, `supersedes`). `relates-to` and `owned-by` are intentionally excluded — `relates-to` is a weak generic association that would generate false positives, and `owned-by` is organizational metadata rather than a functional dependency. Confidence is the product of edge confidences along the path (degrades with each hop). Depends on the semantic layer being populated. Profiles with no semantic data must be flagged as "structural only."

**Historical impact:** Analyze git log for commits touching the target concept's files. For co-occurring files, compute confidence proportional to co-change frequency with recency decay. Should be batched rather than per-concept.

### 5.2 Impact Profile Maintenance

Pre-computed and stored on each concept node. Updated: structurally (immediately when change detector runs and structural edges change), semantically (as a side effect of librarian iterations that discover new relationships), historically (periodically, configurable interval). Stale profiles generate `analyze_impact` work items.

### 5.3 Blast Radius MCP Tool

Input: concept name, concept ID, file path, or function symbol. Plus optional `depth` (max hops) and `min_confidence` (filter threshold, default 0.1). If input resolves to multiple concepts (e.g., a file with many functions), return union of impact profiles.

Output: prioritized list of affected concepts sorted by composite score (`confidence * (1 / depth)`). Each entry includes concept name/ID, confidence, impact layer, depth, relationship path, and human-readable rationale.

Performance: sub-second (under 500ms at p95). Profiles are pre-computed, so query is lookup plus formatting.

### 5.4 Phase 3 Acceptance Criteria

Phase 3 is complete when: (1) `blast_radius` returns correct pre-computed profiles with all three layers when data is available. (2) Confidence scoring is correct per layer. (3) Query latency is under 500ms at p95 on a 10,000-concept graph. (4) Profiles are maintained continuously. (5) Blast radius accuracy meets PRD §9.1 targets (>70% recall, >50% precision) when measured against historical PRs (requires validation methodology from Spike S-4).

---

## 6. Phase 4: Polish & Scale

Phase 4 delivers progressive enrichment, comprehensive CLI, and documentation. This phase refines and hardens the system rather than adding new architectural components.

**PRD Sections Covered:** §6.5 (progressive enrichment), §10.1 (CLI, documentation)

### 6.1 Progressive Enrichment

During initial bootstrap, the librarian must start with the developer's actively-edited files and expand outward by graph distance, respecting token budget. Implemented by modifying the priority engine to heavily weight `developer_proximity` when overall coverage is below a threshold (e.g., 50%). Once coverage exceeds the threshold, revert to standard weight configuration.

Clear progress telemetry: "Analyzed 47/312 source files. Estimated remaining cost: ~$2.30 at current model pricing."

### 6.2 Comprehensive CLI

Expand from Phase 1: `apriori librarian run [--iterations N] [--budget TOKENS]`, `apriori librarian status`, `apriori blast-radius <target>`, `apriori concept <name>`, `apriori validate` (integrity checks), `apriori export [--format json|yaml]`, `apriori doctor` (diagnostic: tree-sitter, LLM connectivity, SQLite health, git integration), `apriori ui` (start audit UI server).

### 6.3 Documentation

README.md (quick-start), configuration reference, MCP tool reference (13 tools with schemas and examples), architecture guide, model quality guide with cost/quality/speed tradeoff analysis, audit UI user guide.

### 6.4 Phase 4 Acceptance Criteria

Phase 4 is complete when: (1) Progressive enrichment correctly prioritizes developer-proximate files during bootstrap and stays within budget. (2) All CLI commands execute correctly. (3) `apriori doctor` validates the full installation. (4) Documentation is sufficient for self-service adoption (time to first value within 60 seconds for structural, within 10 iterations for semantic).

---

## 7. Areas of Concern and Required Spikes

### S-1: Async Architecture Decision — **DECIDED**

**Decision:** Core library functions are synchronous (`def`); LLM adapter calls and MCP server handlers are async (`async def`). See spike decision document in `spikes/` directory.

**Original question:** Should the core library be async-first (`asyncio`) or synchronous? The MCP Python SDK may impose constraints. The librarian and co-regulation review both make network calls that benefit from async.

**Risk if skipped:** Retrofitting async into a synchronous codebase is extremely expensive. Must be decided before Phase 1.

**Timebox:** 2–3 hours. Evaluate MCP Python SDK execution model, test `aiosqlite` with sqlite-vec, decide.

### S-2: Embedding Strategy for Vector Search — **DECIDED**

**Decision:** Use `intfloat/e5-base-v2` via `sentence-transformers` for local embedding generation. 768-dimensional vectors, cosine distance, ~440MB model download cached in `~/.cache/huggingface/`. See spike decision document in `spikes/` directory.

**Original question:** How will concept embeddings be generated for the `semantic` search mode? Options: (a) configured LLM generates embeddings (adds cost), (b) separate local embedding model like `all-MiniLM-L6-v2` via `sentence-transformers` (free, fast), (c) defer vector search to Phase 2. Embedding dimension must be known at schema creation time.

**Timebox:** 3–4 hours. Test `sentence-transformers` integration, measure performance, decide on dimensions.

### S-3: Tree-sitter Grammar Quality

**Question:** What is the actual quality of tree-sitter grammars for Python and TypeScript? Known gaps in function detection, class parsing, import resolution, or JSX/TSX?

**Timebox:** 2 hours. Parse diverse real-world files, manually verify, document gaps.

### S-4: Blast Radius Accuracy Validation Methodology

**Question:** How will we measure blast radius accuracy against real PRs (PRD §9.1 targets)? Design the test harness approach.

**Timebox:** 2–3 hours. Design validation approach, identify suitable test repository, document methodology.

### S-5: YAML Serialization Performance at Scale

**Question:** Performance of one-file-per-concept at 10,000 concepts? Directory listing and `rebuild_index` performance? Need for nested directory structure?

**Timebox:** 2 hours. Generate synthetic files, measure, decide.

### S-6: MCP Python SDK Capabilities and Constraints — **DECIDED**

**Decision:** Use FastMCP framework, pinned to `mcp>=1.26,<2.0`. All tools are plain `def` decorated with `@mcp.tool()` and `@safe_tool` (3–10 lines each). Lifespan context manager initializes `KnowledgeStore`. See spike decision document in `spikes/` directory.

**Original question:** What does the SDK support for tool registration, schemas, error handling, server lifecycle?

**Timebox:** 2 hours. Build minimal MCP server, test with MCP client, document patterns.

### S-7: Audit UI Technology Selection

**Question:** What frontend technology for the audit UI? This is a new spike driven by the addition of §8A to the PRD.

The key constraints are: (a) the UI must be self-contained with no external CDN dependencies at runtime, (b) no build step or Node.js dependency for the end user at install time, (c) the graph visualization must handle at least 500 nodes interactively (larger graphs should gracefully degrade, e.g., by clustering or paging), (d) the technology must be maintainable by a small team that is primarily Python-focused.

Options to evaluate: **Pre-built React SPA** bundled as static assets in the Python package. Best interactivity and ecosystem (D3.js, Cytoscape.js for graph viz), but requires a build pipeline maintained separately from the Python package and adds complexity to the release process. **HTMX + Jinja2 server-rendered.** Minimal JavaScript, naturally Python-native, but graph visualization will require a JavaScript library anyway — so you end up with a hybrid. Good for forms and feeds, weak for interactive graph exploration. **Alpine.js + static assets.** Middle ground. Lightweight enough to include without a build step, capable enough for the interactive UI, but the graph visualization library still drives complexity.

The spike should produce a working prototype of the graph visualization with at least one approach and measure: bundle size, load time, interaction latency at 500 nodes, and developer ergonomics.

**Timebox:** 4–6 hours. This is the longest spike because it involves building a prototype.

### S-8: Co-Regulation Prompt Design

**Question:** How should the co-regulation review prompt be structured to avoid the judge simply agreeing with the analysis? What framing produces genuinely critical evaluation?

**Risk if skipped:** A co-regulation review that rubber-stamps everything is worse than no review — it costs tokens and provides false confidence. The PRD notes that adversarial framing tends to produce better reviews, but the specific prompt design requires experimentation.

**Timebox:** 3–4 hours. Write three candidate review prompts with different framings (confirmatory, adversarial, structured-rubric), test each against a set of known-good and known-bad librarian outputs, measure how well each prompt discriminates quality.

---

## 8. Dependencies and Integration Points

### 8.1 External Dependencies

| Dependency | Version | Purpose | Phase |
|---|---|---|---|
| Python | ≥ 3.11 | Runtime | All |
| tree-sitter | Latest | AST parsing | 1 |
| tree-sitter-python | Latest | Python grammar | 1 |
| tree-sitter-typescript | Latest | TS/JS grammar | 1 |
| SQLite (stdlib) | Bundled | Primary data store | 1 |
| sqlite-vec | Latest | Vector similarity search | 1 or 2 |
| PyYAML | Latest | YAML serialization | 1 |
| MCP Python SDK | Latest | MCP server | 1 |
| Pydantic | Latest | Data model validation | 1 |
| Click or Typer | Latest | CLI framework | 1 |
| Git CLI | ≥ 2.20 | Change detection, history | 1 |
| anthropic (Python SDK) | Latest | Anthropic API adapter | 2 |
| ollama (Python client) | Latest | Ollama adapter | 2 |
| sentence-transformers | Latest (conditional) | Local embeddings (per S-2) | 1 or 2 |
| Flask or FastAPI | Latest | Audit UI backend | 2 |
| Graph visualization library | Per S-7 | Audit UI frontend | 2 |

### 8.2 Internal Integration Points

Critical integration boundaries where contract tests are most valuable:

1. **Storage Protocol ↔ SQLite/YAML implementations.** Both implementations must pass the same protocol test suite. New: work item failure operations (`record_failure`, `escalate_work_item`) and review outcome operations are part of this contract.
2. **LLM Adapter Protocol ↔ Anthropic/Ollama implementations.** Same model identifier format returned from both, since it's written into failure records.
3. **Librarian Orchestrator ↔ Quality Pipeline.** The librarian produces raw output; the quality pipeline validates it and returns either a pass (with the validated output) or a fail (with a FailureRecord to write). This interface is the single most important contract in the system — if it breaks, bad knowledge enters the graph or good knowledge is blocked.
4. **Quality Pipeline ↔ LLM Adapters.** The co-regulation review makes its own LLM call. It uses the same adapter interface as the librarian but with a different prompt. The adapter must not assume it's only called once per iteration.
5. **Audit UI API ↔ Storage Layer.** The UI API reads from SQLite and writes review outcomes. It must not bypass the storage protocol — it delegates to the same `KnowledgeStore` implementation the rest of the system uses.
6. **Priority Engine ↔ Metrics Engine.** The priority engine calls the metrics engine to get current values before modulation. The metrics engine must return consistent results (no race conditions if the librarian is writing simultaneously — WAL mode helps here).

### 8.3 External Integration Points

**LLM Provider APIs.** Subject to rate limits, outages, API changes. The adapter layer handles transient failures with retry/backoff. Note that with co-regulation enabled, each iteration makes two LLM calls — the adapter's rate limiting must account for this doubled call rate.

**Git CLI.** Commands must be compatible with git ≥ 2.20. Handle missing `git` at `apriori init` time with a clear error.

**MCP Clients.** Tool schemas must conform to MCP spec. Error responses must follow MCP conventions.

---

## 9. PRD-to-ERD Traceability Map

| PRD Section | Requirement | ERD Section | Phase |
|---|---|---|---|
| §4.1 Layer 0 | Structural engine, AST parsing, zero LLM | §3.3 | 1 |
| §4.1 Layer 1 | Semantic enrichment, Ralph-Wiggum loop | §4.2 | 2 |
| §4.1 Layer 2 | Knowledge management, temporal tracking | §4.5 | 2 |
| §4.1 Layer 3 | Retrieval interface, MCP, CLI | §3.4, §3.5, §6.2 | 1, 4 |
| §4.2 | Core library + thin shells | §2.1 | 1 |
| §4.3 | SQLite + YAML, dual write | §3.2 | 1 |
| §4.4 | Model-agnostic adapters | §4.1 | 2 |
| §5.1 | Concept node schema | §3.1.1 | 1 |
| §5.2 | Code reference repair chain | §3.1.2 | 1 |
| §5.3 | Edge schema | §3.1.3 | 1 |
| §5.4 | Edge type vocabulary | §3.1.3 | 1 |
| §5.5 | Impact profile schema | §5.1 | 3 |
| §5.6 | Work item schema + FailureRecord | §3.1.4, §3.1.5 | 1 (schema), 2 (exercised) |
| §6.1 | Ralph-Wiggum loop execution | §4.2.1 | 2 |
| §6.2 | Iteration workflow (updated with quality steps) | §4.2.1 | 2 |
| §6.3 | Priority scoring (base weights) | §4.3.1 | 2 |
| §6.3.1 | Adaptive priority modulation | §4.3.2 | 2 |
| §6.4.1 | Level 1 automated consistency check | §4.4.1 | 2 |
| §6.4.2 | Level 1.5 co-regulation review (LLM-as-judge) | §4.4.2 | 2 |
| §6.4.3 | Failure breadcrumbs + escalation | §4.4.3 | 2 |
| §6.4.4 | Level 2 surfaced human review | §4.4.4, §4.7 | 2 |
| §6.4.5 | Level 3 empirical validation (deferred) | N/A (data model ready) | Post-MVP |
| §6.5 | Token budget management | §4.8 | 2 |
| §7.1–7.2 | Blast radius, three-layer impact | §5.1 | 3 |
| §7.3 | Blast radius query interface | §5.3 | 3 |
| §7.4 | Impact profile maintenance | §5.2 | 3 |
| §8.1 | MCP read tools | §3.4, §5.3 | 1, 3 |
| §8.2 | MCP write tools | §3.4 | 1 |
| §8A | Human audit UI | §4.7 | 2 |
| §9.1 | Core product metrics (dual-purpose) | §4.6, §4.3.2 | 2 |
| §9.2 | Cost efficiency metrics | §4.8 | 2 |
| §9.3 | Time to first value | §3.6, §6.4 | 1, 4 |
| §10.1 | MVP scope | All sections | 1–4 |
| §11.3 | Dependencies | §8.1 | All |

---

## 10. Testing Strategy

### 10.1 Unit Tests

Every module must have unit tests. Highest-priority targets: the storage protocol (both SQLite and YAML implementations against an identical test suite), the quality pipeline (both Level 1 and Level 1.5 against known-good and known-bad librarian outputs), the priority engine (verify that modulation math is correct — deficit of 0 produces no change, deficit of 1.0 with modulation_strength of 1.0 doubles the effective weight), and the failure management logic (verify escalation triggers at the correct threshold).

### 10.2 Integration Tests

**End-to-end structural parse:** Point at a known test repository, run init, verify expected concepts and edges.

**Librarian iteration with quality pipeline:** Run a single iteration with a mocked LLM adapter against a test concept. Mock the adapter to return both a passing output and a failing output. Verify that the passing output is integrated into the graph and the failing output is rejected with a correct FailureRecord.

**Retry with failure context:** Create a work item with one failure record. Run a librarian iteration against it. Verify that the prompt includes the failure feedback.

**Escalation flow:** Create a work item with `failure_count = 2`. Run a failing iteration. Verify the item is escalated (flag set, label applied, priority reduced).

**Dual-write consistency:** Write a concept via dual writer, verify it in both SQLite and YAML.

**Rebuild-index round-trip:** Write to YAML only, run rebuild, verify SQLite matches.

**Audit UI integration:** Start the UI server, call each API endpoint, verify correct data is returned. Submit a review action and verify the review outcome is recorded.

### 10.3 Test Fixtures

Create a small, well-understood test repository (50–100 lines of Python) with import relationships, function calls across modules, class inheritance, and diverse code patterns. This repository is the ground truth for structural parsing, semantic analysis, quality pipeline, and blast radius validation.

Additionally, create a set of "librarian output fixtures" — both known-good outputs (that should pass all quality checks) and known-bad outputs (that should fail at specific stages). These fixtures are critical for testing the quality pipeline in isolation without live LLM calls.

---

*This ERD is a living document. It should be updated as spikes are resolved, as implementation reveals new technical decisions, and as scope evolves. Every significant deviation from this plan should be documented with rationale.*
