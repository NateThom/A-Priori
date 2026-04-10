# S-4: Blast Radius Accuracy Validation — Decision Record

**Story:** 12.7 (AP-105) — Blast Radius Accuracy Validation  
**PRD reference:** §9.1  
**Status:** Implemented

---

## Question

How do we validate that blast radius predictions are accurate?  What does the test harness look like, and what are the accuracy targets?

---

## Decision

### Accuracy Targets (PRD §9.1)

| Metric | Target |
|---|---|
| Recall | ≥ 70% |
| Precision | ≥ 50% |

- **Recall** = percentage of actually-changed files that A-Priori predicted would be impacted.
- **Precision** = percentage of predicted files that were actually changed.

---

## Validation Methodology

### 1. PR Selection

Use historical PRs from any git repository. Each PR is represented as the set of files changed between the base commit and the merge commit. The A-Priori knowledge graph must already be built against the repository at the time of validation.

For the reference dataset: use the A-Priori repository itself, which has a rich commit history spanning the full implementation arc.

### 2. Seed Files

For each PR, identify **seed files**: changed files whose associated concepts have pre-computed impact profiles.

- For each changed file `f`, call `store.search_by_file(f)` to find concepts.
- A file is a seed if at least one of its concepts has a non-None `impact_profile`.
- Rationale: only files with computed impact profiles can produce blast radius predictions; files without profiles contribute nothing.

### 3. Prediction

For each seed file, run `query_blast_radius(store, concept_id)` for every concept associated with that file. Collect the file paths from the code references of all returned concepts.

**predicted_files** = union of all file paths across all blast radius results for all seed concepts.

### 4. Ground Truth

**actual_other** = changed files in the PR that are **not** seed files.

These are the "downstream" files — the ones we expect the blast radius to have predicted.

### 5. Per-PR Metrics

```
true_positives  = predicted_files ∩ actual_other
false_positives = predicted_files − actual_other
false_negatives = actual_other − predicted_files

recall    = |true_positives| / |actual_other|       (0.0 if actual_other is empty)
precision = |true_positives| / |predicted_files|    (0.0 if predicted_files is empty)
```

### 6. Aggregate Metrics

Macro-average over all PRs:

```
aggregate_recall    = mean(recall    for each PR)
aggregate_precision = mean(precision for each PR)
```

---

## Test Harness

The validation harness is implemented in:

```
src/apriori/validation/blast_radius_validator.py
```

Key classes:

| Class | Purpose |
|---|---|
| `PRRecord` | Represents a PR as an ID + list of changed files |
| `PRValidationResult` | Per-PR metrics: TP, FP, FN, recall, precision |
| `ValidationReport` | Aggregate report with failure pattern analysis |
| `BlastRadiusValidator` | Runs validation via `validate(prs)` or `validate_pr(pr)` |

Usage:

```python
from apriori.storage.sqlite_store import SQLiteStore
from apriori.validation.blast_radius_validator import (
    BlastRadiusValidator, PRRecord
)

store = SQLiteStore(db_path)
validator = BlastRadiusValidator(store)

prs = [
    PRRecord(pr_id="pr-1", changed_files=["src/module_a.py", "src/module_b.py"]),
    # ... at least 50 PRs
]

report = validator.validate(prs)
print(f"Recall:    {report.aggregate_recall:.1%}")
print(f"Precision: {report.aggregate_precision:.1%}")
print(f"Recall OK: {report.passes_recall_target}")
print(f"Precision OK: {report.passes_precision_target}")
for pattern in report.failure_patterns:
    print(f"  Pattern: {pattern}")
```

---

## Failure Pattern Analysis

The `ValidationReport.failure_patterns` field lists common failure modes:

- **Frequently missed (false negatives):** Files that are regularly changed alongside seed files but are not predicted. Common causes: missing edges in the knowledge graph, low confidence thresholds, or files not yet analyzed.
- **Frequently over-predicted (false positives):** Files that are predicted but rarely actually change in the same PR. Common causes: overly broad structural dependencies (e.g., shared utilities that are imported everywhere but not often co-changed).

---

## Improvement Recommendations (if targets not met)

| Root Cause | Recommended Fix |
|---|---|
| Missing structural edges | Expand tree-sitter extraction to capture more import relationships |
| Missing historical co-change edges | Lower `min_confidence` threshold in historical impact config |
| Files not analyzed | Run `apriori init` on a broader file set; reduce exclude patterns |
| Low profile coverage | Trigger `recompute_impact_profile` maintenance pass |
| Over-broad predictions | Raise `min_confidence` or reduce `max_depth` in blast radius query |

---

## Validation Results

The unit test suite in `tests/validation/test_blast_radius_validator.py` validates the harness mechanics against synthetic PRRecords:

- 16 tests covering: recall computation, precision computation, aggregate metrics, failure patterns, edge cases (single-file PRs, files not in store, multiple concepts per file).
- All tests pass as of AP-105 implementation.

For production validation against real PRs: instantiate `BlastRadiusValidator` with the live SQLiteStore, populate `PRRecord` lists from git history (git log + git diff for each merge commit), and call `report = validator.validate(prs)`.
