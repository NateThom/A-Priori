"""MCP server for A-Priori (AP-68 scaffold; AP-70 read tools; AP-72 write tools; ERD §3.4).

Thin shell using FastMCP. All business logic lives in core apriori modules
(arch:mcp-thin-shell, arch:core-lib-thin-shells). Tool functions are plain
``def`` (arch:sync-first). The lifespan context manager initialises a
DualWriter KnowledgeStore (arch:sqlite-vec-storage).

Usage::

    python -m apriori.mcp.server

Pin: mcp>=1.26,<2.0.
"""

from __future__ import annotations

import functools
import logging
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator, Callable, Optional

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

from apriori.config import load_config
from apriori.embedding.protocol import EmbeddingServiceProtocol
from apriori.models.concept import Concept
from apriori.models.edge import Edge, EdgeTypeVocabulary, load_edge_vocabulary
from apriori.models.work_item import WorkItem
from apriori.storage.dual_writer import DualWriter
from apriori.storage.protocol import KnowledgeStore
from apriori.storage.sqlite_store import SQLiteStore
from apriori.storage.yaml_store import YamlStore

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level store — set by lifespan, accessed by tool functions.
# Tests inject values directly (e.g. ``mcp_server._store = test_store``).
# ---------------------------------------------------------------------------

_store: Optional[KnowledgeStore] = None
_embedding_service: Optional[EmbeddingServiceProtocol] = None
_edge_vocabulary: Optional[EdgeTypeVocabulary] = None


def _get_store() -> KnowledgeStore:
    """Return the active KnowledgeStore or raise ToolError if not initialised."""
    if _store is None:
        raise ToolError("KnowledgeStore not initialised — is the server running?")
    return _store


def _get_embedding_service() -> EmbeddingServiceProtocol:
    """Return the active EmbeddingService, loading it lazily on first call."""
    global _embedding_service
    if _embedding_service is None:
        from apriori.embedding.service import EmbeddingService  # heavy import
        _embedding_service = EmbeddingService()
    return _embedding_service


def _get_edge_vocabulary() -> EdgeTypeVocabulary:
    """Return the active EdgeTypeVocabulary, or raise ToolError if not set."""
    if _edge_vocabulary is None:
        raise ToolError("Edge vocabulary not initialized — is the MCP server running?")
    return _edge_vocabulary


# ---------------------------------------------------------------------------
# Error-handling decorator (AC3)
# ---------------------------------------------------------------------------


def safe_tool(fn: Callable) -> Callable:
    """Catch unexpected exceptions from tool implementations and raise ToolError.

    FastMCP converts ToolError to an isError=True wire response so clients
    receive a descriptive error message rather than a raw exception traceback.

    Args:
        fn: The tool function to wrap.

    Returns:
        Wrapped function that raises ToolError on unexpected exceptions.
    """

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return fn(*args, **kwargs)
        except ToolError:
            raise  # already formatted — let it propagate unchanged
        except Exception as exc:
            raise ToolError(
                f"Tool '{fn.__name__}' failed: {type(exc).__name__}: {exc}"
            ) from exc

    return wrapper


# ---------------------------------------------------------------------------
# Lifespan — initialise KnowledgeStore (AC1, AC4)
# ---------------------------------------------------------------------------


def build_lifespan(
    db_path: Optional[Path] = None,
    yaml_path: Optional[Path] = None,
) -> Callable[..., AsyncIterator[dict[str, Any]]]:
    """Return a FastMCP lifespan context manager factory.

    Reads storage paths from config when not explicitly supplied. Used directly
    by the server (default paths) and by tests (injected tmp_path). Sets the
    module-level ``_store``, ``_embedding_service``, and ``_edge_vocabulary``
    on entry and clears them on exit.

    Args:
        db_path: Override for the SQLite database path.
        yaml_path: Override for the YAML backup directory path.

    Returns:
        An async context manager that yields ``{"store": DualWriter}`` and
        cleans up on exit.
    """

    @asynccontextmanager
    async def lifespan(server: FastMCP) -> AsyncIterator[dict[str, Any]]:
        global _store, _embedding_service, _edge_vocabulary

        config = load_config()

        resolved_db = db_path if db_path is not None else Path(config.storage.sqlite_path)
        resolved_yaml = yaml_path if yaml_path is not None else Path(config.storage.yaml_backup_path)

        logger.info("Initialising SQLiteStore at %s", resolved_db)
        sqlite_store = SQLiteStore(db_path=resolved_db)

        logger.info("Initialising YamlStore at %s", resolved_yaml)
        yaml_store = YamlStore(base_dir=resolved_yaml)

        store = DualWriter(sqlite_store=sqlite_store, yaml_store=yaml_store)
        logger.info("KnowledgeStore ready (DualWriter)")

        _store = store
        _embedding_service = None  # loaded lazily on first semantic search
        _edge_vocabulary = load_edge_vocabulary(config)

        try:
            yield {"store": store}
        finally:
            _store = None
            _embedding_service = None
            _edge_vocabulary = None
            logger.info("MCP server shutting down — KnowledgeStore released")

    return lifespan


# ---------------------------------------------------------------------------
# FastMCP application
# ---------------------------------------------------------------------------

mcp = FastMCP("apriori", lifespan=build_lifespan())

# ---------------------------------------------------------------------------
# Read tools — Story 4.2 (AP-70)
# ---------------------------------------------------------------------------


@mcp.tool()
@safe_tool
def search(query: str, mode: str = "keyword", limit: int = 10) -> list:
    """Search the knowledge graph using one of four modes.

    Modes:
    - ``"keyword"``: FTS5 full-text search on concept name and description.
    - ``"semantic"``: Vector similarity search using the configured embedding model.
    - ``"exact"``: Case-sensitive exact match on concept name.
    - ``"file"``: Return all concepts that reference the given file path.

    Args:
        query: Search string (keyword/semantic/exact) or file path (file mode).
        mode: One of ``"keyword"``, ``"semantic"``, ``"exact"``, ``"file"``.
        limit: Maximum results to return (not applied in ``"file"`` or ``"exact"`` mode).

    Returns:
        List of matching concept dicts.
    """
    store = _get_store()

    if mode == "keyword":
        concepts = store.search_keyword(query, limit=limit)
    elif mode == "semantic":
        embedding = _get_embedding_service().generate_embedding(query, text_type="query")
        concepts = store.search_semantic(embedding, limit=limit)
    elif mode == "exact":
        concepts = [c for c in store.list_concepts() if c.name == query]
    elif mode == "file":
        concepts = store.search_by_file(query)
    else:
        raise ToolError(f"Unknown search mode '{mode}'. Use keyword, semantic, exact, or file.")

    return [c.model_dump(mode="json") for c in concepts]


@mcp.tool()
@safe_tool
def traverse(concept_id: str, max_hops: int = 3) -> dict:
    """Breadth-first traversal of the knowledge graph from a starting concept.

    Follows outgoing edges and returns all reachable concepts up to ``max_hops``
    edges from the starting concept, along with the connecting edges between them.

    Args:
        concept_id: UUID string of the starting concept.
        max_hops: Maximum number of edge hops to follow (default 3).

    Returns:
        Dict with ``concepts`` (list of concept dicts in BFS order) and
        ``edges`` (list of edge dicts connecting those concepts).
    """
    store = _get_store()
    concepts = store.traverse_graph(
        start_id=uuid.UUID(concept_id),
        max_depth=max_hops,
    )
    concept_ids = {c.id for c in concepts}
    edges = [
        e
        for cid in concept_ids
        for e in store.list_edges(source_id=cid)
        if e.target_id in concept_ids
    ]
    return {
        "concepts": [c.model_dump(mode="json") for c in concepts],
        "edges": [e.model_dump(mode="json") for e in edges],
    }


@mcp.tool()
@safe_tool
def get_concept(concept_id: str) -> dict:
    """Retrieve a Concept from the knowledge graph by its UUID.

    Returns the full concept including metadata, code references, and all
    connected edges (both outgoing and incoming).

    Args:
        concept_id: UUID string of the concept to retrieve.

    Returns:
        Concept data as a dict with an additional ``edges`` key listing all
        edges that involve this concept.

    Raises:
        ToolError: If the concept does not exist.
    """
    store = _get_store()
    cid = uuid.UUID(concept_id)
    concept = store.get_concept(cid)
    if concept is None:
        raise ToolError(f"Concept not found: {concept_id}")
    edges = store.list_edges(source_id=cid) + store.list_edges(target_id=cid)
    result = concept.model_dump(mode="json")
    result["edges"] = [e.model_dump(mode="json") for e in edges]
    return result


@mcp.tool()
@safe_tool
def list_edge_types() -> list:
    """Return the configured edge type vocabulary.

    Edge types are defined in ``apriori.config.yaml`` (or the defaults). This
    tool lets agents and callers discover valid edge types before creating edges.

    Returns:
        Sorted list of edge type strings (e.g. ``["calls", "depends-on", ...]``).
    """
    config = load_config()
    return sorted(config.edge_types)


@mcp.tool()
@safe_tool
def get_status() -> dict:
    """Return aggregate statistics about the current knowledge graph.

    Returns:
        Dict with at minimum: ``concept_count``, ``edge_count``,
        ``work_item_count``, ``review_outcome_count``.
    """
    return _get_store().get_metrics()


@mcp.tool()
@safe_tool
def blast_radius(
    target: str,
    depth: Optional[int] = None,
    min_confidence: Optional[float] = None,
) -> list:
    """Return the pre-computed blast-radius impact profile for a target.

    Accepts a concept name, concept UUID, file path, or function symbol and
    returns a prioritised list of impacted concepts sorted by composite score
    (``confidence * 1/depth``).  All business logic lives in
    :mod:`apriori.retrieval.blast_radius_query` (arch:mcp-thin-shell).

    Args:
        target: Concept name, UUID string, file path, or function symbol.
        depth: Maximum hop depth to include (default: no limit).
        min_confidence: Minimum confidence threshold (default: no limit).

    Returns:
        List of impact entry dicts, each with keys: ``concept_id``,
        ``concept_name``, ``confidence``, ``impact_layer``, ``depth``,
        ``relationship_path``, ``rationale``, ``composite_score``.
        Sorted by ``composite_score`` descending.  Empty list when *target*
        cannot be resolved or has no stored impact profile.
    """
    from apriori.retrieval.blast_radius_query import query_blast_radius

    store = _get_store()
    entries = query_blast_radius(
        store,
        target,
        max_depth=depth,
        min_confidence=min_confidence,
    )
    return [
        {
            "concept_id": str(e.concept_id),
            "concept_name": e.concept_name,
            "confidence": e.confidence,
            "impact_layer": e.impact_layer,
            "depth": e.depth,
            "relationship_path": e.relationship_path,
            "rationale": e.rationale,
            "composite_score": e.composite_score,
        }
        for e in entries
    ]


# ---------------------------------------------------------------------------
# Read tools — existing scaffolded stubs, implemented here (AP-70)
# ---------------------------------------------------------------------------


@mcp.tool()
@safe_tool
def list_concepts(labels: Optional[list[str]] = None) -> list:
    """List all Concepts in the knowledge graph, optionally filtered by labels.

    Args:
        labels: When provided, return only concepts whose label set intersects
            with this list. When omitted, return all concepts.

    Returns:
        List of concept dicts.
    """
    store = _get_store()
    label_set = set(labels) if labels else None
    return [c.model_dump(mode="json") for c in store.list_concepts(labels=label_set)]


@mcp.tool()
@safe_tool
def search_keyword(query: str, limit: int = 10) -> list:
    """Find Concepts whose name or description contains the query string (FTS5).

    Args:
        query: Substring to search for (case-insensitive).
        limit: Maximum number of results to return (default 10).

    Returns:
        List of matching concept dicts.
    """
    return [c.model_dump(mode="json") for c in _get_store().search_keyword(query, limit=limit)]


@mcp.tool()
@safe_tool
def search_semantic(query: str, limit: int = 10) -> list:
    """Find Concepts semantically similar to the query string.

    Embeds the query using the configured embedding model and performs a
    nearest-neighbour search over the sqlite-vec index.

    Args:
        query: Natural-language search query.
        limit: Maximum number of results to return (default 10).

    Returns:
        List of concept dicts ordered by similarity descending.
    """
    embedding = _get_embedding_service().generate_embedding(query, text_type="query")
    return [c.model_dump(mode="json") for c in _get_store().search_semantic(embedding, limit=limit)]


@mcp.tool()
@safe_tool
def get_neighbors(
    concept_id: str,
    edge_type: Optional[str] = None,
    direction: str = "both",
) -> list:
    """Return Concepts directly connected to the given Concept via Edges.

    Args:
        concept_id: UUID string of the hub concept.
        edge_type: When provided, consider only edges of this type.
        direction: ``"outgoing"`` | ``"incoming"`` | ``"both"`` (default).

    Returns:
        List of neighbouring concept dicts.
    """
    return [
        c.model_dump(mode="json")
        for c in _get_store().get_neighbors(
            concept_id=uuid.UUID(concept_id),
            edge_type=edge_type,
            direction=direction,
        )
    ]


@mcp.tool()
@safe_tool
def get_metrics() -> dict:
    """Return aggregate statistics about the knowledge graph.

    Returns:
        Dict with keys: concept_count, edge_count, work_item_count,
        review_outcome_count, and any additional implementation metrics.
    """
    return _get_store().get_metrics()


@mcp.tool()
@safe_tool
def get_edge(edge_id: str) -> dict:
    """Retrieve an Edge from the knowledge graph by its UUID.

    Args:
        edge_id: UUID string of the edge to retrieve.

    Returns:
        Edge data as a dict.

    Raises:
        ToolError: If the edge does not exist.
    """
    store = _get_store()
    edge = store.get_edge(uuid.UUID(edge_id))
    if edge is None:
        raise ToolError(f"Edge not found: {edge_id}")
    return edge.model_dump(mode="json")


@mcp.tool()
@safe_tool
def list_edges(
    source_id: Optional[str] = None,
    target_id: Optional[str] = None,
    edge_type: Optional[str] = None,
) -> list:
    """List Edges in the knowledge graph with optional filters.

    All filters are optional and combine with AND semantics.

    Args:
        source_id: When provided, include only edges with this source concept.
        target_id: When provided, include only edges with this target concept.
        edge_type: When provided, include only edges of this type.

    Returns:
        List of edge dicts.
    """
    return [
        e.model_dump(mode="json")
        for e in _get_store().list_edges(
            source_id=uuid.UUID(source_id) if source_id else None,
            target_id=uuid.UUID(target_id) if target_id else None,
            edge_type=edge_type,
        )
    ]


# ---------------------------------------------------------------------------
# Write tools — Story 4.3 (AP-72)
# ---------------------------------------------------------------------------


@mcp.tool()
@safe_tool
def create_concept(
    name: str,
    description: str,
    labels: Optional[list[str]] = None,
) -> dict:
    """Create a new Concept in the knowledge graph.

    Writes to both SQLite (runtime index) and YAML (authoritative backup) via
    the DualWriter (arch:sqlite-vec-storage).

    Args:
        name: Human-readable concept name (must be unique).
        description: Full description of the concept.
        labels: Optional list of label strings for filtering.

    Returns:
        The created concept dict including its assigned UUID.
    """
    store = _get_store()
    concept = Concept(
        name=name,
        description=description,
        labels=set(labels) if labels else set(),
        created_by="human",
    )
    result = store.create_concept(concept)
    return result.model_dump(mode="json")


@mcp.tool()
@safe_tool
def update_concept(
    concept_id: str,
    name: Optional[str] = None,
    description: Optional[str] = None,
    labels: Optional[list[str]] = None,
) -> dict:
    """Update an existing Concept in the knowledge graph.

    Provide only the fields to change; omitted fields are left unchanged.

    Args:
        concept_id: UUID string of the concept to update.
        name: New name for the concept (optional).
        description: New description (optional).
        labels: Replacement label list (optional).

    Returns:
        The updated concept dict.
    """
    store = _get_store()
    cid = uuid.UUID(concept_id)
    existing = store.get_concept(cid)
    if existing is None:
        raise ToolError(f"Concept '{concept_id}' not found")
    updates: dict[str, Any] = {"updated_at": datetime.now(timezone.utc)}
    if name is not None:
        updates["name"] = name
    if description is not None:
        updates["description"] = description
    if labels is not None:
        updates["labels"] = set(labels)
    updated = existing.model_copy(update=updates)
    result = store.update_concept(updated)
    return result.model_dump(mode="json")


@mcp.tool()
@safe_tool
def delete_concept(concept_id: str) -> str:
    """Delete a Concept and all its dependent Edges from the knowledge graph.

    Args:
        concept_id: UUID string of the concept to delete.

    Returns:
        Confirmation message including the deleted concept ID.
    """
    store = _get_store()
    cid = uuid.UUID(concept_id)
    existing = store.get_concept(cid)
    if existing is None:
        raise ToolError(f"Concept '{concept_id}' not found")
    store.delete_concept(cid)
    return f"Concept '{concept_id}' deleted successfully."


@mcp.tool()
@safe_tool
def create_edge(
    source_id: str,
    target_id: str,
    edge_type: str,
    rationale: Optional[str] = None,
) -> dict:
    """Create a directed Edge between two Concepts in the knowledge graph.

    The edge type must belong to the configured vocabulary. Writes to both
    SQLite and YAML via the DualWriter (arch:sqlite-vec-storage).

    Args:
        source_id: UUID string of the source concept.
        target_id: UUID string of the target concept.
        edge_type: Edge type string from the configured vocabulary.
        rationale: Optional explanation of why this edge exists.

    Returns:
        The created edge dict including its assigned UUID.
    """
    store = _get_store()
    vocab = _get_edge_vocabulary()
    try:
        vocab.validate(edge_type)
    except ValueError as exc:
        raise ToolError(str(exc))
    metadata = {"rationale": rationale} if rationale else None
    edge = Edge(
        source_id=uuid.UUID(source_id),
        target_id=uuid.UUID(target_id),
        edge_type=edge_type,
        evidence_type="semantic",
        metadata=metadata,
    )
    result = store.create_edge(edge)
    return result.model_dump(mode="json")


@mcp.tool()
@safe_tool
def update_edge(
    edge_id: str,
    edge_type: Optional[str] = None,
    confidence: Optional[float] = None,
    metadata: Optional[dict] = None,
) -> dict:
    """Update an existing Edge in the knowledge graph.

    Provide only the fields to change; omitted fields are left unchanged.

    Args:
        edge_id: UUID string of the edge to update.
        edge_type: New edge type from the configured vocabulary (optional).
        confidence: New confidence score between 0.0 and 1.0 (optional).
        metadata: Replacement metadata dict (optional).

    Returns:
        The updated edge dict.
    """
    store = _get_store()
    eid = uuid.UUID(edge_id)
    existing = store.get_edge(eid)
    if existing is None:
        raise ToolError(f"Edge '{edge_id}' not found")
    updates: dict[str, Any] = {"updated_at": datetime.now(timezone.utc)}
    if edge_type is not None:
        vocab = _get_edge_vocabulary()
        try:
            vocab.validate(edge_type)
        except ValueError as exc:
            raise ToolError(str(exc))
        updates["edge_type"] = edge_type
    if confidence is not None:
        updates["confidence"] = confidence
    if metadata is not None:
        updates["metadata"] = metadata
    updated = existing.model_copy(update=updates)
    result = store.update_edge(updated)
    return result.model_dump(mode="json")


@mcp.tool()
@safe_tool
def delete_edge(edge_id: str) -> str:
    """Delete an Edge from the knowledge graph.

    Args:
        edge_id: UUID string of the edge to delete.

    Returns:
        Confirmation message including the deleted edge ID.
    """
    store = _get_store()
    eid = uuid.UUID(edge_id)
    existing = store.get_edge(eid)
    if existing is None:
        raise ToolError(f"Edge '{edge_id}' not found")
    store.delete_edge(eid)
    return f"Edge '{edge_id}' deleted successfully."


@mcp.tool()
@safe_tool
def report_gap(description: str, context: Optional[str] = None) -> dict:
    """Report a knowledge gap for the librarian to investigate.

    Creates a placeholder Concept (with label ``auto-generated``) and a
    ``reported_gap`` WorkItem referencing it. The librarian will pick up
    the work item and investigate the gap.

    Args:
        description: Description of the missing or incomplete knowledge.
        context: Optional additional context that helps scope the investigation.

    Returns:
        The created WorkItem dict including its assigned UUID.
    """
    store = _get_store()
    full_description = description
    if context:
        full_description = f"{description}\n\nContext: {context}"

    # A gap concept is a placeholder that will be enriched by the librarian.
    gap_concept = Concept(
        name=f"[Gap] {description[:80]}",
        description=full_description,
        labels={"auto-generated", "needs-review"},
        created_by="human",
    )
    created_concept = store.create_concept(gap_concept)

    work_item = WorkItem(
        item_type="reported_gap",
        concept_id=created_concept.id,
        description=full_description,
    )
    result = store.create_work_item(work_item)
    return result.model_dump(mode="json")


# ---------------------------------------------------------------------------
# Entry point (AC1)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run(transport="stdio")
