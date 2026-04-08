"""LibrarianOutput — raw output schema for one librarian analysis iteration (Layer 1).

This module defines the data structure that the librarian agent produces after
analysing a code file or concept. The quality pipeline (quality/) validates this
raw output before any knowledge is allowed into the graph (arch:quality-invariant).

Intentionally, this model does NOT enforce:
- confidence range [0.0, 1.0]    → Level 1 check: ``confidence_in_range``
- edge type vocabulary membership → Level 1 check: ``edge_type_valid``
- referential integrity of edges  → Level 1 check: ``referential_integrity``
- description specificity         → Level 1 checks: ``description_non_empty``,
                                    ``description_non_generic``

These are all semantic quality checks that belong in the quality pipeline, not
in the data model. The model only enforces structural parsability.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


class CodeReferenceProposal(BaseModel):
    """A code location proposed by the librarian to anchor a concept.

    Unlike the storage-layer CodeReference, this type does not require a
    SHA-256 content hash or git commit hash — those are stamped by the
    integration layer after quality validation.
    """

    symbol: str
    file_path: str
    line_range: Optional[tuple[int, int]] = None
    semantic_anchor: str


class ConceptProposal(BaseModel):
    """A concept proposed by the librarian for integration into the knowledge graph.

    Confidence range [0.0, 1.0] is validated by the Level 1 quality pipeline,
    not here, so that the fixture infrastructure can represent out-of-range values
    for testing.
    """

    name: str
    description: str
    confidence: float
    code_references: list[CodeReferenceProposal] = Field(default_factory=list)


class EdgeProposal(BaseModel):
    """A relationship proposed by the librarian between two concepts.

    Uses concept names rather than UUIDs because the librarian does not know
    storage IDs. Referential integrity (source_name / target_name must both
    appear in the sibling concepts list) is validated by the Level 1 quality
    pipeline, not here.
    """

    source_name: str
    target_name: str
    edge_type: str
    confidence: float
    evidence_type: Literal["structural", "semantic", "historical"] = "semantic"


class LibrarianOutput(BaseModel):
    """Complete output of one librarian analysis iteration.

    The quality pipeline (quality/) receives this object and validates it before
    passing approved concepts and edges to the IntegrationDecisionTree (knowledge/).
    This model represents the boundary between Layer 1 (semantic/) and the quality
    gate — its raw form may contain policy violations that the gate must catch.
    """

    concepts: list[ConceptProposal]
    edges: list[EdgeProposal] = Field(default_factory=list)
