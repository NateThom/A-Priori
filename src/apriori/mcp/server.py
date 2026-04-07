"""MCP server for A-Priori (AP-68 scaffold; AP-70 read tools; ERD §3.4).

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
import uuid as _uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator, Callable, Optional

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

from apriori.config import load_config
from apriori.embedding.protocol import EmbeddingServiceProtocol
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
    by the server (default paths) and by tests (injected tmp_path).

    Args:
        db_path: Override for the SQLite database path.
        yaml_path: Override for the YAML backup directory path.

    Returns:
        An async context manager that yields ``{"store": DualWriter}`` and
        cleans up on exit.
    """

    @asynccontextmanager
    async def lifespan(server: FastMCP) -> AsyncIterator[dict[str, Any]]:
        global _store, _embedding_service

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

        try:
            yield {"store": store}
        finally:
            _store = None
            _embedding_service = None
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
def traverse(concept_id: str, max_hops: int = 3) -> list:
    """Breadth-first traversal of the knowledge graph from a starting concept.

    Follows outgoing edges and returns all reachable concepts up to ``max_hops``
    edges from the starting concept (inclusive).

    Args:
        concept_id: UUID string of the starting concept.
        max_hops: Maximum number of edge hops to follow (default 3).

    Returns:
        List of concept dicts reachable within ``max_hops`` edges, in BFS order.
    """
    store = _get_store()
    concepts = store.traverse_graph(
        start_id=_uuid.UUID(concept_id),
        max_depth=max_hops,
    )
    return [c.model_dump(mode="json") for c in concepts]


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
    cid = _uuid.UUID(concept_id)
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
def blast_radius(concept_id: str) -> str:
    """Analyse the blast radius of changes to a concept (Phase 3 placeholder).

    This tool is not yet implemented. It will be available in Phase 3 once the
    impact analysis pipeline is complete.

    Args:
        concept_id: UUID string of the concept to analyse.

    Returns:
        Placeholder message indicating the feature is not yet available.
    """
    return "Blast radius analysis is not yet available. This feature is planned for Phase 3."


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
            concept_id=_uuid.UUID(concept_id),
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
    edge = store.get_edge(_uuid.UUID(edge_id))
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
            source_id=_uuid.UUID(source_id) if source_id else None,
            target_id=_uuid.UUID(target_id) if target_id else None,
            edge_type=edge_type,
        )
    ]


# ---------------------------------------------------------------------------
# Write tools — Story 4.3 (stubs)
# ---------------------------------------------------------------------------


@mcp.tool()
@safe_tool
def create_concept(
    name: str,
    description: str,
    labels: Optional[list[str]] = None,
) -> dict:
    """Create a new Concept in the knowledge graph.

    Args:
        name: Human-readable concept name (must be unique).
        description: Full description of the concept.
        labels: Optional list of label strings for filtering.

    Returns:
        The created concept dict including its assigned UUID.
    """
    raise NotImplementedError("Implemented in Story 4.3")


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
    raise NotImplementedError("Implemented in Story 4.3")


@mcp.tool()
@safe_tool
def delete_concept(concept_id: str) -> str:
    """Delete a Concept and all its dependent Edges from the knowledge graph.

    Args:
        concept_id: UUID string of the concept to delete.

    Returns:
        Confirmation message including the deleted concept ID.
    """
    raise NotImplementedError("Implemented in Story 4.3")


@mcp.tool()
@safe_tool
def create_edge(
    source_id: str,
    target_id: str,
    edge_type: str,
    rationale: Optional[str] = None,
) -> dict:
    """Create a directed Edge between two Concepts in the knowledge graph.

    Args:
        source_id: UUID string of the source concept.
        target_id: UUID string of the target concept.
        edge_type: Edge type string from the configured vocabulary.
        rationale: Optional explanation of why this edge exists.

    Returns:
        The created edge dict including its assigned UUID.
    """
    raise NotImplementedError("Implemented in Story 4.3")


@mcp.tool()
@safe_tool
def delete_edge(edge_id: str) -> str:
    """Delete an Edge from the knowledge graph.

    Args:
        edge_id: UUID string of the edge to delete.

    Returns:
        Confirmation message including the deleted edge ID.
    """
    raise NotImplementedError("Implemented in Story 4.3")


# ---------------------------------------------------------------------------
# Entry point (AC1)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run(transport="stdio")
