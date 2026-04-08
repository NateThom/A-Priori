"""FastAPI thin shell exposing read-only graph endpoints."""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles

from apriori.config import DEFAULT_BASE_PRIORITIES
from apriori.models.edge import Edge
from apriori.quality.metrics import MetricsEngine
from apriori.quality.modulation import AdaptiveModulator
from apriori.shells.ui.models import (
    ConceptDetailResponse,
    GraphResponse,
    HealthResponse,
)
from apriori.storage.protocol import KnowledgeStore


def _build_graph(store: KnowledgeStore, center: uuid.UUID, radius: int) -> GraphResponse:
    visited: set[uuid.UUID] = {center}
    frontier: set[uuid.UUID] = {center}
    edges_by_id: dict[uuid.UUID, Edge] = {}

    for _ in range(max(0, radius)):
        next_frontier: set[uuid.UUID] = set()
        for node_id in frontier:
            for edge in store.list_edges(source_id=node_id):
                edges_by_id[edge.id] = edge
                if edge.target_id not in visited:
                    visited.add(edge.target_id)
                    next_frontier.add(edge.target_id)
        frontier = next_frontier
        if not frontier:
            break

    concepts = [store.get_concept(concept_id) for concept_id in visited]
    nodes = [
        {
            "data": {
                "id": str(concept.id),
                "label": concept.name,
                "type": "concept",
            }
        }
        for concept in concepts
        if concept is not None
    ]
    edges = [
        {
            "data": {
                "id": str(edge.id),
                "source": str(edge.source_id),
                "target": str(edge.target_id),
                "weight": edge.confidence,
            }
        }
        for edge in edges_by_id.values()
    ]
    return GraphResponse(nodes=nodes, edges=edges)


def create_app(store: KnowledgeStore, total_source_files: int = 0) -> FastAPI:
    """Create the UI API app backed by a KnowledgeStore implementation."""
    app = FastAPI(title="A-Priori UI API", version="0.1.0")

    @app.get("/api/concepts")
    async def list_concepts(label: list[str] = Query(default_factory=list)):
        labels = set(label) if label else None
        concepts = await asyncio.to_thread(store.list_concepts, labels)
        return concepts

    @app.get("/api/concepts/{concept_id}", response_model=ConceptDetailResponse)
    async def get_concept(concept_id: uuid.UUID):
        concept = await asyncio.to_thread(store.get_concept, concept_id)
        if concept is None:
            raise HTTPException(status_code=404, detail="Concept not found")
        edges = await asyncio.to_thread(store.list_edges, source_id=concept_id)
        return ConceptDetailResponse(concept=concept, edges=edges)

    @app.get("/api/graph", response_model=GraphResponse)
    async def graph(center: uuid.UUID, radius: int = 2):
        center_concept = await asyncio.to_thread(store.get_concept, center)
        if center_concept is None:
            raise HTTPException(status_code=404, detail="Center concept not found")
        return await asyncio.to_thread(_build_graph, store, center, radius)

    @app.get("/api/activity")
    async def activity(limit: int = 20):
        return await asyncio.to_thread(store.list_work_items, limit)

    @app.get("/api/health", response_model=HealthResponse)
    async def health():
        metrics_engine = MetricsEngine(store)
        coverage = await asyncio.to_thread(metrics_engine.get_coverage, total_source_files)
        freshness = await asyncio.to_thread(metrics_engine.get_freshness)
        blast_radius = await asyncio.to_thread(metrics_engine.get_blast_radius_completeness)
        modulator = AdaptiveModulator(base_weights=DEFAULT_BASE_PRIORITIES.copy())
        effective_weights, telemetry = modulator.compute_effective_weights(
            coverage=coverage,
            freshness=freshness,
            blast_radius_completeness=blast_radius,
        )
        queue_depth = len(await asyncio.to_thread(store.get_pending_work_items))
        return HealthResponse(
            metrics={
                "coverage": coverage,
                "freshness": freshness,
                "blast_radius_completeness": blast_radius,
            },
            targets={
                "coverage": telemetry.coverage_target,
                "freshness": telemetry.freshness_target,
                "blast_radius_completeness": telemetry.blast_radius_target,
            },
            effective_weights=effective_weights,
            queue_depth=queue_depth,
        )

    static_dir = Path(__file__).with_name("static")
    if static_dir.exists():
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")

    return app
