# MCP Tool Reference

A-Priori exposes its knowledge graph as a [Model Context Protocol](https://modelcontextprotocol.io) (MCP) server. All tools follow the same conventions:

- All IDs are UUID strings
- All tools return JSON-serializable values
- Errors are returned as MCP `isError: true` responses with a descriptive message
- The server must be running (`python -m apriori.mcp.server`) before tools are available

## Starting the MCP Server

```bash
cd /path/to/your/project
python -m apriori.mcp.server
```

Configure in Claude Desktop or any MCP-compatible client:
```json
{
  "mcpServers": {
    "apriori": {
      "command": "python",
      "args": ["-m", "apriori.mcp.server"],
      "cwd": "/path/to/your/project"
    }
  }
}
```

---

## Read Tools

### `search`

Search the knowledge graph using one of four modes.

**Parameters:**

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `query` | string | Yes | — | Search string or file path |
| `mode` | string | No | `"keyword"` | One of `keyword`, `semantic`, `exact`, `file` |
| `limit` | integer | No | `10` | Max results (not applied in `file` or `exact` mode) |

**Modes:**
- `keyword` — FTS5 full-text search on concept name and description
- `semantic` — Vector similarity search using the configured embedding model
- `exact` — Case-sensitive exact match on concept name
- `file` — Return all concepts that reference the given file path

**Returns:** `list[ConceptDict]`

**Example — keyword search:**
```json
{
  "tool": "search",
  "arguments": { "query": "authentication", "mode": "keyword", "limit": 5 }
}
```

**Example — semantic search:**
```json
{
  "tool": "search",
  "arguments": { "query": "how does the system handle expired sessions?", "mode": "semantic" }
}
```

**Example — find all concepts from a file:**
```json
{
  "tool": "search",
  "arguments": { "query": "src/auth/session.py", "mode": "file" }
}
```

---

### `search_keyword`

Find concepts whose name or description contains the query string (FTS5).

**Parameters:**

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `query` | string | Yes | — | Substring to search (case-insensitive) |
| `limit` | integer | No | `10` | Maximum results |

**Returns:** `list[ConceptDict]`

**Example:**
```json
{ "tool": "search_keyword", "arguments": { "query": "cache invalidation", "limit": 10 } }
```

---

### `search_semantic`

Find concepts semantically similar to a natural-language query.

**Parameters:**

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `query` | string | Yes | — | Natural-language query |
| `limit` | integer | No | `10` | Maximum results |

**Returns:** `list[ConceptDict]` ordered by similarity descending

**Example:**
```json
{
  "tool": "search_semantic",
  "arguments": { "query": "components that break when the database schema changes" }
}
```

---

### `list_concepts`

List all concepts in the knowledge graph, optionally filtered by labels.

**Parameters:**

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `labels` | list[string] | No | `null` | Return only concepts matching any of these labels |

Label filter uses OR semantics: a concept is included if it has *any* of the specified labels.

**Returns:** `list[ConceptDict]`

**Example — all concepts:**
```json
{ "tool": "list_concepts", "arguments": {} }
```

**Example — concepts needing review:**
```json
{ "tool": "list_concepts", "arguments": { "labels": ["needs-review", "stale"] } }
```

---

### `get_concept`

Retrieve a concept by UUID with all connected edges.

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `concept_id` | string (UUID) | Yes | UUID of the concept to retrieve |

**Returns:** `ConceptDict` with an additional `edges` key listing all edges involving this concept

**Raises:** `ToolError` if concept not found

**Example:**
```json
{
  "tool": "get_concept",
  "arguments": { "concept_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6" }
}
```

**Sample response:**
```json
{
  "id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "name": "UserAuthService",
  "description": "Handles user authentication including login, logout, and session management.",
  "labels": ["verified"],
  "confidence": 0.92,
  "created_by": "agent",
  "code_references": [
    { "symbol": "UserAuthService", "file_path": "src/auth/service.py", "line_range": [12, 85] }
  ],
  "edges": [
    {
      "id": "...", "source_id": "...", "target_id": "...",
      "edge_type": "depends-on", "confidence": 0.88
    }
  ]
}
```

---

### `get_neighbors`

Return concepts directly connected to a given concept (1-hop only).

**Parameters:**

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `concept_id` | string (UUID) | Yes | — | UUID of the hub concept |
| `edge_type` | string | No | `null` | Filter to only edges of this type |
| `direction` | string | No | `"both"` | `"outgoing"`, `"incoming"`, or `"both"` |

**Returns:** `list[ConceptDict]`

**Example — find what UserAuthService depends on:**
```json
{
  "tool": "get_neighbors",
  "arguments": {
    "concept_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
    "edge_type": "depends-on",
    "direction": "outgoing"
  }
}
```

---

### `traverse`

Breadth-first traversal of the knowledge graph from a starting concept.

**Parameters:**

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `concept_id` | string (UUID) | Yes | — | UUID of the starting concept |
| `max_hops` | integer | No | `3` | Maximum edge hops to follow |

**Returns:**
```json
{
  "concepts": [ /* list of ConceptDict in BFS order */ ],
  "edges": [ /* list of EdgeDict connecting those concepts */ ]
}
```

**Example:**
```json
{
  "tool": "traverse",
  "arguments": { "concept_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6", "max_hops": 2 }
}
```

---

### `blast_radius`

Return the pre-computed impact profile for a concept.

**Parameters:**

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `target` | string | Yes | — | Concept name, UUID, file path, or function symbol |
| `depth` | integer | No | `null` | Maximum hop depth to include (null = no limit) |
| `min_confidence` | float | No | `null` | Minimum confidence threshold (null = no limit) |

**Returns:** `list[ImpactEntryDict]` sorted by `composite_score` descending

Each entry:
```json
{
  "concept_id": "...",
  "concept_name": "PaymentProcessor",
  "confidence": 0.85,
  "impact_layer": "semantic",
  "depth": 2,
  "relationship_path": ["depends-on", "implements"],
  "rationale": "PaymentProcessor depends on SessionManager which is directly impacted",
  "composite_score": 0.425
}
```

`composite_score = confidence * (1 / depth)`

**Example:**
```json
{
  "tool": "blast_radius",
  "arguments": { "target": "DatabaseConnectionPool", "min_confidence": 0.6 }
}
```

---

### `get_edge`

Retrieve an edge by UUID.

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `edge_id` | string (UUID) | Yes | UUID of the edge to retrieve |

**Returns:** `EdgeDict`

**Raises:** `ToolError` if edge not found

---

### `list_edges`

List edges with optional filters (all filters combine with AND).

**Parameters:**

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `source_id` | string (UUID) | No | `null` | Filter by source concept |
| `target_id` | string (UUID) | No | `null` | Filter by target concept |
| `edge_type` | string | No | `null` | Filter by edge type |

**Returns:** `list[EdgeDict]`

**Example — all edges from a concept:**
```json
{
  "tool": "list_edges",
  "arguments": { "source_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6" }
}
```

---

### `list_edge_types`

Return the configured edge type vocabulary.

**Parameters:** None

**Returns:** `list[string]` — sorted list of valid edge type strings

**Example response:** `["calls", "co-changes-with", "depends-on", "extends", "implements", "imports", "inherits", "owned-by", "relates-to", "shares-assumption-about", "supersedes", "type-references"]`

---

### `get_status`

Return aggregate statistics about the knowledge graph.

**Parameters:** None

**Returns:**
```json
{
  "concept_count": 142,
  "edge_count": 891,
  "work_item_count": 23,
  "review_outcome_count": 67
}
```

---

### `get_metrics`

Alias for `get_status`. Returns identical data.

**Parameters:** None

**Returns:** Same as `get_status`

---

## Write Tools

### `create_concept`

Create a new concept in the knowledge graph.

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `name` | string | Yes | Human-readable name (must be unique) |
| `description` | string | Yes | Full description of the concept |
| `labels` | list[string] | No | Optional labels for filtering |

**Returns:** Created `ConceptDict` including its assigned UUID

**Example:**
```json
{
  "tool": "create_concept",
  "arguments": {
    "name": "RateLimiter",
    "description": "Enforces per-user API rate limits using a sliding window algorithm.",
    "labels": ["needs-review"]
  }
}
```

---

### `update_concept`

Update an existing concept. Only provided fields are modified.

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `concept_id` | string (UUID) | Yes | UUID of the concept to update |
| `name` | string | No | New name |
| `description` | string | No | New description |
| `labels` | list[string] | No | Replacement label set |

**Returns:** Updated `ConceptDict`

**Raises:** `ToolError` if concept not found

---

### `delete_concept`

Delete a concept and all its dependent edges.

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `concept_id` | string (UUID) | Yes | UUID of the concept to delete |

**Returns:** Confirmation message string

**Raises:** `ToolError` if concept not found

---

### `create_edge`

Create a directed edge between two concepts.

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `source_id` | string (UUID) | Yes | UUID of the source concept |
| `target_id` | string (UUID) | Yes | UUID of the target concept |
| `edge_type` | string | Yes | Edge type from the configured vocabulary |
| `rationale` | string | No | Explanation of why this edge exists |

**Returns:** Created `EdgeDict` including its assigned UUID

**Raises:** `ToolError` if either concept not found or edge_type not in vocabulary

**Example:**
```json
{
  "tool": "create_edge",
  "arguments": {
    "source_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
    "target_id": "7ba85f64-1234-4562-b3fc-2c963f66afa6",
    "edge_type": "depends-on",
    "rationale": "UserAuthService uses DatabaseConnectionPool for session storage"
  }
}
```

---

### `update_edge`

Update an existing edge. Only provided fields are modified.

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `edge_id` | string (UUID) | Yes | UUID of the edge to update |
| `edge_type` | string | No | New edge type from vocabulary |
| `confidence` | float | No | New confidence score [0.0, 1.0] |
| `metadata` | object | No | Replacement metadata dict |

**Returns:** Updated `EdgeDict`

**Raises:** `ToolError` if edge not found or edge_type not in vocabulary

---

### `delete_edge`

Delete an edge from the knowledge graph.

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `edge_id` | string (UUID) | Yes | UUID of the edge to delete |

**Returns:** Confirmation message string

**Raises:** `ToolError` if edge not found

---

### `report_gap`

Report a knowledge gap for the librarian to investigate.

Creates a placeholder concept (labeled `auto-generated`, `needs-review`) and a `reported_gap` work item. The librarian picks this up in its next run.

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `description` | string | Yes | Description of the missing or incomplete knowledge |
| `context` | string | No | Additional context to scope the investigation |

**Returns:** Created `WorkItemDict` including its assigned UUID

**Example:**
```json
{
  "tool": "report_gap",
  "arguments": {
    "description": "How does the system handle partial payment failures?",
    "context": "This came up during a code review of the checkout flow"
  }
}
```

---

## Data Schemas

### ConceptDict

```json
{
  "id": "UUID",
  "name": "string",
  "description": "string",
  "labels": ["string"],
  "confidence": 0.0,
  "created_by": "agent | human",
  "verified_by": "string | null",
  "last_verified": "ISO datetime | null",
  "derived_from_code_version": "git SHA | null",
  "code_references": [ /* CodeReferenceDict */ ],
  "impact_profile": { /* ImpactProfileDict | null */ },
  "metadata": { /* dict | null */ },
  "created_at": "ISO datetime",
  "updated_at": "ISO datetime"
}
```

### EdgeDict

```json
{
  "id": "UUID",
  "source_id": "UUID",
  "target_id": "UUID",
  "edge_type": "string",
  "evidence_type": "structural | semantic | historical",
  "confidence": 0.0,
  "metadata": { /* dict | null */ },
  "derived_from_code_version": "git SHA | null",
  "created_at": "ISO datetime",
  "updated_at": "ISO datetime"
}
```

### WorkItemDict

```json
{
  "id": "UUID",
  "item_type": "investigate_file | reported_gap | escalated",
  "concept_id": "UUID",
  "description": "string",
  "priority_score": 0.0,
  "failure_count": 0,
  "created_at": "ISO datetime"
}
```
