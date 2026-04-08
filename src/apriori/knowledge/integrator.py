"""Integration decision tree for merging librarian output into the knowledge graph.

Implements ERD §4.5 integration logic for four concept scenarios and edge updates.

Layer 2 (knowledge/) — may import from models/, storage/, adapters/, config.py.
No imports from structural/, semantic/, retrieval/ (arch:layer-flow).
"""

from __future__ import annotations

import re
import subprocess
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Callable, Optional

from pydantic import BaseModel

from apriori.models.concept import Concept
from apriori.models.edge import Edge
from apriori.storage.protocol import KnowledgeStore


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

class IntegrationAction(str, Enum):
    """Outcome of a single integration operation."""

    CREATED = "created"
    VERIFIED = "verified"        # agent concept — librarian agrees, no new info
    EXTENDED = "extended"        # agent concept — new sentences appended
    CONTRADICTED = "contradicted"  # agent concept — < 30% key term overlap
    SUPPLEMENTED = "supplemented"  # human concept — analysis stored as supplement
    EDGE_CREATED = "edge_created"
    EDGE_UPDATED = "edge_updated"
    EDGE_CONTRADICTED = "edge_contradicted"


class ConceptIntegrationResult(BaseModel):
    """Result of integrating a librarian concept analysis."""

    action: IntegrationAction
    concept: Concept


class EdgeIntegrationResult(BaseModel):
    """Result of integrating a librarian edge assertion."""

    action: IntegrationAction
    edge: Edge


# ---------------------------------------------------------------------------
# Git hash provider
# ---------------------------------------------------------------------------

def _get_current_git_hash() -> str:
    """Return the current git HEAD commit hash (40-char hex).

    Falls back to 40 zeros if git is unavailable or HEAD is unresolvable.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except Exception:
        return "0" * 40


# ---------------------------------------------------------------------------
# Key term extraction and overlap calculation
# ---------------------------------------------------------------------------

_STOP_WORDS: frozenset[str] = frozenset(
    {
        "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
        "of", "with", "by", "from", "is", "are", "was", "were", "be", "been",
        "being", "have", "has", "had", "do", "does", "did", "will", "would",
        "could", "should", "may", "might", "shall", "can", "not", "also",
        "it", "its", "this", "that", "these", "those", "as", "if", "then",
        "when", "where", "which", "who", "what", "how",
    }
)


def _key_terms(text: str) -> set[str]:
    """Extract key terms from text: lowercase tokens, min 3 chars, no stop words."""
    tokens = re.findall(r"[a-zA-Z]+", text.lower())
    return {t for t in tokens if len(t) >= 3 and t not in _STOP_WORDS}


def _jaccard_overlap(a: str, b: str) -> float:
    """Jaccard similarity of key term sets from two description strings."""
    terms_a = _key_terms(a)
    terms_b = _key_terms(b)
    if not terms_a and not terms_b:
        return 1.0
    union = terms_a | terms_b
    if not union:
        return 1.0
    intersection = terms_a & terms_b
    return len(intersection) / len(union)


def _new_sentences(existing: str, new_description: str) -> list[str]:
    """Return sentences in new_description that are not near-duplicates of any sentence in existing.

    A sentence is considered redundant if it has ≥ 50% Jaccard overlap with any
    individual sentence already in the existing description.
    """
    existing_sentences = [
        s.strip()
        for s in re.split(r"(?<=[.!?])\s+", existing.strip())
        if s.strip()
    ]
    novel: list[str] = []
    for sentence in re.split(r"(?<=[.!?])\s+", new_description.strip()):
        sentence = sentence.strip()
        if not sentence or not _key_terms(sentence):
            continue
        is_redundant = any(
            _jaccard_overlap(sentence, ex_sent) >= 0.5
            for ex_sent in existing_sentences
        )
        if not is_redundant:
            novel.append(sentence)
    return novel


# ---------------------------------------------------------------------------
# Integration decision tree
# ---------------------------------------------------------------------------

class IntegrationDecisionTree:
    """Integrates librarian output into the knowledge graph (ERD §4.5).

    Handles four concept scenarios:
    1. New concept — create with created_by="agent"
    2. Agent concept, agree — update last_verified and boost confidence
    3. Agent concept, contradict — flag needs-review, log contradiction
    4. Agent concept, extend — append new sentences
    5. Human concept — store analysis as supplementary context only

    And two edge scenarios:
    6. Same (source, target, type) — update confidence to the higher value
    7. Contradicting (same source/target, different type) — flag both needs-review

    All writes stamp derived_from_code_version with the current git HEAD hash.
    """

    # Minimum Jaccard overlap below which a description is flagged as a contradiction
    _CONTRADICTION_THRESHOLD = 0.30

    def __init__(
        self,
        store: KnowledgeStore,
        git_hash_provider: Optional[Callable[[], str]] = None,
    ) -> None:
        self._store = store
        self._git_hash = git_hash_provider or _get_current_git_hash

    # -------------------------------------------------------------------------
    # Concept integration
    # -------------------------------------------------------------------------

    def integrate_concept(
        self,
        name: str,
        description: str,
        code_reference=None,
    ) -> ConceptIntegrationResult:
        """Integrate a librarian concept analysis into the knowledge graph.

        Args:
            name: Concept name as produced by the librarian.
            description: Librarian's description for the concept.
            code_reference: Optional CodeReference to attach (not required for MVP).

        Returns:
            ConceptIntegrationResult with the action taken and resulting concept.
        """
        git_hash = self._git_hash()

        # Look up by exact name
        existing = self._find_concept_by_name(name)

        if existing is None:
            return self._create_new_concept(name, description, git_hash, code_reference)

        if existing.created_by == "human":
            return self._supplement_human_concept(existing, description)

        # Agent-created concept — decide action based on overlap
        return self._integrate_agent_concept(existing, description, git_hash)

    def _find_concept_by_name(self, name: str) -> Optional[Concept]:
        concepts = self._store.list_concepts()
        for concept in concepts:
            if concept.name == name:
                return concept
        return None

    def _create_new_concept(
        self,
        name: str,
        description: str,
        git_hash: str,
        code_reference=None,
    ) -> ConceptIntegrationResult:
        refs = [code_reference] if code_reference else []
        concept = Concept(
            name=name,
            description=description,
            created_by="agent",
            derived_from_code_version=git_hash,
            code_references=refs,
        )
        saved = self._store.create_concept(concept)
        return ConceptIntegrationResult(action=IntegrationAction.CREATED, concept=saved)

    def _supplement_human_concept(
        self, concept: Concept, agent_analysis: str
    ) -> ConceptIntegrationResult:
        metadata = dict(concept.metadata or {})
        analyses: list[str] = list(metadata.get("agent_analyses", []))
        analyses.append(agent_analysis)
        metadata["agent_analyses"] = analyses
        updated = concept.model_copy(
            update={
                "metadata": metadata,
                "updated_at": datetime.now(timezone.utc),
            }
        )
        saved = self._store.update_concept(updated)
        return ConceptIntegrationResult(action=IntegrationAction.SUPPLEMENTED, concept=saved)

    def _integrate_agent_concept(
        self, concept: Concept, new_description: str, git_hash: str
    ) -> ConceptIntegrationResult:
        overlap = _jaccard_overlap(concept.description, new_description)

        if overlap < self._CONTRADICTION_THRESHOLD:
            return self._handle_contradiction(concept, new_description, git_hash)

        novel_sentences = _new_sentences(concept.description, new_description)
        if novel_sentences:
            return self._handle_extension(concept, novel_sentences, git_hash)

        return self._handle_agreement(concept, git_hash)

    def _handle_agreement(self, concept: Concept, git_hash: str) -> ConceptIntegrationResult:
        now = datetime.now(timezone.utc)
        new_confidence = min(1.0, concept.confidence + 0.05)
        updated = concept.model_copy(
            update={
                "last_verified": now,
                "confidence": new_confidence,
                "derived_from_code_version": git_hash,
                "updated_at": now,
            }
        )
        saved = self._store.update_concept(updated)
        return ConceptIntegrationResult(action=IntegrationAction.VERIFIED, concept=saved)

    def _handle_extension(
        self, concept: Concept, novel_sentences: list[str], git_hash: str
    ) -> ConceptIntegrationResult:
        merged_description = concept.description.rstrip()
        for sentence in novel_sentences:
            if not merged_description.endswith(" "):
                merged_description += " "
            merged_description += sentence
        now = datetime.now(timezone.utc)
        updated = concept.model_copy(
            update={
                "description": merged_description,
                "derived_from_code_version": git_hash,
                "updated_at": now,
            }
        )
        saved = self._store.update_concept(updated)
        return ConceptIntegrationResult(action=IntegrationAction.EXTENDED, concept=saved)

    def _handle_contradiction(
        self, concept: Concept, contradicting_description: str, git_hash: str
    ) -> ConceptIntegrationResult:
        labels = set(concept.labels) | {"needs-review"}
        metadata = dict(concept.metadata or {})
        contradictions: list[dict] = list(metadata.get("contradictions", []))
        contradictions.append(
            {
                "description": contradicting_description,
                "detected_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        metadata["contradictions"] = contradictions
        now = datetime.now(timezone.utc)
        updated = concept.model_copy(
            update={
                "labels": labels,
                "metadata": metadata,
                "derived_from_code_version": git_hash,
                "updated_at": now,
            }
        )
        saved = self._store.update_concept(updated)
        return ConceptIntegrationResult(action=IntegrationAction.CONTRADICTED, concept=saved)

    # -------------------------------------------------------------------------
    # Edge integration
    # -------------------------------------------------------------------------

    def integrate_edge(
        self,
        source_id: uuid.UUID,
        target_id: uuid.UUID,
        edge_type: str,
        evidence_type: str,
        confidence: float,
    ) -> EdgeIntegrationResult:
        """Integrate a librarian edge assertion into the knowledge graph.

        Args:
            source_id: UUID of the source concept.
            target_id: UUID of the target concept.
            edge_type: The asserted edge type.
            evidence_type: "structural", "semantic", or "historical".
            confidence: Confidence score [0.0, 1.0].

        Returns:
            EdgeIntegrationResult with the action taken and resulting edge.
        """
        git_hash = self._git_hash()

        # Find all edges between source and target
        existing_edges = self._store.list_edges(source_id=source_id, target_id=target_id)

        # Check for same-type edge
        same_type = next((e for e in existing_edges if e.edge_type == edge_type), None)
        if same_type is not None:
            return self._update_edge_confidence(same_type, confidence, git_hash)

        # Check for contradicting edges (same pair, different type)
        if existing_edges:
            return self._handle_edge_contradiction(
                existing_edges, source_id, target_id, edge_type, evidence_type, confidence, git_hash
            )

        # No existing edge — create new
        return self._create_new_edge(source_id, target_id, edge_type, evidence_type, confidence, git_hash)

    def _update_edge_confidence(
        self, edge: Edge, new_confidence: float, git_hash: str
    ) -> EdgeIntegrationResult:
        updated_confidence = max(edge.confidence, new_confidence)
        updated = edge.model_copy(
            update={
                "confidence": updated_confidence,
                "derived_from_code_version": git_hash,
                "updated_at": datetime.now(timezone.utc),
            }
        )
        saved = self._store.update_edge(updated)
        return EdgeIntegrationResult(action=IntegrationAction.EDGE_UPDATED, edge=saved)

    def _handle_edge_contradiction(
        self,
        existing_edges: list[Edge],
        source_id: uuid.UUID,
        target_id: uuid.UUID,
        edge_type: str,
        evidence_type: str,
        confidence: float,
        git_hash: str,
    ) -> EdgeIntegrationResult:
        now = datetime.now(timezone.utc)

        # Flag all existing edges with needs-review
        for existing in existing_edges:
            metadata = dict(existing.metadata or {})
            labels: list[str] = list(metadata.get("labels", []))
            if "needs-review" not in labels:
                labels.append("needs-review")
            metadata["labels"] = labels
            flagged = existing.model_copy(
                update={
                    "metadata": metadata,
                    "updated_at": now,
                }
            )
            self._store.update_edge(flagged)

        # Create new edge also flagged with needs-review
        new_edge = Edge(
            source_id=source_id,
            target_id=target_id,
            edge_type=edge_type,
            evidence_type=evidence_type,  # type: ignore[arg-type]
            confidence=confidence,
            derived_from_code_version=git_hash,
            metadata={"labels": ["needs-review"]},
        )
        saved = self._store.create_edge(new_edge)
        return EdgeIntegrationResult(action=IntegrationAction.EDGE_CONTRADICTED, edge=saved)

    def _create_new_edge(
        self,
        source_id: uuid.UUID,
        target_id: uuid.UUID,
        edge_type: str,
        evidence_type: str,
        confidence: float,
        git_hash: str,
    ) -> EdgeIntegrationResult:
        edge = Edge(
            source_id=source_id,
            target_id=target_id,
            edge_type=edge_type,
            evidence_type=evidence_type,  # type: ignore[arg-type]
            confidence=confidence,
            derived_from_code_version=git_hash,
        )
        saved = self._store.create_edge(edge)
        return EdgeIntegrationResult(action=IntegrationAction.EDGE_CREATED, edge=saved)
