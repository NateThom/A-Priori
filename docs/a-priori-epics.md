# A-Priori: Epic Breakdown

**Date:** 2026-04-03
**Source:** ERD v2 (`a-priori-erd-v2.md`), Spike decisions S-1, S-2, S-6
**Status:** Ready for story decomposition

---

## How to Read This Document

Each epic below represents a cohesive body of work that can be planned, estimated, and tracked as a unit. Epics are ordered by dependency — an epic's prerequisites are listed explicitly, and no epic should be started before its prerequisites are complete or nearly complete. Within each epic, the "Key Stories" section identifies the major units of work at a granularity suitable for sprint planning, but these are not tickets — they are the natural decomposition points where an engineering lead and the implementing developers should collaboratively break down into stories and tasks.

Spike stories are called out where they exist. These are time-boxed investigation tasks that must complete before the rest of the epic's implementation stories can begin. They are the first thing scheduled when the epic enters active development.

---

## Phase 1: Foundation

Phase 1 delivers a structural knowledge graph with no LLM dependency. A user can run `apriori init`, get a graph of functions/classes/modules and their relationships, and query it via MCP — all within 60 seconds.

---

### Epic 1: Data Models & Configuration

**Goal:** Establish the shared data vocabulary that every other module in the system imports from, and the configuration system that governs all runtime behavior.

**Prerequisites:** None. This is the first epic and has no dependencies.

**Scope:** Implement all Pydantic models defined in the ERD §3.1 (Concept, CodeReference, Edge, WorkItem, FailureRecord, CoRegulationAssessment, ReviewOutcome) and the ImpactProfile and ImpactEntry models from PRD §5.5, the edge type vocabulary with validation, and the configuration loading system with defaults, YAML parsing, and typed access. The FailureRecord, review-related, and impact profile models are defined here but not exercised until later phases — they need to exist in Phase 1 because the storage schema references them (e.g., the `impact_profile` column on the concepts table), avoiding a migration.

**Key Stories:**

The concept and code reference models are the foundation — every other model references them, so they come first. The edge model depends on the edge type vocabulary, which itself depends on the configuration system being able to load the vocabulary from `apriori.config.yaml`. The work item model includes the failure tracking fields (`failure_count`, `failure_records`, `escalated`) and the embedded `FailureRecord` model. Even though these aren't exercised until Phase 2, the SQLite schema must include these columns from day one to avoid a migration. The configuration module loads `apriori.config.yaml`, merges with hardcoded defaults, validates all values (including the new adaptive modulation settings: `modulation_strength`, metric targets), and exposes a typed configuration object. The quality-related models (CoRegulationAssessment, ReviewOutcome) should be implemented here even though they're Phase 2 concerns — they're small, self-contained, and having them defined keeps the model layer complete.

**Acceptance Criteria:** All models serialize to JSON and YAML without loss and deserialize back to identical objects. Pydantic validation rejects invalid inputs with clear error messages (confidence outside `[0.0, 1.0]`, invalid edge types, malformed UUIDs). The configuration system produces a valid typed config from an empty `apriori.config.yaml` (all defaults applied) and correctly merges user overrides.

**Estimated Scope:** Small. These are data definitions and a config loader. The majority of the time is spent getting the Pydantic validation right and writing thorough tests, not on complex logic.

---

### Epic 2: Storage Layer

**Goal:** Implement the `KnowledgeStore` protocol with both the SQLite+sqlite-vec backend and the YAML flat file backend, coordinated through the dual writer. This is the most architecturally significant Phase 1 epic because every other layer depends on it.

**Prerequisites:** Epic 1 (Data Models & Configuration) must be complete — the storage layer persists and retrieves the models defined there.

**Scope:** The `KnowledgeStore` protocol definition (synchronous `def` methods per S-1), the SQLite implementation with the full schema from ERD §3.2.2 (including the `concept_embeddings` vec0 table at 768 dimensions per S-2 and the `review_outcomes` table for Phase 2), the YAML flat file implementation, the dual writer coordinating both, the `EmbeddingService` wrapping `sentence-transformers` with `e5-base-v2` (per S-2), the `rebuild_index` operation, and the connection pooling needed for thread safety (per S-1).

**Spike Story (S-5): YAML Performance at Scale.** Time-boxed at 2–3 hours. Generate 10,000 synthetic concept YAML files, measure directory listing and `rebuild_index` performance, determine whether a nested directory structure is needed. This should be the first story in the epic because its findings may change the YAML file layout.

**Key Stories:**

The `KnowledgeStore` protocol is the first deliverable — it's the contract that both implementations must satisfy and that every other module in the system codes against. Per S-1, all methods are plain `def`. The protocol must include all operations listed in the ERD §3.2.1, including the failure-tracking methods (`record_failure`, `escalate_work_item`, `get_escalated_items`) and the review outcome methods that Phase 2 will exercise.

The SQLite implementation is the largest single story in this epic. It implements the full schema, including the `vec0` table with `FLOAT[768]` and `distance_metric=cosine` (per S-2). It must enable WAL mode and foreign keys per connection. Connection management must be thread-safe — the S-1 decision specifies per-thread connections because sync core functions run in thread pool threads at the MCP and audit UI boundaries. A connection pool (e.g., a thread-local pattern or a simple pool) satisfies this. The `EmbeddingService` is initialized at `SqliteStore` construction time, loading the `e5-base-v2` model into memory (2–5 seconds startup cost per S-2). Concept creation and update methods call the `EmbeddingService` to generate/update embeddings as a side effect. The `search_semantic` method accepts a pre-computed query embedding and uses `vec_distance_cosine()` for similarity search. FTS5 is set up for keyword search on concept names and descriptions.

The YAML implementation writes one YAML file per concept (slugified name) and one per edge (UUID name) into `.apriori/concepts/` and `.apriori/edges/`. Work items, review outcomes, and failure records are SQLite-only — not dual-written. The findings from the S-5 spike story may influence the directory layout (flat vs. nested).

The dual writer implements the `KnowledgeStore` protocol and delegates to both backends. Write order: YAML first, SQLite second. SQLite failure is logged but does not roll back YAML. Reads are served from SQLite. Work item operations and review outcomes are SQLite-only (not dual-written). The `rebuild_index` operation reads all YAML files, deserializes them, re-generates embeddings via the `EmbeddingService` (per S-2's lifecycle spec), and upserts into SQLite. It must be idempotent.

A comprehensive protocol test suite must be written that runs against both the SQLite implementation and the dual writer. Both must pass the identical suite. This is the highest-priority testing target in the entire project.

**Acceptance Criteria:** Both SQLite and dual writer implementations pass the protocol test suite. Concepts can be created, read, updated, and deleted through the dual writer, with correct data in both SQLite and YAML. `rebuild_index` reconstructs SQLite from YAML files with no data loss, including regenerated embeddings. `search_semantic` returns relevant results for a natural language query via vector similarity (e5-base-v2 embeddings, cosine distance). `search_keyword` returns results via FTS5. Thread-safe concurrent reads work correctly under WAL mode.

**Estimated Scope:** Large. The SQLite implementation with sqlite-vec integration, embedding service, FTS5, and thread-safe connection management is the most complex single component in Phase 1.

---

### Epic 3: Structural Engine

**Goal:** Parse source code via tree-sitter, build a graph of structural relationships (calls, imports, inherits, type-references), and detect code changes via git integration to populate the work queue.

**Prerequisites:** Epic 2 (Storage Layer) must be complete — the structural engine writes its output (concept nodes and structural edges) through the `KnowledgeStore`.

**Scope:** The tree-sitter parsing orchestrator, language-specific parsers for Python and TypeScript, the graph builder that transforms parse results into concepts and edges, and the git-based change detector that identifies changed files and generates work items.

**Spike Story (S-3): Tree-sitter Grammar Quality.** Time-boxed at 3–4 hours. Parse a diverse set of real-world Python and TypeScript files (include decorators, nested classes, async functions, generators, JSX/TSX, re-exports, barrel files). Manually verify extraction completeness for functions, classes, modules, and imports. Document gaps and define workarounds. This must complete before the language-specific parser stories begin.

**Key Stories:**

The parsing orchestrator walks the repository file tree respecting include/exclude globs from configuration, determines language by extension, loads the appropriate tree-sitter grammar, and dispatches to the language-specific parser. The language-specific parsers for Python and TypeScript each implement a common interface. They extract functions (name, parameters, return type, line range, file path), classes (name, bases, methods), modules (file path, exports), and imports (source, symbols). The S-3 spike findings will identify any edge cases or gaps that become additional stories.

The graph builder transforms parse results into concept nodes and structural edges via the storage layer. It must be idempotent — running twice on the same code produces the same graph, upserting by fully-qualified symbol name. Each structural edge has `evidence_type = "structural"` and `confidence = 1.0`.

The change detector integrates with git to identify files changed since the last analysis point (stored as a commit hash). For changed files, it re-parses and updates the structural graph. For concepts with stale content hashes, it generates `verify_concept` work items and applies the `needs-review` label. For new files, it generates `investigate_file` items. *(Deferred to Phase 3)* For changed structural edges, it generates `analyze_impact` items.

**Acceptance Criteria:** `apriori init` on a Python repository produces concept nodes for all top-level and class-level functions/methods, all classes, and all modules, with structural edges for calls, imports, and inheritance. The same works for a TypeScript repository. Parsing processes files at sub-second speed per file. Running `init` a second time after code changes correctly detects the changes, updates the graph, and populates appropriate work items. The graph builder is idempotent.

**Estimated Scope:** Medium-large. Tree-sitter integration is well-documented, but the language-specific extraction logic for two languages, plus the git change detection, is substantial. The S-3 spike may reveal additional complexity.

---

### Epic 4: MCP Server

**Goal:** Expose the knowledge graph to AI coding agents via 13 MCP tools (6 read, 7 write) using FastMCP over stdio.

**Prerequisites:** Epic 2 (Storage Layer). Epic 4 can be developed in parallel with Epic 3 — the MCP tools read from and write to the KnowledgeStore and do not depend on the structural engine directly. A populated graph makes testing more meaningful, but is not required for implementation.

**Scope:** The FastMCP server setup with lifespan context manager (per S-6), the `safe_tool` error handling decorator (per S-6), all 13 tool handler functions, and stdio transport. The `blast_radius` tool is registered but returns a "not yet available" message until Phase 3.

**Key Stories:**

Server scaffolding comes first: the FastMCP instance, the lifespan context manager that initializes the `KnowledgeStore` (per S-6's pattern), the `safe_tool` decorator, and stdio transport. Per S-6, the SDK is pinned to `mcp>=1.26,<2.0`.

The six read tools (`search`, `traverse`, `get_concept`, `list_edge_types`, `get_status`, and the placeholder `blast_radius`) are implemented as plain `def` functions decorated with `@mcp.tool()` and `@safe_tool`. Each is 3–10 lines of glue per S-6's pattern. The `search` tool supports all four modes: `keyword` (FTS5), `exact` (name/ID lookup), `file` (concepts referencing a file path), and `semantic` (vector similarity using the `EmbeddingService` to embed the query text, then `search_semantic`). The `semantic` mode is a Phase 1 deliverable per S-2's decision that semantic search is a must-have from day one.

The seven write tools (`create_concept`, `update_concept`, `delete_concept`, `create_edge`, `update_edge`, `delete_edge`, `report_gap`) follow the same pattern. `report_gap` creates a `reported_gap` work item in the queue.

**Acceptance Criteria:** The MCP server starts via `python -m apriori.mcp.server` and accepts connections over stdio. All 13 tools are registered and appear in tool listing. Each tool responds correctly to well-formed requests. Invalid inputs return `isError=True` responses with descriptive messages (via the `safe_tool` decorator). The `search` tool returns relevant results in all four modes, including semantic. All read tool queries on a graph with up to 10,000 concepts complete in under 500ms at p95.

**Estimated Scope:** Small-medium. Per S-6, the glue code per tool is minimal. The bulk of the work is in the retrieval layer (query routing, context assembly, response formatting) that the tools delegate to, which may be developed as part of this epic or pulled into Epic 2 depending on team structure.

---

### Epic 5: CLI & First-Run Experience

**Goal:** Deliver the command-line interface for setup, status, and manual queries, including the "zero to first value" experience where a user runs `apriori init` and has a queryable graph within 60 seconds.

**Prerequisites:** Epics 2, 3, and 4 should be complete — the CLI orchestrates their functionality.

**Scope:** The CLI framework (Click or Typer), the `init`, `status`, `search`, `rebuild-index`, and `config` commands. The first-run experience including `.apriori/` directory creation, default config generation, structural parse, and first-time e5-base-v2 model download (per S-2, ~440MB, cached in `~/.cache/huggingface/`).

**Key Stories:**

The `apriori init` command is the most important story in this epic — it's the "time to first value" path. It creates `.apriori/`, writes a default `apriori.config.yaml`, triggers the structural parser, builds the graph, and reports results. On first run, the `EmbeddingService` will download the e5-base-v2 model (~440MB), which adds a one-time delay. The CLI should surface this clearly ("Downloading embedding model (440MB, one-time)...") rather than leaving the user staring at an unexplained pause.

The remaining commands (`status`, `search`, `rebuild-index`, `config`) are straightforward wrappers. `status` displays coverage metrics, work queue depth, and last parse timestamp. `search` wraps the same logic as the MCP `search` tool. `rebuild-index` wraps the `KnowledgeStore.rebuild_index` method to reconstruct the SQLite database from YAML authoritative files. `config` prints or modifies values.

**Acceptance Criteria:** `apriori init` works in any git repository with zero configuration beyond running the command. The structural graph is queryable via `apriori search` within 60 seconds of running `init` (excluding first-time model download). `apriori status` reports accurate metrics. `apriori rebuild-index` successfully reconstructs the database.

**Estimated Scope:** Small. The CLI is a thin shell over existing functionality. The most complex part is the first-run UX polish.

---

## Phase 2: Semantic Intelligence & Audit

Phase 2 is the largest phase and introduces LLM-dependent functionality: the librarian, the quality pipeline, and the audit UI. I've decomposed it into six epics because the PRD's Phase 2 scope is too large for a single epic — the co-regulation review system, the adaptive priority modulation, and the audit UI are each substantial bodies of work with different skill requirements.

The dependency structure within Phase 2 is important. The LLM Adapter epic is the foundation — everything else in Phase 2 depends on being able to call an LLM. The Quality Pipeline and the Knowledge Manager can be developed in parallel once adapters exist. The Librarian Orchestrator depends on all three (adapters, quality, knowledge manager) because it wires them together. The Priority & Metrics epic can be developed in parallel with the librarian but must be integrated before the librarian is considered complete. The Audit UI depends on all the other Phase 2 epics because it visualizes and interacts with their outputs.

---

### Epic 6: LLM Adapter Layer

**Goal:** Implement the model-agnostic adapter interface and concrete adapters for Anthropic API and Ollama, providing the LLM calling capability that the librarian and co-regulation review both depend on.

**Prerequisites:** Epic 1 (Data Models) — the adapter returns `AnalysisResult` and `ModelInfo` types defined in the models layer.

**Scope:** The `LLMAdapter` protocol (async `analyze` method per S-1), the Anthropic adapter wrapping the Anthropic Python SDK, the Ollama adapter wrapping the Ollama HTTP API, shared retry/backoff logic, and token counting utilities.

**Key Stories:**

The `LLMAdapter` protocol is the first deliverable. Per S-1, the `analyze` method is `async def` (this is the async boundary — network I/O to LLM providers). `get_token_count` and `get_model_info` are plain `def` (pure computation / config lookup). The protocol must be simple enough that adding a new provider (OpenAI, a different local runtime) requires only implementing the protocol, with no changes to calling code.

The Anthropic adapter wraps the Anthropic Python SDK's async client. It maps the adapter's prompt format to the Anthropic messages API, handles rate limiting and retries with exponential backoff, and returns the model name string in the response metadata (this value is written into failure records per ERD §3.1.5).

The Ollama adapter wraps the Ollama HTTP API via `httpx.AsyncClient`. It must handle the "Ollama not running" case with a clear error message, not a connection refused traceback. It maps the adapter's prompt format to Ollama's chat/generate API.

Both adapters must pass an identical test suite defined against the protocol. Tests should use mock HTTP responses (not live API calls) to verify prompt construction, response parsing, retry behavior, and error handling.

**Acceptance Criteria:** Both adapters pass the protocol test suite. The Anthropic adapter successfully sends a prompt and parses the response (verified with a live API call during development, mocked in CI). The Ollama adapter successfully calls a locally-running Ollama instance. Both adapters return accurate model name strings and token count estimates. Both adapters retry on transient failures and surface persistent failures clearly.

**Estimated Scope:** Medium. The adapters themselves are thin, but getting retry logic, error handling, and the protocol contract right takes care.

---

### Epic 7: Quality Assurance Pipeline

**Goal:** Implement the three-level quality assurance system that validates every piece of LLM-produced knowledge before it enters the graph: Level 1 automated consistency checks, Level 1.5 co-regulation LLM-as-judge review, and the failure breadcrumb/escalation machinery.

**Prerequisites:** Epic 6 (LLM Adapters) — the co-regulation review makes its own LLM call. Epic 2 (Storage Layer) — failure records are written to work items via the `KnowledgeStore`.

**Scope:** The Level 1 automated check module, the Level 1.5 co-regulation review module (including its prompt template), the failure record management and escalation logic, and the human review outcome tracking module. The audit UI (Level 2's visual interface) is a separate epic — this epic covers the data layer and logic that the UI will later surface.

**Spike Story (S-8): Co-Regulation Prompt Design.** Time-boxed at 3–4 hours. Write three candidate review prompts with different framings (confirmatory, adversarial, structured-rubric). Test each against a set of known-good and known-bad librarian outputs. Measure discrimination ability (does the prompt catch bad output while passing good output?). Select the best framing and document the prompt structure. This must complete before the Level 1.5 implementation story begins.

**Key Stories:**

Level 1 automated checks are deterministic, no-LLM, millisecond-fast validations. They implement the six checks from ERD §4.4.1: non-empty non-generic description, referential integrity, confidence range, schema validity (Pydantic validation), edge type validity, and structural corroboration (soft check — reduces confidence by configurable factor if no structural backing, but does not reject). A set of "librarian output fixtures" (known-good and known-bad) should be created as test data — these fixtures are reusable across the quality pipeline and the librarian orchestrator.

Level 1.5 co-regulation review constructs a review prompt (informed by S-8 findings), sends it to the configured LLM via the adapter, and parses the structured response into a `CoRegulationAssessment`. The prompt must include the librarian's output, the original code, and the structural context. The review evaluates specificity, structural corroboration, and completeness, each scored 0.0–1.0. The composite pass/fail threshold per dimension is configurable (defaults: 0.5 specificity, 0.3 structural corroboration, 0.4 completeness). On failure, the assessment's `feedback` field must contain specific, actionable guidance for the librarian's retry. The review uses the same LLM as the librarian by default, but supports a separate review model via configuration. The entire Level 1.5 module is gated by a config flag (`quality.co_regulation.enabled`, default `true`).

Failure management and escalation implements the logic from ERD §4.4.3. When a work item fails, a `FailureRecord` is created with full diagnostic context and appended to the work item's `failure_records`. When `failure_count` reaches the configurable threshold (default: 3), escalation triggers: `escalated = True`, `needs-human-review` label applied to the associated concept, and the escalation is logged. The priority reduction (0.5x on escalated items) is applied in the priority engine (Epic 9), not here.

Review outcome tracking manages the `review_outcomes` table. It implements `record_review_outcome` (writing the outcome and updating the concept's verification status or labels) and `get_error_profile` (aggregating error types over time to surface systematic librarian weaknesses).

**Acceptance Criteria:** Level 1 correctly rejects all known-bad fixtures (empty descriptions, invalid confidence, bad edge types, unparseable output) and passes all known-good fixtures. Level 1.5 correctly rejects low-quality analysis with specific, actionable feedback and passes high-quality analysis. Failure records contain enough context for a meaningful retry (model used, prompt template, failure reason, co-regulation feedback). Escalation triggers at the configured threshold and correctly applies the label and flag. The error profile correctly aggregates review outcomes and surfaces patterns.

**Estimated Scope:** Large. The co-regulation review involves prompt engineering (S-8), LLM integration, and structured response parsing. The failure management system has nuanced state transitions. This epic requires careful testing because it guards the integrity of the entire knowledge graph.

---

### Epic 8: Knowledge Manager

**Goal:** Implement the Layer 2 knowledge management logic that decides how new knowledge integrates into the graph — the "never just append" philosophy of update, merge, contradict, and expire.

**Prerequisites:** Epic 2 (Storage Layer) — the knowledge manager reads and writes through the `KnowledgeStore`.

**Scope:** The integration decision tree from ERD §4.5 (concept exists vs. new, human-created vs. agent-created, agree vs. contradict vs. extend), temporal stamping with git commit hashes, staleness detection, and contradiction handling.

**Key Stories:**

The core integration logic implements the decision tree. When the librarian produces a concept: if no concept with that name exists, create it. If one exists and was human-created, don't overwrite — supplement it. If one exists and was agent-created, compare: if agreeing, update `last_verified` and boost confidence; if contradicting, flag both with `needs-review` and log; if extending, merge descriptions. The same logic applies to edges: update confidence on existing edges, create new ones, flag contradictions. Every write stamps `derived_from_code_version` with the current git HEAD hash.

Staleness detection identifies concepts whose `derived_from_code_version` points to a commit that is no longer the latest for the referenced files. These concepts get the `stale` label. This feeds the priority engine's `staleness` factor.

**Acceptance Criteria:** New concepts are created correctly. Existing agent-created concepts are updated (not duplicated) when the librarian re-analyzes the same code. Human-created concepts are not overwritten by agent analysis. Contradictions are flagged and logged without silent overwrites. All writes carry the current git commit hash. Stale concepts are correctly identified.

**Estimated Scope:** Medium. The decision tree logic is moderately complex but well-defined. Most of the effort is in the edge cases (what counts as "contradiction" vs. "extension") and in testing the various paths.

---

### Epic 9: Priority Scoring & Metrics Engine

**Goal:** Implement the priority scoring system with adaptive modulation driven by a metrics feedback loop, so the librarian automatically focuses on whichever product metric is furthest below target.

**Prerequisites:** Epic 2 (Storage Layer) — the metrics engine queries the graph's state. This epic can be developed in parallel with Epics 7 and 8.

**Scope:** The base priority computation (six-factor weighted sum), the metrics engine (coverage, freshness, blast radius completeness), the adaptive modulation loop (deficit computation, weight boosting), the escalated item priority reduction, and the telemetry output that feeds the audit UI health dashboard.

**Key Stories:**

The metrics engine computes the three core product metrics from ERD §4.6. These must be efficient SQL queries, not full-table Python scans, because they run before every librarian iteration. Coverage is the percentage of source files referenced by at least one concept. Freshness is the percentage of concepts whose `last_verified` is more recent than the referenced code's last modification. Blast radius completeness is the percentage of concepts with a non-stale impact profile. Short-TTL caching (30 seconds) is acceptable.

Base priority computation implements the six-factor weighted sum from PRD §6.3. Each factor is computed per work item using data from the storage layer and git.

Adaptive modulation implements the feedback loop from PRD §6.3.1 and ERD §4.3.2. Before each iteration's work item selection, the engine: computes current metric values via the metrics engine, computes deficit for each metric (`max(0, target - current)`), applies modulation to effective weights (`base * (1 + deficit * modulation_strength)`), and for blast radius completeness, directly boosts `analyze_impact` items since this metric doesn't map to a weight factor. *(Note: `blast_radius_completeness` modulation is dormant until Epic 12 in Phase 3).* For escalated items, the final score is multiplied by the reduction factor (default: 0.5).

Telemetry output records the metric values, targets, deficits, effective weights, and selected work item per iteration. This data is stored and served to the audit UI's health dashboard.

**Acceptance Criteria:** When coverage is low and freshness is high, the librarian demonstrably selects `investigate_file` items over `verify_concept` items. When freshness drops (e.g., after a refactor), the librarian demonstrably pivots to `verify_concept` items. Escalated items receive lower effective priority than non-escalated items of similar base score. Setting `modulation_strength = 0.0` produces identical behavior to static weights. Metrics are computed efficiently (under 50ms on a 10,000-concept graph). Telemetry output is accurate and complete.

**Estimated Scope:** Medium. The math is well-defined but the integration with the librarian's selection loop requires careful testing. The metrics engine queries need to be efficient.

---

### Epic 10: Librarian Orchestrator

**Goal:** Implement the Ralph-Wiggum loop that autonomously builds semantic knowledge on top of the structural graph, wiring together the adapter, quality pipeline, knowledge manager, and priority engine into a functioning iteration cycle.

**Prerequisites:** Epics 6 (Adapters), 7 (Quality Pipeline), 8 (Knowledge Manager), and 9 (Priority & Metrics) must be substantially complete. This is an integration epic that connects the components the prior epics built.

**Scope:** The librarian loop execution logic from ERD §4.2.1, prompt template construction (including the failure-context-aware retry mode), response parsing, the token budget management system from ERD §4.8, and telemetry reporting.

**Key Stories:**

The loop orchestrator is the async function from S-1 that manages N concurrent iterations via `asyncio.gather`. Each iteration follows the 10-step sequence: read queue → select item (with adaptive priority) → load context → read code → formulate prompt (with failure feedback if retrying) → call LLM → Level 1 check → Level 1.5 review (if enabled) → integrate knowledge → mark resolved. The iteration is isolated — no state carried between iterations.

Prompt templates are model-specific (Anthropic vs. Ollama) and support the `with_failure_context` mode that incorporates previous failure records and co-regulation feedback into the prompt. The output schema instructs the LLM to return structured JSON: a list of concepts (name, description, confidence, code references), a list of relationships (source, target, edge type, confidence, rationale), and any labels.

Response parsing extracts structured knowledge from the LLM's response. It must handle the LLM returning JSON, JSON-in-markdown-fences, and gracefully fallback for models that don't produce clean structured output. Parsed output is validated against Pydantic models before reaching the quality pipeline.

Token budget management enforces per-iteration limits, per-run iteration limits, and per-run token limits. When co-regulation is enabled, per-iteration cost must be estimated as analysis_tokens + review_tokens. If only the analysis call fits within the remaining budget but the review call would exceed it, the iteration proceeds anyway (skipping the quality check to save tokens defeats its purpose). End-of-run telemetry reports total iterations, tokens (broken down by analysis vs. review), mutations, failures, and escalations.

**Acceptance Criteria:** `apriori librarian run` executes iterations against a real codebase using both the Anthropic and Ollama adapters. Each iteration produces semantic concept descriptions and relationship edges that are integrated into the graph through the full pipeline (quality → knowledge manager). Retry prompts include failure feedback from previous attempts. Token budget limits halt the loop at the configured ceiling. Telemetry output is accurate.

**Estimated Scope:** Large. This is the integration epic — it exposes all the seams between the components built in Epics 6–9. Most of the complexity is in prompt engineering, response parsing edge cases, and the budget management logic.

---

### Epic 11: Human Audit UI

**Goal:** Deliver the local web application for inspecting the knowledge graph, monitoring the librarian, reviewing concepts, and viewing health metrics.

**Prerequisites:** Epics 7 (Quality Pipeline — provides the activity feed and failure data), 8 (Knowledge Manager — provides the concepts and edges), and 9 (Metrics Engine — provides the health dashboard data). The UI can be developed in parallel with Epic 10 (Librarian Orchestrator) since it reads from the same SQLite database.

**Scope:** The backend REST API (FastAPI per S-1), the frontend SPA, and the five capabilities from PRD §8A.3: graph visualization, librarian activity feed, review workflow, health dashboard, and escalated items view.

**Spike Story (S-7): Audit UI Technology Selection.** Time-boxed at 4–6 hours. Build a prototype of the graph visualization with at least one frontend approach. Evaluate at 500 nodes: bundle size, load time, interaction latency, developer ergonomics. Key constraints: self-contained (no external CDN at runtime), no Node.js dependency for end users, maintainable by a Python-focused team. This must complete before frontend implementation begins.

**Key Stories:**

The backend API (FastAPI) implements the REST endpoints from ERD §4.7.2. Read endpoints: `GET /api/concepts`, `GET /api/concepts/{id}`, `GET /api/edges`, `GET /api/graph` (subgraph for visualization), `GET /api/activity` (librarian feed), `GET /api/health` (metrics + effective weights + queue depth), `GET /api/escalated`. Write endpoints (review actions only): `POST /api/concepts/{id}/verify`, `POST /api/concepts/{id}/correct`, `POST /api/concepts/{id}/flag`. The backend is a thin layer over the sync `KnowledgeStore` (called from async FastAPI handlers via `asyncio.to_thread()` per S-1). It reads from the same SQLite database the MCP server and librarian use.

The frontend technology is determined by S-7's findings. Regardless of technology choice, the frontend must implement: interactive node-and-edge graph visualization with filtering (by edge type, confidence, label, recency) and visual confidence distinction (opacity/color/line style); a chronological librarian activity feed showing work items processed, concepts created/updated, co-regulation scores, pass/fail, and failure reasons; the review workflow (view concept alongside code, verify, correct with error type, flag); the health dashboard showing current metric values vs. targets, effective priority weights, and work queue depth; and the escalated items view showing full failure history per item.

Server startup is via `apriori ui` (or `apriori-ui`). Runs on `127.0.0.1:8391` (configurable). No authentication needed (local-only). No internet required. No external data transmission.

**Acceptance Criteria:** `apriori ui` starts a local web server and serves the SPA. The graph visualization renders at least 500 nodes interactively (pan, zoom, click-to-inspect). The activity feed accurately reflects the librarian's recent work. The verify/correct/flag workflow correctly updates concepts and records review outcomes. The health dashboard shows accurate, current metric values. Escalated items display their full failure history.

**Estimated Scope:** Large. This is a full frontend deliverable. The graph visualization library selection (S-7) and integration is the most technically uncertain component. The backend API is straightforward, but the frontend requires UI/UX effort that may be outside the team's primary skill set.

---

## Phase 3: Blast Radius

Phase 3 delivers the flagship capability. It is a single epic because the components (three-layer impact computation, profile maintenance, and the MCP tool) are tightly coupled and difficult to deliver independently.

---

### Epic 12: Blast Radius & Impact Profiles

**Goal:** Deliver pre-computed, three-layer impact analysis so that agents and humans can query "what breaks if I change this?" in sub-second time.

**Prerequisites:** Phase 2 must be substantially complete — blast radius depends on both structural edges (Phase 1) and semantic edges (Phase 2) to produce meaningful multi-layer impact profiles.

**Scope:** The three-layer impact computation (structural, semantic, historical), impact profile storage on concept nodes, continuous profile maintenance, the `blast_radius` MCP tool, and the `blast-radius` CLI command.

**Spike Story (S-4): Blast Radius Validation Methodology.** Time-boxed at 2–3 hours. Design the test harness for measuring blast radius accuracy against historical PRs (>70% recall, >50% precision per PRD §9.1). Identify a suitable test repository with good PR history. Document the methodology. This should complete early in the epic to inform the acceptance testing approach.

**Key Stories:**

Structural impact computation walks the structural edge graph outward from the target concept via BFS. All entries have `confidence = 1.0`. This is deterministic, fast, and testable against the structural graph from Phase 1.

Semantic impact computation walks the semantic edge graph. Confidence is the product of edge confidences along the path. This captures the implicit coupling that structural analysis misses.

Historical impact computation analyzes git log for co-change patterns. This should be batched (analyze once, update all affected profiles) rather than per-concept. Confidence is proportional to co-change frequency with recency decay.

Impact profile maintenance keeps profiles current as the graph evolves: structural changes trigger immediate recomputation, semantic changes update as a librarian side effect, historical data refreshes automatically at the start of each librarian run. Stale profiles generate `analyze_impact` work items.

The `blast_radius` MCP tool is the query interface. It accepts a concept name/ID, file path, or function symbol, resolves to concept(s), and returns the pre-computed impact profile as a prioritized list sorted by composite score. The tool registers in the MCP server (updating the Phase 1 placeholder). The `blast-radius` CLI command wraps the same logic.

**Acceptance Criteria:** `blast_radius` returns correct profiles with all three layers when data is available. Confidence scoring is correct per layer (1.0 for structural, product-of-path for semantic, frequency-based for historical). Query latency is under 500ms at p95 on a 10,000-concept graph. Profiles are maintained continuously. Accuracy meets PRD targets when validated against historical PRs (per S-4 methodology).

**Estimated Scope:** Medium-large. The computation logic is well-defined. The git history analysis for historical impact is moderately complex. The maintenance system (keeping profiles current as the graph evolves) requires careful integration with the librarian and change detector.

---

## Phase 4: Polish & Scale

Phase 4 is a single epic that refines the system rather than adding new architectural components.

---

### Epic 13: Progressive Enrichment, CLI Completion & Documentation

**Goal:** Deliver the bootstrapping experience for large codebases, complete the CLI command set, and produce documentation sufficient for self-service adoption.

**Prerequisites:** All prior phases complete.

**Scope:** Progressive enrichment (prioritize developer-proximate files during bootstrap, respect budget), the remaining CLI commands (`librarian run/status`, `concept`, `validate`, `export`, `doctor`), and full documentation (README, config reference, MCP tool reference, architecture guide, model quality guide, audit UI guide).

**Key Stories:**

Progressive enrichment modifies the priority engine to heavily weight `developer_proximity` when coverage is below a threshold (e.g., 50%). Once coverage exceeds the threshold, revert to standard weights. Clear progress telemetry: "Analyzed 47/312 source files. Estimated remaining cost: ~$2.30."

CLI completion adds the remaining commands: `librarian run` with `--iterations` and `--budget` flags, `librarian status`, `concept <name>` (display full details), `validate` (integrity checks), `export` (full graph as JSON or YAML), and `doctor` (check tree-sitter, LLM connectivity, SQLite health, git integration, embedding model availability).

Documentation covers quick-start (README.md), every configuration option with defaults and effects, all 13 MCP tools with input/output schemas and examples, the four-layer architecture for new contributors, model quality recommendations with cost/quality/speed tradeoffs, and the audit UI user guide.

**Acceptance Criteria:** Progressive enrichment correctly prioritizes nearby files during bootstrap and stays within budget. All CLI commands work. `apriori doctor` validates the installation and reports issues clearly. A new user can go from zero to a queryable graph (structural) within 60 seconds and produce semantic concepts within 10 librarian iterations, guided solely by the documentation.

**Estimated Scope:** Medium. Spread across many small deliverables rather than one complex system.

---

## Epic Dependency Graph

```
Phase 1:
  Epic 1 (Models & Config)
    └─► Epic 2 (Storage Layer)  ←── S-5 spike
          ├─► Epic 3 (Structural Engine)  ←── S-3 spike
          │     └─► Epic 5 (CLI & First-Run)
          └─► Epic 4 (MCP Server)

Phase 2:
  Epic 6 (LLM Adapters)
    └─► Epic 7 (Quality Pipeline)  ←── S-8 spike
          └──────────────────────────────┐
  Epic 2 (Storage Layer)                 │
    ├─► Epic 8 (Knowledge Manager)       │
    │     └──────────────────────────────┤
    └─► Epic 9 (Priority & Metrics)      │
          └──────────────────────────────┤
                                         ▼
                                  Epic 10 (Librarian Orchestrator)
                                         │
  Epic 7 + 8 + 9 ──────────────► Epic 11 (Audit UI)  ←── S-7 spike

Phase 3:
  Phase 2 complete ─► Epic 12 (Blast Radius)  ←── S-4 spike

Phase 4:
  All prior ─► Epic 13 (Polish & Docs)
```

---

## Summary Table

| # | Epic | Phase | Prerequisites | Spikes | Est. Size |
|---|------|-------|---------------|--------|-----------|
| 1 | Data Models & Configuration | 1 | None | — | Small |
| 2 | Storage Layer | 1 | Epic 1 | S-5 | Large |
| 3 | Structural Engine | 1 | Epic 2 | S-3 | Medium-Large |
| 4 | MCP Server | 1 | Epic 2, 3 | — | Small-Medium |
| 5 | CLI & First-Run | 1 | Epic 2, 3, 4 | — | Small |
| 6 | LLM Adapter Layer | 2 | Epic 1 | — | Medium |
| 7 | Quality Assurance Pipeline | 2 | Epic 6, 2 | S-8 | Large |
| 8 | Knowledge Manager | 2 | Epic 2 | — | Medium |
| 9 | Priority & Metrics Engine | 2 | Epic 2 | — | Medium |
| 10 | Librarian Orchestrator | 2 | Epic 6, 7, 8, 9 | — | Large |
| 11 | Human Audit UI | 2 | Epic 7, 8, 9 | S-7 | Large |
| 12 | Blast Radius & Impact | 3 | Phase 2 | S-4 | Medium-Large |
| 13 | Polish & Documentation | 4 | All prior | — | Medium |

---

*This epic breakdown is a planning artifact. Epics should be decomposed into stories collaboratively between the engineering lead and the implementing developers at the start of each epic's active development period, not before. The "Key Stories" sections above identify natural decomposition points but are not prescriptive — the team doing the work should determine the right story boundaries based on their velocity, skill distribution, and working style.*
