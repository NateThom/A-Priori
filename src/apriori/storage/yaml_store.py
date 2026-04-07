"""YAML flat-file store for Concept and Edge entities (ERD §3.2.3; Story 2.6).

Writes one YAML file per Concept (slug-named) and one per Edge (UUID-named)
under a configurable base directory.  WorkItems, ReviewOutcomes, and
FailureRecords are SQLite-only — attempting to write them here raises TypeError.

Directory layout (S-5 spike decision):
    <base_dir>/
        concepts/
            payment-validation.yaml
            payment-validation-2.yaml   # collision suffix
        edges/
            <uuid>.yaml

This module is storage-layer internal.  Callers should go through the
KnowledgeStore protocol (arch:no-raw-sql); the YamlStore is used by the
DualWriter to satisfy the YAML half of dual-write (arch:sqlite-vec-storage).
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Optional

import yaml

from apriori.models.concept import Concept
from apriori.models.edge import Edge
from apriori.models.work_item import WorkItem


# ---------------------------------------------------------------------------
# Slugification
# ---------------------------------------------------------------------------

def slugify(name: str) -> str:
    """Convert a concept name to a deterministic URL-safe slug.

    Rules:
    - Strip leading/trailing whitespace
    - Lowercase
    - Replace one or more whitespace characters with a single hyphen
    - Strip any character that is not alphanumeric, a hyphen, or an underscore
    - Strip leading/trailing hyphens

    Args:
        name: The concept name to slugify.

    Returns:
        A deterministic, lowercase slug suitable for use as a filename stem.

    Examples:
        >>> slugify("Payment Validation")
        'payment-validation'
        >>> slugify("foo/bar!baz")
        'foobarbaz'
    """
    s = name.strip().lower()
    # Replace runs of whitespace with a hyphen
    s = re.sub(r"\s+", "-", s)
    # Strip characters that are not alphanumeric, hyphen, or underscore
    s = re.sub(r"[^a-z0-9_-]", "", s)
    # Collapse multiple hyphens
    s = re.sub(r"-+", "-", s)
    # Strip leading/trailing hyphens
    s = s.strip("-")
    return s


# ---------------------------------------------------------------------------
# YAML serialisation helpers
# ---------------------------------------------------------------------------

def _concept_to_dict(concept: Concept) -> dict:
    """Serialise a Concept to a plain dict suitable for yaml.dump."""
    return concept.model_dump(mode="json")


def _dict_to_concept(data: dict) -> Concept:
    """Deserialise a dict (from yaml.safe_load) back to a Concept."""
    return Concept.model_validate(data)


def _edge_to_dict(edge: Edge) -> dict:
    """Serialise an Edge to a plain dict suitable for yaml.dump."""
    return edge.model_dump(mode="json")


def _dict_to_edge(data: dict) -> Edge:
    """Deserialise a dict (from yaml.safe_load) back to an Edge."""
    return Edge.model_validate(data)


# ---------------------------------------------------------------------------
# YamlStore
# ---------------------------------------------------------------------------

class YamlStore:
    """Flat-file YAML store for Concept and Edge entities.

    Provides read/write/delete operations for Concepts and Edges only.
    Attempting to persist a WorkItem raises TypeError (SQLite-only entity).

    The store maintains an internal slug→id index in memory to resolve
    collisions without scanning the filesystem on every write.

    Args:
        base_dir: Root directory under which ``concepts/`` and ``edges/``
            subdirectories are created. Defaults to ``.apriori/`` relative
            to the current working directory.
    """

    def __init__(self, base_dir: Optional[Path] = None) -> None:
        if base_dir is None:
            base_dir = Path(".apriori")
        self._base = base_dir
        self._concepts_dir = self._base / "concepts"
        self._edges_dir = self._base / "edges"
        self._concepts_dir.mkdir(parents=True, exist_ok=True)
        self._edges_dir.mkdir(parents=True, exist_ok=True)

        # slug → concept id index; populated lazily on first write or by
        # scanning existing files so collision detection survives restarts.
        self._slug_index: dict[str, uuid.UUID] = {}
        self._id_to_slug: dict[uuid.UUID, str] = {}
        self._load_slug_index()

    # ------------------------------------------------------------------
    # Internal: slug index management
    # ------------------------------------------------------------------

    def _load_slug_index(self) -> None:
        """Scan existing concept YAML files and rebuild the in-memory index."""
        for path in self._concepts_dir.glob("*.yaml"):
            try:
                data = yaml.safe_load(path.read_text())
                if data and "id" in data:
                    cid = uuid.UUID(str(data["id"]))
                    stem = path.stem  # filename without extension
                    self._slug_index[stem] = cid
                    self._id_to_slug[cid] = stem
            except Exception:
                # Corrupt file — skip; do not crash the store
                pass

    def _allocate_slug(self, base_slug: str, concept_id: uuid.UUID) -> str:
        """Return the canonical slug filename stem for a concept.

        If the concept was already written (same id), returns its existing
        slug.  Otherwise finds the first non-colliding slug by appending
        numeric suffixes (-2, -3, …).

        Args:
            base_slug: The slug derived from the concept name.
            concept_id: The UUID of the concept being written.

        Returns:
            The slug (filename stem, no extension) to use for this concept.
        """
        # If this id already has a slug, reuse it (idempotent update)
        if concept_id in self._id_to_slug:
            return self._id_to_slug[concept_id]

        # Find a free slug
        candidate = base_slug
        suffix = 2
        while candidate in self._slug_index:
            candidate = f"{base_slug}-{suffix}"
            suffix += 1

        self._slug_index[candidate] = concept_id
        self._id_to_slug[concept_id] = candidate
        return candidate

    # ------------------------------------------------------------------
    # Concept operations
    # ------------------------------------------------------------------

    def write_concept(self, concept: Concept) -> Path:
        """Persist a Concept to a YAML file.

        The filename is derived from the concept name via :func:`slugify`.
        If a file already exists for a *different* concept with the same
        slug, a numeric suffix is appended (-2, -3, …).

        Writing the same concept twice (same ``concept.id``) is idempotent
        and overwrites the existing file in place.

        Args:
            concept: The Concept to persist.

        Returns:
            The :class:`~pathlib.Path` of the written file.
        """
        base_slug = slugify(concept.name)
        slug = self._allocate_slug(base_slug, concept.id)
        path = self._concepts_dir / f"{slug}.yaml"
        data = _concept_to_dict(concept)
        path.write_text(yaml.dump(data, allow_unicode=True, sort_keys=True))
        return path

    def read_concept(self, concept_id: uuid.UUID) -> Optional[Concept]:
        """Deserialise a Concept from its YAML file.

        Args:
            concept_id: The UUID of the Concept to read.

        Returns:
            The :class:`~apriori.models.concept.Concept` if the file exists,
            otherwise ``None``.
        """
        if concept_id not in self._id_to_slug:
            return None
        slug = self._id_to_slug[concept_id]
        path = self._concepts_dir / f"{slug}.yaml"
        if not path.exists():
            return None
        data = yaml.safe_load(path.read_text())
        return _dict_to_concept(data)

    def delete_concept(self, concept_id: uuid.UUID) -> None:
        """Remove a Concept's YAML file.

        Args:
            concept_id: The UUID of the Concept to delete.

        Raises:
            KeyError: If no YAML file exists for this concept id.
        """
        if concept_id not in self._id_to_slug:
            raise KeyError(concept_id)
        slug = self._id_to_slug.pop(concept_id)
        del self._slug_index[slug]
        path = self._concepts_dir / f"{slug}.yaml"
        if path.exists():
            path.unlink()

    # ------------------------------------------------------------------
    # Edge operations
    # ------------------------------------------------------------------

    def write_edge(self, edge: Edge) -> Path:
        """Persist an Edge to a YAML file named by its UUID.

        Args:
            edge: The Edge to persist.

        Returns:
            The :class:`~pathlib.Path` of the written file.
        """
        path = self._edges_dir / f"{edge.id}.yaml"
        data = _edge_to_dict(edge)
        path.write_text(yaml.dump(data, allow_unicode=True, sort_keys=True))
        return path

    def read_edge(self, edge_id: uuid.UUID) -> Optional[Edge]:
        """Deserialise an Edge from its YAML file.

        Args:
            edge_id: The UUID of the Edge to read.

        Returns:
            The :class:`~apriori.models.edge.Edge` if the file exists,
            otherwise ``None``.
        """
        path = self._edges_dir / f"{edge_id}.yaml"
        if not path.exists():
            return None
        data = yaml.safe_load(path.read_text())
        return _dict_to_edge(data)

    def delete_edge(self, edge_id: uuid.UUID) -> None:
        """Remove an Edge's YAML file.

        Args:
            edge_id: The UUID of the Edge to delete.

        Raises:
            KeyError: If no YAML file exists for this edge id.
        """
        path = self._edges_dir / f"{edge_id}.yaml"
        if not path.exists():
            raise KeyError(edge_id)
        path.unlink()

    # ------------------------------------------------------------------
    # SQLite-only entity guard
    # ------------------------------------------------------------------

    def write_work_item(self, work_item: WorkItem) -> None:
        """Raise TypeError — WorkItems are SQLite-only (arch:sqlite-vec-storage).

        Args:
            work_item: Ignored.

        Raises:
            TypeError: Always.  WorkItems must not be written to YAML.
        """
        raise TypeError(
            f"WorkItem '{work_item.id}' cannot be persisted to YAML. "
            "WorkItems are SQLite-only entities (arch:sqlite-vec-storage). "
            "Use the SQLiteStore for work item persistence."
        )
