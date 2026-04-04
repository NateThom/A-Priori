# A-Priori: Engineering Ingestion Plan — Full Story Decomposition

**Date:** 2026-04-03
**Source Documents:** PRD (2026-04-03), ERD v2 (2026-04-03), Epic Breakdown (2026-04-03)
**Status:** Ready for engineering review

---

## Part 1: Epic-Level Dependency Map

Before decomposing into stories, this section captures the inter-epic dependency structure that governs sequencing and parallelization decisions. The dependency graph from the epics document is accurate and reproduced here with annotations about what specifically flows between epics.

### Phase 1 Dependency Chain

Epic 1 (Models & Config) produces the Pydantic model definitions and the typed configuration object. Every other module in the system imports from these. There are no meaningful parallelization opportunities until Epic 1 is complete.

Epic 2 (Storage Layer) depends on Epic 1 because it persists and retrieves those models. It is the largest Phase 1 epic and the most architecturally significant — nothing can write to or read from the knowledge graph until the KnowledgeStore protocol and at least one implementation exist. The S-5 spike (YAML performance at scale) should start on day one of this epic because its findings may change the YAML file layout.

Epic 3 (Structural Engine) and Epic 4 (MCP Server) both depend on Epic 2, and they can be developed **in parallel** once Epic 2 is substantially complete (protocol defined + SQLite implementation working). Epic 3 writes structural concepts/edges through the store. Epic 4 reads from the store and exposes it via MCP.

Epic 5 (CLI & First-Run) depends on Epics 2, 3, and 4 — it orchestrates their functionality into the `apriori init` experience.

### Phase 2 Dependency Structure

Epic 6 (LLM Adapters) depends only on Epic 1 (the adapter returns types defined in the models layer). It can start as soon as Epic 1 is done, even while Phase 1's later epics are still in progress.

Epics 7 (Quality Pipeline), 8 (Knowledge Manager), and 9 (Priority & Metrics) can all be developed **in parallel** once Epic 6 and Epic 2 are available. This is the major parallelization opportunity in the project.

Epic 10 (Librarian Orchestrator) is the integration epic — it wires together Epics 6, 7, 8, and 9. It cannot begin until all four are substantially complete.

Epic 11 (Audit UI) depends on Epics 7, 8, and 9 for the data it displays. It can be developed in parallel with Epic 10 since both read from the same SQLite database.

### Phase 3 and 4

Epic 12 (Blast Radius) requires Phase 2 to be substantially complete — it needs both structural and semantic edges.

Epic 13 (Polish & Docs) is the capstone — it requires all prior phases.

### Critical Path

The critical path through the project is: **Epic 1 → Epic 2 → Epic 3 → Epic 10 → Epic 12 → Epic 13**. Any delay on these epics delays the entire project. Epics 4, 5, 6, 7, 8, 9, and 11 have varying degrees of parallelization flexibility.

### Shared Foundations

Three components are consumed by nearly everything downstream and represent bottleneck risks if they slip or change significantly:

1. **The Pydantic models** (Epic 1) — imported by every layer.
2. **The KnowledgeStore protocol** (Epic 2) — the interface every reader/writer codes against.
3. **The LLMAdapter protocol** (Epic 6) — the interface both the librarian and co-regulation review use.

---

## Part 2: Story Decomposition

Each story below follows this structure:

- **Title** — descriptive enough to stand alone on a board.
- **Story statement** — "As a [persona], I want [capability] so that [value]."
- **Context** — where this fits in the epic and what PRD/ERD sections it traces to.
- **Acceptance criteria** — testable conditions in Given/When/Then format.
- **Technical notes** — implementation guidance that informs but does not constrain.
- **Definition of done** — what must be true beyond just the acceptance criteria.
- **Intra-epic dependencies** — which other stories within this epic must precede this one.

---

## Phase 1: Foundation

---

### Epic 1: Data Models & Configuration

**Epic goal:** Establish the shared data vocabulary and configuration system.
**PRD sections:** §5.1–5.6, §2.3 (config)
**ERD sections:** §3.1.1–3.1.7, §2.3

---

#### Story 1.1: Concept and CodeReference Pydantic Models

**As a** developer implementing the storage layer, **I want** validated Pydantic models for Concept and CodeReference **so that** every module in the system works against a single, well-validated schema definition with clear serialization contracts.

**Context:** The Concept node is the fundamental unit of knowledge in the graph. CodeReference is embedded within Concept and implements the repair chain (symbol → content_hash → semantic_anchor). These are the most-imported models in the entire codebase — every layer references them. PRD §5.1, §5.2; ERD §3.1.1, §3.1.2.

**Acceptance Criteria:**

- Given a valid set of Concept fields, when a Concept is instantiated, then the `id` field auto-generates a UUID4 and `created_at`/`updated_at` are set to the current timestamp.
- Given a confidence value of 1.5, when a Concept is instantiated, then Pydantic raises a ValidationError with a message indicating the value must be between 0.0 and 1.0.
- Given a confidence value of -0.1, when a Concept is instantiated, then Pydantic raises a ValidationError.
- Given a `created_by` value of "system", when a Concept is instantiated, then Pydantic raises a ValidationError indicating the value must be "agent" or "human".
- Given a Concept with two CodeReferences, when the Concept is serialized to JSON and deserialized back, then the round-tripped object is identical to the original (all fields, including nested CodeReferences, match exactly).
- Given a Concept with two CodeReferences, when the Concept is serialized to YAML and deserialized back, then the round-tripped object is identical to the original.
- Given a CodeReference with `content_hash` as a 64-character hex string, when instantiated, then validation passes. Given a non-hex string, then validation fails.

**Technical Notes:** `content_hash` uses SHA-256 (64-character hex). `labels` is `set[str]`, not validated against a vocabulary at the model level (labels are extensible). The initial label set (`needs-review`, `auto-generated`, `deprecated`, `verified`, `stale`, `needs-human-review`) should be documented as constants but not enforced by the model. `derived_from_code_version` is a nullable 40-character hex string (git commit hash).

**Definition of Done:** Models implemented with full Pydantic validation. JSON and YAML round-trip tests pass. Invalid input tests cover all constrained fields. Code reviewed and merged.

**Intra-epic dependencies:** None. This is the first story.

---

#### Story 1.2: Edge Model and Edge Type Vocabulary

**As a** developer implementing the storage or structural engine, **I want** a validated Edge model and a loadable edge type vocabulary **so that** all relationship data is typed against a controlled vocabulary and edges with invalid types are rejected at creation time.

**Context:** Edges are directed relationships between concepts. The edge type vocabulary is organized into three categories (structural, semantic, historical) and loaded from configuration. PRD §5.3, §5.4; ERD §3.1.3.

**Acceptance Criteria:**

- Given valid source/target UUIDs and an edge type of "calls", when an Edge is instantiated, then it succeeds with `evidence_type` accepted as "structural", "semantic", or "historical".
- Given an edge type of "made-up-type", when validated against the vocabulary, then validation fails with a clear message listing valid types.
- Given the default `apriori.config.yaml`, when the edge type vocabulary is loaded, then it contains exactly the 12 edge types defined in PRD §5.4 (4 structural, 7 semantic, 1 historical).
- Given a user-extended config adding a custom edge type, when the vocabulary is loaded, then the custom type is included alongside the defaults.
- Given a confidence of 0.5 and evidence_type of "structural", when an Edge is serialized to JSON and back, then the round-trip is lossless.

**Technical Notes:** The `UNIQUE(source, target, edge_type)` constraint is enforced at the storage layer, not the model layer. The model only validates field types and ranges. The vocabulary is defined in config and loaded by the configuration system (Story 1.5), so this story depends on Story 1.5 being at least partially complete or uses a hardcoded fallback for testing.

**Definition of Done:** Edge model with full validation. Edge type vocabulary loader implemented. Round-trip serialization tests pass. Invalid edge type rejection tested.

**Intra-epic dependencies:** Story 1.1 (Concept must exist for edge source/target type references). Partial dependency on Story 1.5 (config loading for vocabulary), but can use hardcoded defaults for initial development.

---

#### Story 1.3: WorkItem and FailureRecord Models

**As a** developer implementing the librarian or quality pipeline, **I want** validated WorkItem and FailureRecord models with all failure-tracking fields **so that** the work queue, failure breadcrumbs, and escalation state are well-defined from day one and the SQLite schema doesn't need migration later.

**Context:** WorkItems are transient operational state (SQLite-only, not dual-written to YAML). FailureRecord is embedded in WorkItem and captures the diagnostic context of a failed librarian iteration. These models are defined in Phase 1 but exercised in Phase 2. PRD §5.6; ERD §3.1.4, §3.1.5.

**Acceptance Criteria:**

- Given a valid WorkItem with `item_type = "investigate_file"`, when instantiated, then it succeeds with `failure_count = 0`, `failure_records = []`, `escalated = False`, and `resolved = False`.
- Given an `item_type` of "invalid_type", when instantiated, then Pydantic raises a ValidationError listing the six valid types.
- Given a WorkItem, when a FailureRecord is appended to its `failure_records` list, then the record includes `attempted_at`, `model_used`, `prompt_template`, and `failure_reason` as required fields.
- Given a FailureRecord with `quality_scores = {"specificity": 0.2, "structural_corroboration": 0.8, "completeness": 0.4}`, when serialized to JSON, then all scores round-trip without loss.
- Given a WorkItem with `failure_count = 3` and `escalated = False`, when serialized and deserialized, then both fields are preserved correctly (escalation logic is not in the model — it's in the quality pipeline).

**Technical Notes:** The six valid `item_type` values are: `investigate_file`, `verify_concept`, `evaluate_relationship`, `reported_gap`, `review_concept`, `analyze_impact`. `priority_score` is a computed float — it's stored on the model but recalculated fresh by the priority engine before each librarian iteration. `failure_records` is a `list[FailureRecord]` stored as a JSON array in SQLite.

**Definition of Done:** WorkItem and FailureRecord models implemented. All six item types validated. Serialization round-trip tests pass. Invalid input rejection tests for all constrained fields.

**Intra-epic dependencies:** Story 1.1 (WorkItem references `concept_id` which is a Concept UUID).

---

#### Story 1.4: Quality and Review Models

**As a** developer implementing the quality pipeline or audit UI, **I want** validated CoRegulationAssessment and ReviewOutcome models **so that** the data structures for the co-regulation review output and human review actions are defined consistently and available for Phase 2 implementation.

**Context:** These models are small and self-contained. CoRegulationAssessment captures the output of the Level 1.5 co-regulation review. ReviewOutcome captures a human reviewer's action from the Level 2 audit UI. Both are Phase 2 concerns but are defined here to keep the model layer complete. ERD §3.1.6, §3.1.7.

**Acceptance Criteria:**

- Given specificity, structural_corroboration, and completeness scores all at 0.7 with a pass threshold of 0.5/0.3/0.4, when a CoRegulationAssessment is instantiated, then `composite_pass` is True.
- Given a specificity score of 0.3 (below the 0.5 threshold), when the composite is computed, then `composite_pass` is False.
- Given a ReviewOutcome with `action = "corrected"` and `error_type = "relationship_missing"`, when instantiated, then validation passes.
- Given a ReviewOutcome with `action = "verified"` and an `error_type` set, when instantiated, then validation raises an error (error_type is only populated when action is "corrected").
- Given a ReviewOutcome with `action = "corrected"` and no `error_type`, when instantiated, then validation raises an error (error_type is required for corrections).

**Technical Notes:** The five valid `error_type` values for ReviewOutcome are: `description_wrong`, `relationship_missing`, `relationship_hallucinated`, `confidence_miscalibrated`, `other`. The composite pass/fail thresholds for CoRegulationAssessment should be configurable, with defaults from ERD §3.1.6 (0.5, 0.3, 0.4).

**Definition of Done:** Both models implemented with validation. Conditional validation logic for ReviewOutcome (error_type required only on correction) working. Serialization round-trips pass.

**Intra-epic dependencies:** None (self-contained models).

---

#### Story 1.5: Configuration System

**As a** user setting up A-Priori for the first time, **I want** a configuration system that produces sensible defaults with zero configuration **so that** I can start using the tool immediately and customize behavior later as I understand my needs.

**Context:** The configuration system loads `apriori.config.yaml`, merges with hardcoded defaults, validates all values, and exposes a typed configuration object. It governs LLM provider settings, librarian settings, adaptive modulation parameters, quality thresholds, storage paths, structural engine settings, the edge type vocabulary, impact profile settings, and audit UI settings. PRD §2.3; ERD §2.3.

**Acceptance Criteria:**

- Given no `apriori.config.yaml` file, when the configuration is loaded, then all defaults are applied and the resulting typed config object has valid values for every setting.
- Given a config file with only `llm.provider: anthropic` and `llm.api_key_env: ANTHROPIC_API_KEY`, when loaded, then all other settings use defaults and the config is valid.
- Given a config file with `librarian.modulation_strength: 0.0`, when loaded, then adaptive modulation is effectively disabled (the value is accepted as valid).
- Given a config file with `quality.co_regulation.enabled: false`, when loaded, then co-regulation is disabled.
- Given a config file with an invalid value like `librarian.base_weights.staleness: 2.0` (weights should sum to 1.0 or be normalizable), when loaded, then the system either normalizes or raises a clear validation error.
- Given a config file with `edge_types` containing a custom type, when loaded, then the custom type is appended to the default vocabulary (not replacing it).

**Technical Notes:** API keys are referenced by environment variable name (e.g., `llm.api_key_env: ANTHROPIC_API_KEY`), never stored in the config file. The six default base priority weights must sum to 1.0: staleness (0.25), needs_review (0.20), coverage_gap (0.15), git_activity (0.10), semantic_delta (0.10), developer_proximity (0.20). The config module should expose a single `load_config(path: Path | None) -> Config` function and a `Config` typed object (dataclass or Pydantic model) for attribute-style access.

**Definition of Done:** Config loader implemented. Default config produces a valid, fully-populated typed object. Override merging works correctly. Validation catches invalid values with clear messages. Unit tests cover: no config file, partial config, full config, invalid values.

**Intra-epic dependencies:** None (can be developed in parallel with the models, but the edge type vocabulary in Story 1.2 will consume it).

---

### Epic 2: Storage Layer

**Epic goal:** Implement KnowledgeStore protocol with SQLite, YAML, and dual writer.
**PRD sections:** §4.3
**ERD sections:** §3.2.1–3.2.4

---

#### Story 2.1: Spike — YAML Performance at Scale (S-5)

**As a** technical lead, **I want** to validate YAML flat file performance at 10,000 concepts **so that** we make an informed decision about directory layout before implementing the YAML store.

**Context:** The YAML store uses one file per concept and one per edge. At 10,000 concepts with a proportional number of edges, the `.apriori/concepts/` directory could contain 10,000+ files. Some file systems degrade with flat directories of this size. S-5 spike; ERD §3.2.3.

**Acceptance Criteria:**

- Given 10,000 synthetic concept YAML files in a flat directory, when directory listing is performed, then the time is measured and documented.
- Given 10,000 YAML files, when `rebuild_index` is simulated (read all, parse all, insert into SQLite), then the time is measured and documented.
- Given the measurements, when performance is unacceptable (>30s for rebuild), then a nested directory structure is designed (e.g., first 2 characters of slug as subdirectory) and retested.
- The spike produces a written decision document (≤1 page) with the measurement data and the chosen directory layout.

**Technical Notes:** Time-box: 2–3 hours. Use `os.listdir()` and `pathlib.glob()` to measure. Generate YAML files with realistic sizes (500–2000 bytes per concept). Test on the target development OS.

**Definition of Done:** Decision document written. Directory layout decided. Findings communicated to the team.

**Intra-epic dependencies:** None. This is the first story in the epic.

---

#### Story 2.2: KnowledgeStore Protocol Definition

**As a** developer working on any layer of A-Priori, **I want** a complete, well-documented protocol definition for the KnowledgeStore **so that** I can code against the interface without depending on a specific implementation and future backend swaps require zero changes to my code.

**Context:** The KnowledgeStore protocol is the most important interface in the system. It defines the contract for all data operations. Both the SQLite implementation and the dual writer must satisfy it identically. ERD §3.2.1.

**Acceptance Criteria:**

- Given the protocol definition, when a developer reads it, then every method has a clear docstring specifying its parameters, return type, error behavior, and any side effects.
- Given the protocol, when it is checked for completeness against ERD §3.2.1, then it includes all operation categories: Concept CRUD, Edge CRUD, Work Item operations (including `record_failure`, `escalate_work_item`, `get_escalated_items`), Review Outcome operations, Search (semantic, keyword, by-file), Graph traversal, Metrics, and Bulk operations (`rebuild_index`).
- Given the protocol, when inspected, then all methods are synchronous `def` (per S-1 decision).
- Given the protocol, when a write method is called, then it returns the created/updated entity (not just a success flag).

**Technical Notes:** Use Python's `typing.Protocol` for structural subtyping. The protocol should have approximately 25–30 methods organized by category. Include type annotations for all parameters and return values using the models from Epic 1.

**Definition of Done:** Protocol class defined with full type annotations and docstrings. Reviewed by at least one other developer for completeness and clarity.

**Intra-epic dependencies:** Epic 1 complete (the protocol references Concept, Edge, WorkItem, ReviewOutcome types).

---

#### Story 2.3: SQLite Schema and Base CRUD Implementation

**As a** developer, **I want** a working SQLite implementation of the KnowledgeStore protocol with the full schema and basic CRUD operations **so that** concepts, edges, work items, and review outcomes can be persisted and retrieved.

**Context:** The SQLite store is the query-performance backbone. It implements the full schema from ERD §3.2.2 including tables for concepts, edges, work items, review outcomes, FTS5 for keyword search, and the vec0 table for vector search. This story covers schema creation, CRUD operations, and connection management. ERD §3.2.2.

**Acceptance Criteria:**

- Given a new SQLite database, when the store is initialized, then all tables, indexes, and virtual tables (FTS5, vec0) are created with the correct schema.
- Given the database, when WAL mode and foreign keys are checked, then both are enabled (`PRAGMA journal_mode` returns `wal`, `PRAGMA foreign_keys` returns `1`).
- Given a Concept object, when `create_concept` is called, then the concept is inserted and the method returns the created Concept with all fields populated.
- Given an existing concept, when `update_concept` is called with a modified description, then the concept's description and `updated_at` are updated in the database.
- Given a concept with edges, when `delete_concept` is called, then the concept and all its edges are removed (CASCADE).
- Given an Edge referencing a non-existent concept, when `create_edge` is called, then a referential integrity error is raised.
- Given a WorkItem, when `record_failure` is called with a FailureRecord, then the record is appended to `failure_records` JSON array and `failure_count` is incremented.
- Given a WorkItem with `failure_count = 2` and escalation threshold of 3, when `record_failure` is called, then `failure_count` becomes 3 but `escalated` remains False (escalation is a separate call).
- Given a WorkItem, when `escalate_work_item` is called, then `escalated` is set to True.
- Given multiple threads reading concurrently, when the store is accessed, then no locking errors occur (WAL mode enables concurrent reads).

**Technical Notes:** Connection management must be thread-safe — use per-thread connections (thread-local pattern or a simple pool) per S-1 decision. The `failure_records` column is `TEXT NOT NULL DEFAULT '[]'` storing a JSON array. The `UNIQUE(source, target, edge_type)` constraint on edges prevents duplicate relationships. All timestamps stored as ISO 8601 text strings. The vec0 table uses `FLOAT[768]` dimensions per S-2 decision.

**Definition of Done:** Full schema creation. All CRUD operations for all four entity types. Connection pooling working. Thread safety verified. Unit tests for every CRUD method including edge cases (duplicate names, referential integrity violations, concurrent access).

**Intra-epic dependencies:** Story 2.2 (protocol definition to implement against).

---

#### Story 2.4: EmbeddingService Implementation

**As a** developer implementing semantic search, **I want** an EmbeddingService that wraps `sentence-transformers` with the `e5-base-v2` model **so that** concept embeddings can be generated for storage and query embeddings can be generated for similarity search.

**Context:** Per S-2 spike decision, the system uses `intfloat/e5-base-v2` via `sentence-transformers` for local embedding generation. This produces 768-dimensional vectors. The model is ~440MB and is downloaded on first use to `~/.cache/huggingface/`. ERD §3.2.2 (embedding table); S-2 findings.

**Acceptance Criteria:**

- Given the EmbeddingService is initialized, when the model is not cached, then it downloads and caches the model with a clear progress message.
- Given a concept description string, when `generate_embedding` is called, then it returns a 768-dimensional float array.
- Given two semantically similar descriptions ("payment validation logic" and "validates payment amounts"), when embeddings are generated and cosine similarity computed, then similarity is above 0.7.
- Given two unrelated descriptions ("payment validation" and "user authentication"), when cosine similarity is computed, then similarity is below the similar-pair threshold.
- Given the e5-base-v2 model requirement for "query: " and "passage: " prefixes, when embeddings are generated for a search query vs. a stored concept, then the correct prefix is applied automatically.

**Technical Notes:** e5-base-v2 requires input prefixes: "query: " for search queries and "passage: " for documents being stored. The service should abstract this so callers don't need to know about prefixes. Model loading takes 2–5 seconds and should happen once at service initialization, not per-embedding call. The service is initialized at `SqliteStore` construction time.

**Definition of Done:** EmbeddingService implemented with proper prefix handling. Model download with progress indication. Embedding generation verified for correctness. Performance measured (should be <50ms per embedding after model load).

**Intra-epic dependencies:** None (can be developed in parallel with Story 2.3).

---

#### Story 2.5: SQLite Vector Search and FTS5 Integration

**As an** AI coding agent querying the knowledge graph, **I want** semantic vector search and keyword text search **so that** I can find relevant concepts by meaning (not just exact name) and by keyword matching in descriptions.

**Context:** This story wires the EmbeddingService into the SQLite store so that concept creation/update automatically generates embeddings, and implements the `search_semantic` and `search_keyword` methods on the store. ERD §3.2.2.

**Acceptance Criteria:**

- Given a concept is created via `create_concept`, when the concept is stored, then an embedding is automatically generated and inserted into the `concept_embeddings` vec0 table.
- Given a concept's description is updated, when `update_concept` is called, then the embedding is regenerated and updated.
- Given 100 stored concepts, when `search_semantic` is called with a natural language query, then results are returned ranked by cosine similarity with the most relevant concepts first.
- Given a query "payment validation", when `search_semantic` is called, then concepts related to payments appear before unrelated concepts.
- Given a keyword query "authentication", when `search_keyword` is called, then concepts whose name or description contain "authentication" are returned via FTS5.
- Given a concept is deleted, when `delete_concept` is called, then its embedding is also removed from the vec0 table.

**Technical Notes:** FTS5 content sync: use `content='concepts'` with `content_rowid='rowid'` triggers to keep the FTS index synchronized. For vec0, use `vec_distance_cosine()` for similarity queries. The `search_semantic` method accepts a pre-computed query embedding (generated by calling `EmbeddingService.embed_query()`), not raw text — the caller is responsible for embedding the query.

**Definition of Done:** Automatic embedding generation on concept create/update. Vector similarity search returning ranked results. FTS5 keyword search working. Deletion cleanup verified. Integration tests with realistic concept data.

**Intra-epic dependencies:** Story 2.3 (SQLite store base), Story 2.4 (EmbeddingService).

---

#### Story 2.6: YAML Flat File Store Implementation

**As a** user who wants to version-control their knowledge graph, **I want** concepts and edges persisted as human-readable YAML files **so that** the knowledge graph is inspectable, portable, and can be committed to git alongside the codebase.

**Context:** The YAML store is the authoritative source of truth. It writes one YAML file per concept (slugified name) and one per edge (UUID). Work items, review outcomes, and failure records are NOT written to YAML — they are SQLite-only operational state. ERD §3.2.3.

**Acceptance Criteria:**

- Given a concept named "Payment Validation", when it is saved, then a file `.apriori/concepts/payment-validation.yaml` is created with all concept fields.
- Given two concepts with names that would slugify identically, when both are saved, then the second receives a numeric suffix (e.g., `payment-validation-2.yaml`) and no data is lost.
- Given an edge, when it is saved, then a file `.apriori/edges/{uuid}.yaml` is created.
- Given a WorkItem, when a save is attempted to YAML, then the operation is skipped (work items are SQLite-only).
- Given a concept YAML file, when read and deserialized, then the resulting Concept object is identical to the original.
- Given the directory layout decision from S-5, when the YAML store is initialized, then it creates the directory structure accordingly (flat or nested).

**Technical Notes:** Use PyYAML for serialization. Slugification should be deterministic: lowercase, hyphens for spaces, strip special characters. The slug-to-filename mapping must be deterministic and documented. Edge YAML files use the edge's UUID as the filename since edges don't have human-readable names.

**Definition of Done:** YAML store implemented for concepts and edges. Slug collision handling working. SQLite-only entities correctly excluded. Round-trip serialization tests pass. Directory layout follows S-5 decision.

**Intra-epic dependencies:** Story 2.1 (S-5 spike for directory layout decision), Story 2.2 (protocol to implement against).

---

#### Story 2.7: Dual Writer Implementation

**As a** developer using the storage layer, **I want** a single KnowledgeStore implementation that transparently coordinates writes to both SQLite and YAML **so that** I don't need to manage two backends manually and data consistency is maintained automatically.

**Context:** The dual writer implements the KnowledgeStore protocol by delegating to both backends. It is the primary store used by all other modules. Write order: YAML first (authoritative), SQLite second (acceleration). SQLite failure is logged but does not roll back YAML. Reads served from SQLite. Work items and review outcomes are SQLite-only. ERD §3.2.4.

**Acceptance Criteria:**

- Given a concept is created through the dual writer, when the operation completes, then the concept exists in both SQLite and YAML.
- Given a concept is updated through the dual writer, when the operation completes, then both stores reflect the update.
- Given a SQLite write failure (simulated), when a concept is created, then the YAML write succeeds, a warning is logged, and the method does not raise an exception.
- Given a work item is created through the dual writer, when the operation completes, then it exists only in SQLite (no YAML file created).
- Given a review outcome is recorded, when the operation completes, then it exists only in SQLite.
- Given all reads, when any query method is called, then it is served from SQLite (not by scanning YAML files).

**Technical Notes:** The dual writer composes a `SqliteStore` and a `YamlStore` internally. It should implement the full KnowledgeStore protocol. The SQLite failure tolerance means the dual writer must catch SQLite exceptions on write and log them without propagating.

**Definition of Done:** Dual writer implemented and passing the protocol test suite (Story 2.9). Write coordination verified. SQLite failure tolerance tested. Read delegation to SQLite confirmed.

**Intra-epic dependencies:** Story 2.3 (SQLite store), Story 2.5 (vector/FTS), Story 2.6 (YAML store).

---

#### Story 2.8: Rebuild-Index Operation

**As a** user whose SQLite index has become corrupted or out of sync, **I want** to rebuild the entire SQLite database from the authoritative YAML files **so that** I can recover to a known-good state without losing any knowledge.

**Context:** The YAML files are the source of truth. `rebuild_index` reads all YAML files, deserializes them, regenerates embeddings, and upserts into a fresh SQLite database. It must be idempotent. ERD §3.2.4.

**Acceptance Criteria:**

- Given a set of concept and edge YAML files, when `rebuild_index` is run, then a new SQLite database is created with all concepts, edges, embeddings, and FTS5 entries matching the YAML data.
- Given the rebuilt database, when any query is run, then results match what was in the YAML files exactly.
- Given `rebuild_index` is run twice consecutively, when the second run completes, then the database state is identical to after the first run (idempotent).
- Given 1,000 concept YAML files, when `rebuild_index` is run, then it completes within a reasonable time (target: under 60 seconds including embedding regeneration).
- Given `rebuild_index` is invoked, when it runs, then it reports progress ("Rebuilding: 450/1000 concepts processed...").

**Technical Notes:** Embedding regeneration via the EmbeddingService is the bottleneck for large rebuilds. Consider batching embeddings. The operation should create a new SQLite file and swap it in atomically (write to temp file, then rename) to avoid corrupting the active database if the rebuild is interrupted.

**Definition of Done:** Rebuild operation working end-to-end. Idempotency verified. Progress reporting implemented. Atomic file swap implemented. Performance acceptable at scale.

**Intra-epic dependencies:** Story 2.7 (dual writer, which composes both stores).

---

#### Story 2.9: Protocol Test Suite

**As a** developer maintaining the storage layer, **I want** a comprehensive test suite written against the KnowledgeStore protocol **so that** both the SQLite implementation and the dual writer can be verified against identical expectations and any future backend passes the same tests.

**Context:** This is the highest-priority testing target in the entire project. The suite must exercise every protocol method with both valid and invalid inputs, including the failure-tracking methods and review outcome methods that Phase 2 will exercise. ERD §3.2.1.

**Acceptance Criteria:**

- Given the test suite, when run against the SQLite store implementation, then all tests pass.
- Given the test suite, when run against the dual writer implementation, then all tests pass.
- Given the test suite, when a new backend implementation is added, then it can be plugged in with zero test modifications (tests are parameterized by implementation).
- Given the test suite, when reviewed for coverage, then every protocol method has at least one positive test and one negative/edge-case test.

**Technical Notes:** Use pytest fixtures with parameterization: `@pytest.fixture(params=[SqliteStore, DualWriter])`. The suite should cover: CRUD for all entities, search (semantic and keyword), graph traversal, work item lifecycle (create → fail → fail → fail → escalate), review outcome recording, metrics queries, and rebuild-index.

**Definition of Done:** Test suite implemented and passing against both implementations. Suite is parameterized for future backends. Coverage report confirms all protocol methods are tested.

**Intra-epic dependencies:** Story 2.7 (both implementations must exist to test against).

---

### Epic 3: Structural Engine

**Epic goal:** Parse source code, build structural graph, detect changes.
**PRD sections:** §4.1 (Layer 0)
**ERD sections:** §3.3.1–3.3.3

---

#### Story 3.1: Spike — Tree-sitter Grammar Quality (S-3)

**As a** technical lead, **I want** to validate tree-sitter's extraction quality for Python and TypeScript **so that** we know exactly what edge cases and gaps exist before implementing language-specific parsers.

**Context:** Tree-sitter grammars vary in quality. This spike parses diverse real-world code and manually verifies extraction completeness. S-3 spike; ERD §3.3.

**Acceptance Criteria:**

- Given diverse Python files (decorators, nested classes, async functions, generators, `*args/**kwargs`, property methods), when parsed with tree-sitter-python, then extraction gaps are identified and documented.
- Given diverse TypeScript files (JSX/TSX, re-exports, barrel files, generic types, decorators, namespace imports), when parsed with tree-sitter-typescript, then gaps are identified and documented.
- The spike produces a written document listing: what is extracted correctly, what is missing, what is partially extracted, and proposed workarounds for gaps.

**Technical Notes:** Time-box: 3–4 hours. Focus on extraction of functions, classes, modules, imports, calls, and inheritance. Test against real-world open-source repositories (e.g., a FastAPI project for Python, a Next.js project for TypeScript).

**Definition of Done:** Gap analysis document written. Workarounds proposed. Findings shared with team.

**Intra-epic dependencies:** None. First story in the epic.

---

#### Story 3.2: Parsing Orchestrator

**As a** developer running `apriori init`, **I want** a file-tree walker that respects include/exclude patterns and dispatches each file to the correct language parser **so that** the structural engine processes only relevant source files efficiently.

**Context:** The orchestrator walks the repository, determines language by extension, loads the appropriate tree-sitter grammar, and delegates to language-specific parsers. It respects glob patterns from configuration. ERD §3.3.1.

**Acceptance Criteria:**

- Given a repository with `.py`, `.ts`, `.tsx`, `.js`, and `.md` files, when the orchestrator runs, then only the source files matching configured include patterns are processed.
- Given a `.gitignore`-excluded directory like `node_modules/`, when the orchestrator runs, then those files are skipped.
- Given a file with an unrecognized extension, when encountered, then it is skipped with a debug log message.
- Given a file larger than the configured max file size, when encountered, then it is skipped with a warning.
- Given 100 source files, when the orchestrator processes them, then total wall-clock time is under 100 seconds (sub-second per file per PRD §4.1).

**Technical Notes:** Language detection by extension: `.py` → Python, `.ts`/`.tsx` → TypeScript, `.js`/`.jsx` → JavaScript (use TypeScript parser). The orchestrator should yield `(file_path, language, parse_result)` tuples for downstream processing by the graph builder.

**Definition of Done:** Orchestrator traverses file tree correctly. Include/exclude globs working. Language dispatch working. Performance verified at sub-second per file.

**Intra-epic dependencies:** Story 3.1 (S-3 spike findings inform what to expect from parsers).

---

#### Story 3.3: Python Language Parser

**As a** user analyzing a Python codebase, **I want** accurate extraction of functions, classes, imports, and their relationships from Python source files **so that** the structural knowledge graph correctly represents the codebase's structure.

**Context:** The Python parser uses tree-sitter-python to extract structural entities from `.py` files. It must handle Python-specific patterns identified in the S-3 spike. ERD §3.3.1.

**Acceptance Criteria:**

- Given a Python file with top-level functions, when parsed, then each function is extracted with name, parameters, return type annotation (if present), line range, and file path.
- Given a Python file with a class, when parsed, then the class is extracted with name, base classes, and methods, and `inherits` relationships are identified.
- Given `from module import func`, when parsed, then an import relationship from the current module to `module.func` is recorded.
- Given `import module`, when parsed, then an import of the full module is recorded.
- Given a function that calls `other_module.some_function()`, when parsed, then a `calls` relationship is identified.
- Given a decorated function (e.g., `@app.route`, `@property`), when parsed, then the function is still extracted correctly.
- Given an async function (`async def`), when parsed, then it is extracted identically to a synchronous function.

**Technical Notes:** The common interface that all language parsers implement should be defined before this story begins (could be a simple Protocol or ABC with methods like `extract_entities(tree, file_path) -> ParseResult`). The `ParseResult` should contain lists of functions, classes, modules, and relationships.

**Definition of Done:** Python parser extracting all entity types correctly. All S-3 identified patterns handled or documented as known limitations. Unit tests against a curated set of Python files covering all patterns.

**Intra-epic dependencies:** Story 3.2 (orchestrator that dispatches to this parser).

---

#### Story 3.4: TypeScript Language Parser

**As a** user analyzing a TypeScript codebase, **I want** accurate extraction of functions, classes, imports, and their relationships from TypeScript/JavaScript files **so that** the structural graph covers both supported languages.

**Context:** The TypeScript parser handles `.ts`, `.tsx`, `.js`, and `.jsx` files. TypeScript has unique patterns (interfaces, type aliases, re-exports, barrel files, JSX) identified in S-3. ERD §3.3.1.

**Acceptance Criteria:**

- Given a TypeScript file with exported functions, when parsed, then each function is extracted with name, parameter types, return type, line range, and file path.
- Given a TypeScript class with `extends`, when parsed, then `inherits` relationships are identified.
- Given `import { Foo } from './module'`, when parsed, then an import relationship is recorded.
- Given a barrel file (`export * from './submodule'`), when parsed, then re-exports are tracked.
- Given a `.tsx` file with JSX, when parsed, then functions and components are extracted without the JSX confusing the parser.
- Given a TypeScript interface, when parsed, then it is extracted as a structural entity (similar to a class without implementation).

**Technical Notes:** Use `tree-sitter-typescript` which includes both TypeScript and TSX grammars. The parser implements the same common interface as the Python parser.

**Definition of Done:** TypeScript parser extracting all entity types. JSX/TSX handled. Re-exports tracked. Unit tests against curated TypeScript files.

**Intra-epic dependencies:** Story 3.2 (orchestrator), same common parser interface as Story 3.3.

---

#### Story 3.5: Graph Builder

**As a** user running `apriori init`, **I want** parse results automatically converted into concept nodes and structural edges in the knowledge graph **so that** the structural graph is populated without any manual steps.

**Context:** The graph builder takes parse results and writes concept nodes and structural edges through the KnowledgeStore. It must be idempotent — running twice on the same code produces the same graph state. ERD §3.3.2.

**Acceptance Criteria:**

- Given parse results containing 5 functions and 3 classes, when the graph builder runs, then 8 concept nodes are created with `created_by = "agent"` and `confidence = 1.0`.
- Given parse results with a call from `func_a` to `func_b`, when the builder runs, then a `calls` edge is created with `evidence_type = "structural"` and `confidence = 1.0`.
- Given the graph builder has already run on the same codebase, when run again with no changes, then no duplicate concepts or edges are created (upsert by fully-qualified symbol name).
- Given a function that was renamed, when the builder runs on the updated code, then the old concept is updated (not duplicated) and its `updated_at` is refreshed.
- Given parse results, when the builder runs, then every concept has at least one CodeReference with a valid `content_hash` (SHA-256 of the referenced code block).

**Technical Notes:** "Fully-qualified symbol name" means `file_path::class_name::method_name` or `file_path::function_name`. This is the upsert key. The builder should use the KnowledgeStore's `create_concept` and `create_edge` methods (or a bulk upsert variant if needed for performance).

**Definition of Done:** Graph builder populating concepts and edges from parse results. Idempotency verified. Content hashes generated. Integration test against the test repository producing the expected graph.

**Intra-epic dependencies:** Story 3.3 and 3.4 (parsers produce the input), Story 2.7 (dual writer to persist through).

---

#### Story 3.6: Git Change Detector

**As a** user whose code has changed since the last analysis, **I want** automatic detection of which files changed and generation of appropriate work items **so that** the knowledge graph stays current without manual intervention.

**Context:** The change detector uses `git diff` to find changed files, re-parses them, updates the structural graph, and generates work items for the librarian. It stores the last-analyzed commit hash and uses it as the baseline for subsequent diffs. ERD §3.3.3.

**Acceptance Criteria:**

- Given a repository analyzed at commit A, when files are modified and `change_detector.run()` is called at commit B, then only the changed files are re-parsed (not the entire repository).
- Given a modified function whose concept exists in the graph, when the change detector runs, then a `verify_concept` work item is created and the `needs-review` label is applied to the concept.
- Given a newly added file, when the change detector runs, then an `investigate_file` work item is created for each new file.
- Given a deleted function whose concept exists in the graph, when the change detector runs, then the concept is flagged (not immediately deleted — the knowledge manager handles cleanup).
- Given structural edges have changed (e.g., a new import was added), when the change detector runs, then structural updates proceed *without* generating impact tasks in Phase 1 (impact task generation is deferred to Phase 3).
- Given the change detector runs successfully, when it completes, then the stored last-analyzed commit hash is updated to HEAD.

**Technical Notes:** Uses `git diff --name-only {last_hash}..HEAD` to identify changed files. For the first run (no last hash), all files are "changed." The detector must not re-parse unchanged files — only pass changed file paths to the parsing orchestrator. Content hash comparison (`CodeReference.content_hash`) is used to detect whether a concept's referenced code has actually changed.

**Definition of Done:** Change detection working with git. Work item generation for all three types (verify, investigate, analyze_impact). Hash tracking for incremental analysis. Tests using a git repository with staged changes.

**Intra-epic dependencies:** Story 3.5 (graph builder, which the detector invokes for re-parsing).

---

#### Story 3.7: Code Reference Resolution

**As a** system resolving concept-to-code links, **I want** the repair chain to try symbol lookup first, fall back to content hash matching, and finally use semantic anchor search **so that** code references survive renames, refactors, and file moves without losing the concept-to-code link.

**Context:** PRD §5.2 defines the three-step repair chain: symbol → content_hash → semantic_anchor. ERD §3.1.2 notes the resolution order is enforced in the retrieval layer, not the model. The model (Story 1.1) and content hash generation (Story 3.5) exist, but the runtime resolution algorithm that executes the fallback chain does not.

**Acceptance Criteria:**

- Given a code reference with a valid symbol, when resolved, then symbol lookup succeeds and the content hash is verified against current code.
- Given a code reference whose symbol was renamed but content is unchanged, when symbol lookup fails, then the content hash is used to locate the code by scanning the referenced file, and the symbol is updated.
- Given a code reference whose symbol was renamed and content changed, when both symbol and hash fail, then the semantic anchor is used as a fallback description for re-finding the code (requires LLM; expensive path).
- Given all three resolution methods fail, when resolution is attempted, then the code reference is marked unresolved and the parent concept is labeled `needs-review`.

**Technical Notes:** Symbol lookup should succeed ~80% of the time (PRD §5.2). Content hash comparison is a SHA-256 check — fast and deterministic. Semantic anchor resolution is the expensive fallback and should only be invoked when both prior steps fail. The resolution function should return a result indicating which method succeeded (or that all failed) for telemetry.

**Definition of Done:** Three-step fallback implemented. Each step tested independently. Graceful degradation on total failure. Parent concept correctly labeled on unresolved reference.

**Intra-epic dependencies:** Story 3.5 (graph builder produces content hashes), Story 1.1 (CodeReference model).

---

### Epic 4: MCP Server

**Epic goal:** Expose the knowledge graph via 13 MCP tools over stdio.
**PRD sections:** §8.1, §8.2
**ERD sections:** §3.4; S-6 findings

---

#### Story 4.1: MCP Server Scaffolding

**As a** developer integrating A-Priori with AI coding agents, **I want** a running MCP server with the FastMCP framework, lifespan management, and error handling **so that** the server can start, initialize its resources, register tools, and communicate over stdio.

**Context:** The MCP server is a thin shell using FastMCP. It initializes a KnowledgeStore via a lifespan context manager and wraps all tools with a `safe_tool` error decorator. Per S-6 findings. ERD §3.4.

**Acceptance Criteria:**

- Given the command `python -m apriori.mcp.server`, when executed, then the MCP server starts, initializes the KnowledgeStore, and listens on stdio.
- Given the server is running, when a client requests the tool listing, then all 13 tools are listed with names, descriptions, and input schemas.
- Given a tool throws an unexpected exception, when the `safe_tool` decorator catches it, then an `isError=True` response is returned with a descriptive error message (not a traceback).
- Given the server receives a shutdown signal, when the lifespan context manager exits, then resources are cleaned up gracefully.

**Technical Notes:** Pin to `mcp>=1.26,<2.0` per S-6. Use FastMCP's `@mcp.tool()` decorator. The lifespan context manager should initialize the `DualWriter` store and make it available to all tool functions. Per S-1, tool functions are plain `def` (the SDK handles async wrapping).

**Definition of Done:** Server starts and accepts MCP connections over stdio. Tool listing works. Error handling decorator catches and formats exceptions. Lifespan management working.

**Intra-epic dependencies:** None (first story in the epic, but requires Epic 2 to be substantially complete).

---

#### Story 4.2: MCP Read Tools

**As an** AI coding agent, **I want** to query the knowledge graph through MCP read tools (search, traverse, get_concept, list_edge_types, get_status, blast_radius) **so that** I can understand codebase structure and relationships before making changes.

**Context:** Six read tools expose the knowledge graph. All delegate to the KnowledgeStore. The `blast_radius` tool is registered as a placeholder returning "not yet available" until Phase 3. The `search` tool supports four modes: keyword, exact, file, and semantic. PRD §8.1; ERD §3.4.

**Acceptance Criteria:**

- Given a keyword query "payment", when the `search` tool is called with mode "keyword", then concepts with "payment" in their name or description are returned ranked by FTS5 relevance.
- Given a semantic query "how does the system validate transactions", when `search` is called with mode "semantic", then semantically relevant concepts are returned ranked by vector similarity.
- Given an exact concept name, when `search` is called with mode "exact", then the matching concept is returned (or empty if not found).
- Given a file path, when `search` is called with mode "file", then all concepts referencing that file are returned.
- Given a starting concept and max hops of 2, when `traverse` is called, then all concepts within 2 edges of the start are returned with the connecting edges.
- Given a concept name, when `get_concept` is called, then the full concept with metadata, code references, edges, and impact profile is returned.
- Given the current graph state, when `get_status` is called, then accurate metrics are returned (total concepts, edges, coverage percentage, work queue depth).
- Given Phase 1, when `blast_radius` is called, then a message "Blast radius analysis is not yet available. It will be enabled in a future update." is returned.

**Technical Notes:** Each tool handler should be 3–10 lines of glue code per S-6's findings. The `search` semantic mode requires the EmbeddingService to embed the query text before calling `search_semantic`. Filter parameters (labels, confidence threshold, date range) should be optional on `search`.

**Definition of Done:** All six read tools registered and responding correctly. All four search modes working. Traverse returning correct subgraphs. Status metrics accurate. Query latency under 500ms at p95.

**Intra-epic dependencies:** Story 4.1 (server scaffolding).

---

#### Story 4.3: MCP Write Tools

**As an** AI coding agent or human user, **I want** to create, update, and delete concepts and edges, and report knowledge gaps through MCP write tools **so that** the knowledge graph can be enriched by external contributors, not just the librarian.

**Context:** Seven write tools enable graph modification. `report_gap` creates a work item for the librarian. All write operations go through the KnowledgeStore (dual writer). PRD §8.2; ERD §3.4.

**Acceptance Criteria:**

- Given valid concept data, when `create_concept` is called, then the concept is created in both SQLite and YAML and the created concept is returned.
- Given an existing concept, when `update_concept` is called with a new description, then the concept is updated and the updated concept is returned.
- Given a concept with edges, when `delete_concept` is called, then the concept and its edges are removed.
- Given two existing concepts and a valid edge type, when `create_edge` is called, then the edge is created.
- Given an existing edge, when `update_edge` is called with a new confidence, then the edge is updated.
- Given an existing edge, when `delete_edge` is called, then the edge is removed.
- Given an invalid edge type, when `create_edge` is called, then an `isError=True` response is returned listing valid types.
- Given a knowledge gap description, when `report_gap` is called, then a `reported_gap` work item is created in the work queue with the provided description and optional context.

**Technical Notes:** Write tools must validate edge types against the configured vocabulary before delegating to the store. The `report_gap` tool accepts `description: str` and optional `context: str` and creates a WorkItem with `item_type = "reported_gap"`.

**Definition of Done:** All seven write tools registered and working. Edge type validation enforced. `report_gap` creating work items. Error responses clear and descriptive.

**Intra-epic dependencies:** Story 4.1 (server scaffolding).

---

### Epic 5: CLI & First-Run Experience

**Epic goal:** Deliver the CLI and the "zero to first value" init experience.
**PRD sections:** §9.3 (time to first value)
**ERD sections:** §3.5, §3.6

---

#### Story 5.1: CLI Framework and `apriori init`

**As a** new user, **I want** to run `apriori init` in my git repository and have a queryable structural knowledge graph within 60 seconds **so that** I get immediate value with zero configuration.

**Context:** This is the "time to first value" story — the most important UX moment in the product. It creates `.apriori/`, generates default config, triggers structural parsing, builds the graph, and reports results. On first run, the embedding model download adds a one-time delay. PRD §9.3; ERD §3.5, §3.6.

**Acceptance Criteria:**

- Given any git repository with Python or TypeScript files, when `apriori init` is run with no prior setup, then `.apriori/` is created with a default `apriori.config.yaml`, SQLite database, and YAML concept files.
- Given first-time initialization with no cached embedding model, when the model downloads, then progress is displayed ("Downloading embedding model (440MB, one-time)...").
- Given a repository with 100 source files, when `apriori init` completes (excluding model download), then total time is under 60 seconds.
- Given a synthetic repository with 10,000 source files, when `apriori init` completes (excluding model download), then total time is under 60 seconds (per ERD §3.6 and PRD §9.3 acceptance criteria).
- Given init completes, when the user runs `apriori search "main"`, then they receive search results from the newly created graph.
- Given init completes, when the user checks `apriori status`, then accurate metrics are reported (concept count, edge count, coverage).
- Given init was already run, when `apriori init` is run again, then it detects the existing `.apriori/` directory and performs an incremental update (not a full re-parse).

**Technical Notes:** Use Click or Typer for the CLI framework. The init command orchestrates: (1) create `.apriori/` directory structure, (2) write default config, (3) initialize DualWriter (triggers embedding model download if needed), (4) run structural parser + graph builder, (5) print summary. The summary should show: "Created X concepts, Y edges. Coverage: Z%. Knowledge graph ready. Run `apriori search <query>` to explore."

**Definition of Done:** `apriori init` working end-to-end in a real repository. Under 60 seconds (post-model-download). Clear progress and summary output. Incremental mode for re-initialization.

**Intra-epic dependencies:** None (first story, but requires Epics 2, 3, 4 substantially complete).

---

#### Story 5.2: Status, Search, Rebuild-Index, and Config Commands

**As a** user managing my knowledge graph, **I want** CLI commands for checking status, searching, rebuilding the index, and viewing/modifying configuration **so that** I can operate the system without needing MCP tools or direct database access.

**Context:** These are thin wrappers over existing functionality. ERD §3.5.

**Acceptance Criteria:**

- Given a populated graph, when `apriori status` is run, then it displays: total concepts, total edges, coverage percentage, work queue depth, and last parse timestamp.
- Given a query string, when `apriori search "payment"` is run, then results are displayed in a human-readable format with concept names, descriptions (truncated), and confidence scores.
- Given YAML files exist but SQLite is missing, when `apriori rebuild-index` is run, then the SQLite database is reconstructed and a success message is displayed.
- Given no arguments, when `apriori config` is run, then the current configuration is printed with all effective values (defaults + overrides).
- Given a key-value pair, when `apriori config set librarian.max_iterations 50` is run, then the config file is updated.

**Technical Notes:** `status` should be fast — it reads from SQLite metrics queries only. `search` wraps the same logic as the MCP `search` tool. Output formatting should use a simple table or aligned text (not JSON, unless `--json` flag is passed).

**Definition of Done:** All four commands working. Output is human-readable and informative. JSON output available via flag for scripting.

**Intra-epic dependencies:** Story 5.1 (CLI framework and init must exist first).

---

## Phase 2: Semantic Intelligence & Audit

---

### Epic 6: LLM Adapter Layer

**Epic goal:** Implement model-agnostic adapter interface with Anthropic and Ollama backends.
**PRD sections:** §4.4
**ERD sections:** §4.1

---

#### Story 6.1: LLMAdapter Protocol Definition

**As a** developer implementing the librarian or co-regulation review, **I want** a clean adapter protocol that abstracts LLM provider differences **so that** calling code doesn't need to know whether it's talking to Claude, GPT, or a local Ollama model.

**Context:** The adapter protocol defines the interface for all LLM interactions. Per S-1, the `analyze` method is `async def` (network I/O). `get_token_count` and `get_model_info` are plain `def`. ERD §4.1.1.

**Acceptance Criteria:**

- Given the protocol definition, when inspected, then it includes `async analyze(prompt, context) -> AnalysisResult`, `get_token_count(text) -> int`, and `get_model_info() -> ModelInfo`.
- Given the protocol, when `analyze` is called, then the response includes `content` (the LLM's text output), `model_name` (string for failure record tracking), `tokens_used` (input + output token count), and `raw_response` (provider-specific response for debugging).
- Given the protocol, when reviewed, then adding a new provider requires only implementing the protocol — no changes to calling code.

**Technical Notes:** `AnalysisResult` and `ModelInfo` should be defined in the models layer or in `adapters/base.py`. The protocol should be minimal — retry logic should be shared via a mixin or base class, not reimplemented per adapter.

**Definition of Done:** Protocol defined with full type annotations. AnalysisResult and ModelInfo types defined. Documentation explains how to add a new provider.

**Intra-epic dependencies:** None (first story in the epic).

---

#### Story 6.2: Anthropic Adapter

**As a** user with an Anthropic API key, **I want** an adapter that calls the Anthropic Messages API **so that** the librarian can use Claude for semantic analysis and co-regulation review.

**Context:** Wraps the Anthropic Python SDK's async client. ERD §4.1.2.

**Acceptance Criteria:**

- Given a valid API key and prompt, when `analyze` is called, then the adapter sends the prompt to the configured Claude model and returns a structured AnalysisResult.
- Given a transient API error (rate limit, 500), when `analyze` is called, then the adapter retries with exponential backoff (up to 3 retries) before raising.
- Given a persistent API error (invalid key, 401), when `analyze` is called, then the adapter raises immediately with a clear error message (no retry).
- Given any successful response, when the AnalysisResult is inspected, then `model_name` matches the configured model string (e.g., "claude-sonnet-4-20250514").
- Given a prompt, when `get_token_count` is called, then it returns a reasonable token estimate.

**Technical Notes:** Use `anthropic.AsyncAnthropic` client. API key is loaded from the environment variable specified in config (e.g., `ANTHROPIC_API_KEY`). Retry with exponential backoff: 1s, 2s, 4s delays.

**Definition of Done:** Adapter passing protocol test suite (mocked). One verified live API call during development. Retry logic tested with simulated failures.

**Intra-epic dependencies:** Story 6.1 (protocol to implement).

---

#### Story 6.3: Ollama Adapter

**As a** user running a local model via Ollama, **I want** an adapter that calls the Ollama API **so that** the librarian can run completely locally with zero cloud dependency.

**Context:** Wraps Ollama's HTTP API (typically localhost:11434). ERD §4.1.2.

**Acceptance Criteria:**

- Given a running Ollama instance with a loaded model, when `analyze` is called, then the adapter sends the prompt and returns a structured AnalysisResult.
- Given Ollama is not running, when `analyze` is called, then the adapter raises a clear error: "Ollama is not running. Start it with `ollama serve` or check if it's running on the configured port."
- Given a model that is not pulled, when `analyze` is called, then the error message mentions the model name and suggests `ollama pull <model>`.
- Given any successful response, when the AnalysisResult is inspected, then `model_name` matches the Ollama model string (e.g., "qwen2.5:7b").

**Technical Notes:** Use `httpx.AsyncClient` for HTTP calls. Default base URL: `http://localhost:11434`. The Ollama API uses `/api/chat` or `/api/generate` endpoints. Token counting for Ollama models may require a rough heuristic (characters / 4) since exact tokenizers may not be available.

**Definition of Done:** Adapter passing protocol test suite (mocked). Verified with a live Ollama instance during development. Clear error messages for common failure modes.

**Intra-epic dependencies:** Story 6.1 (protocol to implement).

---

#### Story 6.4: Adapter Protocol Test Suite

**As a** developer maintaining adapters, **I want** a shared test suite that runs against any adapter implementation **so that** all adapters are verified against identical behavioral expectations.

**Context:** Both adapters must pass the same tests. Tests use mock HTTP responses. ERD §4.1.

**Acceptance Criteria:**

- Given the test suite, when run against the Anthropic adapter (mocked), then all tests pass.
- Given the test suite, when run against the Ollama adapter (mocked), then all tests pass.
- Given the test suite, when reviewed for coverage, then it tests: successful prompt/response, retry on transient failure, immediate failure on permanent error, correct model_name in response, and token count estimation.

**Definition of Done:** Parameterized test suite passing against both adapters with mocked HTTP responses.

**Intra-epic dependencies:** Stories 6.2 and 6.3 (both adapters must exist).

---

### Epic 7: Quality Assurance Pipeline

**Epic goal:** Validate every piece of LLM-produced knowledge before it enters the graph.
**PRD sections:** §6.4.1–6.4.4
**ERD sections:** §4.4.1–4.4.4

---

#### Story 7.1: Spike — Co-Regulation Prompt Design (S-8)

**As a** technical lead, **I want** to test different co-regulation review prompt framings **so that** we select a prompt that genuinely discriminates quality rather than rubber-stamping everything.

**Context:** The co-regulation review's value depends entirely on prompt quality. Adversarial framing tends to produce better reviews than confirmatory framing. S-8 spike; ERD §4.4.2.

**Acceptance Criteria:**

- Given three candidate prompts (confirmatory: "evaluate this analysis", adversarial: "find the weaknesses in this analysis", structured-rubric: "score this on three dimensions"), when tested against known-good and known-bad librarian outputs, then discrimination ability is measured for each.
- The winning prompt must correctly pass at least 80% of known-good outputs and reject at least 70% of known-bad outputs.
- The spike produces a written decision document with the selected prompt structure and the test results.

**Technical Notes:** Time-box: 3–4 hours. Create at least 3 known-good and 3 known-bad librarian outputs as test cases. Test with the same model that will be used in production (Claude Sonnet). Measure both false positive rate (bad output passed) and false negative rate (good output rejected).

**Definition of Done:** Prompt selected. Test results documented. Prompt template structure documented for implementation.

**Intra-epic dependencies:** None (first story in the epic).

---

#### Story 7.2: Librarian Output Test Fixtures

**As a** developer testing the quality pipeline, **I want** a curated set of known-good and known-bad librarian outputs **so that** I can test the quality pipeline deterministically without live LLM calls.

**Context:** These fixtures are used across the quality pipeline (Level 1 and Level 1.5) and by the librarian orchestrator (Epic 10). They are the foundation for testing the system's quality gate.

**Acceptance Criteria:**

- Given the fixture set, when reviewed, then it includes at least 5 known-good outputs (correct descriptions, valid relationships, proper confidence scores) and at least 8 known-bad outputs covering each Level 1 failure mode: empty description, generic/boilerplate description, referential integrity violation (references non-existent concept), confidence out of range, unparseable schema, invalid edge type.
- Given each fixture, when it includes metadata, then the metadata documents which checks it should pass and which it should fail.
- Given the fixtures, when they are used in tests, then they are loadable from a standard location (e.g., `tests/fixtures/librarian_outputs/`).

**Technical Notes:** Fixtures should be JSON files matching the librarian's expected output schema: `{"concepts": [...], "relationships": [...], "labels": [...]}`. Create them manually based on realistic code analysis scenarios.

**Definition of Done:** Fixture set created with documented expectations. Loadable in tests. Reviewed for comprehensiveness.

**Intra-epic dependencies:** None (can be developed in parallel with Story 7.1).

---

#### Story 7.3: Level 1 Automated Consistency Checks

**As a** system operator, **I want** every librarian output checked for basic consistency before it touches the knowledge graph **so that** obviously malformed, empty, or invalid output is rejected instantly without spending tokens on co-regulation review.

**Context:** Level 1 is deterministic, requires no LLM calls, and executes in milliseconds. It implements six checks. ERD §4.4.1.

**Acceptance Criteria:**

- Given a librarian output with an empty description, when Level 1 runs, then it fails with `failure_reason = "Level 1: empty description"`.
- Given a librarian output matching a boilerplate pattern ("this module handles data processing"), when Level 1 runs, then it fails with a message identifying the generic description.
- Given a librarian output asserting a relationship to a concept name that doesn't exist in the graph, when Level 1 runs, then it fails with a referential integrity error.
- Given a librarian output with `confidence = 1.5`, when Level 1 runs, then it fails with a confidence range error.
- Given a librarian output that cannot be parsed into the expected Pydantic models, when Level 1 runs, then it fails with a schema validity error including the Pydantic validation message.
- Given a librarian output using edge type "invented-type", when Level 1 runs, then it fails with an invalid edge type error.
- Given a librarian output asserting a `depends-on` relationship with no structural corroboration (no import/call/type-reference between the entities), when Level 1 runs, then it **passes** but the confidence score is reduced by the configured factor (default: 0.2) and a metadata note is attached.
- Given a known-good fixture, when Level 1 runs, then it passes.

**Technical Notes:** The boilerplate pattern check should use a short list of banned patterns plus a minimum character length (50 characters). The structural corroboration check (item 6) is a soft check — it adjusts confidence but does not reject. Keep the banned pattern list small and specific to avoid false positives.

**Definition of Done:** All six checks implemented. Tested against all fixtures from Story 7.2. Execution time under 10ms per check. FailureRecord produced on rejection with specific failure_reason.

**Intra-epic dependencies:** Story 7.2 (test fixtures).

---

#### Story 7.4: Level 1.5 Co-Regulation Review

**As a** system operator, **I want** a second LLM call that critically evaluates the librarian's output for specificity, structural corroboration, and completeness **so that** subtle quality issues (generic descriptions, missed relationships, incomplete analysis) are caught before they enter the graph.

**Context:** This is the most architecturally novel component. It uses the prompt design from S-8, sends the librarian's output alongside the original code and structural context to a judge model, and parses the structured response into a CoRegulationAssessment. ERD §4.4.2.

**Acceptance Criteria:**

- Given a librarian output that passed Level 1, when Level 1.5 runs, then a second LLM call is made with the review prompt containing the librarian's output, the original code, and the structural context.
- Given a high-quality librarian output, when the co-regulation review evaluates it, then specificity, structural_corroboration, and completeness scores are all above their thresholds and `composite_pass = True`.
- Given a generic librarian output (description could describe any module), when reviewed, then the specificity score is below threshold, `composite_pass = False`, and the `feedback` field contains actionable guidance on what specific details are missing.
- Given a review failure, when the CoRegulationAssessment is inspected, then the `feedback` field provides guidance specific enough to improve a retry (not just "the analysis is insufficient").
- Given `quality.co_regulation.enabled = false` in config, when Level 1.5 is called, then it returns an automatic pass without making an LLM call.
- Given a separate review model is configured, when Level 1.5 runs, then it uses the review model (not the analysis model).

**Technical Notes:** Use the prompt structure selected in S-8. The review prompt must include adversarial framing to avoid rubber-stamping. The co-regulation review uses the same adapter interface as the librarian — the adapter doesn't need to know it's being called for review. Default thresholds: specificity ≥ 0.5, structural_corroboration ≥ 0.3, completeness ≥ 0.4.

**Definition of Done:** Co-regulation review implemented with S-8 prompt. Correctly discriminates good and bad output (verified against fixtures). Feedback is actionable. Configurable enable/disable working. Separate review model support working.

**Intra-epic dependencies:** Story 7.1 (S-8 prompt design), Story 7.3 (Level 1 must pass before Level 1.5 runs), Story 6.2 or 6.3 (needs an adapter to make LLM calls).

---

#### Story 7.5: Failure Management and Escalation

**As a** system operator, **I want** failed analysis attempts to leave structured diagnostic breadcrumbs and items that fail repeatedly to escalate to human attention **so that** the librarian doesn't burn tokens on intractable work and humans can focus on the items that actually need their help.

**Context:** When a work item fails either Level 1 or Level 1.5, a FailureRecord is written with full diagnostic context. When failure_count reaches the escalation threshold (default: 3), the item escalates. ERD §4.4.3.

**Acceptance Criteria:**

- Given a Level 1 failure, when the failure is recorded, then a FailureRecord is appended to the work item's `failure_records` with `failure_reason`, `model_used`, `prompt_template`, and `attempted_at`.
- Given a Level 1.5 failure, when the failure is recorded, then the FailureRecord additionally includes `quality_scores` (the three dimensional scores) and `reviewer_feedback`.
- Given a work item with `failure_count = 2` (threshold is 3), when a third failure occurs, then `failure_count` becomes 3, `escalated` is set to True, and the `needs-human-review` label is applied to the associated concept.
- Given an escalated item, when inspected, then all previous failure records are preserved with full diagnostic context.
- Given a work item with no associated concept (e.g., `investigate_file`), when escalation occurs, then escalation still proceeds (the label application is skipped but the flag and priority reduction apply).

**Technical Notes:** The escalation logic is in this module. The priority reduction (0.5x on escalated items) is applied in the priority engine (Epic 9), not here — this module just flips the `escalated` flag. Use the KnowledgeStore's `record_failure` and `escalate_work_item` methods.

**Definition of Done:** Failure recording working for both Level 1 and Level 1.5 failures. Escalation triggering at the correct threshold. Label application working. Full diagnostic context preserved in failure records.

**Intra-epic dependencies:** Stories 7.3 and 7.4 (the quality checks that produce failures).

---

#### Story 7.6: Review Outcome Tracking and Error Profiling

**As an** engineering lead, **I want** human review actions (verify, correct, flag) tracked and aggregated into an error profile **so that** I can see the librarian's systematic weaknesses over time and improve prompt templates accordingly.

**Context:** ReviewOutcomes are stored in their own SQLite table. The error profile aggregates review outcomes to surface patterns (e.g., "40% of corrections are for missing relationships"). ERD §4.4.4.

**Acceptance Criteria:**

- Given a concept, when a human marks it as "verified" through the review workflow, then `verified_by` and `last_verified` are set on the concept, confidence is boosted by +0.1 (capped at 1.0), and a ReviewOutcome is recorded.
- Given a concept, when a human submits a "corrected" action with `error_type = "relationship_missing"`, then the concept is updated, the correction is recorded, and the ReviewOutcome is stored.
- Given a concept, when a human "flags" it, then `needs-review` label is applied and a `review_concept` work item is created.
- Given 20 review outcomes over the past 30 days, when `get_error_profile` is called, then it returns an aggregated summary showing the distribution of error types (e.g., `{"relationship_missing": 8, "description_wrong": 5, "confidence_miscalibrated": 4, "other": 3}`).

**Technical Notes:** The error profile is computed from the `review_outcomes` table with grouping and counting queries. This data is consumed by the audit UI (Epic 11) for display.

**Definition of Done:** Review outcome recording working for all three actions. Concept updates (verify/correct/flag) correct. Error profile aggregation returning accurate distributions.

**Intra-epic dependencies:** None (can be developed in parallel with other quality stories, uses KnowledgeStore directly).

---

### Epic 8: Knowledge Manager

**Epic goal:** Implement the "never just append" knowledge integration logic.
**PRD sections:** §4.1 (Layer 2)
**ERD sections:** §4.5

---

#### Story 8.1: Knowledge Integration Decision Tree

**As a** system maintaining knowledge graph integrity, **I want** the knowledge manager to intelligently integrate librarian output by deciding whether to create, update, merge, or flag contradictions **so that** the graph evolves cleanly without duplicates, silent overwrites, or lost human contributions.

**Context:** The integration decision tree handles four scenarios: new concept, update to agent-created concept (agree/contradict/extend), update to human-created concept (supplement only), and edge updates. ERD §4.5.

**Acceptance Criteria:**

- Given the librarian produces a concept named "PaymentValidator" that doesn't exist, when integration runs, then a new concept is created with `created_by = "agent"`.
- Given an existing agent-created concept "PaymentValidator" with description A, when the librarian produces a new analysis with description B that agrees with A, then `last_verified` is updated and confidence is boosted.
- Given an existing agent-created concept with description A, when the librarian produces contradictory description C, then both descriptions are preserved, the concept is flagged with `needs-review`, and the contradiction is logged.
- Given an existing agent-created concept with description A, when the librarian produces an extending description (adding new information), then descriptions are merged (new information appended, existing preserved).
- Given an existing **human-created** concept, when the librarian produces analysis for the same code, then the human description is NOT overwritten — the librarian's analysis is captured as supplementary context or as relationship edges only.
- Given the librarian asserts an edge that already exists, when integration runs, then the edge's confidence is updated (take the higher value).
- Given the librarian asserts an edge contradicting an existing edge, when integration runs, then both are flagged with `needs-review`.
- Given any integration action, when it writes to the graph, then `derived_from_code_version` is stamped with the current git HEAD hash.

**Technical Notes:** "Contradiction" vs. "extension" detection is a judgment call. For MVP, use a simple heuristic: if the new description shares fewer than 30% of key terms with the existing description, flag as potential contradiction. This can be refined over time. The merge strategy for "extend" should append new sentences from the new description that aren't semantically redundant with existing ones (simple substring or sentence-level dedup).

**Definition of Done:** Decision tree implemented for all four concept scenarios and edge updates. Human-created concepts protected from overwrite. Contradictions flagged and logged. Git version stamping on all writes.

**Intra-epic dependencies:** None (first story in the epic, but requires Epic 2 for storage access).

---

#### Story 8.2: Staleness Detection

**As a** system maintaining knowledge freshness, **I want** concepts whose referenced code has changed since their last verification automatically detected and labeled as stale **so that** the priority engine can direct the librarian to re-verify them.

**Context:** Staleness is determined by comparing `derived_from_code_version` against the current git HEAD for the referenced files. ERD §4.5.

**Acceptance Criteria:**

- Given a concept derived from commit A, when the referenced code is modified in commit B, then the concept is labeled `stale`.
- Given a concept derived from commit B and the current HEAD is also B, when staleness detection runs, then the concept is NOT labeled stale.
- Given a stale concept, when the librarian re-verifies it, then the `stale` label is removed and `derived_from_code_version` is updated.

**Technical Notes:** This integrates with the change detector (Story 3.6) which already generates `verify_concept` work items for changed code. Staleness detection adds the label that feeds the priority engine's `staleness` factor.

**Definition of Done:** Staleness detection working. Labels applied and removed correctly. Integration with change detector verified.

**Intra-epic dependencies:** Story 8.1 (core integration logic).

---

### Epic 9: Priority Scoring & Metrics Engine

**Epic goal:** Implement adaptive priority that automatically focuses the librarian on what matters most.
**PRD sections:** §6.3, §6.3.1, §9.1
**ERD sections:** §4.3, §4.6

---

#### Story 9.1: Metrics Engine

**As a** system operator, **I want** accurate, efficient computation of coverage, freshness, and blast radius completeness metrics **so that** both the health dashboard and the adaptive modulation loop have reliable inputs.

**Context:** These three metrics serve dual purpose: reporting and driving adaptive modulation. They must be efficient SQL queries because they run before every librarian iteration. ERD §4.6.

**Acceptance Criteria:**

- Given 100 source files and 60 referenced by at least one concept, when `get_coverage` is called, then it returns 0.60.
- Given 50 concepts referencing actively-developed files and 45 with `last_verified` more recent than the code's last modification, when `get_freshness` is called, then it returns 0.90.
- Given 100 concepts and 70 with non-stale impact profiles, when `get_blast_radius_completeness` is called, then it returns 0.70.
- Given a 10,000-concept graph, when any metric is computed, then execution time is under 50ms.
- Given metrics were computed 10 seconds ago and no writes have occurred, when metrics are requested again, then cached values are returned (30-second TTL cache).

**Technical Notes:** "Actively-developed files" for freshness means files modified in the last 30 days (configurable). "Total source files" for coverage uses the same glob patterns as the structural parser. These should be single SQL queries with appropriate JOINs, not Python-side iteration.

**Definition of Done:** All three metrics computed correctly. SQL queries efficient. Caching implemented. Integration tests with known graph states.

**Intra-epic dependencies:** None (first story in the epic, uses KnowledgeStore directly).

---

#### Story 9.2: Base Priority Computation

**As a** librarian selecting its next work item, **I want** a weighted priority score computed for every unresolved work item **so that** the most important work is done first.

**Context:** The six-factor weighted sum from PRD §6.3. ERD §4.3.1.

**Acceptance Criteria:**

- Given a work item for an `investigate_file` with `coverage_gap = 1.0` and default weights, when the score is computed, then the `coverage_gap` factor contributes 0.15 to the total score.
- Given a work item for a concept labeled `needs-review`, when the score is computed, then the `needs_review` factor contributes 0.20.
- Given a work item near recently-modified files (graph distance = 1), when the score is computed, then the `developer_proximity` factor is high.
- Given all six factors at their maximum (1.0), when the score is computed with default weights, then the total is 1.0.
- Given custom weights configured in `apriori.config.yaml`, when scores are computed, then the custom weights are used.

**Technical Notes:** Each factor must be normalized to [0, 1] before weighting. `developer_proximity` uses graph distance from recently modified files (configured window of recent commits), inverted and normalized (closer = higher score). `git_activity` normalizes commit count over a configurable window.

**Definition of Done:** Six-factor scoring implemented. All factors normalized correctly. Custom weight support verified. Unit tests for each factor individually and the composite score.

**Intra-epic dependencies:** Story 9.1 (metrics engine, because some factors like coverage_gap depend on overall metrics context).

---

#### Story 9.3: Adaptive Modulation

**As a** system operator, **I want** the librarian to automatically shift its focus toward whichever product metric is furthest below target **so that** I don't need to manually adjust priorities as the graph evolves.

**Context:** The feedback loop computes metric deficits and boosts relevant weights. PRD §6.3.1; ERD §4.3.2.

**Acceptance Criteria:**

- Given coverage at 0.50 (target 0.80, deficit 0.30) and freshness at 0.95 (target 0.90, deficit 0.0), when modulation runs with `modulation_strength = 1.0`, then the effective weight for `coverage_gap` is `0.15 * (1 + 0.30 * 1.0) = 0.195` while `staleness` and `needs_review` weights are unchanged.
- Given `modulation_strength = 0.0`, when modulation runs, then effective weights equal base weights exactly (modulation disabled).
- *(Deferred to Phase 3)* Given blast_radius_completeness below target, when modulation runs, then `analyze_impact` work items receive a direct priority score boost.
- Given an escalated work item, when its final priority is computed, then it is multiplied by 0.5 (the configured reduction factor).
- Given the modulation computation, when telemetry is emitted, then it includes: current metric values, targets, deficits, effective weights (before and after modulation), and the selected work item with its score.

**Technical Notes:** The modulation formula is `effective_weight = base_weight * (1 + deficit * modulation_strength)`. Blast radius completeness modulation is applied as a direct score multiplier on `analyze_impact` items rather than a weight boost (because it doesn't map to one of the six weight factors). Telemetry output is stored for the audit UI health dashboard.

**Definition of Done:** Modulation math verified with exact test cases. Escalated item reduction working. Telemetry output complete and stored. `modulation_strength = 0.0` produces exact static behavior.

**Intra-epic dependencies:** Stories 9.1 (metrics) and 9.2 (base priority).

---

### Epic 10: Librarian Orchestrator

**Epic goal:** Wire together adapters, quality, knowledge manager, and priority into an autonomous analysis loop.
**PRD sections:** §6.1, §6.2, §6.5
**ERD sections:** §4.2, §4.8

---

#### Story 10.1: Loop Execution and Iteration Workflow

**As a** user running `apriori librarian run`, **I want** an autonomous loop that picks work items, analyzes code via LLM, validates output through the quality pipeline, and integrates knowledge into the graph **so that** semantic understanding is built progressively without manual intervention.

**Context:** This is the integration story that connects all Phase 2 components. Each iteration follows the 10-step sequence from ERD §4.2.1. ERD §4.2.1.

**Acceptance Criteria:**

- Given unresolved work items in the queue, when `apriori librarian run --iterations 3` is executed, then exactly 3 iterations run (or fewer if the queue empties).
- Given an iteration, when the 10-step sequence completes successfully, then: a work item is selected by the priority engine, context is loaded, code is read from disk, a prompt is sent to the LLM, the output passes Level 1 and Level 1.5, the knowledge manager integrates the result, and the work item is marked resolved.
- Given an iteration where Level 1 fails, when the failure is handled, then a FailureRecord is written, the work item remains unresolved, and the loop proceeds to the next iteration.
- Given an iteration where Level 1.5 fails, when the failure is handled, then a FailureRecord with co-regulation feedback is written and the loop continues.
- Given a work item with previous failure records, when it is selected for retry, then the prompt includes the failure history and co-regulation feedback from previous attempts.
- Given an empty work queue, when the loop starts, then it logs "No unresolved work items. Nothing to do." and exits cleanly.
- Given each iteration, when it completes, then no state is carried to the next iteration (context is loaded fresh from disk).

**Technical Notes:** Per S-1, the loop orchestrator is an async function managing iterations via `asyncio.gather()` for concurrency within a single run. Each iteration is isolated. The adapter's `analyze` call is the async boundary. Everything else (storage reads/writes, quality checks) uses sync methods called from the thread pool.

**Definition of Done:** Loop executing the full 10-step sequence end-to-end. Integration verified with both Anthropic and Ollama adapters. Failure handling and retry working. Clean exit on empty queue.

**Intra-epic dependencies:** Requires Epics 6, 7, 8, 9 to be substantially complete.

---

#### Story 10.2: Prompt Template System

**As a** librarian analyzing code, **I want** model-specific prompt templates that produce high-quality structured output and incorporate failure feedback for retries **so that** analysis quality is maximized for each model and failed work items get better on retry.

**Context:** Prompt templates are model-specific (Anthropic vs. Ollama) and support a `with_failure_context` mode. ERD §4.2.2.

**Acceptance Criteria:**

- Given a work item for `investigate_file`, when the prompt is constructed, then it includes the source code, structural context (imports, calls, inheritance), and instructions to produce structured JSON output.
- Given a work item with 2 previous failure records, when the prompt is constructed in `with_failure_context` mode, then it includes the failure history with each attempt's failure reason and co-regulation feedback.
- Given the Anthropic prompt template, when used with Claude, then the output is structured JSON with concepts, relationships, and labels.
- Given the Ollama prompt template, when used with a local model, then the output schema is the same but the prompt is adapted for models that may need more explicit JSON formatting instructions.
- Given the output schema, when the LLM returns JSON (or JSON in markdown fences), then the response parser can extract it correctly.

**Technical Notes:** The output schema instructs the LLM to return: `{"concepts": [{"name": str, "description": str, "confidence": float, "code_references": [...]}], "relationships": [{"source": str, "target": str, "edge_type": str, "confidence": float, "rationale": str}], "labels": [...]}`. The `with_failure_context` mode appends the failure history section to the base prompt. Different `item_type` values may need different prompt templates (investigation vs. verification vs. relationship evaluation).

**Definition of Done:** Prompt templates for both providers. Failure context mode working. Response parser handling JSON and JSON-in-fences. Output validated against Pydantic models.

**Intra-epic dependencies:** Story 10.1 (loop that uses the templates).

---

#### Story 10.3: Token Budget Management

**As a** user controlling LLM costs, **I want** configurable budget limits that halt the librarian when spending reaches the ceiling **so that** I never get a surprise token bill.

**Context:** Budget management enforces per-iteration limits, per-run iteration limits, and per-run token limits. When co-regulation is enabled, per-iteration cost is doubled. ERD §4.8.

**Acceptance Criteria:**

- Given a per-run token limit of 100,000 tokens, when cumulative tokens reach 95,000 and the estimated next iteration cost is 10,000, then the loop stops with a message "Token budget would be exceeded. Stopping. Used: 95,000 / 100,000."
- Given a per-iteration limit of 5,000 tokens, when a prompt exceeds it, then the graph context is truncated (not the code) to fit, and a warning is logged.
- Given co-regulation is enabled, when per-iteration cost is estimated, then it accounts for both the analysis call and the review call.
- Given co-regulation is enabled and the analysis call completes within budget but the review call would exceed it, when the iteration proceeds, then the review call is still made (never skip quality checks to save tokens).
- Given the run completes, when telemetry is output, then it includes: total iterations, total tokens (analysis vs. review breakdown), concepts created/updated, edges created/updated, work items resolved, work items failed, work items escalated, and iteration yield (total mutations / total iterations) per PRD §9.2.

**Technical Notes:** Token estimation uses a running average of recent iterations to predict the next iteration's cost. The per-iteration limit uses `get_token_count` from the adapter for prompt sizing. Context truncation strategy: reduce graph context (neighbor concepts, distant edges) while preserving the code being analyzed and the structural context.

**Definition of Done:** All three budget limits enforced. Co-regulation cost correctly accounted for. Context truncation working. End-of-run telemetry accurate.

**Intra-epic dependencies:** Story 10.1 (loop execution that enforces the budget).

---

### Epic 11: Human Audit UI

**Epic goal:** Deliver the local web application for graph inspection and review.
**PRD sections:** §8A
**ERD sections:** §4.7

---

#### Story 11.1: Spike — UI Technology Selection (S-7)

**As a** technical lead, **I want** a prototype-based evaluation of frontend technology options **so that** we select an approach that handles graph visualization well and is maintainable by a Python-focused team.

**Context:** Key constraints: self-contained (no external CDN), no Node.js for end users, graph visualization at 500 nodes. S-7 spike; ERD §4.7.1.

**Acceptance Criteria:**

- Given at least one prototype (ideally two), when evaluated, then measurements include: bundle size, load time, interaction latency at 500 nodes, and developer ergonomics assessment.
- The spike produces a written decision selecting one approach with rationale, measurements, and tradeoffs.

**Technical Notes:** Time-box: 4–6 hours. Options: Pre-built React SPA (best interactivity, Cytoscape.js for graph), HTMX + Jinja2 (Python-native, weak for graph viz), Alpine.js (middle ground). The graph visualization library (Cytoscape.js, D3.js, Sigma.js) likely drives the decision more than the framework.

**Definition of Done:** Prototype built. Measurements documented. Technology selected.

**Intra-epic dependencies:** None (first story in the epic).

---

#### Story 11.2: Backend REST API

**As a** frontend developer, **I want** a complete REST API serving graph data, activity feeds, health metrics, and review actions **so that** the frontend can be built against a stable, well-documented API.

**Context:** FastAPI backend serving the frontend. Read-only except for review actions. ERD §4.7.2.

**Acceptance Criteria:**

- Given the API, when `GET /api/concepts` is called with filters (labels, confidence threshold, recency), then filtered concepts are returned.
- Given a concept ID, when `GET /api/concepts/{id}` is called, then the full concept with edges and impact profile is returned.
- Given `GET /api/graph?center={id}&radius=2`, when called, then a subgraph (concepts and edges within 2 hops of center) is returned in a format suitable for graph visualization.
- Given `GET /api/activity?limit=20`, when called, then the 20 most recent librarian iterations are returned with work item details, pass/fail status, and co-regulation scores.
- Given `GET /api/health`, when called, then current metric values, targets, effective priority weights, and work queue depth are returned.
- Given `GET /api/escalated`, when called, then escalated work items with full failure history are returned.
- Given `POST /api/concepts/{id}/verify`, when called, then the concept is verified and a ReviewOutcome is recorded.
- Given `POST /api/concepts/{id}/correct` with error type and correction details, when called, then the concept is updated and a ReviewOutcome is recorded.
- Given `POST /api/concepts/{id}/flag`, when called, then the concept is flagged and a `review_concept` work item is created.

**Technical Notes:** Use FastAPI with `asyncio.to_thread()` for sync KnowledgeStore calls per S-1. The API reads from the same SQLite database as the MCP server and librarian. CORS is not needed (same origin — served from the same process). The backend also serves the static frontend assets.

**Definition of Done:** All endpoints implemented and tested. API documentation auto-generated by FastAPI. Review actions correctly delegating to the review outcomes module.

**Intra-epic dependencies:** Story 11.1 (technology decision informs response format for graph data).

---

#### Story 11.3: Knowledge Graph Visualization

**As an** engineer exploring the knowledge graph, **I want** an interactive node-and-edge visualization with filtering and confidence-based visual styling **so that** I can visually understand the structure and quality of the knowledge graph.

**Context:** The core visual component of the audit UI. Must handle 500 nodes interactively. PRD §8A.3.

**Acceptance Criteria:**

- Given a knowledge graph with 200 concepts and 400 edges, when the visualization loads, then all nodes and edges are rendered with pan and zoom capability.
- Given a concept node, when clicked, then its full details are shown (description, code references, confidence, evidence type, timestamps, impact profile).
- Given the filter controls, when filtering by edge type "structural", then only structural edges are displayed.
- Given the filter controls, when filtering by confidence ≥ 0.7, then only nodes and edges meeting the threshold are shown.
- Given the filter controls, when filtering by label "needs-review", then only concepts with that label are highlighted.
- Given a high-confidence concept (0.9) and a low-confidence concept (0.3), when rendered, then they are visually distinguishable (e.g., opacity, color intensity, or node border style).
- Given 500 nodes, when the user pans and zooms, then interaction is smooth (no visible lag).

**Technical Notes:** The graph visualization library selected in S-7 determines implementation details. Common options: Cytoscape.js (best for network graphs, supports filtering and styling natively), D3.js force layout (more customizable but more effort), Sigma.js (good performance for large graphs). Layout algorithm should default to force-directed but allow the user to toggle.

**Definition of Done:** Graph rendering working at 500 nodes. Click-to-inspect working. All filter types working. Visual confidence distinction implemented.

**Intra-epic dependencies:** Story 11.1 (S-7 technology selection), Story 11.2 (API to serve graph data).

---

#### Story 11.4: Librarian Activity Feed

**As an** engineer casually monitoring the librarian, **I want** a chronological feed of recent librarian iterations **so that** I can tell at a glance whether the librarian is doing useful work or struggling.

**Context:** The primary mechanism for casual quality monitoring. PRD §8A.3.

**Acceptance Criteria:**

- Given the librarian has run 10 iterations, when the activity feed loads, then 10 entries are displayed in reverse chronological order.
- Given each entry, when displayed, then it shows: work item processed, concept created/updated, co-regulation scores (if applicable), pass/fail status, and on failure, the failure reason.
- Given a failed iteration, when its entry is clicked or expanded, then the full FailureRecord is visible including reviewer_feedback.

**Definition of Done:** Activity feed displaying correct data. Failed iterations clearly distinguished from successful ones. Expandable detail view for failures.

**Intra-epic dependencies:** Story 11.2 (API endpoint for activity data).

---

#### Story 11.5: Review Workflow UI

**As an** engineer reviewing the librarian's work, **I want** to view a concept alongside its referenced code, verify it, flag it, or submit corrections **so that** I can efficiently audit the knowledge graph and build the librarian's error profile.

**Context:** The Level 2 human review workflow in the UI. PRD §8A.3.

**Acceptance Criteria:**

- Given a concept, when the review view is opened, then the concept's description is displayed alongside the actual code it references (shown inline or as a code block).
- Given the "Verify" button, when clicked, then the concept is marked as verified and a success confirmation is shown.
- Given the "Flag" button, when clicked, then the concept is flagged for re-review and a `review_concept` work item is created.
- Given the "Correct" button, when clicked, then an inline editor opens for the description and relationships, with a dropdown for error type selection.
- Given a correction is submitted, when the API call completes, then the concept is updated and a ReviewOutcome is recorded.

**Definition of Done:** Full verify/correct/flag workflow working end-to-end. Review actions correctly updating concepts and recording outcomes.

**Intra-epic dependencies:** Story 11.2 (API review endpoints), Story 11.3 (graph visualization for navigation to concepts).

---

#### Story 11.6: Health Dashboard

**As an** engineering lead, **I want** a single-glance view of the knowledge graph's health — metric values vs. targets, current priority weights, and work queue depth **so that** I can quickly assess whether the librarian is on track or needs attention.

**Context:** Displays the metrics that drive adaptive modulation alongside their targets. PRD §8A.3.

**Acceptance Criteria:**

- Given the dashboard, when loaded, then it displays: coverage (X% vs. 80% target), freshness (Y% vs. 90% target), blast radius completeness (Z% vs. 70% target).
- Given the dashboard, when loaded, then it shows the current effective priority weights (including adaptive modulation adjustments).
- Given the dashboard, when loaded, then it shows the work queue depth (total unresolved, escalated count).
- Given metrics change, when the dashboard is refreshed, then updated values are shown.

**Definition of Done:** Dashboard displaying all three metrics with targets. Priority weights shown. Work queue depth shown.

**Intra-epic dependencies:** Story 11.2 (API health endpoint).

---

#### Story 11.7: Escalated Items View

**As an** engineer, **I want** a dedicated view for escalated work items with their full failure history **so that** I can assess whether failures are due to model limitations, ambiguous code, or prompt template issues.

**Context:** Escalated items have exceeded the failure threshold (default: 3 attempts). PRD §8A.3.

**Acceptance Criteria:**

- Given 5 escalated work items, when the escalated view loads, then all 5 are listed with their descriptions and associated concepts.
- Given an escalated item, when expanded, then the full failure history is shown: each attempt's model, failure reason, co-regulation scores, and reviewer feedback.
- Given the failure history, when reviewed by an engineer, then they can determine the failure pattern (e.g., "all three attempts used the same model and failed on specificity" suggests a model limitation, while "each attempt failed on different checks" suggests ambiguous code).

**Definition of Done:** Escalated items view listing all escalated work items. Full failure history expandable per item.

**Intra-epic dependencies:** Story 11.2 (API escalated endpoint).

---

## Phase 3: Blast Radius

---

### Epic 12: Blast Radius & Impact Profiles

**Epic goal:** Deliver pre-computed, three-layer impact analysis.
**PRD sections:** §5.5, §7.1–7.4
**ERD sections:** §5.1–5.3

---

#### Story 12.1: Spike — Blast Radius Validation Methodology (S-4)

**As a** technical lead, **I want** a designed test harness for measuring blast radius accuracy against historical PRs **so that** we can objectively evaluate whether the system meets the PRD's accuracy targets (>70% recall, >50% precision).

**Context:** S-4 spike. PRD §9.1.

**Acceptance Criteria:**

- The spike produces a design document describing: how to select test PRs, how to compute A-Priori's predicted impact set, how to compute the actual impact set from the PR's changed files, and how to calculate recall and precision.
- The design identifies a suitable test repository with sufficient PR history (at least 50 PRs with multi-file changes).
- The methodology is implementable as an automated test.

**Technical Notes:** Time-box: 2–3 hours. Recall = (correctly predicted files / actually affected files). Precision = (correctly predicted files / total predicted files). The test harness should be able to run retrospectively against closed PRs.

**Definition of Done:** Validation methodology documented. Test repository identified. Methodology reviewed.

**Intra-epic dependencies:** None (first story).

---

#### Story 12.2: Structural Impact Computation

**As a** user querying blast radius, **I want** deterministic impact analysis based on the structural call graph **so that** I see all direct code-level dependencies with 100% confidence.

**Context:** BFS traversal of structural edges (calls, imports, inherits, type-references) outward from a target concept. ERD §5.1.

**Acceptance Criteria:**

- Given a function that is called by 3 other functions, when structural impact is computed, then all 3 callers appear with `confidence = 1.0` and `depth = 1`.
- Given a class that is inherited by 2 subclasses, each calling 1 additional function, when structural impact is computed with max depth 2, then 4 concepts appear (2 at depth 1, 2 at depth 2).
- Given the traversal, when an `ImpactEntry` is produced, then it includes `relationship_path` (the chain of edge IDs connecting source to target) and a `rationale` (e.g., "Called by validate_payment which calls process_order").
- Given a concept with no structural dependents, when impact is computed, then the structural impact list is empty.

**Definition of Done:** BFS traversal of structural edges working. ImpactEntries produced with correct confidence (1.0), depth, path, and rationale. Performance verified on test graph.

**Intra-epic dependencies:** Story 12.1 (S-4 informs testing approach).

---

#### Story 12.3: Semantic Impact Computation

**As a** user querying blast radius, **I want** impact analysis that captures implicit semantic coupling beyond the call graph **so that** I see modules that share assumptions, implement coupled business logic, or depend on the same contracts.

**Context:** BFS traversal of semantic edges. Confidence is the product of edge confidences along the path. ERD §5.1.

**Acceptance Criteria:**

- Given two concepts connected by a `shares-assumption-about` edge with confidence 0.8, when semantic impact is computed, then the target appears with `confidence = 0.8` and `depth = 1`.
- Given a chain of semantic edges A→B (0.8) → C (0.7), when traversal reaches C, then confidence is `0.8 * 0.7 = 0.56`.
- Given a concept with no semantic edges, when impact is computed, then the semantic impact list is empty and the profile is flagged as "structural only."

**Definition of Done:** Semantic BFS traversal working. Confidence product computed correctly. "Structural only" flag applied when no semantic data exists.

**Intra-epic dependencies:** Story 12.2 (shares ImpactProfile storage).

---

#### Story 12.4: Historical Impact Computation

**As a** user querying blast radius, **I want** empirically-derived co-change patterns from git history **so that** I see coupling that isn't captured by either structural or semantic analysis.

**Context:** Analyzes git log for files that frequently change together. ERD §5.1.

**Acceptance Criteria:**

- Given two files that were modified together in 8 out of 10 recent commits, when historical impact is computed, then they appear with high confidence reflecting co-change frequency.
- Given co-change analysis, when recency decay is applied, then recent co-changes contribute more to confidence than older ones.
- Given the computation, when it runs, then it processes git history in batch (not per-concept) for efficiency.

**Technical Notes:** Confidence formula: `co_change_count / total_changes * recency_weight`. Recency decay can be exponential or linear over a configurable window (e.g., last 90 days). Batch processing: analyze the git log once and update all affected profiles.

**Definition of Done:** Git history analysis extracting co-change patterns. Confidence with recency decay working. Batch processing efficient.

**Intra-epic dependencies:** Story 12.2 (shares ImpactProfile storage).

---

#### Story 12.5: Impact Profile Storage and Maintenance

**As a** system maintaining blast radius readiness, **I want** impact profiles pre-computed and stored on concept nodes, with automatic updates when the graph changes **so that** blast radius queries are always fast and reasonably current.

**Context:** Profiles are stored on each concept node and maintained continuously. ERD §5.2.

**Acceptance Criteria:**

- Given a structural edge change (new import added), when the change detector runs, then the affected concept's structural impact profile is recomputed immediately.
- Given the librarian discovers a new semantic relationship, when integration completes, then both endpoint concepts' impact profiles are updated.
- Given a profile whose `last_computed` is older than the staleness threshold, when detected, then an `analyze_impact` work item is generated.
- Given a blast radius query, when the profile is returned, then it includes the `last_computed` timestamp so the consumer knows how fresh the data is.

**Definition of Done:** Impact profiles stored on concepts. Structural updates immediate. Semantic updates on librarian integration. Staleness detection generating work items.

**Intra-epic dependencies:** Stories 12.2, 12.3, 12.4 (all three computation layers).

---

#### Story 12.6: Blast Radius MCP Tool and CLI Command

**As an** AI coding agent, **I want** to query "what breaks if I change this?" via the `blast_radius` MCP tool and receive a prioritized, confidence-scored impact assessment in under 500ms **so that** I can make informed decisions before modifying code.

**Context:** This replaces the Phase 1 placeholder. Accepts concept name/ID, file path, or function symbol. Returns pre-computed impact profile. PRD §7.3; ERD §5.3.

**Acceptance Criteria:**

- Given a concept name, when `blast_radius` is called, then the pre-computed impact profile is returned as a prioritized list sorted by composite score (`confidence * (1/depth)`).
- Given a file path that maps to multiple concepts, when `blast_radius` is called, then the union of all impact profiles is returned.
- Given a function symbol, when `blast_radius` is called, then the concept referencing that symbol is identified and its profile is returned.
- Given an optional `depth=2` parameter, when `blast_radius` is called, then only impacts within 2 hops are returned.
- Given an optional `min_confidence=0.5`, when `blast_radius` is called, then only impacts with confidence ≥ 0.5 are returned.
- Given each impact entry in the response, when inspected, then it includes: concept name/ID, confidence, impact layer (structural/semantic/historical), depth, relationship path, and human-readable rationale.
- Given a 10,000-concept graph, when `blast_radius` is called, then the response is returned in under 500ms at p95.
- Given `apriori blast-radius src/payments/validate.py`, when the CLI command is run, then the same information is displayed in a human-readable format.

**Definition of Done:** MCP tool replacing Phase 1 placeholder. All input types (name, ID, path, symbol) resolving correctly. Filtering by depth and confidence working. Response format complete. Latency under 500ms. CLI command wrapping the same logic.

**Intra-epic dependencies:** Story 12.5 (profiles must be stored and maintained).

---

#### Story 12.7: Blast Radius Accuracy Validation

**As a** technical lead, **I want** blast radius predictions validated against historical PRs using the S-4 methodology **so that** I have evidence the system meets its accuracy targets before shipping.

**Context:** PRD §9.1 requires >70% recall and >50% precision for blast radius predictions, measured against actual file changes in historical PRs. Spike S-4 (Story 12.1) designs the validation methodology. This story applies that methodology. ERD §5.4 acceptance criterion #5.

**Acceptance Criteria:**

- Given at least 50 historical PRs in the test repository (identified by S-4 spike), when blast radius predictions are compared to actual file changes in each PR, then recall is ≥70% (the percentage of actually-affected files that A-Priori predicted).
- Given the same PR set, when precision is measured, then precision is ≥50% (the percentage of predicted files that were actually affected).
- Given the validation results, when reviewed, then a written report documents per-PR results, aggregate metrics, and identified failure patterns (e.g., types of changes the system consistently misses).

**Technical Notes:** The S-4 spike defines the test harness, test repository, and methodology. This story runs it. If accuracy targets are not met, the report should identify the most impactful improvements (e.g., missing edge types, confidence calibration issues) to guide iteration.

**Definition of Done:** Validation run against ≥50 PRs. Results documented. Recall and precision measured and reported. If targets are not met, failure analysis completed with recommended improvements.

**Intra-epic dependencies:** Story 12.1 (methodology), Story 12.5 (profiles stored), Story 12.6 (blast_radius tool functional).

---

## Phase 4: Polish & Scale

---

### Epic 13: Progressive Enrichment, CLI Completion & Documentation

**Epic goal:** Deliver the bootstrapping experience, complete CLI, and documentation.
**PRD sections:** §6.5, §10.1
**ERD sections:** §6.1–6.3

---

#### Story 13.1: Progressive Enrichment for Large Codebases

**As a** user bootstrapping A-Priori on a large codebase, **I want** the librarian to start analyzing my actively-edited files first and expand outward within my token budget **so that** I get value quickly in the areas I'm working on without paying to analyze the entire codebase upfront.

**Context:** Modifies the priority engine to heavily weight `developer_proximity` when coverage is low. ERD §6.1.

**Acceptance Criteria:**

- Given a codebase with 500 files and coverage below 50%, when the librarian runs, then it prioritizes files near the developer's recent git activity over distant files.
- Given coverage exceeds 50%, when the priority engine recomputes, then standard weight distribution is restored.
- Given a token budget of $2.00, when the librarian runs, then it stays within budget and reports: "Analyzed 47/312 source files. Estimated remaining cost: ~$2.30 at current model pricing."

**Definition of Done:** Priority engine modified for bootstrap behavior. Coverage threshold triggering correctly. Cost estimation in telemetry output.

**Intra-epic dependencies:** None (first story).

---

#### Story 13.2: CLI Completion

**As a** user managing A-Priori, **I want** all remaining CLI commands (`librarian run/status`, `concept`, `validate`, `export`, `doctor`) **so that** I have a complete command-line interface for all operations.

**Context:** Adds the commands deferred from Phase 1. ERD §6.2.

**Acceptance Criteria:**

- Given `apriori librarian run --iterations 10 --budget 50000`, when run, then the librarian executes up to 10 iterations within a 50,000 token budget.
- Given `apriori librarian status`, when run, then it displays the current work queue depth, last run timestamp, and recent iteration results.
- Given `apriori concept "PaymentValidator"`, when run, then the full concept details are displayed (description, code references, edges, confidence, timestamps).
- Given `apriori validate`, when run, then integrity checks verify: all edge references point to existing concepts, all code references have valid file paths, no orphaned YAML files, SQLite matches YAML.
- Given `apriori export --format json`, when run, then the full knowledge graph is exported as a single JSON file.
- Given `apriori doctor`, when run, then it checks: tree-sitter availability, LLM connectivity (if configured), SQLite health, git integration, embedding model availability — and reports pass/fail for each with actionable guidance on failures.

**Definition of Done:** All commands working. `doctor` checking all subsystems. `validate` catching common integrity issues.

**Intra-epic dependencies:** Story 13.1 (progressive enrichment informs `librarian run` behavior).

---

#### Story 13.3: Documentation Suite

**As a** new user adopting A-Priori, **I want** comprehensive documentation covering setup, configuration, all MCP tools, architecture, and model quality recommendations **so that** I can adopt and operate the system without needing to read the source code.

**Context:** Documentation must enable self-service adoption with time to first value within 60 seconds (structural) and 10 librarian iterations (semantic). ERD §6.3.

**Acceptance Criteria:**

- Given the README.md, when a new user follows the quick-start guide, then they can go from zero to a queryable structural graph within 60 seconds.
- Given the configuration reference, when consulted, then every configuration option is documented with its default value, valid range, and effect on system behavior.
- Given the MCP tool reference, when consulted, then all 13 tools are documented with input/output schemas and usage examples.
- Given the architecture guide, when read by a new contributor, then they understand the four-layer architecture, the quality pipeline, and the adaptive priority system well enough to navigate the codebase.
- Given the model quality guide, when a user is choosing an LLM, then they can compare cost/quality/speed tradeoffs for Claude Sonnet, Claude Haiku, Qwen 7B, and other recommended models.
- Given the audit UI guide, when a user opens the UI for the first time, then they can navigate the graph, use the review workflow, and interpret the health dashboard.

**Definition of Done:** All six documentation deliverables written. Quick-start guide validated by someone who hasn't used the system before. Reviewed for accuracy against the implemented system.

**Intra-epic dependencies:** Stories 13.1 and 13.2 (documentation must reflect final behavior).

---

## Part 3: Story Dependency Map (Post-Decomposition)

Now that all stories are defined, the following cross-epic dependencies emerge:

### Hard Dependencies (must complete before downstream starts)

1. **Story 1.1 → Story 2.2:** The KnowledgeStore protocol references Concept/Edge types.
2. **Story 1.5 → Story 1.2:** Edge type vocabulary is loaded from config.
3. **Story 2.2 → Stories 2.3, 2.6:** Protocol must be defined before implementations begin.
4. **Stories 2.3 + 2.4 → Story 2.5:** Vector search requires both the SQLite base and the embedding service.
5. **Stories 2.5 + 2.6 → Story 2.7:** Dual writer composes both implementations.
6. **Story 2.7 → Stories 3.5, 4.1:** Graph builder and MCP server both need a working store.
7. **Story 6.1 → Stories 6.2, 6.3:** Adapters implement the protocol.
8. **Stories 6.2/6.3 → Story 7.4:** Co-regulation review needs an adapter for its LLM call.
9. **Stories 7.3 + 7.4 → Story 7.5:** Failure management handles failures from both quality levels.
10. **Stories 9.1 + 9.2 → Story 9.3:** Modulation requires both metrics and base priority.
11. **Epics 6 + 7 + 8 + 9 → Story 10.1:** The librarian orchestrator wires all four together.
12. **Stories 12.2 + 12.3 + 12.4 → Story 12.5:** Profile storage needs all three computation layers.
13. **Story 12.5 → Story 12.6:** The MCP tool queries stored profiles.
14. **Story 12.6 → Story 12.7:** Accuracy validation requires the blast_radius tool to be functional.

### Parallelization Opportunities

1. **Within Phase 1:** Stories 3.3 and 3.4 (Python and TypeScript parsers) can be developed in parallel. Stories 4.2 and 4.3 (read and write tools) can be developed in parallel.
2. **Phase 1 → Phase 2 overlap:** Epic 6 (LLM Adapters) depends only on Epic 1 — it can start as soon as models are done, while Phase 1's later epics are still in progress.
3. **Within Phase 2:** Epics 7, 8, and 9 can all proceed in parallel once Epic 6 and Epic 2 are available. Epic 11 (Audit UI) can be developed in parallel with Epic 10 (Librarian).
4. **Within Phase 3:** Stories 12.2, 12.3, and 12.4 (three impact computation layers) can be developed in parallel.

### Bottleneck Stories

These stories are on the critical path and block the most downstream work:

1. **Story 2.2 (KnowledgeStore Protocol)** — blocks all storage implementation and everything downstream.
2. **Story 2.3 (SQLite Implementation)** — blocks dual writer, which blocks everything that writes data.
3. **Story 6.1 (LLMAdapter Protocol)** — blocks all of Phase 2's LLM-dependent work.
4. **Story 10.1 (Loop Execution)** — the integration point where all Phase 2 components come together.

### Total Story Count

| Phase | Epic | Stories | Spikes |
|-------|------|---------|--------|
| 1 | Epic 1: Models & Config | 5 | 0 |
| 1 | Epic 2: Storage Layer | 9 | 1 (S-5) |
| 1 | Epic 3: Structural Engine | 7 | 1 (S-3) |
| 1 | Epic 4: MCP Server | 3 | 0 |
| 1 | Epic 5: CLI & First-Run | 2 | 0 |
| 2 | Epic 6: LLM Adapters | 4 | 0 |
| 2 | Epic 7: Quality Pipeline | 6 | 1 (S-8) |
| 2 | Epic 8: Knowledge Manager | 2 | 0 |
| 2 | Epic 9: Priority & Metrics | 3 | 0 |
| 2 | Epic 10: Librarian Orchestrator | 3 | 0 |
| 2 | Epic 11: Audit UI | 7 | 1 (S-7) |
| 3 | Epic 12: Blast Radius | 7 | 1 (S-4) |
| 4 | Epic 13: Polish & Docs | 3 | 0 |
| **Total** | **13 epics** | **61 stories** | **5 spikes** |

---

*This ingestion plan is ready for engineering review. Each story is sized to be completable within a single sprint by one developer. Stories should be refined further during sprint planning conversations between the engineering lead and implementing developers — the acceptance criteria and technical notes here provide the starting point for those conversations, not the final word.*
