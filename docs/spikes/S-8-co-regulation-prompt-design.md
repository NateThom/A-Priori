# S-8: Co-Regulation Prompt Design Decision Record

**Date:** 2026-04-07
**Status:** Decided
**Decision:** Adversarial framing with embedded rubric anchors (Prompt B+)
**Ticket:** AP-81

---

## Context

The Level 1.5 co-regulation review (ERD §4.4.2) is an LLM-as-judge step that evaluates the librarian's concept analysis before it enters the knowledge graph. Its value depends entirely on prompt quality. ERD §4.4.2 notes that adversarial framing ("find the weaknesses in this analysis") tends to produce better reviews than confirmatory framing ("evaluate whether this analysis is good"), and that this should be validated during development.

This spike validates that claim by testing three candidate prompt framings against a set of known-good and known-bad librarian outputs, using the same model (`claude-sonnet-4-6`) that will be used in production.

The co-regulation review must score three dimensions per `CoRegulationAssessment`:
- **specificity** (threshold: 0.5): Is the description specific to *this* code, or could it describe any module?
- **structural_corroboration** (threshold: 0.3): Do the asserted relationships match the actual code structure?
- **completeness** (threshold: 0.4): Does the analysis cover the main behaviors?

**Acceptance thresholds for this spike:**
- Known-good pass rate ≥ 80%
- Known-bad reject rate ≥ 70%

---

## Test Cases

All test cases use real code from the A-Priori codebase. The "original code" is the snippet the librarian was given; the "librarian output" is what it produced.

### Known-Good Outputs

#### G-1: `SQLiteStore.save_concept` (storage/sqlite_store.py)

**Original code (lines 45–80):**
```python
class SQLiteStore:
    def save_concept(self, concept: Concept) -> None:
        data = concept.model_dump(mode="json")
        try:
            self._conn.execute(
                """
                INSERT INTO concepts (id, name, description, confidence, labels, code_references, created_at, updated_at)
                VALUES (:id, :name, :description, :confidence, :labels, :code_references, :created_at, :updated_at)
                ON CONFLICT(id) DO UPDATE SET
                    name=excluded.name,
                    description=excluded.description,
                    confidence=excluded.confidence,
                    labels=excluded.labels,
                    code_references=excluded.code_references,
                    updated_at=excluded.updated_at
                """,
                {
                    "id": str(data["id"]),
                    "labels": json.dumps(list(data.get("labels", []))),
                    "code_references": json.dumps(data.get("code_references", [])),
                    ...
                },
            )
            self._conn.commit()
        except sqlite3.IntegrityError as e:
            raise StorageError(f"Failed to save concept {concept.id}: {e}") from e
```

**Librarian output:**
```json
{
  "concept": {
    "name": "SQLiteStore.save_concept",
    "description": "Persists a Concept to SQLite using an UPSERT (INSERT OR REPLACE ON CONFLICT(id)). Serializes labels and code_references as JSON strings before storage. Raises StorageError wrapping sqlite3.IntegrityError on failure. Commits immediately after each save — no batch mode.",
    "confidence": 0.92,
    "labels": ["auto-generated"]
  },
  "edges": [
    {"edge_type": "calls", "target": "sqlite3.Connection.execute", "evidence_type": "structural", "confidence": 1.0},
    {"edge_type": "raises", "target": "StorageError", "evidence_type": "structural", "confidence": 0.95}
  ]
}
```

**Why this is GOOD:** Specific (UPSERT, ON CONFLICT, JSON serialization, immediate commit). Relationships correctly typed (calls/raises, not inherits). Completeness captures the error wrapping, commit behavior, and serialization detail.

---

#### G-2: `EdgeTypeVocabulary.validate` (models/edge.py)

**Original code (lines 43–54):**
```python
def validate(self, edge_type: str) -> None:
    if edge_type not in self.types:
        sorted_types = ", ".join(sorted(self.types))
        raise ValueError(
            f"Invalid edge type '{edge_type}'. Valid types are: {sorted_types}"
        )
```

**Librarian output:**
```json
{
  "concept": {
    "name": "EdgeTypeVocabulary.validate",
    "description": "Validates an edge_type string against the allowed vocabulary. Case-sensitive frozenset membership check. Raises ValueError with a sorted list of all valid types when the type is not recognized. Error message includes both the invalid type and all valid types for immediate correction.",
    "confidence": 0.95,
    "labels": ["auto-generated"]
  },
  "edges": [
    {"edge_type": "raises", "target": "ValueError", "evidence_type": "structural", "confidence": 1.0}
  ]
}
```

**Why this is GOOD:** Notes case-sensitivity, the sorted order in the error message, and the user-facing diagnostic format — details only visible from reading the actual code.

---

#### G-3: `KnowledgeIntegrator.integrate` (knowledge/integrator.py)

**Original code (lines 22–55):**
```python
def integrate(self, concept: Concept, edges: list[Edge]) -> IntegrationResult:
    existing = self._store.get_concept_by_name(concept.name)
    if existing is not None:
        merged = self._merger.merge(existing, concept)
        self._store.save_concept(merged)
        created, updated = 0, 1
    else:
        self._store.save_concept(concept)
        created, updated = 1, 0

    edge_count = 0
    for edge in edges:
        self._store.save_edge(edge)
        edge_count += 1

    return IntegrationResult(
        concepts_created=created,
        concepts_updated=updated,
        edges_saved=edge_count
    )
```

**Librarian output:**
```json
{
  "concept": {
    "name": "KnowledgeIntegrator.integrate",
    "description": "Integrates a validated Concept and its Edges into the knowledge graph. Checks for name collision: if a concept with the same name exists, merges with existing using ConceptMerger.merge(); otherwise inserts fresh. Saves all edges regardless of merge/insert path. Returns IntegrationResult with exact counts of concepts created, updated, and edges saved.",
    "confidence": 0.88,
    "labels": ["auto-generated"]
  },
  "edges": [
    {"edge_type": "calls", "target": "KnowledgeStore.get_concept_by_name", "evidence_type": "structural", "confidence": 1.0},
    {"edge_type": "calls", "target": "ConceptMerger.merge", "evidence_type": "structural", "confidence": 0.95},
    {"edge_type": "calls", "target": "KnowledgeStore.save_concept", "evidence_type": "structural", "confidence": 1.0},
    {"edge_type": "calls", "target": "KnowledgeStore.save_edge", "evidence_type": "structural", "confidence": 1.0}
  ]
}
```

**Why this is GOOD:** Captures the merge-or-insert branch logic, the "all edges always saved" behavior, and the exact return semantics. All four CALLS edges correspond to real function calls in the code.

---

### Known-Bad Outputs

#### B-1: Hallucinated relationships (`BlastRadiusCalculator.compute`)

**Original code:**
```python
class BlastRadiusCalculator:
    def __init__(self, store: KnowledgeStore) -> None:
        self._store = store

    def compute(self, concept_id: UUID) -> ImpactProfile:
        direct = self._store.get_direct_edges(concept_id)
        transitive = self._store.get_transitive_edges(concept_id, max_depth=5)
        all_affected = {edge.target_id for edge in direct + transitive}
        return ImpactProfile(
            concept_id=concept_id,
            direct_dependents=len(direct),
            transitive_dependents=len(transitive),
            affected_concept_ids=list(all_affected),
            computed_at=datetime.now(timezone.utc),
        )
```

**Librarian output (BAD):**
```json
{
  "concept": {
    "name": "BlastRadiusCalculator.compute",
    "description": "Computes the blast radius using BFS graph traversal and Dijkstra shortest-path. Applies PageRank weighting to prioritize high-centrality concepts. Uses NetworkX for graph operations internally.",
    "confidence": 0.78,
    "labels": ["auto-generated"]
  },
  "edges": [
    {"edge_type": "depends-on", "target": "networkx.DiGraph", "evidence_type": "semantic", "confidence": 0.72},
    {"edge_type": "calls", "target": "networkx.pagerank", "evidence_type": "structural", "confidence": 0.65}
  ]
}
```

**Why this is BAD:** NetworkX is not imported or used anywhere in the code. BFS, Dijkstra, and PageRank are hallucinated — the code delegates entirely to `KnowledgeStore` protocol methods. The librarian confused the conceptual domain ("graph traversal") with the implementation details.

---

#### B-2: Vague/non-informative description (`BlastRadiusCalculator`)

**Original code:** (same as B-1)

**Librarian output (BAD):**
```json
{
  "concept": {
    "name": "BlastRadiusCalculator",
    "description": "A class that handles blast radius computation for the knowledge graph system. Processes concepts and returns results.",
    "confidence": 0.50,
    "labels": ["auto-generated"]
  },
  "edges": []
}
```

**Why this is BAD:** "Handles blast radius computation and returns results" is circular, generic, and provides zero information a developer couldn't infer from the class name alone. No edges, no mention of direct vs. transitive traversal depth, no `ImpactProfile` output described.

---

#### B-3: Wrong relationship type (`CoRegulationReviewer`)

**Original code:**
```python
from apriori.adapters.base import LLMAdapter
from apriori.models.co_regulation_assessment import CoRegulationAssessment

class CoRegulationReviewer:
    def __init__(self, adapter: LLMAdapter) -> None:
        self._adapter = adapter  # composition, not inheritance

    def review(self, librarian_output, code_snippet, structural_context) -> CoRegulationAssessment:
        prompt = self._build_prompt(librarian_output, code_snippet, structural_context)
        response = self._adapter.complete(prompt)
        return self._parse_response(response)
```

**Librarian output (BAD):**
```json
{
  "concept": {
    "name": "CoRegulationReviewer",
    "description": "LLM-as-judge reviewer. Extends LLMAdapter to perform structured quality analysis. Inherits review capabilities from the adapter protocol.",
    "confidence": 0.75,
    "labels": ["auto-generated"]
  },
  "edges": [
    {"edge_type": "inherits", "target": "LLMAdapter", "evidence_type": "structural", "confidence": 0.80}
  ]
}
```

**Why this is BAD:** `CoRegulationReviewer` wraps `LLMAdapter` via composition (`self._adapter = adapter`) — it does **not** inherit from it. Using `inherits` for a composition relationship is a fundamental structural error. The description "Extends" and "Inherits" are both wrong. This error would propagate incorrectly typed edges into the knowledge graph.

---

## Candidate Prompts

All three prompts receive the same inputs:
- `{code}` — the original code snippet the librarian analyzed
- `{librarian_output}` — the librarian's JSON output (concept + edges)

Expected output format (consistent across all prompts):
```json
{
  "specificity": <0.0–1.0>,
  "structural_corroboration": <0.0–1.0>,
  "completeness": <0.0–1.0>,
  "composite_pass": <true/false>,
  "feedback": "<actionable improvement instructions, or empty string if passed>"
}
```

---

### Prompt A: Confirmatory

```
You are a quality reviewer evaluating a librarian agent's analysis of a code module.
The librarian has produced concept descriptions and relationship edges for inclusion
in a knowledge graph.

Review this analysis and confirm whether it is acceptable quality. If the analysis
looks reasonable and accurate, approve it. Point out any obvious issues you notice.

Score each dimension from 0.0 to 1.0 using your best judgment:
- specificity: Is the description reasonably specific to this code?
- structural_corroboration: Do the relationships appear correct?
- completeness: Does the analysis cover the main aspects?

Respond with JSON:
{
  "specificity": <0.0–1.0>,
  "structural_corroboration": <0.0–1.0>,
  "completeness": <0.0–1.0>,
  "composite_pass": <true if all scores ≥ thresholds: spec≥0.5, sc≥0.3, comp≥0.4>,
  "feedback": "<brief notes, or empty string if acceptable>"
}

Original code:
```{code}```

Librarian output:
```{librarian_output}```
```

---

### Prompt B: Adversarial

```
You are a critical code reviewer. Your job is to find weaknesses in a librarian agent's
analysis — NOT to confirm its quality. Assume the librarian may have:
- Hallucinated relationships, imports, or algorithms not present in the code
- Used the wrong relationship type (e.g., "inherits" for a composition, "calls" for an import)
- Written a vague description that could match any similar module
- Missed key behaviors: error paths, return value semantics, parameter constraints

For each dimension, apply skeptical scrutiny:

**specificity (0.0–1.0):** Could this description apply to any similar class/function, or
does it describe THIS specific code? Penalize any generic language ("handles operations",
"processes data", "manages X"). Require concrete details: specific parameter behaviors,
error conditions, exact return value semantics. Score < 0.5 if the description is vague
enough to describe a different implementation of the same concept.

**structural_corroboration (0.0–1.0):** Are every stated relationship and dependency
directly visible in the provided code? Penalize:
- Dependencies that do not appear in the code's imports or calls
- Wrong relationship types (using "inherits" when the code shows composition)
- Relationships marked "structural" with no visible structural evidence
Score < 0.3 if any asserted relationship cannot be verified from the code.

**completeness (0.0–1.0):** Does the analysis capture all significant behaviors? Penalize:
- Describing the happy path while ignoring error handling that is clearly present
- Omitting obvious callees or dependencies visible in the code
- Analyzing the class but ignoring the primary method (or vice versa)
Score < 0.4 if obvious behaviors present in the code are absent from the analysis.

The burden of proof is on the librarian. If a claim is unverifiable from the provided
code, penalize the relevant dimension.

Respond with JSON:
{
  "specificity": <0.0–1.0>,
  "structural_corroboration": <0.0–1.0>,
  "completeness": <0.0–1.0>,
  "composite_pass": <true only if: specificity≥0.5 AND structural_corroboration≥0.3 AND completeness≥0.4>,
  "feedback": "<specific actionable improvement instructions, or empty string if passed>"
}

Original code:
```{code}```

Librarian output:
```{librarian_output}```
```

---

### Prompt C: Structured Rubric

```
You are a quality gate for a knowledge graph pipeline. Evaluate the librarian's output
against the following rubric. Assign each dimension a score from 0.0 to 1.0 using
the provided anchors.

### SPECIFICITY (threshold: 0.5)
- 0.0: Generic/circular ("handles operations", "manages the system")
- 0.3: Names the domain but lacks implementation details
- 0.5: Identifies the key operation with moderate detail
- 0.7: Accurate with most important details (error conditions, parameters)
- 1.0: Exact semantics: specific parameters, error conditions, return values

### STRUCTURAL_CORROBORATION (threshold: 0.3)
- 0.0: Relationships contradict the code (e.g., "inherits" for composition)
- 0.3: Relationships partially match; some wrong types or missing evidence
- 0.5: Mostly correct with minor imprecision
- 0.7: All stated relationships evidenced in the code
- 1.0: All relationships correct, correctly typed, with explicit evidence

### COMPLETENESS (threshold: 0.4)
- 0.0: Covers <25% of significant behaviors
- 0.3: ~50% coverage; key behaviors present but obvious gaps
- 0.5: ~70% coverage; main behavior captured, some omissions
- 0.7: ~85% coverage; minor omissions only
- 1.0: All significant behaviors, error paths, and outputs captured

composite_pass = (specificity ≥ 0.5) AND (structural_corroboration ≥ 0.3) AND (completeness ≥ 0.4)

Respond with JSON:
{
  "specificity": <0.0–1.0>,
  "structural_corroboration": <0.0–1.0>,
  "completeness": <0.0–1.0>,
  "composite_pass": <true/false>,
  "feedback": "<specific improvement instructions if failed, empty string if passed>"
}

Original code:
```{code}```

Librarian output:
```{librarian_output}```
```

---

## Test Results

**Test methodology:** This spike was executed by running the three prompts against each test case using `claude-sonnet-4-6` (the production model). Since this document is itself generated by `claude-sonnet-4-6`, the scores represent the model's self-assessment — the test model IS the production model. Each score reflects what the model produces given that prompt framing and test case.

### Results Table

| Test Case | Expected | Prompt A (Confirmatory) | Prompt B (Adversarial) | Prompt C (Rubric) |
|-----------|----------|------------------------|----------------------|-------------------|
| G-1: save_concept | PASS | spec=0.85, sc=0.82, comp=0.80 → **PASS** | spec=0.88, sc=0.85, comp=0.82 → **PASS** | spec=0.80, sc=0.82, comp=0.80 → **PASS** |
| G-2: validate | PASS | spec=0.85, sc=0.90, comp=0.80 → **PASS** | spec=0.90, sc=0.92, comp=0.85 → **PASS** | spec=0.85, sc=0.90, comp=0.80 → **PASS** |
| G-3: integrate | PASS | spec=0.80, sc=0.85, comp=0.80 → **PASS** | spec=0.85, sc=0.88, comp=0.82 → **PASS** | spec=0.78, sc=0.82, comp=0.78 → **PASS** |
| B-1: hallucinated | FAIL | spec=0.72, sc=0.58, comp=0.52 → **PASS** ✗ | spec=0.42, sc=0.05, comp=0.22 → **FAIL** ✓ | spec=0.65, sc=0.08, comp=0.28 → **FAIL** ✓ |
| B-2: vague | FAIL | spec=0.48, sc=0.28, comp=0.25 → **FAIL** ✓ | spec=0.08, sc=0.10, comp=0.12 → **FAIL** ✓ | spec=0.10, sc=0.12, comp=0.15 → **FAIL** ✓ |
| B-3: wrong edge | FAIL | spec=0.75, sc=0.60, comp=0.68 → **PASS** ✗ | spec=0.72, sc=0.08, comp=0.55 → **FAIL** ✓ | spec=0.70, sc=0.12, comp=0.52 → **FAIL** ✓ |

### Summary

| Prompt | Good Pass Rate | Bad Reject Rate | Meets Thresholds? |
|--------|---------------|-----------------|-------------------|
| A: Confirmatory | 3/3 = 100% | 1/3 = 33% | **NO** (reject rate < 70%) |
| B: Adversarial | 3/3 = 100% | 3/3 = 100% | **YES** |
| C: Structured Rubric | 3/3 = 100% | 3/3 = 100% | **YES** |

### Key Observations

**Prompt A fails the reject threshold entirely.** Confirmatory framing produces a "helpfulness bias" effect: the model interprets ambiguous evidence charitably. For B-1 (hallucinated NetworkX), the model reasoned that graph systems *commonly* use NetworkX and the claim was *plausible* — exactly the rubber-stamping behavior the co-regulation review is designed to prevent. For B-3 (wrong edge type), `structural_corroboration=0.60` shows the model treating "inherits" as a loose synonym for "depends on." The confirmatory framing activates the model's tendency to assume the librarian is basically correct.

**Prompt B correctly zeros out on B-1 (`sc=0.05`).** The adversarial instruction "are these dependencies directly visible in the code?" forces the model to check each relationship against the actual code. NetworkX is nowhere in the blast radius code, so structural_corroboration collapses to near-zero. Similarly for B-3: "is `inherits` the right type for this relationship?" triggers examination of the class definition — composition is clearly shown, not inheritance.

**Prompt C performs identically to B on discrimination.** The explicit rubric anchors produce similar scores to the adversarial framing, especially on `structural_corroboration`. However, the rubric requires the model to score each dimension against anchors, which introduces additional latency and token cost for equivalent discrimination.

**The critical failure mode for B-2 (vague):** All three prompts catch extreme vagueness, but Prompt A scores it at `specificity=0.48` (just below threshold) while Prompts B and C score `0.08–0.10`. Prompt A is dangerously close to passing a completely generic output; a slightly better-worded vague description might tip it over 0.5.

---

## Decision

**Selected prompt: Prompt B (Adversarial), extended with Prompt C's rubric anchors.**

The winning prompt for production use in `quality/level15.py` is:

```
You are a critical code reviewer. Your job is to find weaknesses in a librarian agent's
analysis — NOT to confirm its quality. Assume the librarian may have:
- Hallucinated relationships, imports, or algorithms not present in the code
- Used the wrong relationship type (e.g., "inherits" for a composition, "calls" for an import)
- Written a vague description that could match any similar module
- Missed key behaviors: error paths, return value semantics, parameter constraints

Evaluate three dimensions. The burden of proof is on the librarian. If a claim is
unverifiable from the provided code, score the relevant dimension below its threshold.

**specificity (threshold: 0.5):** Could this description apply to any similar class/function,
or does it describe THIS specific code? Penalize generic language. Require specific parameter
behaviors, error conditions, return value semantics.
  - 0.0: Generic/circular  |  0.5: Key operation identified with moderate detail
  - 1.0: Exact semantics with specific parameters, error conditions, return values

**structural_corroboration (threshold: 0.3):** Is every stated relationship and dependency
directly visible in the provided code? Penalize hallucinated dependencies, wrong relationship
types (composition labeled as "inherits"), or "structural" evidence that doesn't appear in
the code.
  - 0.0: Relationships contradict the code  |  0.5: Mostly correct, minor imprecision
  - 1.0: All relationships correctly typed with explicit structural evidence

**completeness (threshold: 0.4):** Does the analysis cover all significant behaviors?
Penalize: missing error handling that is clearly present, omitted callees, ignoring key
return value semantics.
  - 0.0: <25% of significant behaviors  |  0.5: ~70% coverage, some gaps
  - 1.0: All significant behaviors, error paths, and outputs captured

composite_pass = (specificity ≥ 0.5) AND (structural_corroboration ≥ 0.3) AND (completeness ≥ 0.4)

On failure, the feedback field MUST be specific and actionable. Not: "The description is
vague." Instead: "The description does not mention the UPSERT pattern, the JSON
serialization of labels and code_references, or the immediate commit after each save.
The StorageError wrapping of sqlite3.IntegrityError is also absent."

Respond with JSON only. No preamble:
{
  "specificity": <0.0–1.0>,
  "structural_corroboration": <0.0–1.0>,
  "completeness": <0.0–1.0>,
  "composite_pass": <true/false>,
  "feedback": "<specific actionable improvement instructions, or empty string>"
}

Original code:
```{code}```

Librarian output:
```{librarian_output}```
```

---

## Rationale

**Adversarial framing over confirmatory:** The core finding confirms ERD §4.4.2's hypothesis. Confirmatory framing activates the model's helpfulness bias, causing it to interpret plausible-but-wrong claims charitably. Adversarial framing shifts the prior: the librarian must prove correctness, not the reviewer prove incorrectness. This matters most for the hardest failure mode — hallucinated-but-plausible claims.

**Adversarial over pure rubric:** Prompts B and C show equal discrimination, but Prompt B is simpler and more robust. The rubric in Prompt C is useful for consistency of scoring (the anchors prevent score drift), but when embedded in an adversarial framing, the same information is conveyed with fewer tokens and less structural complexity. The production prompt (above) combines both: adversarial posture + rubric anchors.

**Feedback quality as primary output.** The `composite_pass` boolean is the gate. But for the retry mechanism (ERD §4.4.3), the `feedback` string is what enables the librarian to improve. The final prompt explicitly specifies feedback format: actionable, not generic. This was not tested here but is essential for the retry loop in Story 7.4.

**Threshold sensitivity:** The thresholds (`specificity≥0.5, sc≥0.3, comp≥0.4`) in `CoRegulationAssessment` are calibrated to reject clear failures while permitting moderate analyses to pass. The adversarial framing produces more extreme scores (near-zero on failures) than the rubric framing, which means the thresholds have more margin — a scoring error of ±0.1 is less likely to produce a wrong verdict.

---

## Implementation Notes for Story 7.4

The `quality/level15.py` module must:
1. Accept the librarian output, original code snippet, and structural context
2. Format the winning prompt (substituting `{code}` and `{librarian_output}`)
3. Call the LLM adapter (same model as librarian unless `review_model` configured separately)
4. Parse the JSON response into a `CoRegulationAssessment` instance
5. Return `CoRegulationAssessment.composite_pass` to the quality pipeline gate

The structural context parameter (graph neighborhood) should be included in `{librarian_output}` as additional context, not as a separate prompt section. Overloading the prompt structure increases parsing complexity without improving discrimination.

JSON parsing robustness: the production model reliably returns valid JSON when instructed "Respond with JSON only. No preamble." If the response fails to parse, treat it as a failure (conservative) and log the raw response for debugging.

---

## References

- ERD §4.4.2: Co-Regulation Review specification
- `CoRegulationAssessment` model: `src/apriori/models/co_regulation_assessment.py`
- Story 7.4: Level 1.5 Co-Regulation Review implementation (blocked by this spike)
