"""ImpactProfile and ImpactEntry models (PRD §5.5)."""

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, Field


_Confidence = Annotated[float, Field(ge=0.0, le=1.0)]


class ImpactEntry(BaseModel):
    """A single entry in an impact profile describing one affected concept."""

    target_concept_id: uuid.UUID
    confidence: _Confidence
    relationship_path: list[str]  # ordered list of edge UUIDs
    depth: int
    rationale: str


class ImpactProfile(BaseModel):
    """Pre-computed blast-radius profile embedded in every Concept node."""

    structural_impact: list[ImpactEntry] = Field(default_factory=list)
    semantic_impact: list[ImpactEntry] = Field(default_factory=list)
    historical_impact: list[ImpactEntry] = Field(default_factory=list)
    structural_only: bool = False
    last_computed: datetime
