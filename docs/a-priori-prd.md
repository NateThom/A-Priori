# A-Priori: Product Requirements Document

**Date:** 2026-04-03
**Status:** Draft
**Authors:** Nate Thom + Claude
**Prior Art:** `2026-03-25-a-priori-system-design.md`, `2026-03-25-a-priori-mvp.md`
**Research:** `research-compendium.md`

---

## 1. Purpose & Problem Statement

### 1.1 The Problem

AI coding agents are writing more code, faster, with less understanding of what their changes will break. A 2025 survey of 500 engineering leaders found that 92% report AI tools are increasing the blast radius of bad code. In early 2026, Amazon implemented a 90-day "code safety reset" across its critical engineering systems after a series of outages caused by AI-assisted changes with "high blast radius," including one incident where an AI tool deleted and recreated an entire coding environment.

The root cause is a context gap. AI agents lack persistent understanding of the codebases they modify. Every session starts from zero. The agent that spent twenty minutes understanding the payment flow yesterday has no memory of it today. The agent that knows `auth/middleware.ts` depends on three downstream services can't tell you that, because it discovered that relationship in a previous session and didn't retain it. The engineering leader who describes this as "the highest-value projects that most need de-risking are often the ones least amenable to LLM assistance, because they require deep context, involve low-level systems, or have high blast radius" captures the problem precisely.

Existing tools attack pieces of this problem but leave the core unsolved. Structural code analysis tools (codebase-memory-mcp, GitNexus, GraQle) parse ASTs and build call graphs, giving agents a map of what-calls-what, but they have no semantic understanding of what the code means, how it fits together conceptually, or what assumptions are shared between modules. Context retrieval systems (Augment Context Engine, Sourcegraph Cody) search indexes and serve relevant code to agents at query time, but they recompute context on every query rather than building persistent knowledge, and their cost scales linearly with usage rather than decreasing as understanding matures. Agent memory tools (Supermemory, Mem0, Zep) manage evolving knowledge for conversational agents, but they treat code as generic text and have no code-specific intelligence — no AST parsing, no dependency tracking, no concept of a function or a module.

No existing tool combines structural code intelligence with semantic understanding maintained by autonomous agents in a persistent, evolving knowledge graph that gets smarter over time and cheaper to operate as it matures.

### 1.2 The Opportunity

A-Priori fills this gap. It is a locally-built knowledge infrastructure layer that automatically constructs and maintains a hybrid structural-semantic knowledge graph for a codebase. It is designed to be consumed primarily by AI coding agents via MCP, though it is also usable by humans. Its flagship capability is pre-computed blast radius analysis — answering "if I change this, what else is affected and how confident are we?" in sub-second time, because autonomous librarian agents have already done the analysis before the question is asked.

The product's value proposition is that it converts expensive, repeated, session-bounded code understanding into cheap, persistent, evolving knowledge. The first time a librarian agent analyzes a module costs LLM tokens. Every subsequent query against that knowledge costs nothing. The knowledge graph gets richer over time while the cost of maintaining it decreases, because the structural layer's change detection ensures the librarian only re-analyzes code that has actually changed.

### 1.3 Design Principles

**The product is infrastructure, not intelligence.** A-Priori provides the persistent, structured, evolving knowledge base. The user brings their own LLM (Claude, GPT, local Qwen, or any other model) to power the librarian agents. The LLM is a pluggable dependency, not a built-in capability.

**Agents get the context they need, but ONLY the context they need.** Precision over volume. The knowledge graph enables targeted retrieval of exactly the relevant subgraph rather than dumping large amounts of raw code into an agent's context window.

**Pre-computed knowledge over just-in-time retrieval.** Unlike search-based tools that assemble context at query time, A-Priori builds understanding proactively through background analysis, so answers are ready before they're needed.

**The cost curve shall decrease over time.** Once knowledge is derived and persisted, it is not recomputed. The structural layer's change detection ensures LLM calls are made only for genuinely new or changed code. This is the opposite of per-query pricing models where cost is roughly constant regardless of how much understanding already exists.

**If you can name it, it's a concept, not a label.** Labels are reserved for metadata about the state of knowledge (`needs-review`, `auto-generated`, `deprecated`). Domain knowledge is modeled as concept nodes with typed edges between them. This prevents ontological drift and keeps the graph semantically clean.

---

## 2. Target Users

### 2.1 Primary: AI Coding Agents (via MCP)

The primary consumers of A-Priori are AI coding agents — Claude Code, Cursor, Windsurf, Cline, Codex, and any future MCP-compatible tool. These agents interact with the knowledge graph programmatically through MCP tools. They query for context before making changes, check blast radius before modifying code, and optionally contribute knowledge back to the graph as a side effect of their work.

The agent's experience should be that the knowledge graph is a trusted, always-available source of codebase understanding that reduces the number of exploratory tool calls (grep, file reads, glob searches) needed to accomplish a task. Research demonstrates that a weaker model with great context can outperform a stronger model with poor context. A-Priori provides the great context.

### 2.2 Secondary: Software Engineers

Engineers interact with A-Priori in three modes. First, as configurators — they set up the project, configure their LLM provider, tune the librarian's priority weights and budget, and manage the knowledge graph's lifecycle. Second, as consumers — they query the knowledge graph directly via CLI or (eventually) UI to understand unfamiliar code, assess the impact of planned changes, or explore architectural relationships. Third, as contributors — they provide high-value knowledge that the librarian can't derive autonomously, such as architectural decision records, design rationale, and domain-specific context that isn't captured in the code itself.

### 2.3 Tertiary: Engineering Teams & Leads

Team leads and engineering managers benefit from the knowledge graph as a form of living documentation. Onboarding new team members becomes faster because the graph contains structured, up-to-date understanding of how the system works. Institutional knowledge that would otherwise exist only in senior engineers' heads is captured and maintained. The blast radius tool provides risk assessment for proposed changes that informs sprint planning and code review prioritization.

---

## 3. Product Positioning & Differentiation

### 3.1 Category

A-Priori is a **persistent code intelligence layer** — infrastructure that sits between a codebase and the AI tools that work on it, providing structured, evolving understanding via MCP.

### 3.2 Competitive Differentiation

**Against Augment Context Engine:** Augment recomputes context on every query using a credit-based pricing model (40-70 credits per query). A-Priori pre-computes knowledge through background librarian analysis and stores it persistently. Augment is a search engine for code; A-Priori is a knowledge base that evolves. Augment's cost is roughly constant per query; A-Priori's cost decreases over time as the knowledge graph matures.

**Against Sourcegraph Cody:** Cody uses a search-first RAG architecture that retrieves relevant code before generating responses. It excels at enterprise-scale multi-repo search (300,000+ repositories) but has no persistent semantic understanding, no proactive analysis, and no temporal tracking. Cody's cross-repo awareness requires explicit @-mentions from the user. A-Priori proactively builds cross-module understanding without user prompting. Cody's free and Pro plans were discontinued in July 2025; A-Priori serves individual developers and small teams that Cody no longer targets.

**Against structural code graph tools (codebase-memory-mcp, GitNexus, GraQle):** These tools parse ASTs and build call graphs but have no semantic understanding. They can tell you what calls what, but not what the code means, what patterns it implements, or what implicit assumptions are shared between modules. A-Priori's structural layer provides the same AST-derived intelligence as these tools while adding semantic enrichment through its librarian agents. The combination enables blast radius analysis that spans both structural dependencies (what calls what) and semantic coupling (what shares assumptions with what).

**Against agent memory tools (Supermemory, Mem0, Zep, Letta):** These tools manage evolving knowledge for conversational agents but treat code as generic text. They have no AST parsing, no dependency tracking, no concept of functions or modules. A-Priori applies the best ideas from agent memory research — temporal reasoning, knowledge evolution, contradiction handling — to the specific domain of code understanding, where structural analysis provides a deterministic foundation that general-purpose memory tools lack.

### 3.3 What A-Priori Is Not

A-Priori is not an IDE or code editor. It is not an AI coding assistant. It is not a code generation tool. It does not write, modify, or execute code. It provides knowledge that other tools consume to do those things better. It is infrastructure, analogous to how a database provides storage that applications consume, or how a search index provides retrieval that interfaces consume.

---

## 4. Architecture Overview

### 4.1 Core Architecture: Four Layers

A-Priori is organized as four layers, each with distinct responsibilities, data ownership, and dependency characteristics.

**Layer 0 — The Structural Engine** runs entirely locally with zero LLM dependency. It performs AST parsing (via tree-sitter), call graph construction, dependency resolution, import mapping, type analysis, and git-diff impact detection. This layer is fast (sub-second per file), deterministic, and free to operate. It produces the structural knowledge graph — nodes for functions, classes, modules, and files; edges for calls, imports, inherits, and type references. This layer also serves as the change detection system that populates the librarian's work queue when code changes. The structural graph provides immediate value for code navigation and basic impact analysis even before any LLM enrichment occurs.

**Layer 1 — The Semantic Enrichment Engine** uses the user's configured LLM to add natural language understanding on top of the structural graph. Autonomous librarian agents, running in a Ralph-Wiggum loop execution model, process a prioritized work queue. Each iteration starts with a clean context, reads the current state of the knowledge graph and work queue from disk, picks the highest-priority item, formulates a targeted analysis prompt, sends it to the user's LLM, integrates the response into the knowledge graph, and exits. This layer adds concept descriptions, pattern labels, relationship characterizations, behavioral summaries, cross-module understanding, and semantic coupling detection.

**Layer 2 — The Knowledge Management Layer** handles the lifecycle of knowledge in the graph. It is deterministic logic that requires no LLM calls. Its responsibilities include temporal tracking (when was this knowledge derived, from what version of the code), staleness detection (this knowledge was derived from code that has since changed), contradiction resolution (new analysis says this module does X but existing knowledge says Y), confidence scoring (this relationship was inferred from a single analysis pass vs. confirmed across multiple passes), and garbage collection (removing knowledge about code that no longer exists). This layer implements the "never just append" philosophy — knowledge updates, merges, supersedes, and expires rather than accumulating indefinitely.

**Layer 3 — The Retrieval Interface** exposes the knowledge graph to consumers via MCP, direct API, and CLI. It handles query routing (should this query use graph traversal, vector search, or both?), context assembly (pulling the right subgraph to answer a question), response formatting (structuring knowledge for consumption by an LLM agent, IDE, or human), and blast radius queries (returning pre-computed impact profiles with confidence scores).

### 4.2 Deployment Model: Core Library + Thin Shells

The knowledge graph logic lives in a core Python package (`apriori`). The MCP server and librarian agent loop are thin wrappers that import and use the core. This provides clean separation without distributed systems complexity and naturally supports the storage abstraction and future entry points (CLI, UI server, scheduled jobs).

### 4.3 Storage Architecture

The MVP storage backend is SQLite with sqlite-vec for vector search, supplemented by flat YAML files as a portable, human-readable, version-controllable source of truth. Flat files are authoritative; the SQLite index is a derived acceleration layer that can be rebuilt from flat files at any time. Write operations update both simultaneously. This dual-write design provides the query performance of a database with the portability and inspectability of plain files.

The storage layer is defined by an abstract protocol (`KnowledgeStore`) that enables future backend swaps (Postgres + pgvector, Neo4j, etc.) without changes to the core library, MCP tools, or librarian agents.

### 4.4 Model-Agnostic Design

The interface between the librarian orchestrator and the LLM is a clean adapter abstraction. Adapters exist for cloud providers (Claude/Anthropic API, OpenAI API) and local model runtimes (Ollama). Model-specific prompt templates optimize quality for each provider while keeping all orchestration and knowledge management logic model-agnostic.

The user configures their LLM provider by specifying API credentials and model selection. Multi-model routing is supported: a user can configure a cheaper model (e.g., local Qwen 7B via Ollama) for routine function-level summarization and reserve a more capable model (e.g., Claude Sonnet via API) for deep architectural analysis. The adapter interface handles routing based on analysis complexity.

---

## 5. Data Model

### 5.1 Concept Node

A concept is the fundamental unit of semantic knowledge in the graph. Concepts represent named, describable aspects of the codebase at a higher level than individual code entities. A piece of code can belong to multiple concepts. "Payment Validation" is a concept that references specific functions; "Authentication Flow" is a concept that references modules, middleware, and configuration across multiple files.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | UUID | Yes | Unique identifier, auto-generated |
| `name` | string | Yes | Human-readable, unique within project |
| `description` | string | Yes | Rich, markdown-compatible description of what this concept represents |
| `labels` | set[string] | No | Housekeeping metadata only (e.g., `needs-review`, `auto-generated`, `deprecated`) |
| `code_references` | list[CodeReference] | No | Links to specific code entities (see 5.2) |
| `created_by` | `"agent"` or `"human"` | Yes | Provenance tracking |
| `verified_by` | optional string | No | Whether and by whom the concept was verified |
| `last_verified` | timestamp | No | When the concept's accuracy was last confirmed |
| `confidence` | float (0.0–1.0) | Yes | Confidence in the accuracy of this concept's description |
| `derived_from_code_version` | string | No | Git commit hash from which this knowledge was derived |
| `created_at` | timestamp | Yes | Creation time |
| `updated_at` | timestamp | Yes | Last modification time |

### 5.2 Code Reference (embedded in Concept)

Code references link concepts to specific code entities using a repair chain for resilience. Resolution tries each method in order, escalating only on failure.

The repair chain operates as follows. First, the symbol name is used as the primary lookup key — this is fast, free, and exact, working approximately 80% of the time. Second, the content hash detects code changes even when the symbol resolves correctly. A hash mismatch triggers a `needs-review` label on the parent concept. Third, the semantic anchor — a natural language description — is used as a fallback to re-find code after major refactors. This step is expensive (requires LLM) and is invoked only when symbol lookup fails.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `symbol` | string | Yes | e.g., `validate_amount` — primary lookup key |
| `file_path` | string | Yes | e.g., `src/payments/validate.py` |
| `content_hash` | string | Yes | Hash of referenced code at last verification |
| `semantic_anchor` | string | Yes | Natural language description for repair fallback |
| `line_range` | optional tuple[int, int] | No | Line range hint, not authoritative |

### 5.3 Edge

Edges represent typed, directed relationships between concepts. Every edge carries a confidence score reflecting how reliably the relationship has been established.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | UUID | Yes | Unique identifier |
| `source` | concept_id | Yes | Source concept |
| `target` | concept_id | Yes | Target concept |
| `edge_type` | string | Yes | From controlled vocabulary (see 5.4) |
| `confidence` | float (0.0–1.0) | Yes | Confidence in this relationship |
| `evidence_type` | `"structural"`, `"semantic"`, or `"historical"` | Yes | How this relationship was established |
| `metadata` | optional dict | No | Additional context, notes |
| `derived_from_code_version` | string | No | Git commit hash from which this edge was derived |
| `created_at` | timestamp | Yes | Creation time |
| `updated_at` | timestamp | Yes | Last modification time |

### 5.4 Edge Type Vocabulary

The edge vocabulary is organized into three categories corresponding to how relationships are established.

**Structural edges** are derived deterministically from AST analysis (Layer 0). They have 1.0 confidence by default.

| Edge Type | Description |
|-----------|-------------|
| `calls` | Function/method X invokes function/method Y |
| `imports` | Module X imports from module Y |
| `inherits` | Class X inherits from class Y |
| `type-references` | Entity X references type Y |

**Semantic edges** are derived by librarian agents through LLM analysis (Layer 1). They carry variable confidence scores.

| Edge Type | Description |
|-----------|-------------|
| `depends-on` | Concept X requires concept Y to function (logical dependency) |
| `implements` | Concept X is the concrete realization of concept Y |
| `relates-to` | Generic semantic association (fallback when a more specific type doesn't fit) |
| `shares-assumption-about` | X and Y both depend on the same implicit contract (schema, config, API format) |
| `extends` | Concept X builds on or specializes concept Y |
| `supersedes` | Concept X replaced concept Y |
| `owned-by` | Person or team responsible for concept X |

**Historical edges** are derived from git history analysis (Layer 2). They carry confidence based on co-change frequency.

| Edge Type | Description |
|-----------|-------------|
| `co-changes-with` | Entities X and Y have historically been modified together, suggesting implicit coupling |

New edge types may be added through a governance process (deferred to post-MVP). The vocabulary is defined in `apriori.config.yaml` and is the single source of truth for valid edge types.

### 5.5 Impact Profile (embedded in Concept)

Every concept node carries a continuously-maintained impact profile that describes what happens if that concept's code changes. This is the data structure that powers blast radius queries.

| Field | Type | Description |
|-------|------|-------------|
| `structural_impact` | list[ImpactEntry] | Nodes with direct structural dependencies (from Layer 0). Always 1.0 confidence. |
| `semantic_impact` | list[ImpactEntry] | Nodes with inferred semantic coupling (from Layer 1). Variable confidence. |
| `historical_impact` | list[ImpactEntry] | Nodes with empirical co-change patterns (from Layer 2). Confidence based on frequency/recency. |
| `last_computed` | timestamp | When this impact profile was last fully computed |
| `structural_last_updated` | timestamp | When the structural layer last updated this profile |

Each `ImpactEntry` contains:

| Field | Type | Description |
|-------|------|-------------|
| `target_concept_id` | UUID | The concept that would be affected |
| `confidence` | float (0.0–1.0) | How confident we are in this impact |
| `relationship_path` | list[edge_id] | The chain of edges connecting source to target |
| `depth` | int | Number of hops from source to target |
| `rationale` | string | Human-readable explanation of why this impact exists |

### 5.6 Work Item

Work items represent units of analysis work for the librarian agents. They are persisted in SQLite as a separate table (not concept nodes).

| Field | Type | Description |
|-------|------|-------------|
| `id` | UUID | Unique identifier |
| `item_type` | WorkItemType enum | Category of work (see below) |
| `description` | string | What needs to be done |
| `concept_id` | optional UUID | Related concept, if applicable |
| `file_path` | optional string | Related file, if applicable |
| `priority_score` | float | Computed advisory priority |
| `resolved` | bool | Whether this item has been completed |
| `failure_count` | int | Number of times this item has been attempted and failed quality verification |
| `failure_records` | list[FailureRecord] | Structured history of previous failed attempts (see below) |
| `escalated` | bool | Whether this item has exceeded the failure threshold and been escalated |
| `created_at` | timestamp | Creation time |
| `resolved_at` | optional timestamp | Completion time |

Each `FailureRecord` contains:

| Field | Type | Description |
|-------|------|-------------|
| `attempted_at` | timestamp | When the attempt was made |
| `model_used` | string | Which LLM model processed this attempt |
| `prompt_template` | string | Which prompt template was used |
| `failure_reason` | string | Which quality check failed and why |
| `quality_scores` | optional dict | Scores from the co-regulation review, if applicable |
| `reviewer_feedback` | optional string | Specific feedback from the co-regulation agent for use in retry |

When a work item's `failure_count` reaches a configurable threshold (default: 3), the item shall be escalated. Escalation moves the item to a lower priority tier, flags it with `needs-human-review`, and if multi-model routing is configured, marks it for processing by a more capable model on the next attempt. The failure records are preserved so that any future attempt — whether by the librarian or a human — has full diagnostic context about what was tried and why it failed.

**Work item types:**

| Type | Source | Description |
|------|--------|-------------|
| `investigate_file` | Structural layer (new/unanalyzed files) | Code exists with no semantic coverage |
| `verify_concept` | Change detection (code changed since last analysis) | Concept's referenced code has been modified |
| `evaluate_relationship` | Semantic-graph disagreement scan | Semantic search suggests a relationship that the graph doesn't have |
| `reported_gap` | External agent via `report_gap` MCP tool | An agent or human flagged a knowledge gap |
| `review_concept` | Label trigger | Concept is labeled `needs-review` |
| `analyze_impact` | Structural layer (dependency graph changed) | A concept's structural dependencies changed; impact profile needs recomputation |

---

## 6. Librarian Agent System

### 6.1 Execution Model: Ralph-Wiggum Loop

The librarian agents shall execute using the Ralph-Wiggum loop pattern. Each iteration is a fresh, stateless process that reads the knowledge graph and work queue from disk, picks one task, performs the analysis using the user's configured LLM, writes results back to the knowledge graph, and exits. The loop restarts with a clean context for the next iteration.

This execution model provides four critical properties. First, context window management is a non-issue because each iteration starts clean — the knowledge graph on disk is the persistent memory, not the context window. Second, cost control is natural because the user controls how many iterations the loop runs. Third, model-agnosticism is trivially achievable because models can be swapped between iterations without session state to migrate. Fourth, the librarian can work through a codebase of any size — it just takes more iterations, not more context.

### 6.2 Iteration Workflow

Each librarian iteration shall follow this sequence:

1. Read the current work queue from the knowledge store.
2. Select the highest-priority unresolved work item based on the adaptively-modulated priority score (Section 6.3.1), with bias toward items related to the developer's recent activity. If the selected item has previous failure records, include the failure history in the analysis context.
3. Load the relevant subgraph context — the concept being analyzed, its structural neighborhood (from Layer 0), and any existing semantic knowledge about related concepts.
4. Formulate a targeted analysis prompt using model-specific templates. The prompt includes the code to be analyzed, the structural context, instructions for what knowledge to extract, and any failure feedback from previous attempts on this work item.
5. Send the prompt to the user's configured LLM via the adapter interface.
6. Run the output through the Level 1 automated consistency check (Section 6.4.1). If the check fails, write a failure record to the work item and exit without committing.
7. If co-regulation review is enabled, run the output through the Level 1.5 co-regulation review (Section 6.4.2). If the review fails, write a failure record — including the co-regulation agent's specific feedback — to the work item and exit without committing.
8. Parse the validated output and integrate the resulting knowledge into the graph via Layer 2's knowledge management logic (update, merge, contradict, or create entries as appropriate).
9. Mark the work item as resolved and exit.

### 6.3 Priority Scoring

Each work item receives a computed advisory priority score. The score is advisory, not directive — the librarian sees the full backlog with scores but the selection logic may incorporate additional heuristics (such as proximity to recent developer activity).

```
priority = w1 * staleness
         + w2 * needs_review
         + w3 * coverage_gap
         + w4 * git_activity
         + w5 * semantic_delta
         + w6 * developer_proximity
```

| Weight | Default | Description |
|--------|---------|-------------|
| `staleness` | 0.25 | How long since the concept's knowledge was last verified relative to code change recency |
| `needs_review` | 0.20 | Binary: 1 if the concept is flagged `needs-review`, 0 otherwise |
| `coverage_gap` | 0.15 | Whether unreferenced code exists with no semantic coverage |
| `git_activity` | 0.10 | Change frequency in the related files over a configurable window |
| `semantic_delta` | 0.10 | Semantic search suggests a relationship that the graph doesn't capture |
| `developer_proximity` | 0.20 | How close the work item is to the developer's recently-modified files (measured by graph distance) |

All base weights are configurable in `apriori.config.yaml`.

#### 6.3.1 Adaptive Priority Modulation

The base priority weights defined above are modulated dynamically by a goal-seeking feedback loop tied to the success metrics defined in Section 9. Before each librarian iteration selects a work item, the system runs a lightweight health check that computes the current values for each core product metric (coverage, freshness, blast radius completeness) and compares them against their configured targets.

For each metric, the system computes a deficit — how far below target the metric currently sits. This deficit becomes a multiplier on the base weights most relevant to that metric. Coverage deficit boosts the effective weight of `coverage_gap`, causing the librarian to prioritize `investigate_file` work items. Freshness deficit boosts `staleness` and `needs_review`, causing the librarian to prioritize `verify_concept` work items. Blast radius completeness deficit boosts work items of type `analyze_impact`.

The modulated priority formula is:

```
effective_weight[i] = base_weight[i] * (1 + metric_deficit[relevant_metric] * modulation_strength)
```

The `modulation_strength` parameter (default: 1.0) controls how aggressively the feedback loop shifts priorities. A value of 0.0 disables modulation entirely, falling back to static base weights. Higher values cause the librarian to respond more aggressively to metric deficits. This parameter is user-configurable.

The metric targets themselves shall be user-configurable with the following opinionated defaults:

| Metric | Default Target | Description |
|--------|---------------|-------------|
| `coverage_target` | 0.80 | 80% of source files referenced by at least one concept |
| `freshness_target` | 0.90 | 90% of concepts verified more recently than their code's last modification |
| `blast_radius_completeness_target` | 0.70 | 70% of concepts have a non-stale impact profile |

The practical effect of this feedback loop is that the librarian's behavior adapts organically to the knowledge graph's current state. Early in a project's life, when coverage is low, the librarian focuses on investigating new files and building breadth. As coverage improves, the librarian naturally shifts toward maintaining freshness and deepening existing knowledge. If a major refactor causes freshness to plummet, the librarian automatically pivots to re-verification without anyone needing to manually adjust weights. The librarian's telemetry shall surface the current metric values, their targets, and the resulting modulated weights so that the user can see why the librarian is making the choices it makes.

### 6.4 Review & Quality Assurance System

The knowledge graph's value depends entirely on its trustworthiness. Confidence scores assigned by the librarian are self-assessed by the same system that produced the knowledge, so external review is essential for calibrating trust. The review system operates at three levels, each with different mechanisms and degrees of human involvement.

#### 6.4.1 Level 1: Automated Consistency Review

Every librarian iteration shall pass through a rule-based consistency check before its output is committed to the knowledge graph. These checks are deterministic, require no LLM calls, and execute in milliseconds. They verify the following conditions: the analysis produced a non-empty, non-generic description (not boilerplate that could describe any function); any asserted relationships reference concepts that actually exist in the graph; confidence scores are within the valid range of 0.0 to 1.0; the output is parseable into the expected data model format; and if the librarian asserts a dependency relationship, the structural graph is checked for corroborating evidence (an import, call, or type reference between the relevant code entities). Structural corroboration is not required for the output to pass — a semantic relationship with no structural backing may be legitimate — but the absence of structural support shall reduce the confidence score by a configurable factor (default: 0.2) and attach a metadata note indicating the lack of structural corroboration.

#### 6.4.2 Level 1.5: Co-Regulation Review (LLM-as-Judge)

After the automated consistency check passes, the librarian's output shall be evaluated by a co-regulation review step. This step makes a second LLM call that receives the librarian's output alongside the code that was analyzed and the structural context, and evaluates it on three quality dimensions.

**Specificity** assesses whether the description is specific to the actual code analyzed or whether it is generic boilerplate that could describe any module. A description like "this module handles data processing" for a payment validation function would score low on specificity.

**Structural corroboration** assesses whether the relationships identified by the librarian are consistent with what the structural graph shows. This is a deeper, LLM-powered version of the rule-based check in Level 1 — it reasons about whether the relationships make sense given the code structure rather than just checking for the presence of edges.

**Completeness** assesses whether the analysis addressed the main entities and behaviors in the code or whether it missed obvious aspects. If the code contains error handling, validation logic, and database interaction, an analysis that only describes the database interaction would score low on completeness.

The co-regulation review produces a structured assessment containing a score (0.0 to 1.0) on each dimension, a composite pass/fail verdict, and on failure, specific feedback identifying what was insufficient and how it could be improved. This feedback is written into the work item's failure record (see Section 5.6) so that the next librarian iteration attempting the same work item has guidance on what to do differently.

The co-regulation review shall use the same LLM model the librarian used for analysis by default. Users may optionally configure a separate review model if they wish to use a different model for quality assessment. The co-regulation review is enabled by default but can be disabled via configuration for users on tight token budgets. When enabled, it approximately doubles the LLM cost per librarian iteration (one call for analysis, one call for review). The token budget management system (Section 6.5) shall account for this when calculating iteration costs.

#### 6.4.3 Failure Breadcrumbs and Escalation

When a librarian iteration fails either the automated consistency check (Level 1) or the co-regulation review (Level 1.5), the output shall not be committed to the knowledge graph. Instead, the system shall write a structured failure record to the work item (as defined in Section 5.6) capturing what was attempted, which checks failed, the specific feedback from the co-regulation review (if applicable), and the model and prompt template used. The work item's `failure_count` is incremented and the item remains unresolved in the queue.

When a subsequent librarian iteration picks up a work item that has previous failure records, the prompt shall include the failure history — specifically, the failure reasons and any co-regulation feedback — so the librarian can attempt a different analytical approach. The prompt should instruct the librarian to consider the previous failure feedback and adjust its analysis accordingly.

When a work item's `failure_count` reaches the escalation threshold (default: 3, configurable), the item shall be escalated. Escalation performs three actions: the work item's effective priority is reduced by a configurable factor (default: 0.5x) so the librarian focuses on more tractable work; the item is flagged with `needs-human-review` so it surfaces in the audit UI for human attention; and if multi-model routing is configured, the item is marked for processing by the configured review-tier model on its next attempt.

#### 6.4.4 Level 2: Surfaced Human Review

The system shall make the librarian's outputs visible and easy for engineers to validate without requiring them to seek it out. This is a pull model — the system surfaces its work for casual review rather than interrupting the developer.

The audit UI (Section 8A) and the MCP tool surface shall provide the following review capabilities: viewing recently-created or recently-updated concepts with their full context (description, code references, confidence scores, evidence type, when derived, from what code version); filtering concepts by confidence level to surface low-confidence knowledge for review; viewing the librarian's recent activity log showing what was analyzed, what was created, what failed, and why; and marking a concept as verified, which promotes the concept by setting `verified_by`, updating `last_verified`, and boosting the confidence score.

When a developer reviews a concept and provides a correction (editing the description, adding or removing relationships, adjusting the characterization), the correction is tracked as a review outcome. Review outcomes are first-class data: they record the nature of the error (was the description wrong? was a relationship missing? was a relationship hallucinated? was confidence miscalibrated?) and over time create an error profile of the librarian's systematic weaknesses. This error profile can inform prompt template refinements and confidence score calibration.

#### 6.4.5 Level 3: Empirical Validation (Deferred)

The most powerful review mechanism requires the least human effort but is deferred to post-MVP. When A-Priori predicts a blast radius for a change and the change is subsequently made via a merged PR, the system shall compare its prediction against the actual set of files modified in the PR. This retrospective analysis provides ground-truth calibration for confidence scores and identifies areas where the knowledge graph is systematically wrong. The MVP data model (impact profiles with timestamps, concept versioning) shall be designed to support this validation when it is built, even though the validation logic itself is deferred.

### 6.5 Token Budget Management

The product shall help users understand and control their LLM spending. This includes a configurable maximum token budget per iteration (preventing any single analysis from consuming excessive resources), a configurable maximum iterations per loop run (controlling total spend for a background session), telemetry tracking tokens consumed, knowledge nodes created/updated, and work items resolved per run, and progressive enrichment on initial setup — when bootstrapping a new codebase, the librarian shall start with the developer's actively-edited files and expand outward based on configured budget limits rather than attempting to analyze the entire codebase at once.

---

## 7. Blast Radius & Impact Analysis

### 7.1 Overview

Blast radius analysis is A-Priori's flagship capability. It answers the question "if I change this code, what else is affected and how confident are we?" in sub-second time by querying pre-computed impact profiles rather than performing analysis at query time.

### 7.2 Three-Layer Impact Model

Impact profiles are built from three complementary layers.

**Structural impact** is derived deterministically from Layer 0's AST analysis. It traces the call graph and dependency tree outward from a changed entity to find everything that calls it, imports it, or inherits from it. Structural impact always carries 1.0 confidence and is updated instantly when code changes. This layer catches all explicit, code-level dependencies.

**Semantic impact** is derived by the librarian agents in Layer 1. It identifies modules that share implicit assumptions — they depend on the same database schema, make the same API contract assumptions, or implement coupled parts of the same business flow without direct structural relationships. Semantic impact carries variable confidence based on the recency and depth of the librarian's analysis. This layer catches the dependencies that structural analysis misses — the ones that cause the most surprising and costly breakages.

**Historical impact** is derived from git history analysis in Layer 2. It identifies files and concepts that have historically been modified together, suggesting coupling that isn't captured by either structural or semantic analysis. Historical impact carries confidence based on the frequency and recency of co-change patterns. This layer provides empirical evidence that supplements the other two.

### 7.3 Blast Radius Query Interface

The MCP tool surface shall include a dedicated `blast_radius` tool that accepts a concept identifier (name or ID), file path, or function symbol and returns the pre-computed impact profile. The response shall be structured as a prioritized list of affected concepts, sorted by a composite score combining confidence and depth, with the following information per entry: concept name and ID, confidence score, impact layer (structural/semantic/historical), depth (hops from source), relationship path through the graph, and a human-readable rationale for why this concept is affected.

The tool shall also accept an optional `depth` parameter to limit the number of hops traversed and a `min_confidence` parameter to filter out low-confidence impacts.

### 7.4 Impact Profile Maintenance

Impact profiles shall be maintained continuously rather than computed on demand. The structural layer updates impact profiles instantly when AST analysis detects a dependency change. The semantic layer updates impact profiles as a side effect of the librarian's analysis work — when the librarian analyzes a concept and discovers a new semantic relationship, the impact profiles of both the source and target concepts are updated. The historical layer updates impact profiles periodically by analyzing recent git history for co-change patterns.

When an impact profile's underlying data changes (a structural dependency is added or removed, a semantic relationship's confidence changes, or a co-change pattern strengthens or weakens), the profile's `last_computed` timestamp is updated. Profiles whose `last_computed` is older than a configurable threshold are flagged as stale, and `analyze_impact` work items are generated for the librarian.

---

## 8. MCP Tool Surface

### 8.1 Read Tools

**`search`** — Unified lookup with multiple modes and composable filters. Modes include `semantic` (vector similarity), `keyword` (text matching), `exact` (name or ID lookup), and `file` (concepts referencing a given file path). All modes support composable filters on labels, provenance, verification status, timestamps, staleness, edge types, and file references. Returns a ranked list of concepts with relevance scores.

**`traverse`** — Graph traversal from a starting concept. Accepts start concept, optional edge type filter, max hops, max nodes, and traversal strategy (BFS or DFS). Returns a subgraph — the set of concepts and edges reachable from the start, respecting filters.

**`blast_radius`** — Returns the pre-computed impact profile for a concept, file, or symbol. Accepts optional depth and minimum confidence filters. Returns a prioritized, scored list of affected concepts with rationale (see 7.3).

**`get_concept`** — Retrieve a single concept by ID or name, including its full metadata, code references, edges, and impact profile.

**`list_edge_types`** — Returns the current edge type vocabulary with descriptions.

**`get_status`** — Returns knowledge graph health metrics: total concepts, total edges, coverage percentage (files with at least one concept reference vs. total source files), staleness metrics, work queue depth, and recent librarian activity.

### 8.2 Write Tools

**`create_concept`** — Create a new concept node with name, description, optional labels, and optional code references.

**`update_concept`** — Update an existing concept's description, labels, or code references.

**`delete_concept`** — Remove a concept and its associated edges.

**`create_edge`** — Create a typed, directed edge between two concepts.

**`update_edge`** — Modify an edge's type, confidence, or metadata.

**`delete_edge`** — Remove an edge.

**`report_gap`** — Flag a knowledge gap for the librarian's attention. Creates a `reported_gap` work item in the maintenance backlog. Accepts a description and optional context.

---

## 8A. Human Audit UI

### 8A.1 Purpose and Scope

The audit UI is a local web application that provides a visual interface for inspecting, reviewing, and validating the knowledge graph. Its primary purpose is to give engineers confidence that the librarian is producing accurate knowledge, and to enable the Level 2 human review workflow described in Section 6.4.4.

The audit UI is an **audit and review interface**, not a management application. Creating, editing, and deleting concepts and edges remain CLI and MCP operations. The UI is for reading, reviewing, and verifying — not for writing. This keeps the UI scope bounded and avoids building duplicate write paths that would need to be maintained alongside the CLI and MCP tools. The one exception is the review workflow: the UI shall support marking concepts as verified and providing corrections, since these are review actions that flow through the same data model as other knowledge updates.

### 8A.2 Deployment Model

The audit UI shall be a locally-served single-page web application, started via a shell command (`apriori-ui`). It serves on localhost and reads from the same SQLite database that the MCP server and librarian use. It does not require authentication (it runs on the developer's local machine), does not require internet connectivity, and does not transmit any data externally.

### 8A.3 Required Capabilities

**Knowledge Graph Visualization.** The UI shall render the knowledge graph as an interactive node-and-edge visualization. Concepts appear as nodes, edges as connections. The user can click any concept to see its full details: description, code references, confidence score, evidence type, when it was created, when it was last verified, what code version it was derived from, and its impact profile. The visualization shall support filtering by edge type (show only structural edges, only semantic edges, etc.), by confidence threshold, by label, and by recency. The visualization shall visually distinguish between high-confidence and low-confidence knowledge (e.g., through opacity, color coding, or line style).

**Librarian Activity Feed.** The UI shall display a chronological feed of the librarian's recent work. Each entry shows what work item was processed, what concept was created or updated, the co-regulation review score (if applicable), whether the iteration passed or failed quality checks, and if it failed, the failure reason. This feed is the primary mechanism by which a developer can casually monitor whether the librarian is doing useful work.

**Review Workflow.** The UI shall support the Level 2 review actions: viewing a concept's details alongside the actual code it references (showing the code inline or linking to it), marking a concept as verified (setting `verified_by` and updating `last_verified`), and flagging a concept as needing correction (which opens an inline editor for the description and relationships, submits the correction, and logs the review outcome for the librarian's error profile).

**Health Dashboard.** The UI shall display the current values of the core product metrics from Section 9 (coverage, freshness, blast radius completeness) alongside their configured targets. It shall also show the current effective priority weights (including the adaptive modulation from Section 6.3.1) and the work queue depth, so the user can understand at a glance what state the knowledge graph is in and what the librarian is currently focused on.

**Escalated Items View.** The UI shall provide a dedicated view for work items that have been escalated due to repeated failures (see Section 6.4.3). This view shows the full failure history for each escalated item, making it easy for a developer to assess whether the failure is due to a limitation of the LLM model, an inherently ambiguous piece of code, or a problem with the analysis prompt.

---

## 9. Success Metrics

The success metrics defined in this section serve a dual purpose. They are the product-level outcomes that determine whether A-Priori is working as intended, and they are the inputs to the adaptive priority modulation system (Section 6.3.1) that guides the librarian's work. All metric targets are user-configurable with the opinionated defaults listed below. Adjusting a target changes both how success is reported and how the librarian prioritizes its work — if a user cares more about freshness than coverage, they can raise the freshness target and lower the coverage target, and the librarian's behavior will adapt accordingly.

### 9.1 Core Product Metrics

**Knowledge coverage** shall be measured as the percentage of source files in the repository that are referenced by at least one concept. The target for a fully-indexed codebase is greater than 80% file coverage.

**Knowledge freshness** shall be measured as the percentage of concepts whose `last_verified` timestamp is more recent than the last modification time of their referenced code. The target is greater than 90% freshness for actively-developed code (files modified in the last 30 days).

**Blast radius accuracy** shall be measured by comparing A-Priori's predicted impact set for a change against the actual set of files modified in the corresponding pull request (using historical PRs as ground truth). The target is greater than 70% recall (the percentage of actually-affected files that A-Priori predicted) and greater than 50% precision (the percentage of predicted files that were actually affected).

**Query latency** for all MCP read tools shall be under 500ms for the 95th percentile of queries on a knowledge graph with up to 10,000 concept nodes.

### 9.2 Cost Efficiency Metrics

**Cost per concept** shall be tracked as the average LLM token cost to create and maintain a concept node (including initial analysis plus ongoing verification). This metric should decrease over time as the knowledge graph matures and fewer new concepts need creation.

**Iteration yield** shall be tracked as the average number of knowledge graph mutations (concepts created, updated, or edges added) per librarian iteration. The target is greater than 1.0 mutations per iteration (each iteration should produce useful knowledge).

### 9.3 User Experience Metrics

**Time to first value** shall be measured as the elapsed time from installation to the first useful MCP query response. The structural layer should provide basic value (file dependencies, call graphs) within 60 seconds of initial setup. Semantic enrichment should begin producing concept-level knowledge within the first 10 librarian iterations.

**Agent efficiency improvement** should be measurable as a reduction in the number of tool calls (grep, file reads, glob searches) that an AI coding agent makes when A-Priori is available versus when it is not. The target is a 30% or greater reduction in exploratory tool calls.

---

## 10. Scope Boundaries

### 10.1 MVP Scope (Build Now)

The MVP shall include the complete four-layer architecture as described in Section 4, the full data model as described in Section 5 (including failure records on work items and impact profiles on concepts), the librarian agent system with Ralph-Wiggum loop execution (Section 6), the three-level review system including automated consistency checks and the co-regulation LLM-as-judge (Section 6.4), blast radius analysis with all three impact layers (Section 7), the complete MCP tool surface (Section 8), the human audit UI for knowledge graph inspection and review workflow (Section 8A), local storage backend (SQLite + sqlite-vec + flat YAML files), the storage abstraction protocol for future backend swaps, model-agnostic adapter layer with adapters for Anthropic API and Ollama, the adaptive priority modulation system driven by user-configurable success metric targets (Section 6.3.1), configuration system with sensible defaults, initial bootstrap via repo crawl, diff-based maintenance backlog generation via git integration, and CLI for setup, status, and manual queries.

### 10.2 Deferred (in priority order)

1. Full coverage scan and semantic-graph disagreement scan (automated gap detection).
2. Multi-model routing (cheap model for routine work, expensive model for complex analysis within a single configuration).
3. Empirical validation system (Level 3 review) — retrospective comparison of blast radius predictions against actual PR outcomes for ground-truth confidence calibration.
4. RAG chat (`ask` tool) — conversational interface for querying the knowledge graph in natural language.
5. Persistent quality monitoring agent — an advanced evolution of the MVP co-regulation review that runs as a continuous background process, monitors the knowledge graph for systematic quality issues across many concepts, detects knowledge drift over time, and proactively generates improvement work items. This builds on the per-iteration co-regulation review in the MVP.
6. Multi-repository support — federated graphs across multiple repositories with cross-repo relationship tracking.
7. Cloud/hosted storage backend (Postgres + pgvector, Neo4j).
8. Federation between A-Priori instances across teams or organizations.
9. Edge type governance workflow (formal process for proposing, vetting, and migrating edge types).

### 10.3 Explicitly Out of Scope

A-Priori shall not write, modify, or execute code. It shall not provide code completion, code generation, or code review capabilities. It shall not replace or compete with IDE features. It shall not require a specific IDE, editor, or development environment. It shall not require an internet connection for core functionality (structural analysis and knowledge graph queries work fully offline; only the librarian's LLM calls require network access, and even those can be local if using Ollama). It shall not store or transmit source code to any service other than the user's explicitly configured LLM provider.

---

## 11. Assumptions, Risks, and Dependencies

### 11.1 Assumptions

The codebase is managed with git, which provides change history, diff information, and commit metadata that the structural layer and historical impact analysis depend on. The user has access to at least one LLM provider (cloud API or local model) for the librarian agents to use. The user's development machine has sufficient resources to run the knowledge graph database (SQLite), the structural analysis engine (tree-sitter), and the librarian orchestration logic concurrently with normal development work. These components are lightweight (estimated at less than 500MB RAM total, excluding the LLM if run locally).

### 11.2 Risks

**Semantic analysis quality is dependent on the user's chosen LLM.** If a user configures a small, low-quality local model, the semantic layer's output may be unreliable. Mitigation: confidence scoring on all semantic knowledge, the co-regulation review as a quality gate (Section 6.4.2), automated consistency checks, human review via the audit UI, and clear documentation about model quality tradeoffs.

**The co-regulation review approximately doubles the LLM cost per librarian iteration.** For users on tight token budgets, this may be prohibitive. Mitigation: the co-regulation review is enabled by default but can be disabled via configuration. Users who disable it accept lower knowledge quality assurance in exchange for lower cost. The token budget management system accounts for co-regulation cost when estimating iteration costs.

**Initial bootstrapping of large codebases may consume significant LLM tokens.** A 100,000-line codebase could require hundreds of librarian iterations to achieve reasonable semantic coverage. Mitigation: progressive enrichment strategy that prioritizes the developer's active working area, configurable budget limits, and clear telemetry so users can predict and control costs.

**The knowledge graph may accumulate incorrect or outdated knowledge over time.** If the librarian produces low-quality analysis that passes the quality gate, it persists in the graph and may be served to agents as trusted context. Mitigation: confidence scoring, temporal tracking (knowledge derived from old code versions is flagged), human verification workflow (concepts can be marked as verified), and the ability to regenerate knowledge from scratch if needed.

**Tree-sitter parsing coverage varies by language.** Some languages have mature, high-quality tree-sitter grammars; others have incomplete or buggy grammars. The structural layer's quality is bounded by tree-sitter's quality for the target language. Mitigation: graceful degradation — if structural analysis fails for a file, it is excluded from the structural graph but can still be analyzed semantically by the librarian.

### 11.3 Dependencies

Python 3.11 or higher. SQLite with sqlite-vec extension. Tree-sitter and language-specific grammar packages. PyYAML for flat file serialization. MCP Python SDK for the MCP server shell. At least one LLM provider adapter (Anthropic API client or Ollama client). Git CLI for change detection and history analysis.

---

## 12. Phasing & Milestones

### Phase 1: Foundation

Deliver the structural engine (Layer 0), the core data model, the storage layer (SQLite + flat files), and basic MCP read/write tools. At the end of this phase, a user can point A-Priori at a repository and get a structural knowledge graph (functions, classes, modules, and their call/import/inheritance relationships) queryable via MCP. No LLM required. This provides immediate value comparable to codebase-memory-mcp or GitNexus.

### Phase 2: Semantic Intelligence & Audit

Deliver the librarian agent system (Layer 1), the model-agnostic adapter layer, the knowledge management layer (Layer 2), the work queue system with failure records and adaptive priority modulation, the co-regulation review (LLM-as-judge), and the human audit UI. At the end of this phase, the librarian can autonomously analyze code using the user's LLM and build semantic knowledge (concept descriptions, semantic relationships, pattern labels) on top of the structural graph. The co-regulation agent validates each iteration's output before it enters the graph. Engineers can inspect the knowledge graph, review the librarian's work, and verify or correct concepts through the audit UI. The knowledge graph evolves over time as the librarian runs, with quality assured by automated checks, LLM review, and human oversight.

### Phase 3: Blast Radius

Deliver the impact profile data model, the three-layer impact computation (structural + semantic + historical), the `blast_radius` MCP tool, and impact profile maintenance. At the end of this phase, agents can query "what breaks if I change this?" and receive pre-computed, confidence-scored impact assessments.

### Phase 4: Polish & Scale

Deliver token budget management and cost telemetry, progressive enrichment for initial bootstrapping, multi-model routing configuration, comprehensive CLI for setup, status, diagnostics, and manual queries, and documentation sufficient for self-service adoption.

---

## 13. Key Design Decisions

This section records architectural decisions and their rationale for future reference.

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Primary consumer | Agents (MCP-first) | Agents need precise, structured context; human audit UI supplements but does not replace MCP |
| Execution model for librarian | Ralph-Wiggum loop | Clean context per iteration, natural cost control, model-agnostic, handles any codebase size |
| Node granularity | Concept-level (not code-entity-level) | Concepts reference code but live at a higher semantic level; one piece of code can belong to multiple concepts |
| Edge typing | Controlled vocabulary, three categories (structural, semantic, historical) | Structural edges from AST are deterministic; semantic edges from LLM are probabilistic; separating them enables confidence scoring |
| LLM dependency | Bring your own model via adapter interface | The product is infrastructure, not intelligence; model-agnosticism enables both cloud and local operation |
| Storage | SQLite + flat YAML files with abstract protocol | Zero cost, private, portable, inspectable; protocol enables future backend swaps |
| Code references | Repair chain (symbol → hash → semantic anchor) | Symbol for speed, hash for change detection, semantic anchor for resilience across refactors |
| Blast radius | Pre-computed impact profiles, not query-time computation | Sub-second response time; the librarian invests LLM tokens once so every future query is free |
| Priority scoring | Advisory with adaptive modulation from success metrics | Base weights provide sensible defaults; metric-driven modulation ensures the librarian converges toward product-level goals; user-configurable targets enable different operational priorities |
| Knowledge management | "Never just append" — update, merge, contradict, expire | Prevents knowledge graph degradation over time; directly inspired by Supermemory's architecture |
| Structural layer | Tree-sitter AST parsing, zero LLM dependency | Fast, deterministic, free; provides immediate value and acts as cost filter for the semantic layer |
| Temporal tracking | Git commit hash stamped on all derived knowledge | Enables staleness detection — if the code version a concept was derived from is no longer current, the concept is flagged for re-analysis |
| Quality assurance | Three-level review: automated consistency, co-regulation LLM-as-judge, surfaced human review | Automated checks are free and catch format errors; co-regulation catches substantive quality issues without human effort; human review provides ground-truth calibration and builds the librarian's error profile |
| Failure handling | Structured failure breadcrumbs with escalation threshold | Failed iterations leave diagnostic context for retries; repeated failures escalate to human review rather than grinding indefinitely; prevents token waste on intractable items |
| Human audit UI | Local web application for inspection and review, read-only except for review actions | The knowledge graph is too complex to audit via CLI alone; the UI enables casual quality assessment and the Level 2 review workflow; scoped to read/review to avoid duplicate write paths |
| Success metrics as control system | Metrics drive adaptive priority, not just reporting | Coverage, freshness, and blast radius completeness targets are both the definition of success and the inputs to the priority modulation loop; this ensures the librarian's behavior converges toward the outcomes that matter |

---

*This PRD supersedes the 2026-03-25 system design specification. Design decisions from the prior spec that are carried forward are noted in Section 13. The research compendium (`research-compendium.md`) provides source material and competitive analysis underlying this document.*
