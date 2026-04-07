"""MCP server for A-Priori (Story 4.1 scaffold; Stories 4.2/4.3 write tools; ERD §3.4).

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
from apriori.models.concept import Concept
from apriori.models.edge import Edge, EdgeTypeVocabulary, load_edge_vocabulary
from apriori.models.work_item import WorkItem
from apriori.storage.dual_writer import DualWriter
from apriori.storage.protocol import KnowledgeStore
from apriori.storage.sqlite_store import SQLiteStore
from apriori.storage.yaml_store import YamlStore

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level store state — set by lifespan, injectable for tests
# ---------------------------------------------------------------------------

_store: Optional[KnowledgeStore] = None
_edge_vocabulary: Optional[EdgeTypeVocabulary] = None


def _get_store() -> KnowledgeStore:
    """Return the active KnowledgeStore, or raise RuntimeError if not set."""
    if _store is None:
        raise RuntimeError("Store not initialized — is the MCP server running?")
    return _store


def _get_edge_vocabulary() -> EdgeTypeVocabulary:
    """Return the active EdgeTypeVocabulary, or raise RuntimeError if not set."""
    if _edge_vocabulary is None:
        raise RuntimeError("Edge vocabulary not initialized — is the MCP server running?")
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
    module-level ``_store`` and ``_edge_vocabulary`` on entry and clears them
    on exit.

    Args:
        db_path: Override for the SQLite database path.
        yaml_path: Override for the YAML backup directory path.

    Returns:
        An async context manager that yields ``{"store": DualWriter}`` and
        cleans up on exit.
    """

    @asynccontextmanager
    async def lifespan(server: FastMCP) -> AsyncIterator[dict[str, Any]]:
        global _store, _edge_vocabulary

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
        _edge_vocabulary = load_edge_vocabulary(config)

        try:
            yield {"store": store}
        finally:
            _store = None
            _edge_vocabulary = None
            logger.info("MCP server shutting down — KnowledgeStore released")

    return lifespan


# ---------------------------------------------------------------------------
# FastMCP application
# ---------------------------------------------------------------------------

mcp = FastMCP("apriori", lifespan=build_lifespan())

# ---------------------------------------------------------------------------
# Concept tools (Stories 4.2 / 4.3)
# ---------------------------------------------------------------------------


@mcp.tool()
@safe_tool
def get_concept(concept_id: str) -> dict:
    """Retrieve a Concept from the knowledge graph by its UUID.

    Args:
        concept_id: UUID string of the concept to retrieve.

    Returns:
        Concept data as a dict, or an error if not found.
    """
    raise NotImplementedError("Implemented in Story 4.2")


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
    raise NotImplementedError("Implemented in Story 4.2")


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
    raise NotImplementedError("Implemented in Story 4.2")


@mcp.tool()
@safe_tool
def search_keyword(query: str, limit: int = 10) -> list:
    """Find Concepts whose name or description contains the query string.

    Args:
        query: Substring to search for (case-insensitive).
        limit: Maximum number of results to return (default 10).

    Returns:
        List of matching concept dicts.
    """
    raise NotImplementedError("Implemented in Story 4.2")


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
    raise NotImplementedError("Implemented in Story 4.2")


@mcp.tool()
@safe_tool
def get_metrics() -> dict:
    """Return aggregate statistics about the knowledge graph.

    Returns:
        Dict with keys: concept_count, edge_count, work_item_count,
        review_outcome_count, and any additional implementation metrics.
    """
    raise NotImplementedError("Implemented in Story 4.2")


@mcp.tool()
@safe_tool
def get_edge(edge_id: str) -> dict:
    """Retrieve an Edge from the knowledge graph by its UUID.

    Args:
        edge_id: UUID string of the edge to retrieve.

    Returns:
        Edge data as a dict, or an error if not found.
    """
    raise NotImplementedError("Implemented in Story 4.2")


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
    raise NotImplementedError("Implemented in Story 4.2")


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
