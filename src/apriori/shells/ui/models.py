"""Response models for the A-Priori read-only Graph API (Story 11.2a)."""

from __future__ import annotations

import uuid
from typing import Any, Optional

from pydantic import BaseModel


class ConceptSummary(BaseModel):
    """Minimal concept representation for the list endpoint."""

    id: uuid.UUID
    name: str
    description: str
    labels: list[str]
    confidence: float
    created_by: str
    created_at: str
    updated_at: str


class EdgeSummary(BaseModel):
    """Edge representation for the concept detail and graph endpoints."""

    id: uuid.UUID
    source_id: uuid.UUID
    target_id: uuid.UUID
    edge_type: str
    evidence_type: str
    confidence: float


class CodeReferenceView(BaseModel):
    """Code reference plus optional inline snippet for review workflows."""

    symbol: str
    file_path: str
    line_range: Optional[tuple[int, int]]
    semantic_anchor: str
    is_unresolved: bool
    snippet: Optional[str]


class ConceptDetail(BaseModel):
    """Full concept with edges and impact profile for the detail endpoint."""

    id: uuid.UUID
    name: str
    description: str
    labels: list[str]
    confidence: float
    created_by: str
    verified_by: Optional[str]
    last_verified: Optional[str]
    impact_profile: Optional[Any]
    created_at: str
    updated_at: str
    edges: list[EdgeSummary]
    code_references: list[CodeReferenceView]


class CytoscapeNodeData(BaseModel):
    """Cytoscape node data bag: id, label, type."""

    id: str
    label: str
    type: str


class CytoscapeNode(BaseModel):
    """Cytoscape node element."""

    data: CytoscapeNodeData


class CytoscapeEdgeData(BaseModel):
    """Cytoscape edge data bag: id, source, target, weight."""

    id: str
    source: str
    target: str
    weight: float


class CytoscapeEdge(BaseModel):
    """Cytoscape edge element."""

    data: CytoscapeEdgeData


class GraphResponse(BaseModel):
    """Subgraph in Cytoscape-compatible format (from AP-97 spike decision)."""

    nodes: list[CytoscapeNode]
    edges: list[CytoscapeEdge]


class ActivityItem(BaseModel):
    """A single work item representing one librarian iteration."""

    id: uuid.UUID
    item_type: str
    concept_id: uuid.UUID
    description: str
    file_path: Optional[str]
    created_at: str
    resolved_at: Optional[str]
    failure_count: int
    escalated: bool
    resolved: bool


class HealthMetrics(BaseModel):
    """Current values for the three quality metrics."""

    coverage: float
    freshness: float
    blast_radius_completeness: float


class HealthTargets(BaseModel):
    """Configured target thresholds for the three quality metrics."""

    coverage_target: float
    freshness_target: float
    blast_radius_target: float


class HealthResponse(BaseModel):
    """Dashboard payload: metrics, targets, effective weights, queue depth."""

    metrics: HealthMetrics
    targets: HealthTargets
    effective_weights: dict[str, float]
    work_queue_depth: int
