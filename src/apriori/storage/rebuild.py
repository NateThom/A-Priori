"""Rebuild-index operation: reconstruct the SQLite database from YAML files.

Story 2.8 (ERD §3.2.4) — The YAML store is the authoritative source of truth.
``rebuild_index_from_yaml`` reads every concept and edge YAML file, regenerates
embeddings, loads everything into a *fresh* SQLite database, then atomically
swaps the new database file into place.

The operation is idempotent: running it twice on the same YAML files produces
an identical database.

Usage::

    from apriori.storage.rebuild import rebuild_index_from_yaml
    from apriori.storage.yaml_store import YamlStore
    from apriori.embedding.service import EmbeddingService

    yaml_store = YamlStore(base_dir=Path(".apriori"))
    embedding_svc = EmbeddingService()

    rebuild_index_from_yaml(
        yaml_store,
        db_path=Path("graph.db"),
        embedding_service=embedding_svc,
        progress_callback=lambda current, total, msg: print(f"[{current}/{total}] {msg}"),
    )
"""

from __future__ import annotations

import logging
import os
import uuid
from pathlib import Path
from typing import Callable, Optional

import yaml

from apriori.embedding.protocol import EmbeddingServiceProtocol
from apriori.models.concept import Concept
from apriori.models.edge import Edge
from apriori.storage.sqlite_store import SQLiteStore
from apriori.storage.yaml_store import YamlStore, _dict_to_concept, _dict_to_edge

logger = logging.getLogger(__name__)

# Batch size for embedding generation — trade-off between memory and throughput.
_EMBED_BATCH_SIZE = 64

ProgressCallback = Callable[[int, int, str], None]


def _report(
    callback: Optional[ProgressCallback], current: int, total: int, message: str
) -> None:
    """Call the progress callback if one was provided."""
    if callback is not None:
        callback(current, total, message)


def rebuild_index_from_yaml(
    yaml_store: YamlStore,
    db_path: Path,
    embedding_service: EmbeddingServiceProtocol,
    progress_callback: Optional[ProgressCallback] = None,
) -> None:
    """Rebuild the SQLite database from YAML files and atomically swap it in.

    Reads every concept and edge YAML file from *yaml_store*, regenerates
    embeddings for all concepts, loads everything into a temporary SQLite
    database, then atomically replaces *db_path* with the new database.

    The operation is idempotent: calling it twice with the same YAML store and
    *db_path* produces identical database state.

    Args:
        yaml_store: The YAML store to read concept and edge files from.
        db_path: Path where the live SQLite database resides (or will be
            created). The existing file (if any) is replaced atomically.
        embedding_service: Used to regenerate 768-dim embeddings for every
            concept description. All embeddings are regenerated from scratch
            to ensure the index is consistent with the current model.
        progress_callback: Optional callable invoked periodically during the
            rebuild. Signature: ``(current: int, total: int, message: str)``.
            ``current`` is the number of items processed so far, ``total`` is
            the total number of items expected, and ``message`` is a
            human-readable status string.

    Raises:
        yaml.YAMLError: If any YAML file is malformed and cannot be parsed.
        pydantic.ValidationError: If a deserialized YAML dict does not satisfy
            the Concept or Edge schema.
    """
    # ------------------------------------------------------------------
    # Step 1 — Read all concepts from YAML
    # ------------------------------------------------------------------
    _report(progress_callback, 0, 0, "Scanning YAML store for concepts…")
    concepts: list[Concept] = _load_all_concepts(yaml_store)
    concept_count = len(concepts)
    logger.info("rebuild_index_from_yaml: found %d concepts in YAML store", concept_count)

    # ------------------------------------------------------------------
    # Step 2 — Read all edges from YAML
    # ------------------------------------------------------------------
    _report(progress_callback, 0, concept_count, "Scanning YAML store for edges…")
    edges: list[Edge] = _load_all_edges(yaml_store)
    edge_count = len(edges)
    logger.info("rebuild_index_from_yaml: found %d edges in YAML store", edge_count)

    # ------------------------------------------------------------------
    # Step 3 — Build a fresh SQLite database in a temporary file.
    #
    # We write to db_path.with_suffix(".tmp") (next to the target file)
    # so that the final os.replace() is guaranteed to be on the same
    # filesystem, making it atomic on POSIX.
    # ------------------------------------------------------------------
    tmp_path = db_path.with_suffix(".rebuild_tmp")
    if tmp_path.exists():
        tmp_path.unlink()

    # SQLiteStore initialises the schema on construction.
    tmp_store = SQLiteStore(tmp_path, embedding_service=None)

    # ------------------------------------------------------------------
    # Step 4 — Insert all concepts (no embeddings yet)
    # ------------------------------------------------------------------
    total_items = concept_count  # progress denominator during concept phase
    _report(progress_callback, 0, total_items, f"Loading {concept_count} concepts into SQLite…")

    for idx, concept in enumerate(concepts, start=1):
        tmp_store.create_concept(concept)
        if idx % 50 == 0 or idx == concept_count:
            _report(
                progress_callback,
                idx,
                concept_count,
                f"Loaded concept {idx}/{concept_count}",
            )

    logger.info("rebuild_index_from_yaml: inserted %d concepts", concept_count)

    # ------------------------------------------------------------------
    # Step 5 — Generate embeddings in batches and upsert into concept_embeddings
    # ------------------------------------------------------------------
    if concept_count > 0:
        _report(
            progress_callback, 0, concept_count, "Generating embeddings…"
        )
        _batch_embed_concepts(tmp_store, concepts, embedding_service, progress_callback)
        logger.info("rebuild_index_from_yaml: embeddings generated for %d concepts", concept_count)

    # ------------------------------------------------------------------
    # Step 6 — Insert all edges
    # ------------------------------------------------------------------
    _report(progress_callback, 0, edge_count, f"Loading {edge_count} edges into SQLite…")
    for idx, edge in enumerate(edges, start=1):
        tmp_store.create_edge(edge)
        if idx % 50 == 0 or idx == edge_count:
            _report(
                progress_callback,
                idx,
                edge_count,
                f"Loaded edge {idx}/{edge_count}",
            )

    logger.info("rebuild_index_from_yaml: inserted %d edges", edge_count)

    # ------------------------------------------------------------------
    # Step 7 — Rebuild FTS5 content table from the freshly populated concepts
    # ------------------------------------------------------------------
    _report(progress_callback, concept_count, concept_count, "Rebuilding FTS5 index…")
    conn = tmp_store._get_connection()
    conn.execute("INSERT INTO concepts_fts(concepts_fts) VALUES('rebuild')")
    conn.commit()

    # ------------------------------------------------------------------
    # Step 8 — Atomic swap: replace the live DB with the new one
    # ------------------------------------------------------------------
    _report(progress_callback, concept_count, concept_count, "Swapping database file…")

    # Close the thread-local connection before renaming the file so that the
    # OS file handle is released on all platforms.
    conn.close()
    tmp_store._local.conn = None  # type: ignore[attr-defined]

    db_path.parent.mkdir(parents=True, exist_ok=True)

    # Remove any WAL / SHM files for the old database before the swap.
    # SQLite WAL mode creates <db>-wal and <db>-shm sidecar files.  If we
    # replace only the main database file, the old WAL would be replayed by
    # the next connection and corrupt the fresh data.
    for suffix in ("-wal", "-shm"):
        sidecar = db_path.parent / (db_path.name + suffix)
        if sidecar.exists():
            sidecar.unlink()

    os.replace(str(tmp_path), str(db_path))

    logger.info(
        "rebuild_index_from_yaml: atomic swap complete — %s is now the live database",
        db_path,
    )
    _report(
        progress_callback,
        concept_count,
        concept_count,
        f"Rebuild complete: {concept_count} concepts, {edge_count} edges.",
    )


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _load_all_concepts(yaml_store: YamlStore) -> list[Concept]:
    """Read and deserialize every concept YAML file from the store directory.

    Skips malformed files with a warning rather than aborting the rebuild.
    """
    concepts: list[Concept] = []
    for path in sorted(yaml_store._concepts_dir.glob("*.yaml")):
        try:
            data = yaml.safe_load(path.read_text())
            if data:
                concepts.append(_dict_to_concept(data))
        except Exception as exc:
            logger.warning(
                "rebuild_index_from_yaml: skipping malformed concept file %s: %s",
                path,
                exc,
            )
    return concepts


def _load_all_edges(yaml_store: YamlStore) -> list[Edge]:
    """Read and deserialize every edge YAML file from the store directory.

    Skips malformed files with a warning rather than aborting the rebuild.
    """
    edges: list[Edge] = []
    for path in sorted(yaml_store._edges_dir.glob("*.yaml")):
        try:
            data = yaml.safe_load(path.read_text())
            if data:
                edges.append(_dict_to_edge(data))
        except Exception as exc:
            logger.warning(
                "rebuild_index_from_yaml: skipping malformed edge file %s: %s",
                path,
                exc,
            )
    return edges


def _batch_embed_concepts(
    store: SQLiteStore,
    concepts: list[Concept],
    embedding_service: EmbeddingServiceProtocol,
    progress_callback: Optional[ProgressCallback],
) -> None:
    """Generate embeddings in batches and upsert into the store.

    Batching amortizes model overhead for large corpora. Each batch of up to
    ``_EMBED_BATCH_SIZE`` concept descriptions is embedded in one call when
    the service supports ``generate_embeddings_batch``; otherwise falls back
    to individual ``generate_embedding`` calls.
    """
    import sqlite_vec

    total = len(concepts)
    conn = store._get_connection()

    for batch_start in range(0, total, _EMBED_BATCH_SIZE):
        batch = concepts[batch_start : batch_start + _EMBED_BATCH_SIZE]

        # Try batch embedding first; fall back to individual calls.
        try:
            vectors = embedding_service.generate_embeddings_batch(
                [c.description for c in batch], text_type="passage"
            )
        except (AttributeError, TypeError, NotImplementedError):
            vectors = [
                embedding_service.generate_embedding(c.description, text_type="passage")
                for c in batch
            ]

        for concept, vector in zip(batch, vectors):
            serialized = sqlite_vec.serialize_float32(vector)
            conn.execute(
                "DELETE FROM concept_embeddings WHERE concept_id = ?",
                (str(concept.id),),
            )
            conn.execute(
                "INSERT INTO concept_embeddings(concept_id, embedding) VALUES (?, ?)",
                (str(concept.id), serialized),
            )

        conn.commit()

        batch_end = min(batch_start + _EMBED_BATCH_SIZE, total)
        _report(
            progress_callback,
            batch_end,
            total,
            f"Embedded concepts {batch_end}/{total}",
        )
