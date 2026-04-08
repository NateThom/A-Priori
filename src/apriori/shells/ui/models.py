"""Pydantic response models for the UI read-only API."""

from __future__ import annotations

from pydantic import BaseModel

from apriori.models.concept import Concept
from apriori.models.edge import Edge
from apriori.models.work_item import WorkItem


class ConceptDetailResponse(BaseModel):
    """Full concept detail payload with connected edges."""

    concept: Concept
    edges: list[Edge]


class CytoscapeNodeData(BaseModel):
    id: str
    label: str
    type: str


class CytoscapeNode(BaseModel):
    data: CytoscapeNodeData


class CytoscapeEdgeData(BaseModel):
    id: str
    source: str
    target: str
    weight: float


class CytoscapeEdge(BaseModel):
    data: CytoscapeEdgeData


class GraphResponse(BaseModel):
    """Cytoscape-compatible graph payload."""

    nodes: list[CytoscapeNode]
    edges: list[CytoscapeEdge]


class HealthResponse(BaseModel):
    """Health dashboard payload."""

    metrics: dict[str, float]
    targets: dict[str, float]
    effective_weights: dict[str, float]
    queue_depth: int


ActivityResponse = list[WorkItem]
