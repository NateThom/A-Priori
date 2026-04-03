# S-2: Embedding Strategy Decision Record

**Date:** 2026-04-03
**Status:** Decided
**Decision:** Local embeddings via `e5-base-v2` (768 dimensions) using `sentence-transformers`

---

## Context

A-Priori's `search` MCP tool supports a `semantic` mode that finds concepts by meaning rather than keyword. This requires vector embeddings of concept descriptions stored in a sqlite-vec `vec0` virtual table. The `vec0` table requires a fixed embedding dimension at creation time — it cannot be changed without rebuilding the entire index.

Three options were considered: (a) local embedding model via `sentence-transformers`, (b) configured LLM provider's embedding API, (c) defer vector search to Phase 2. Semantic search was determined to be a must-have for Phase 1 — agents need to find concepts by meaning from day one.

## Decision

**Local embeddings via `intfloat/e5-base-v2` with 768 dimensions.**

Embeddings are generated locally using `sentence-transformers`. No network calls, no API cost, no provider dependency. The embedding model is configurable but the dimension is immutable per database.

## Rationale

### Local embeddings align with the cost curve principle

The PRD's design principle is that "the cost curve shall decrease over time." LLM-generated embeddings have a per-embedding cost that scales linearly with the number of concepts. Local embeddings cost nothing after the initial model download. Once a concept is embedded, querying it is free forever.

### Provider independence

Anthropic does not offer a public embedding API. OpenAI's `text-embedding-3-small` uses 1536 dimensions, Cohere uses 1024, and Ollama users would need to configure a separate embedding model anyway. A local model works identically regardless of the user's LLM provider choice, eliminating a category of configuration complexity.

### e5-base-v2 is the right quality/size trade-off

`e5-base-v2` (109M params, 768d, ~440MB) outperforms many models 70x its size on retrieval benchmarks. It produces strong embeddings for technical and natural language text. At 768 dimensions, sqlite-vec queries at 1k-10k vectors are sub-10ms with SIMD-accelerated brute-force scan.

`all-MiniLM-L6-v2` (384d) was considered but is now outperformed by e5-base on retrieval quality. The ~300MB difference in model size is not meaningful for a developer tool.

### sqlite-vec cosine distance is native

sqlite-vec supports `vec_distance_cosine()` natively and the `distance_metric=cosine` option on `vec0` tables. No pre-normalization required. At MVP scale (1k-10k vectors), brute-force scan is effectively instant — no ANN indexing needed.

## What Gets Embedded

The concatenation of a concept's `name` and `description` fields. Specifically:

```
{concept.name}: {concept.description}
```

**Why not code references?** Code references contain file paths (`src/payments/validate.py`) and symbol names (`validate_amount`) — structured identifiers, not natural language. Embedding them produces low-quality vectors and introduces false matches based on path similarity rather than semantic similarity. The concept description already captures what the referenced code *means and does*, which is the semantic signal that vector search needs.

**Why not raw code content?** A-Priori matches on what code means, not how it's written. The librarian's description is a higher-level behavioral summary that enables matching across different implementations. "Validate user input" should match both a regex-based email checker and a JSON Schema validator despite completely different code. Embedding descriptions achieves this; embedding code would not.

**The chained query pattern for "files like X":**
1. `search_by_file("path/to/file.py")` → returns concepts referencing that file (exact match, no embeddings)
2. Take those concepts' embeddings → find similar concepts via vector similarity
3. Similar concepts' `code_references` point to the other files that do similar things

## Embedding Lifecycle

**When embeddings are generated:**
- `create_concept` — embed `name: description` and insert into `concept_embeddings`
- `update_concept` — if `name` or `description` changed, regenerate and update the embedding
- `rebuild_index` — regenerate all embeddings from YAML flat files (handles model changes)

**Where the embedding logic lives:** A thin `EmbeddingService` class that wraps `sentence-transformers`. Initialized once at startup (model loaded into memory), reused across all operations. This is an implementation detail of `sqlite_store.py`, not part of the `KnowledgeStore` protocol — the protocol's `search_semantic` method accepts a pre-computed query embedding vector.

The query path:
1. Caller provides a text query to the retrieval layer
2. Retrieval layer calls `EmbeddingService.embed(query_text)` to get a vector
3. Retrieval layer calls `store.search_semantic(embedding, limit)` to find similar concepts

## Schema

```sql
CREATE VIRTUAL TABLE concept_embeddings USING vec0(
    concept_id TEXT PRIMARY KEY,
    embedding FLOAT[768],
    +distance_metric=cosine
);
```

## Configuration

New fields in `apriori.config.yaml`:

```yaml
storage:
  embedding_model: "intfloat/e5-base-v2"  # HuggingFace model ID
  embedding_dimensions: 768                 # Must match model output
```

Startup validation: if `embedding_dimensions` doesn't match the existing `vec0` table, the system raises a clear error with instructions to run `apriori rebuild-index` to regenerate embeddings with the new model.

## Dependency Impact

New dependencies:
- `sentence-transformers` (pulls in `transformers`, `torch`)
- Total installed size: ~2GB (dominated by PyTorch)
- Model download: ~440MB on first use, cached in `~/.cache/huggingface/`

This is significant but acceptable for a Python developer tool. The alternative (requiring users to configure an LLM embedding endpoint) trades dependency size for configuration complexity and ongoing API cost.

## Consequences

### Storage Layer
- The `concept_embeddings` vec0 table is created with `FLOAT[768]` and `distance_metric=cosine`
- `EmbeddingService` is initialized at `SqliteStore` construction time
- `create_concept` and `update_concept` generate embeddings as a side effect
- `rebuild_index` must regenerate all embeddings (iterate YAML files, re-embed, re-insert)

### Retrieval Layer
- `search_semantic` accepts a `query_embedding: list[float]` parameter
- The `query_router` embeds the text query before calling `search_semantic`
- Vector search results are ranked by cosine similarity

### Performance Characteristics
- Embedding generation: ~25ms per concept on CPU (e5-base-v2)
- Vector query: sub-10ms at 1k-10k vectors (sqlite-vec brute-force with SIMD)
- Model loading: 2-5 seconds at startup (one-time)

### Scaling Considerations
- sqlite-vec brute-force scan degrades linearly beyond ~100k vectors
- At MVP scale (1k-10k concepts), this is not a concern
- If A-Priori grows to 100k+ concepts, ANN indexing (e.g., DiskANN, HNSW via a different backend) becomes relevant — but that's a future concern, not an MVP one

## What This Decision Does NOT Cover

- Whether to embed edge descriptions (decision: no — edges are typed relationships, not free-text)
- Multi-model embedding routing (YAGNI)
- ANN indexing strategy (not needed at MVP scale)
- Embedding code content directly (not A-Priori's use case — see rationale above)
- The specific `e5-base-v2` prompt prefix (`query:` vs `passage:`) — implementation detail for the embedding service. Note: e5 models expect `query: ` prefix for queries and `passage: ` prefix for documents to achieve optimal retrieval quality. The `EmbeddingService` must handle this transparently.
