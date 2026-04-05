"""Edge model and edge type vocabulary (PRD §5.3, §5.4)."""

import re
import uuid
from datetime import datetime, timezone
from typing import Annotated, Literal, Optional

from pydantic import BaseModel, Field, field_validator


_Confidence = Annotated[float, Field(ge=0.0, le=1.0)]
_GIT_HASH_RE = re.compile(r"^[0-9a-fA-F]{40}$")


# ---------------------------------------------------------------------------
# Edge type vocabulary — PRD §5.4
# ---------------------------------------------------------------------------
EDGE_TYPE_VOCABULARY: frozenset[str] = frozenset(
    {
        # Structural: derived deterministically from AST analysis (Layer 0)
        "calls",
        "imports",
        "inherits",
        "type-references",
        # Semantic: derived by librarian agents via LLM analysis (Layer 1)
        "depends-on",
        "implements",
        "relates-to",
        "shares-assumption-about",
        "extends",
        "supersedes",
        "owned-by",
        # Historical: derived from git history analysis (Layer 2)
        "co-changes-with",
    }
)


class EdgeTypeVocabulary:
    """Holds a set of valid edge types and validates edge_type strings against it."""

    def __init__(self, types: frozenset[str]) -> None:
        self.types = types

    def validate(self, edge_type: str) -> None:
        """Raise ValueError if edge_type is not in this vocabulary.

        The error message lists all valid types so the caller can correct the input.
        """
        if edge_type not in self.types:
            sorted_types = ", ".join(sorted(self.types))
            raise ValueError(
                f"Invalid edge type '{edge_type}'. Valid types are: {sorted_types}"
            )


def load_edge_vocabulary(config) -> EdgeTypeVocabulary:
    """Load the edge type vocabulary from a Config object.

    Args:
        config: A Config instance (apriori.config.Config).

    Returns:
        EdgeTypeVocabulary containing all types from config.edge_types.
    """
    return EdgeTypeVocabulary(frozenset(config.edge_types))


class Edge(BaseModel):
    """A typed, directed relationship between two Concept nodes (PRD §5.3).

    The UNIQUE(source_id, target_id, edge_type) constraint is enforced at the
    storage layer, not here. Edge type vocabulary validation is performed by
    EdgeTypeVocabulary.validate(), not at model instantiation.
    """

    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    source_id: uuid.UUID
    target_id: uuid.UUID
    edge_type: str
    evidence_type: Literal["structural", "semantic", "historical"]
    confidence: _Confidence = 1.0
    metadata: Optional[dict] = None
    derived_from_code_version: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("derived_from_code_version")
    @classmethod
    def git_hash_must_be_40_hex(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not _GIT_HASH_RE.match(v):
            raise ValueError(
                "derived_from_code_version must be a 40-character hex string (git commit hash)"
            )
        return v.lower() if v is not None else None
