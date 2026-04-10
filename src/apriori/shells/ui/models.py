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
    derived_from_code_version: Optional[str]
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
    labels: list[str]
    confidence: float
    highlighted: bool
    confidence_bucket: str
    visual_opacity: float
    visual_color: str


class CytoscapeNode(BaseModel):
    """Cytoscape node element."""

    data: CytoscapeNodeData


class CytoscapeEdgeData(BaseModel):
    """Cytoscape edge data bag: id, source, target, weight."""

    id: str
    source: str
    target: str
    weight: float
    edge_type: str
    evidence_type: str
    confidence: float
    confidence_bucket: str
    visual_opacity: float
    visual_line_style: str


class CytoscapeEdge(BaseModel):
    """Cytoscape edge element."""

    data: CytoscapeEdgeData


class GraphResponse(BaseModel):
    """Subgraph in Cytoscape-compatible format (from AP-97 spike decision)."""

    nodes: list[CytoscapeNode]
    edges: list[CytoscapeEdge]
    layout: str


class ActivityItem(BaseModel):
    """A compact summary of the processed work item."""

    id: uuid.UUID
    item_type: str
    description: str


class ActivityConcept(BaseModel):
    """A compact summary of the concept created or updated in an iteration."""

    id: uuid.UUID
    name: str


class ActivityFailureRecord(BaseModel):
    """Failure details used by expandable failed-iteration entries."""

    attempted_at: str
    model_used: str
    prompt_template: str
    failure_reason: str
    quality_scores: Optional[dict[str, float]]
    reviewer_feedback: Optional[str]


class ActivityEntry(BaseModel):
    """A single librarian iteration entry for the activity feed."""

    id: uuid.UUID
    run_id: uuid.UUID
    iteration: int
    created_at: str
    status: str
    passed: bool
    failure_reason: Optional[str]
    work_item: Optional[ActivityItem]
    concept: Optional[ActivityConcept]
    co_regulation_scores: Optional[dict[str, float]]
    failure_record: Optional[ActivityFailureRecord]
    concepts_integrated: int
    edges_integrated: int
    model_used: str
    duration_seconds: float


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
    escalated_count: int


class EscalatedAssociatedConcept(BaseModel):
    """Concept context shown alongside an escalated work item."""

    id: uuid.UUID
    name: Optional[str]
    labels: list[str]


class EscalatedFailureAttempt(BaseModel):
    """One failed attempt from a WorkItem.failure_records entry."""

    attempted_at: str
    model_used: str
    prompt_template: str
    failure_reason: str
    quality_scores: Optional[dict[str, float]]
    reviewer_feedback: Optional[str]


class EscalatedItemView(BaseModel):
    """Escalated work item payload for the dedicated escalated-items view."""

    id: uuid.UUID
    item_type: str
    description: str
    failure_count: int
    associated_concept: EscalatedAssociatedConcept
    failure_history: list[EscalatedFailureAttempt]
