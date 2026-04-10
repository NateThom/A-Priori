"""FastAPI server for the A-Priori read-only Graph API (Story 11.2a).

Thin shell: all logic delegated to core apriori modules (arch:core-lib-thin-shells).
Sync KnowledgeStore calls wrapped with asyncio.to_thread() per Technical Notes S-1.

Routes:
    GET /api/concepts             — list concepts with optional label filter
    GET /api/concepts/{id}        — full concept with edges and impact profile
    GET /api/graph                — subgraph in Cytoscape format
    GET /api/activity             — recent librarian iterations (work items)
    GET /api/health               — quality metrics, targets, weights, queue depth

Static frontend assets are served from a ``static/`` directory adjacent to this
file when that directory exists. In development the React app is served by Vite
directly; in production the built assets are placed in ``static/``.
"""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from typing import Literal, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse

from apriori.config import Config
from apriori.quality.metrics import MetricsEngine
from apriori.quality.modulation import AdaptiveModulator
from apriori.shells.ui.models import (
    ActivityItem,
    ConceptDetail,
    ConceptSummary,
    CytoscapeEdge,
    CytoscapeEdgeData,
    CytoscapeNode,
    CytoscapeNodeData,
    EdgeSummary,
    GraphResponse,
    HealthMetrics,
    HealthResponse,
    HealthTargets,
)
from apriori.storage.protocol import KnowledgeStore


def create_app(store: KnowledgeStore, config: Config) -> FastAPI:
    """Construct and return the FastAPI application.

    This factory keeps the module free of global state, making it easy to
    inject a test store in unit tests.

    Args:
        store: The KnowledgeStore to delegate all data access to.
        config: The loaded Config providing metric targets and weights.

    Returns:
        A configured FastAPI application instance.
    """
    app = FastAPI(
        title="A-Priori Graph API",
        description="Read-only REST API serving knowledge graph data for the frontend.",
        version="0.1.0",
    )

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------

    def _to_concept_summary(concept) -> ConceptSummary:
        return ConceptSummary(
            id=concept.id,
            name=concept.name,
            description=concept.description,
            labels=sorted(concept.labels),
            confidence=concept.confidence,
            created_by=concept.created_by,
            created_at=concept.created_at.isoformat(),
            updated_at=concept.updated_at.isoformat(),
        )

    def _to_edge_summary(edge) -> EdgeSummary:
        return EdgeSummary(
            id=edge.id,
            source_id=edge.source_id,
            target_id=edge.target_id,
            edge_type=edge.edge_type,
            evidence_type=edge.evidence_type,
            confidence=edge.confidence,
        )

    def _to_concept_detail(concept, edges) -> ConceptDetail:
        return ConceptDetail(
            id=concept.id,
            name=concept.name,
            description=concept.description,
            labels=sorted(concept.labels),
            confidence=concept.confidence,
            code_references=[
                {
                    "symbol": ref.symbol,
                    "file_path": ref.file_path,
                    "line_range": ref.line_range,
                    "content_hash": ref.content_hash,
                    "semantic_anchor": ref.semantic_anchor,
                    "derived_from_code_version": ref.derived_from_code_version,
                    "is_unresolved": ref.is_unresolved,
                }
                for ref in concept.code_references
            ],
            created_by=concept.created_by,
            verified_by=concept.verified_by,
            last_verified=(
                concept.last_verified.isoformat() if concept.last_verified else None
            ),
            derived_from_code_version=concept.derived_from_code_version,
            impact_profile=(
                concept.impact_profile.model_dump() if concept.impact_profile else None
            ),
            created_at=concept.created_at.isoformat(),
            updated_at=concept.updated_at.isoformat(),
            edges=[_to_edge_summary(e) for e in edges],
        )

    def _confidence_bucket(confidence: float) -> str:
        if confidence >= 0.8:
            return "high"
        if confidence >= 0.5:
            return "medium"
        return "low"

    def _node_visuals(bucket: str) -> tuple[float, str]:
        if bucket == "high":
            return 0.95, "#0f766e"
        if bucket == "medium":
            return 0.72, "#b45309"
        return 0.48, "#b91c1c"

    def _edge_visuals(bucket: str) -> tuple[float, str]:
        if bucket == "high":
            return 0.9, "solid"
        if bucket == "medium":
            return 0.65, "solid"
        return 0.42, "dashed"

    def _to_activity_item(wi) -> ActivityItem:
        return ActivityItem(
            id=wi.id,
            item_type=wi.item_type,
            concept_id=wi.concept_id,
            description=wi.description,
            file_path=wi.file_path,
            created_at=wi.created_at.isoformat(),
            resolved_at=(wi.resolved_at.isoformat() if wi.resolved_at else None),
            failure_count=wi.failure_count,
            escalated=wi.escalated,
            resolved=wi.resolved,
        )

    # -------------------------------------------------------------------------
    # Endpoints
    # -------------------------------------------------------------------------

    @app.get(
        "/api/concepts",
        response_model=list[ConceptSummary],
        summary="List concepts with optional label filter",
    )
    async def list_concepts(
        label: list[str] = Query(default=[]),
    ) -> list[ConceptSummary]:
        """Return all concepts, optionally filtered by label.

        Multiple ``label`` params are combined with OR semantics: a concept is
        included if it has any of the specified labels.
        """
        filter_set: Optional[set[str]] = set(label) if label else None
        concepts = await asyncio.to_thread(store.list_concepts, filter_set)
        return [_to_concept_summary(c) for c in concepts]

    @app.get(
        "/api/concepts/{concept_id}",
        response_model=ConceptDetail,
        summary="Get full concept with edges and impact profile",
    )
    async def get_concept(concept_id: uuid.UUID) -> ConceptDetail:
        """Return a single concept by ID with its outgoing edges and impact profile."""
        concept = await asyncio.to_thread(store.get_concept, concept_id)
        if concept is None:
            raise HTTPException(status_code=404, detail="Concept not found")
        edges = await asyncio.to_thread(store.list_edges, concept_id)
        return _to_concept_detail(concept, edges)

    @app.get(
        "/api/graph",
        response_model=GraphResponse,
        summary="Subgraph in Cytoscape format",
    )
    async def get_graph(
        center: uuid.UUID,
        radius: int = Query(default=2, ge=1, le=5),
        edge_type: Optional[str] = Query(default=None),
        min_confidence: float = Query(default=0.0, ge=0.0, le=1.0),
        highlight_label: Optional[str] = Query(default=None),
        layout: Literal["force-directed", "breadthfirst"] = Query(
            default="force-directed"
        ),
        max_nodes: int = Query(default=500, ge=1, le=500),
    ) -> GraphResponse:
        """Return a subgraph rooted at ``center`` within ``radius`` hops.

        Response is in Cytoscape.js-compatible format per the AP-97 spike
        decision: ``{nodes: [{data: {id, label, type}}], edges: [{data: {id,
        source, target, weight}}]}``.
        """
        traversed = await asyncio.to_thread(store.traverse_graph, center, radius)
        concepts = [
            concept for concept in traversed if concept.confidence >= min_confidence
        ][:max_nodes]
        concept_ids = {c.id for c in concepts}

        # Collect all edges whose both endpoints are in the subgraph
        all_edges = []
        seen_edge_ids: set[uuid.UUID] = set()
        for concept in concepts:
            edges = await asyncio.to_thread(store.list_edges, concept.id)
            for edge in edges:
                edge_matches_type = (
                    edge_type is None
                    or edge.edge_type == edge_type
                    or edge.evidence_type == edge_type
                )
                if (
                    edge.target_id in concept_ids
                    and edge.confidence >= min_confidence
                    and edge_matches_type
                    and edge.id not in seen_edge_ids
                ):
                    all_edges.append(edge)
                    seen_edge_ids.add(edge.id)

        nodes = [
            CytoscapeNode(
                data=CytoscapeNodeData(
                    id=str(c.id),
                    label=c.name,
                    type=next(iter(c.labels), "concept") if c.labels else "concept",
                    labels=sorted(c.labels),
                    confidence=c.confidence,
                    highlighted=bool(highlight_label and highlight_label in c.labels),
                    confidence_bucket=_confidence_bucket(c.confidence),
                    visual_opacity=_node_visuals(_confidence_bucket(c.confidence))[0],
                    visual_color=_node_visuals(_confidence_bucket(c.confidence))[1],
                )
            )
            for c in concepts
        ]
        edges_cy = [
            CytoscapeEdge(
                data=CytoscapeEdgeData(
                    id=str(e.id),
                    source=str(e.source_id),
                    target=str(e.target_id),
                    weight=e.confidence,
                    edge_type=e.edge_type,
                    evidence_type=e.evidence_type,
                    confidence=e.confidence,
                    confidence_bucket=_confidence_bucket(e.confidence),
                    visual_opacity=_edge_visuals(_confidence_bucket(e.confidence))[0],
                    visual_line_style=_edge_visuals(_confidence_bucket(e.confidence))[1],
                )
            )
            for e in all_edges
        ]
        return GraphResponse(nodes=nodes, edges=edges_cy, layout=layout)

    @app.get(
        "/api/activity",
        response_model=list[ActivityItem],
        summary="Recent librarian iterations",
    )
    async def get_activity(
        limit: int = Query(default=20, ge=1, le=100),
    ) -> list[ActivityItem]:
        """Return the most recent librarian work items, newest first."""
        items = await asyncio.to_thread(store.list_work_items, limit)
        return [_to_activity_item(wi) for wi in items]

    @app.get(
        "/api/health",
        response_model=HealthResponse,
        summary="Quality metrics, targets, effective weights, queue depth",
    )
    async def get_health() -> HealthResponse:
        """Return current metric values, configured targets, effective priority weights,
        and pending work queue depth.
        """
        metrics_engine = MetricsEngine(store, cache_ttl=30.0)
        total_source_files = getattr(config, "project_file_count", 0)
        coverage = await asyncio.to_thread(
            metrics_engine.get_coverage, total_source_files
        )
        freshness = await asyncio.to_thread(metrics_engine.get_freshness)
        blast_radius = await asyncio.to_thread(
            metrics_engine.get_blast_radius_completeness
        )

        modulator = AdaptiveModulator(
            base_weights=dict(config.base_priority_weights),
        )
        effective_weights, _ = modulator.compute_effective_weights(
            coverage=coverage,
            freshness=freshness,
            blast_radius_completeness=blast_radius,
        )

        stats = await asyncio.to_thread(store.get_work_item_stats)

        return HealthResponse(
            metrics=HealthMetrics(
                coverage=coverage,
                freshness=freshness,
                blast_radius_completeness=blast_radius,
            ),
            targets=HealthTargets(
                coverage_target=0.80,
                freshness_target=0.90,
                blast_radius_target=0.80,
            ),
            effective_weights=effective_weights,
            work_queue_depth=stats["pending"],
        )

    # -------------------------------------------------------------------------
    # Static file serving (production: built React app)
    # -------------------------------------------------------------------------
    _static_dir = Path(__file__).parent / "static"
    if _static_dir.is_dir():
        from fastapi.staticfiles import StaticFiles
        app.mount("/", StaticFiles(directory=str(_static_dir), html=True), name="static")

    return app
