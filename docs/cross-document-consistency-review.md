# Cross-Document Consistency Review — Repeatable Process

**Purpose:** Systematically verify consistency across a set of design documents (PRD, ERD, Epics, Stories) and fix every confirmed issue while respecting each document's rules.

**When to run:** After any significant edit to one or more design documents, after adding a new document to the set, or on a regular cadence during active planning.

---

## Inputs

Before starting, confirm the following:

1. **Document set** — the files to review. Default: PRD, ERD, Epics, Stories.
2. **Document rules** — the authoring rules that govern each document type. These are provided below and must be respected when proposing fixes.
3. **Consistency categories** — which types of inconsistency to check. Default: all five.
   - (A) Terminology drift — same concept called different things
   - (B) Requirement gaps — a feature in one doc missing from another
   - (C) Contradictions — documents actively disagree on a fact
   - (D) Scope drift — downstream docs introduce features not grounded upstream
   - (E) Acceptance criteria gaps — requirements with no testable downstream criterion

---

## Process

### Step 1: Assess the Documents

Read the first ~40 lines and line count of each document. Produce a summary table:

| Document | Lines | Purpose | Date |
|----------|-------|---------|------|

Confirm the document hierarchy (e.g., PRD → ERD → Epics → Stories) and note which documents are upstream sources of truth vs. downstream elaborations.

### Step 2: Extract Structured Inventories (Parallel)

Launch **one agent per document**, all in parallel. Each agent reads its entire document and produces a structured inventory covering:

**For all document types:**
- Features & capabilities — every named feature, tool, or capability with section references
- Named entities — every model, schema, data type, edge type, component, agent, service, protocol
- Quantitative claims — every specific number (counts, thresholds, targets, defaults, performance numbers)
- Terminology — key domain terms and any within-document naming variations
- Architecture & layers — any architectural structure described
- Phases & milestones — any phasing or ordering information
- External dependencies — tools, libraries, APIs, services

**Additional categories by document type:**
- ERD: Interfaces & protocols (signatures, parameters, types), acceptance criteria per phase
- Epics: Dependencies between epics, acceptance criteria per epic, scope estimates, spikes
- Stories: Story list with IDs and parent epics, intra-story dependencies, MCP tools, data models referenced, spikes with resolution status

**Agent prompt template:**

```
You are extracting a structured inventory from a [DOCUMENT TYPE] for a cross-document
consistency review. This is a research-only task — do NOT write or edit any files.

Read the file [PATH] in its entirety (it is [N] lines — read it all, using multiple
reads if needed).

Then produce a structured inventory covering ALL of the following categories. Be
exhaustive — capture every instance, not just the first few.

[LIST CATEGORIES FROM ABOVE]

Format the output as clean markdown with headers for each category. Use bullet points.
Include section references (e.g., "§1.2", "§3.1") where applicable.
```

### Step 3: Cross-Reference Inventories (Parallel)

Launch **three cross-reference agents** in parallel, each checking one category of inconsistency across all documents:

**Agent A — Terminology & Named Entities:**
- Where the same concept is called different things across documents
- Entity count mismatches (e.g., "12 edge types" in one doc, different count in another)
- Entities defined in upstream docs that never appear downstream (orphans)
- Entities in downstream docs with no upstream origin (scope drift)

**Agent B — Quantitative Claims & Metrics:**
- Every specific number compared across all documents (thresholds, targets, counts, defaults)
- Metric definitions compared for consistency (same formula, same denominator, same edge cases)
- Acceptance criteria gaps — upstream requirements with no testable downstream criterion
- Performance targets compared across docs

**Agent C — Requirements Coverage & Architecture:**
- Forward traceability: for each upstream feature, verify it appears in every downstream doc
- Reverse traceability: for each downstream item, verify it traces to an upstream source
- Phase boundary consistency — is the same work placed in the same phase everywhere?
- Dependency graph consistency — do epic/story dependencies match across docs?
- Spike consistency — same IDs, same resolution status, same assignments
- Deferred items consistently marked as deferred

**Agent prompt template:**

```
You are performing a cross-document consistency review. Your job is to find
inconsistencies in [CATEGORY] across these documents.

Read all documents:
[LIST PATHS AND LINE COUNTS]

Check for these specific inconsistency types:
[LIST CHECKS FROM ABOVE]

For each finding, provide:
- The specific inconsistency
- Exact quotes from each document showing the discrepancy
- Which documents are involved (with section/line references)
- Severity: HIGH (could cause implementation bugs or missing requirements),
  MEDIUM (confusing but manageable), LOW (cosmetic)

Be thorough and precise.
```

### Step 4: Consolidate Findings

Merge the three agents' outputs into a single report, organized by severity:

```
## HIGH Severity
| # | Finding | Documents |
...

## MEDIUM Severity
| # | Finding | Documents |
...

## LOW Severity
| # | Finding | Documents |
...
```

Deduplicate findings that appear in multiple agents' output.

### Step 5: Verify Each Finding

For every finding (HIGH and MEDIUM at minimum; LOW if time allows):

1. **Read the exact source text** in each document cited by the finding.
2. **Confirm or reject** the finding based on the actual text.
3. If confirmed, **assess whether it needs a fix** or is acceptable as-is (e.g., an ERD introducing implementation types not in the PRD may be by design).
4. If it needs a fix, **propose a specific edit** that respects the document rules below.

Use this verdict format for each finding:

```
## [ID]: [Short Title]

**Verdict: CONFIRMED / NOT AN ISSUE**

[Evidence from source text]

**Proposed fix ([DOCUMENT]):** [Specific text change]
```

### Step 6: Apply Fixes

Once the user approves the fix list, apply all edits grouped by document. After editing, update any cross-references (story counts, dependency lists, etc.) that are affected by the changes.

---

## Document Rules

These rules govern what belongs in each document type and how it should be written. When proposing fixes, never violate the rules for the document you are changing.

### PRD Rules

- Define "what" the product must do, never "how" it should be built — if you're prescribing implementation, ask "why do I need this?" to find the real requirement
- Use "shall" for mandatory requirements that must be verified, "should" for aspirational goals that don't require verification
- Be exhaustive in coverage but concise in expression — a PRD with shallow coverage of all areas beats deep coverage of a few
- Make the "why" compelling enough that an engineer who hits an ambiguous decision during implementation can resolve it independently by reasoning from the motivation
- Define success metrics upfront with specific, measurable targets so instrumentation gets built during development, not retrofitted after launch
- State what's explicitly out of scope — this prevents scope creep and gives engineers confidence that edge cases outside the boundary are intentionally excluded
- Document assumptions honestly — every product plan rests on assumptions about user behavior, technical feasibility, and external dependencies, and making them explicit lets the team validate them early
- Specify edge cases, error states, and "what happens when things go wrong" for every feature — great specs anticipate failure, not just the happy path
- Tier requirements into must-have, should-have, and nice-to-have using language that engineers can use to make tradeoff decisions without coming back to you
- Include real data, user research, or competitive evidence — a PRD that motivates with evidence excites teams to build in a way that abstract problem statements don't
- Keep the document a living artifact — structure it so that most of the content (problem, users, architecture, data models) stands the test of time, even as priorities and details evolve during execution
- Organize in the order an engineer would naturally ask questions: why are we building this, who is it for, what does it do, how will we know it works, what are the boundaries, when does it ship

### ERD Rules

- The ERD answers how — the PRD answers what and why. If a section reads like the PRD restated in technical language, it hasn't done its job. If it reads like a Jira ticket, it's gone too granular.
- Every PRD requirement must trace to a specific ERD section, and every ERD section must trace back to a specific PRD requirement. Maintain an explicit traceability map.
- Define concrete interfaces an engineer can code against — protocol signatures, SQL schemas, directory structures, configuration keys with defaults and types. Abstract descriptions of what a component "should do" are not engineering specifications.
- Specify the decision tree for ambiguous runtime behavior. "Handle contradictions" is a PRD-level statement. "If the existing concept was human-created, do not overwrite; if agent-created and contradicting, flag both with needs-review" is an ERD-level specification.
- Dependency flow must be explicit and strict — what imports from what, what layer may call what other layer, and what is forbidden. Draw the dependency graph. Violations of the dependency direction are architectural bugs.
- Identify areas of technical uncertainty as named spikes with explicit questions, risk assessments, timeboxes, and a clear statement of what is blocked until the spike resolves.
- Separate the data model definitions from the logic that operates on them. Models are shared across layers; logic is owned by exactly one layer. This separation must be visible in the package structure.
- Include acceptance criteria per phase that are specific enough to be tested — latency targets at stated scale, coverage percentages, concrete user actions that must work end-to-end.
- Incorporate spike decisions directly into the specification. If a spike determined that interfaces are synchronous, the protocol signatures shown in the ERD must be synchronous. The ERD reflects decided reality, not open questions.
- The document is a living blueprint, not a contract. State this explicitly. Mandate that deviations during implementation are documented with rationale, not silently diverged from.

### Epics Rules

- Epics are ordered by dependency. Every epic lists its prerequisites explicitly, and no epic can be started until its prerequisites are complete or nearly complete. Draw the dependency graph.
- An epic's scope is defined in terms of capabilities and outcomes, not implementation details. The acceptance criteria should be stable even if the implementation approach changes.
- Spikes that block implementation but not definition are scheduled as the first story inside their parent epic, not as standalone pre-work that delays planning.
- Each epic has a single, clear integration boundary with the rest of the system — a protocol it implements, an API it exposes, a data model it writes to.
- Acceptance criteria are observable — an engineer or stakeholder can verify them by running a command, calling an API, or checking a metric.
- Integration epics should be identified explicitly. They carry different risk — their primary value is exposing interface mismatches.
- Epics that require different skill sets should be separated, even if the PRD groups them into a single phase.
- The "Key Stories" within an epic identify natural decomposition points suitable for sprint planning, but they are not prescriptive tickets.
- Every item in the PRD's explicit MVP scope list must trace to at least one epic. Verify this exhaustively.
- State the estimated size of each epic and flag which carry the most technical uncertainty.

### Stories Rules

- Every story traces to a source requirement. If it doesn't map back to the PRD, ERD, or an epic's key story, it's scope creep or the upstream docs are incomplete. Pick one and fix it.
- The persona is never "developer." The story's "As a..." names the person or system that receives the value.
- Acceptance criteria are in Given/When/Then format, and they test observable behavior.
- Each story has 2–5 acceptance criteria. Fewer than 2 means under-specified. More than 5 means it should be split.
- Include at least one failure-mode criterion.
- Slice vertically, not horizontally. Each story delivers a testable, demonstrable outcome end-to-end.
- Apply INVEST as a checklist: Independent, Negotiable, Valuable, Estimable, Small, Testable.
- Technical notes inform but do not constrain.
- State intra-epic dependencies explicitly. If there are no dependencies, say "None."
- Definition of done goes beyond acceptance criteria — tests passing, documentation updated, code reviewed.
- Name the story so it stands alone on a board.
- Spike stories have a time-box, a specific question, a concrete deliverable, and acceptance criteria.
- Cross-cutting concerns become their own stories or acceptance criteria — never implicit assumptions.
- Map the ERD entities to stories and check for orphans.
- Write the story so a developer who missed the planning meeting can pick it up and build exactly what's needed.

---

## Common Inconsistency Patterns

These are the patterns most frequently found during reviews. Check for them specifically:

1. **Phasing conflicts** — a feature described in Phase N of one document but Phase M of another. Often caused by moving work between phases without updating all docs.
2. **Stale spike references** — text that says "pending spike S-X" when the spike has been resolved. The resolution should be incorporated into the specification.
3. **"Shall" vs. "should" mismatch with phasing** — a PRD section using mandatory "shall" language for a feature that is deferred to a later phase or post-MVP.
4. **Internal PRD contradictions** — the MVP scope section (§10.1) including something that the phasing section (§12) defers, or the architecture section describing a capability as present that the scope section defers.
5. **Adapter/provider list drift** — the PRD listing providers (e.g., "OpenAI API") that no downstream document implements.
6. **Missing data model entries** — behavioral descriptions in the PRD that produce structured output (e.g., "the review produces a score on three dimensions") without a corresponding data model definition in §5.
7. **Dependency overstatement** — epics listing prerequisites that aren't actually required (e.g., the MCP server "depending on" the structural engine when it only needs the storage layer).
8. **Acceptance criteria orphans** — upstream requirements (especially metrics with specific targets) that have no testable acceptance criterion in any downstream story.
9. **Metric definition ambiguity** — metrics that don't specify edge cases in their denominator (e.g., what happens to freshness for concepts that have never been verified?).
10. **Edge type / vocabulary drift** — downstream documents using different names for items in a controlled vocabulary defined upstream.

---

## Output Format

The final deliverable is a report followed by applied fixes:

```
# Cross-Document Consistency Report — [DATE]

## Documents Reviewed
[Table of documents, line counts, dates]

## Methodology
[Brief description: parallel extraction → cross-reference → verify → fix]

## Findings by Severity

### HIGH (N findings)
| # | Finding | Documents | Fix |
...

### MEDIUM (N findings)
| # | Finding | Documents | Fix |
...

### LOW (N findings)
| # | Finding | Documents | Fix |
...

## Changes Applied
[Table of edits made, grouped by document]
```
