# Audit UI Guide

The A-Priori Audit UI is a read-only web interface for browsing the knowledge graph, reviewing concepts, and monitoring the health of the enrichment pipeline.

---

## Starting the UI

```bash
apriori ui
```

Options:

| Flag | Default | Description |
|---|---|---|
| `--host HOST` | `127.0.0.1` | Host to bind to |
| `--port PORT` | `8000` | Port to listen on |
| `--db PATH` | config default | Path to the SQLite database |
| `--reload` | off | Auto-reload on file changes (development mode) |

Open `http://127.0.0.1:8000` in your browser.

---

## Navigation Overview

The UI has five main sections, accessible from the sidebar:

| Section | Purpose |
|---|---|
| **Graph** | Interactive knowledge graph visualization |
| **Concepts** | Searchable list of all concepts |
| **Activity** | Recent librarian iterations and analysis history |
| **Health** | Quality metrics, priority weights, and targets |
| **Escalated** | Concepts the librarian repeatedly failed to analyze |

---

## Graph View

The Graph view shows an interactive visualization of the knowledge graph centered on a selected concept.

### Controls

| Control | Description |
|---|---|
| **Center concept** | UUID or name of the concept to center the graph on |
| **Radius** | Number of hops to display (1–5, default 2) |
| **Edge type filter** | Show only edges of a specific type (e.g., `depends-on`) |
| **Min confidence** | Hide edges below this confidence threshold [0.0, 1.0] |
| **Layout** | `force-directed` (physics-based) or `breadthfirst` (tree layout) |

### Visual Encoding

Nodes and edges are styled by confidence level:

| Confidence | Color | Meaning |
|---|---|---|
| High (≥ 0.8) | Teal (`#0f766e`) | Verified, high-confidence knowledge |
| Medium (0.5–0.8) | Amber (`#b45309`) | Accepted but may need review |
| Low (< 0.5) | Red (`#b91c1c`) | Uncertain; review recommended |

Edges are drawn as:
- **Solid line** — high or medium confidence
- **Dashed line** — low confidence

### Interacting with the Graph

- **Click a node** to open the concept detail panel on the right
- **Click an edge** to see the edge type and metadata
- **Scroll** to zoom in/out
- **Drag** to pan
- **Double-click a node** to re-center the graph on it

---

## Concepts List

The Concepts list shows all concepts in the knowledge graph with search and filter capabilities.

### Filtering

- **Search box** — FTS5 keyword search on name and description
- **Label filter** — Filter by label(s) with OR semantics: `needs-review`, `verified`, `stale`, `auto-generated`, `deprecated`

### Concept Summary Fields

Each concept in the list shows:
- Name and truncated description
- Confidence score (color-coded: green/amber/red)
- Labels (badge chips)
- `created_by`: `agent` or `human`
- Last updated timestamp

### Concept Detail Panel

Click any concept to open the detail panel:

**Metadata tab:**
- Full description
- All labels
- Confidence score
- Created by / verified by
- Last verified timestamp
- Git SHA the analysis was derived from
- Impact profile (structural, semantic, historical impact scores)

**Code References tab:**
- Symbol name and file path
- Line range
- Code snippet (read from disk at request time)
- `[unresolved]` badge if the file or line range no longer exists

**Edges tab:**
- All outgoing and incoming edges
- Edge type, evidence type (structural/semantic/historical), confidence

---

## Review Workflow

A-Priori supports three review actions for any concept. These are the primary way humans contribute to knowledge quality.

> **Access:** Review actions are available in the concept detail panel under the **Review** tab.

### Verify

Mark a concept as correct. Use this when you've read the concept description and it accurately represents the code.

**Effect:**
- Confidence is boosted (toward 1.0)
- `verified` label added
- `last_verified` timestamp updated
- `needs-review` label removed

**When to use:** When the librarian's analysis is accurate and complete.

### Correct

Submit a correction for a concept. Use this when the description is wrong, incomplete, or misleading.

**Fields:**
- **Reviewer name** — Your name or handle
- **Error type** — Choose from the valid error types (see below)
- **Correction details** — Describe what was wrong
- **Corrected description** — Optional replacement description
- **Corrected relationships** — Optional replacement edges

**Error types:**

| Error Type | When to Use |
|---|---|
| `incorrect_description` | The description doesn't match what the code does |
| `missing_relationships` | Important edges are absent |
| `wrong_relationships` | Edges point to the wrong concepts |
| `scope_mismatch` | Concept captures too much or too little |
| `stale_description` | Description was accurate but the code has changed |
| `hallucination` | The librarian invented facts not present in the code |

**Effect:**
- Review outcome recorded
- Concept queued for re-analysis with correction context
- `needs-review` label added

### Flag

Mark a concept for re-investigation without providing a specific correction. Use this when something seems off but you're not sure what.

**Effect:**
- New work item created (`reported_gap` type)
- Concept labeled `needs-review`
- Librarian will investigate in its next run

---

## Activity View

The Activity view shows the librarian's recent analysis history.

### Reading Activity Entries

Each entry represents one librarian iteration:

| Field | Description |
|---|---|
| **Timestamp** | When the iteration ran |
| **Work item** | What the librarian analyzed (file investigation or reported gap) |
| **Concept** | The concept that was created or updated |
| **Tokens used** | API tokens consumed by this iteration |
| **Yield** | Whether the iteration produced accepted knowledge (✓) or was rejected (✗) |
| **Failure reason** | If rejected, why the quality pipeline rejected it |
| **Co-regulation score** | The confidence score from the co-regulation review |

### Patterns to Watch

- **Low yield rate** (many ✗): The model is struggling. Check the failure reasons — common causes are overly generic descriptions or hallucinated relationships. Consider switching to a more capable model.
- **Consistent failure on same concepts**: These may be escalated. Check the Escalated view.
- **High token counts**: The librarian is processing very large files. Consider breaking them up or increasing `budget.max_tokens_per_iteration`.

---

## Health Dashboard

The Health dashboard gives you an at-a-glance view of knowledge graph quality.

### Metrics

| Metric | Formula | Target |
|---|---|---|
| **Coverage** | Files with ≥1 concept / total source files | ≥ 80% |
| **Freshness** | Recently verified concepts / total concepts | ≥ 70% |
| **Blast Radius Completeness** | Concepts with impact profile / total concepts | ≥ 80% |

Metrics are shown as progress bars with:
- **Green** — at or above target
- **Amber** — below target but within 20%
- **Red** — significantly below target

### Priority Weights Panel

Shows the **effective** priority weights after adaptive modulation, compared to the **base** weights from config. When these differ significantly, the system is actively compensating for a health gap.

For example, if coverage is low, you'll see `developer_proximity` boosted above its base weight of 0.25.

### Work Queue Panel

Shows:
- Total pending work items
- Escalated item count
- Items by type (investigate_file, reported_gap, escalated)

A large escalated count means concepts that the librarian cannot analyze successfully. These need human review to unblock.

---

## Escalated Items View

Escalated items are concepts the librarian has failed to analyze multiple times. They require human intervention.

### Reading an Escalated Item

Each escalated item shows:
- The concept name and current labels
- Total failure count
- Associated concept (if any)

**Failure History** accordion (expand to see):
- Attempt timestamp
- Model used
- Prompt template
- Failure reason
- Quality scores from co-regulation
- Reviewer feedback (if any)

### Resolving Escalated Items

1. Click the concept name to open the concept detail panel
2. Read the failure history to understand why analysis failed
3. Use **Correct** to provide a description that resolves the conflict
4. Or use **Flag** if more investigation is needed
5. The librarian will re-analyze the concept with your correction context

Common causes of escalation:
- The code is highly abstract or framework-generated
- The concept spans many files and the context window is insufficient
- The librarian and co-regulator consistently disagree on the relationship vocabulary
- The file has been deleted or significantly restructured since the work item was created

---

## REST API

The audit UI is backed by a FastAPI server that you can query directly.

| Endpoint | Description |
|---|---|
| `GET /api/concepts` | List concepts (optional `?label=X` filter) |
| `GET /api/concepts/{id}` | Full concept with edges, impact profile, code references |
| `GET /api/graph` | Subgraph in Cytoscape.js format |
| `GET /api/activity` | Recent librarian activity (optional `?limit=N`) |
| `GET /api/health` | Quality metrics, targets, effective weights |
| `GET /api/escalated-items` | All escalated items with failure history |
| `GET /api/review/error-types` | Valid error types for corrections |
| `POST /api/concepts/{id}/verify` | Verify a concept |
| `POST /api/concepts/{id}/correct` | Submit a correction |
| `POST /api/concepts/{id}/flag` | Flag for re-investigation |

### API Documentation

When the server is running, visit `http://127.0.0.1:8000/docs` for the interactive Swagger UI with full request/response schemas.

### Example: Query the graph

```bash
# List all concepts needing review
curl "http://127.0.0.1:8000/api/concepts?label=needs-review"

# Get graph around a concept
curl "http://127.0.0.1:8000/api/graph?center=3fa85f64-5717-4562-b3fc-2c963f66afa6&radius=2"

# Verify a concept
curl -X POST "http://127.0.0.1:8000/api/concepts/3fa85f64.../verify" \
  -H "Content-Type: application/json" \
  -d '{"reviewer": "alice"}'
```
