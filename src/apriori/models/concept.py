"""Concept and CodeReference models (PRD §5.1, §5.2)."""

import re
import uuid
from datetime import datetime, timezone
from typing import Annotated, Literal, Optional

from pydantic import BaseModel, Field, field_validator

from apriori.models.impact import ImpactProfile


# ---------------------------------------------------------------------------
# Label vocabulary (documented, not enforced at the model layer)
# ---------------------------------------------------------------------------
INITIAL_LABELS: frozenset[str] = frozenset(
    {
        "needs-review",
        "auto-generated",
        "deprecated",
        "verified",
        "stale",
        "needs-human-review",
    }
)

_Confidence = Annotated[float, Field(ge=0.0, le=1.0)]

_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_GIT_HASH_RE = re.compile(r"^[0-9a-fA-F]{40}$")


class CodeReference(BaseModel):
    """A code location that anchors a Concept to a specific code artefact.

    Implements the repair chain: symbol → content_hash → semantic_anchor.
    The resolution order is enforced by the retrieval layer, not here.
    """

    symbol: str
    file_path: str
    line_range: Optional[tuple[int, int]] = None  # advisory only
    content_hash: str  # SHA-256 of the referenced code block, 64-char hex
    semantic_anchor: str
    derived_from_code_version: Optional[str] = None  # 40-char git commit hash

    @field_validator("content_hash")
    @classmethod
    def content_hash_must_be_sha256_hex(cls, v: str) -> str:
        if not _SHA256_RE.match(v):
            raise ValueError("content_hash must be a 64-character lowercase hex string (SHA-256)")
        return v.lower()

    @field_validator("derived_from_code_version")
    @classmethod
    def git_hash_must_be_40_hex(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not _GIT_HASH_RE.match(v):
            raise ValueError("derived_from_code_version must be a 40-character hex string (git commit hash)")
        return v.lower() if v is not None else None


class Concept(BaseModel):
    """The fundamental unit of knowledge in the A-Priori knowledge graph."""

    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    name: str
    description: str
    labels: set[str] = Field(default_factory=set)
    code_references: list[CodeReference] = Field(default_factory=list)
    created_by: Literal["agent", "human"]
    verified_by: Optional[str] = None
    last_verified: Optional[datetime] = None
    confidence: _Confidence = 0.5
    derived_from_code_version: Optional[str] = None  # 40-char git commit hash
    metadata: Optional[dict] = None
    impact_profile: Optional[ImpactProfile] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("derived_from_code_version")
    @classmethod
    def git_hash_must_be_40_hex(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not _GIT_HASH_RE.match(v):
            raise ValueError("derived_from_code_version must be a 40-character hex string (git commit hash)")
        return v.lower() if v is not None else None
