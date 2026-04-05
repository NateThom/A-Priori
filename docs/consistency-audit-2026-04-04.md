# Cross-Document Consistency Audit — 2026-04-04

## Documents Reviewed

| Document | Approx. Length | Purpose | Date |
|----------|---------------|---------|------|
| a-priori-prd.md | ~67KB / 620 lines | Product requirements (upstream source of truth) | 2026-04-03 |
| a-priori-erd.md | ~78KB / 750 lines | Engineering design (how) | 2026-04-04 |
| a-priori-epics.md | ~44KB / 400 lines | Epic decomposition with dependencies | 2026-04-04 |
| a-priori-stories.md | ~134KB / 1600 lines | User stories with acceptance criteria | 2026-04-04 |

## Methodology

Four parallel inventory extractions (one per document) followed by three parallel cross-reference passes (terminology & entities, quantitative claims & metrics, requirements coverage & architecture), then manual verification of flagged findings against source text.

## Summary

- **HIGH:** 1 finding (confirmed, actionable)
- **MEDIUM:** 4 findings (confirmed, actionable)
- **LOW:** 2 findings (cosmetic, no action required)

---

## Findings

### HIGH Severity

#### H1: Label Vocabulary Drift — PRD Lists 3 Labels, ERD Expands to 6

- **Category:** (A) Terminology drift
- **Documents:** PRD §1.3, §5.1 vs. ERD §3.1.1 vs. Stories 1.1
- **Inconsistency:** The PRD defines the concept label vocabulary as three items. The ERD introduces three additional labels without the PRD being updated to include them.
- **Evidence:**
  - **PRD §1.3** (line 39): "Labels are reserved for metadata about the state of knowledge (`needs-review`, `auto-generated`, `deprecated`)."
  - **PRD §5.1** (line 126): "`labels` | set[string] | No | Housekeeping metadata only (e.g., `needs-review`, `auto-generated`, `deprecated`)"
  - **ERD §3.1.1** (line 183): "The initial label vocabulary is: `needs-review`, `auto-generated`, `deprecated`, `verified`, `stale`, `needs-human-review` (new — used by the escalation system)."
  - The PRD *does* reference `needs-human-review` in §5.6 (line 252) and §6.4.3 (line 375) when describing escalation behavior, confirming it is an intended label. Similarly, the PRD's §4.1 description of Layer 2 describes staleness detection behavior that implies a `stale` label, and §5.1 includes `verified_by` and `last_verified` fields that imply a `verified` label.
- **Verdict: CONFIRMED** — The three additional labels (`verified`, `stale`, `needs-human-review`) are clearly intended by the PRD's behavioral descriptions, but the PRD's explicit label vocabulary list in §1.3 and §5.1 was never updated to include them. This is a documentation gap, not a design disagreement.
- **Proposed fix (PRD):**
  - §1.3: Change to: "Labels are reserved for metadata about the state of knowledge (`needs-review`, `auto-generated`, `deprecated`, `verified`, `stale`, `needs-human-review`)."
  - §5.1: Change the `labels` field description to: "Housekeeping metadata only. Initial vocabulary: `needs-review`, `auto-generated`, `deprecated`, `verified`, `stale`, `needs-human-review`"

---

### MEDIUM Severity

#### M1: "Cost per Concept" Metric Has No Downstream Acceptance Criteria

- **Category:** (E) Acceptance criteria gaps
- **Documents:** PRD §9.2 vs. Stories (absent)
- **Inconsistency:** The PRD defines "cost per concept" as a core cost efficiency metric, but no story contains acceptance criteria that operationalize it with a specific target or test.
- **Evidence:**
  - **PRD §9.2:** Defines "Cost per concept — Average LLM token cost per concept (create + maintain)" with the expectation it "should decrease over time as the graph matures."
  - **Stories:** No story contains a testable assertion about cost-per-concept tracking, thresholds, or reporting. Token budget management (Story 10.3) tracks total spend but not per-concept cost.
- **Verdict: CONFIRMED**
- **Proposed fix (Stories):** Add acceptance criteria to Story 10.3 (Token Budget Management) or Story 9.1 (Metrics Engine): "Given the librarian has run N iterations, when `get_status` is called, then it includes `cost_per_concept` showing the average token cost across all concept create and update operations."

#### M2: Freshness Metric "Actively-Developed Code" Boundary Not Tested

- **Category:** (E) Acceptance criteria gaps
- **Documents:** PRD §9.1 vs. Stories 9.1
- **Inconsistency:** The PRD specifies freshness is measured only for "actively-developed code (files modified in the last 30 days)" but no story tests the boundary behavior (29 days vs. 31 days).
- **Evidence:**
  - **PRD §9.1:** "at least 90% freshness (≥ 0.90) for actively-developed code (files modified in the last 30 days)"
  - **Stories 9.1 Technical Notes** (line 1034): "'Actively-developed files' for freshness means files modified in the last 30 days (configurable)."
  - No acceptance criterion in Story 9.1 explicitly tests that files older than 30 days are excluded from the freshness denominator.
- **Verdict: CONFIRMED**
- **Proposed fix (Stories):** Add to Story 9.1 acceptance criteria: "Given a concept referencing a file last modified 31 days ago, when freshness is computed, then that concept is excluded from the freshness denominator."

#### M3: Bootstrap Coverage Threshold "e.g., 50%" Treated as Hard Value

- **Category:** (C) Contradictions
- **Documents:** ERD §4.8.1, Epics §13 vs. Stories 13.1
- **Inconsistency:** ERD and Epics use suggestive language ("e.g., 50%") for the progressive enrichment coverage threshold, but Stories acceptance criteria treat 50% as the definitive threshold.
- **Evidence:**
  - **ERD §4.8.1:** "heavily weight `developer_proximity` when overall coverage is below a threshold (e.g., 50%)"
  - **Epics §13:** Same "e.g., 50%" phrasing
  - **Stories 13.1 acceptance criteria:** "Given a codebase with 500 files and coverage below 50%..." and "Given coverage exceeds 50%..."
- **Verdict: CONFIRMED** — The "e.g." implies this is an example, but the stories test against exactly 50%. Either the upstream docs should commit to 50% as the default, or the stories should test against a configurable threshold.
- **Proposed fix (ERD, Epics):** Change "e.g., 50%" to "default: 50%, configurable" to match how the stories test it.

#### M4: Precision/Recall Target Language — "Greater Than" vs. "≥"

- **Category:** (C) Contradictions
- **Documents:** PRD §9.1 vs. Stories 12.7
- **Inconsistency:** The PRD uses strict "greater than" language for blast radius accuracy targets, while Stories use "≥" (greater-than-or-equal).
- **Evidence:**
  - **PRD §9.1:** "> 0.70" and "> 0.50" (strictly greater than)
  - **Stories 12.7:** "recall is ≥70%" and "precision is ≥50%" (greater than or equal)
- **Verdict: CONFIRMED** — Minor mathematical ambiguity. Does exactly 70.0% recall pass or fail?
- **Proposed fix (PRD):** Change to "≥ 0.70" and "≥ 0.50" to match Stories, since the boundary case is immaterial in practice but the docs should agree.

---

### LOW Severity

#### L1: "co-changes-with" — Natural Language Phrasing Varies

- **Category:** (A) Terminology drift
- **Documents:** PRD §5.4 vs. ERD §3.3 vs. Epics §12 vs. Stories 12.4
- **Inconsistency:** The formal edge type name `co-changes-with` is consistent everywhere. Natural language descriptions vary between "co-change patterns," "co-change analysis," and "co-changes-with" but all refer to the same concept.
- **Verdict: NOT AN ISSUE** — The controlled vocabulary name is consistent. Natural language variation is expected.

#### L2: "Knowledge Management Layer" vs. "Knowledge Manager"

- **Category:** (A) Terminology drift
- **Documents:** PRD §4.1 vs. Epics §8 vs. Stories §8
- **Inconsistency:** The PRD uses "Layer 2 — The Knowledge Management Layer" (architectural layer name). Epics and Stories use "Knowledge Manager" (component name).
- **Verdict: NOT AN ISSUE** — These are contextually appropriate: the PRD names the architectural layer, while Epics/Stories name the implementing component.

---

## Proposed Changes by Document

### PRD

| # | Finding ID | Section | Change |
|---|-----------|---------|--------|
| 1 | H1 | §1.3 | Update label list to include all six: `needs-review`, `auto-generated`, `deprecated`, `verified`, `stale`, `needs-human-review` |
| 2 | H1 | §5.1 | Update `labels` field description to list full initial vocabulary |
| 3 | M4 | §9.1 | Change blast radius accuracy targets from "> 0.70" / "> 0.50" to "≥ 0.70" / "≥ 0.50" |

### ERD

| # | Finding ID | Section | Change |
|---|-----------|---------|--------|
| 1 | M3 | §4.8.1 | Change "e.g., 50%" to "default: 50%, configurable" |

### Epics

| # | Finding ID | Section | Change |
|---|-----------|---------|--------|
| 1 | M3 | §13 | Change "e.g., 50%" to "default: 50%, configurable" |

### Stories

| # | Finding ID | Section | Change |
|---|-----------|---------|--------|
| 1 | M1 | Story 10.3 or 9.1 | Add acceptance criterion for cost-per-concept metric reporting |
| 2 | M2 | Story 9.1 | Add acceptance criterion testing the 30-day boundary exclusion for freshness |

---

## Assessment: Should You Continue Looping?

**No. You should stop looping.**

This audit found **1 HIGH** and **4 MEDIUM** findings across ~320KB of documentation. Here is why continued iterations will yield diminishing returns:

### What the audit found (and didn't find)

**Strong consistency across all major dimensions:**

- Forward traceability: every PRD MVP feature traces to ERD, Epics, and Stories. Zero gaps.
- Reverse traceability: no scope drift detected. No downstream items lack upstream grounding.
- Phase boundaries: all four documents agree on which work belongs in which phase.
- Architecture: the four-layer model is described identically everywhere.
- Spike tracking: all 8 spikes have consistent IDs, status (decided vs. pending), and timeboxes across all docs.
- Deferred items: all 9 post-MVP items are cleanly isolated — none leak into MVP scope.
- Epic dependencies: the dependency graph is consistent and acyclic across Epics and Stories.
- Quantitative claims: 15+ numeric values (latency, metric targets, thresholds, defaults) verified consistent.
- Adapter scope: Anthropic + Ollama consistently MVP; OpenAI consistently deferred.
- MCP tool count: 13 (6 read + 7 write) consistent across all four documents.
- Edge type vocabulary: all 12 types (4 structural + 7 semantic + 1 historical) consistent.

**The remaining findings are:**

1. **H1 (label vocabulary):** A documentation gap where the PRD's explicit list wasn't updated to match its own behavioral descriptions. The ERD already has the correct list — this is a 2-line PRD edit.
2. **M1–M2 (acceptance criteria gaps):** Two metrics that need test coverage in Stories. These are additive (new AC lines), not corrections.
3. **M3–M4 (minor language alignment):** Small phrasing fixes for consistency.

### Why further loops won't help

The review prompt is designed to catch structural inconsistencies: terminology drift, missing requirements, contradictions, scope drift, and acceptance criteria gaps. After this pass, the document set is clean on all structural dimensions. The remaining findings are all minor and easily fixable. Further iterations would likely:

- Re-find the same issues (the label vocabulary gap is the most visible inconsistency)
- Generate false positives (as happened with some inventory extractions during this audit)
- Not find new HIGH-severity issues, since the major consistency axes all pass

### Recommended next step

Apply the 7 proposed changes above (estimated: 15 minutes of editing), then resume development. If you make significant structural changes to any document in the future, run the review again at that point.
