"""SQLiteStore — concrete KnowledgeStore implementation backed by SQLite + sqlite-vec.

Schema implements ERD §3.2.2:
- concepts: core concept data (JSON for labels, code_references, metadata, impact_profile)
- edges: typed directed relationships with UNIQUE(source_id, target_id, edge_type)
- work_items: librarian work queue (JSON for failure_records)
- review_outcomes: human audit trail
- concepts_fts: FTS5 virtual table for keyword search on name + description
- concept_embeddings: sqlite-vec vec0 table (768-dim) for semantic search

Thread safety: per-thread SQLite connections via threading.local().
All timestamps stored as ISO 8601 text. WAL mode + FK enforcement on every connection.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

import sqlite_vec

from apriori.embedding.protocol import EmbeddingServiceProtocol
from apriori.models.concept import Concept, CodeReference
from apriori.models.edge import Edge
from apriori.models.impact import ImpactEntry, ImpactProfile
from apriori.models.review_outcome import ReviewOutcome
from apriori.models.work_item import FailureRecord, WorkItem

_EMBEDDING_DIMS = 768  # e5-base-v2 per S-2 decision


# ---------------------------------------------------------------------------
# DDL
# ---------------------------------------------------------------------------

_DDL = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS concepts (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    description     TEXT NOT NULL,
    labels          TEXT NOT NULL DEFAULT '[]',
    code_references TEXT NOT NULL DEFAULT '[]',
    created_by      TEXT NOT NULL,
    verified_by     TEXT,
    last_verified   TEXT,
    confidence      REAL NOT NULL DEFAULT 0.5,
    derived_from_code_version TEXT,
    metadata        TEXT,
    impact_profile  TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_concepts_name ON concepts(name);

CREATE TABLE IF NOT EXISTS edges (
    id              TEXT PRIMARY KEY,
    source_id       TEXT NOT NULL REFERENCES concepts(id) ON DELETE CASCADE,
    target_id       TEXT NOT NULL REFERENCES concepts(id) ON DELETE CASCADE,
    edge_type       TEXT NOT NULL,
    evidence_type   TEXT NOT NULL,
    confidence      REAL NOT NULL DEFAULT 1.0,
    metadata        TEXT,
    derived_from_code_version TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    UNIQUE(source_id, target_id, edge_type)
);

CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source_id);
CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target_id);
CREATE INDEX IF NOT EXISTS idx_edges_type   ON edges(edge_type);

CREATE TABLE IF NOT EXISTS work_items (
    id                  TEXT PRIMARY KEY,
    item_type           TEXT NOT NULL,
    concept_id          TEXT NOT NULL REFERENCES concepts(id),
    description         TEXT NOT NULL,
    file_path           TEXT,
    created_at          TEXT NOT NULL,
    resolved_at         TEXT,
    failure_count       INTEGER NOT NULL DEFAULT 0,
    failure_records     TEXT NOT NULL DEFAULT '[]',
    escalated           INTEGER NOT NULL DEFAULT 0,
    resolved            INTEGER NOT NULL DEFAULT 0,
    base_priority_score REAL
);

CREATE INDEX IF NOT EXISTS idx_work_items_concept ON work_items(concept_id);
CREATE INDEX IF NOT EXISTS idx_work_items_resolved ON work_items(resolved);
CREATE INDEX IF NOT EXISTS idx_work_items_escalated ON work_items(escalated);
CREATE INDEX IF NOT EXISTS idx_work_items_priority ON work_items(base_priority_score DESC);

CREATE TABLE IF NOT EXISTS review_outcomes (
    id                  TEXT PRIMARY KEY,
    concept_id          TEXT NOT NULL REFERENCES concepts(id),
    reviewer            TEXT NOT NULL,
    action              TEXT NOT NULL,
    error_type          TEXT,
    correction_details  TEXT,
    created_at          TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_review_outcomes_concept ON review_outcomes(concept_id);

CREATE VIRTUAL TABLE IF NOT EXISTS concepts_fts USING fts5(
    id UNINDEXED,
    name,
    description,
    content='concepts',
    content_rowid='rowid'
);
"""

# FTS5 sync triggers — defined separately because trigger bodies contain
# semicolons that would break the simple split(";") DDL executor.
_FTS5_TRIGGERS = [
    """
    CREATE TRIGGER IF NOT EXISTS concepts_ai AFTER INSERT ON concepts BEGIN
        INSERT INTO concepts_fts(rowid, id, name, description)
        VALUES (new.rowid, new.id, new.name, new.description);
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS concepts_ad AFTER DELETE ON concepts BEGIN
        INSERT INTO concepts_fts(concepts_fts, rowid, id, name, description)
        VALUES ('delete', old.rowid, old.id, old.name, old.description);
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS concepts_au AFTER UPDATE ON concepts BEGIN
        INSERT INTO concepts_fts(concepts_fts, rowid, id, name, description)
        VALUES ('delete', old.rowid, old.id, old.name, old.description);
        INSERT INTO concepts_fts(rowid, id, name, description)
        VALUES (new.rowid, new.id, new.name, new.description);
    END
    """,
]


# ---------------------------------------------------------------------------
# SQLiteStore
# ---------------------------------------------------------------------------

class SQLiteStore:
    """SQLite + sqlite-vec implementation of KnowledgeStore (ERD §3.2.2).

    Thread safety: each thread gets its own sqlite3.Connection via
    threading.local(). WAL mode is set on every new connection so that
    readers never block writers.

    Usage::

        store = SQLiteStore(Path("graph.db"))
        concept = store.create_concept(Concept(name="foo", ...))
    """

    def __init__(
        self,
        db_path: Path,
        embedding_service: Optional[EmbeddingServiceProtocol] = None,
    ) -> None:
        self._db_path = db_path
        self._embedding_service = embedding_service
        self._local = threading.local()
        # Initialize schema on the calling thread's connection
        conn = self._get_connection()
        self._init_schema(conn)

    # -----------------------------------------------------------------------
    # Connection management
    # -----------------------------------------------------------------------

    def _get_connection(self) -> sqlite3.Connection:
        """Return the per-thread sqlite3 connection, creating it if needed."""
        if not hasattr(self._local, "conn") or self._local.conn is None:
            conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("PRAGMA foreign_keys = ON")
            conn.enable_load_extension(True)
            sqlite_vec.load(conn)
            conn.enable_load_extension(False)
            self._local.conn = conn
        return self._local.conn

    def _init_schema(self, conn: sqlite3.Connection) -> None:
        """Create all tables, indexes, virtual tables, and triggers if they don't exist."""
        # Execute DDL statements individually (executescript resets auto-commit)
        cursor = conn.cursor()
        for statement in _DDL.strip().split(";"):
            stmt = statement.strip()
            if stmt:
                cursor.execute(stmt)
        conn.commit()
        # vec0 virtual table (requires sqlite_vec extension)
        cursor.execute(
            f"""
            CREATE VIRTUAL TABLE IF NOT EXISTS concept_embeddings
            USING vec0(
                concept_id TEXT PRIMARY KEY,
                embedding FLOAT[{_EMBEDDING_DIMS}]
            )
            """
        )
        conn.commit()
        # FTS5 sync triggers (defined separately to avoid semicolon-split issues)
        for trigger_sql in _FTS5_TRIGGERS:
            cursor.execute(trigger_sql)
        conn.commit()

    def _execute_scalar(self, sql: str, params: tuple = ()) -> Any:
        """Execute a scalar query and return the single value."""
        conn = self._get_connection()
        row = conn.execute(sql, params).fetchone()
        return row[0] if row else None

    def _upsert_embedding(self, concept_id: uuid.UUID, text: str) -> None:
        """Generate an embedding for text and upsert it into concept_embeddings.

        vec0 does not support INSERT OR REPLACE, so we DELETE then INSERT.
        No-op if no embedding_service is configured.
        """
        if self._embedding_service is None:
            return
        vector = self._embedding_service.generate_embedding(text, text_type="passage")
        serialized = sqlite_vec.serialize_float32(vector)
        conn = self._get_connection()
        # Delete existing entry (if any) before re-inserting — vec0 does not
        # support INSERT OR REPLACE / ON CONFLICT clauses.
        conn.execute(
            "DELETE FROM concept_embeddings WHERE concept_id = ?",
            (str(concept_id),),
        )
        conn.execute(
            "INSERT INTO concept_embeddings(concept_id, embedding) VALUES (?, ?)",
            (str(concept_id), serialized),
        )
        conn.commit()

    def _delete_embedding(self, concept_id: uuid.UUID) -> None:
        """Remove the embedding for a concept from concept_embeddings."""
        conn = self._get_connection()
        conn.execute(
            "DELETE FROM concept_embeddings WHERE concept_id = ?",
            (str(concept_id),),
        )
        conn.commit()

    # -----------------------------------------------------------------------
    # Serialisation helpers
    # -----------------------------------------------------------------------

    @staticmethod
    def _dt_to_iso(dt: Optional[datetime]) -> Optional[str]:
        if dt is None:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.isoformat()

    @staticmethod
    def _iso_to_dt(s: Optional[str]) -> Optional[datetime]:
        if not s:
            return None
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt

    @staticmethod
    def _concept_to_row(c: Concept) -> tuple:
        return (
            str(c.id),
            c.name,
            c.description,
            json.dumps(sorted(c.labels)),
            json.dumps([ref.model_dump() for ref in c.code_references]),
            c.created_by,
            c.verified_by,
            SQLiteStore._dt_to_iso(c.last_verified),
            c.confidence,
            c.derived_from_code_version,
            json.dumps(c.metadata) if c.metadata is not None else None,
            c.impact_profile.model_dump_json() if c.impact_profile is not None else None,
            SQLiteStore._dt_to_iso(c.created_at),
            SQLiteStore._dt_to_iso(c.updated_at),
        )

    @staticmethod
    def _row_to_concept(row: sqlite3.Row) -> Concept:
        labels_raw = json.loads(row["labels"] or "[]")
        refs_raw = json.loads(row["code_references"] or "[]")
        code_refs = [CodeReference(**r) for r in refs_raw]
        impact = None
        if row["impact_profile"]:
            impact = ImpactProfile.model_validate_json(row["impact_profile"])
        metadata = json.loads(row["metadata"]) if row["metadata"] else None
        return Concept(
            id=uuid.UUID(row["id"]),
            name=row["name"],
            description=row["description"],
            labels=set(labels_raw),
            code_references=code_refs,
            created_by=row["created_by"],
            verified_by=row["verified_by"],
            last_verified=SQLiteStore._iso_to_dt(row["last_verified"]),
            confidence=row["confidence"],
            derived_from_code_version=row["derived_from_code_version"],
            metadata=metadata,
            impact_profile=impact,
            created_at=SQLiteStore._iso_to_dt(row["created_at"]),
            updated_at=SQLiteStore._iso_to_dt(row["updated_at"]),
        )

    @staticmethod
    def _edge_to_row(e: Edge) -> tuple:
        return (
            str(e.id),
            str(e.source_id),
            str(e.target_id),
            e.edge_type,
            e.evidence_type,
            e.confidence,
            json.dumps(e.metadata) if e.metadata is not None else None,
            e.derived_from_code_version,
            SQLiteStore._dt_to_iso(e.created_at),
            SQLiteStore._dt_to_iso(e.updated_at),
        )

    @staticmethod
    def _row_to_edge(row: sqlite3.Row) -> Edge:
        metadata = json.loads(row["metadata"]) if row["metadata"] else None
        return Edge(
            id=uuid.UUID(row["id"]),
            source_id=uuid.UUID(row["source_id"]),
            target_id=uuid.UUID(row["target_id"]),
            edge_type=row["edge_type"],
            evidence_type=row["evidence_type"],
            confidence=row["confidence"],
            metadata=metadata,
            derived_from_code_version=row["derived_from_code_version"],
            created_at=SQLiteStore._iso_to_dt(row["created_at"]),
            updated_at=SQLiteStore._iso_to_dt(row["updated_at"]),
        )

    @staticmethod
    def _work_item_to_row(wi: WorkItem) -> tuple:
        return (
            str(wi.id),
            wi.item_type,
            str(wi.concept_id),
            wi.description,
            wi.file_path,
            SQLiteStore._dt_to_iso(wi.created_at),
            SQLiteStore._dt_to_iso(wi.resolved_at),
            wi.failure_count,
            json.dumps([r.model_dump(mode="json") for r in wi.failure_records]),
            int(wi.escalated),
            int(wi.resolved),
            wi.base_priority_score,
        )

    @staticmethod
    def _row_to_work_item(row: sqlite3.Row) -> WorkItem:
        records_raw = json.loads(row["failure_records"] or "[]")
        records = [FailureRecord(**r) for r in records_raw]
        return WorkItem(
            id=uuid.UUID(row["id"]),
            item_type=row["item_type"],
            concept_id=uuid.UUID(row["concept_id"]),
            description=row["description"],
            file_path=row["file_path"],
            created_at=SQLiteStore._iso_to_dt(row["created_at"]),
            resolved_at=SQLiteStore._iso_to_dt(row["resolved_at"]),
            failure_count=row["failure_count"],
            failure_records=records,
            escalated=bool(row["escalated"]),
            resolved=bool(row["resolved"]),
            base_priority_score=row["base_priority_score"],
        )

    @staticmethod
    def _review_outcome_to_row(o: ReviewOutcome) -> tuple:
        return (
            str(uuid.uuid4()),  # generated PK
            str(o.concept_id),
            o.reviewer,
            o.action,
            o.error_type,
            o.correction_details,
            SQLiteStore._dt_to_iso(o.created_at),
        )

    @staticmethod
    def _row_to_review_outcome(row: sqlite3.Row) -> ReviewOutcome:
        return ReviewOutcome(
            concept_id=uuid.UUID(row["concept_id"]),
            reviewer=row["reviewer"],
            action=row["action"],
            error_type=row["error_type"],
            correction_details=row["correction_details"],
            created_at=SQLiteStore._iso_to_dt(row["created_at"]),
        )

    # -----------------------------------------------------------------------
    # Concept CRUD
    # -----------------------------------------------------------------------

    def create_concept(self, concept: Concept) -> Concept:
        """Persist a new Concept. Raises ValueError if id already exists."""
        conn = self._get_connection()
        existing = conn.execute(
            "SELECT id FROM concepts WHERE id = ?", (str(concept.id),)
        ).fetchone()
        if existing:
            raise ValueError(f"Concept {concept.id} already exists")
        conn.execute(
            """
            INSERT INTO concepts
                (id, name, description, labels, code_references, created_by,
                 verified_by, last_verified, confidence, derived_from_code_version,
                 metadata, impact_profile, created_at, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            self._concept_to_row(concept),
        )
        conn.commit()
        self._upsert_embedding(concept.id, concept.description)
        return concept

    def get_concept(self, concept_id: uuid.UUID) -> Optional[Concept]:
        """Return Concept by id, or None if not found."""
        conn = self._get_connection()
        row = conn.execute(
            "SELECT * FROM concepts WHERE id = ?", (str(concept_id),)
        ).fetchone()
        return self._row_to_concept(row) if row else None

    def update_concept(self, concept: Concept) -> Concept:
        """Replace an existing Concept. Raises KeyError if not found."""
        conn = self._get_connection()
        existing = conn.execute(
            "SELECT id FROM concepts WHERE id = ?", (str(concept.id),)
        ).fetchone()
        if not existing:
            raise KeyError(f"Concept {concept.id} not found")
        row = self._concept_to_row(concept)
        conn.execute(
            """
            UPDATE concepts SET
                name=?, description=?, labels=?, code_references=?, created_by=?,
                verified_by=?, last_verified=?, confidence=?,
                derived_from_code_version=?, metadata=?, impact_profile=?,
                created_at=?, updated_at=?
            WHERE id=?
            """,
            row[1:] + (row[0],),  # all fields except id, then id for WHERE
        )
        conn.commit()
        self._upsert_embedding(concept.id, concept.description)
        return concept

    def delete_concept(self, concept_id: uuid.UUID) -> None:
        """Delete a Concept and cascade-delete its Edges. Raises KeyError if not found."""
        conn = self._get_connection()
        existing = conn.execute(
            "SELECT id FROM concepts WHERE id = ?", (str(concept_id),)
        ).fetchone()
        if not existing:
            raise KeyError(f"Concept {concept_id} not found")
        self._delete_embedding(concept_id)
        conn.execute("DELETE FROM concepts WHERE id = ?", (str(concept_id),))
        conn.commit()

    def list_concepts(self, labels: Optional[set[str]] = None) -> list[Concept]:
        """Return all Concepts, optionally filtered by label intersection."""
        conn = self._get_connection()
        rows = conn.execute("SELECT * FROM concepts").fetchall()
        concepts = [self._row_to_concept(r) for r in rows]
        if labels:
            concepts = [c for c in concepts if labels & c.labels]
        return concepts

    # -----------------------------------------------------------------------
    # Edge CRUD
    # -----------------------------------------------------------------------

    def create_edge(self, edge: Edge) -> Edge:
        """Persist a new Edge. Raises ValueError on duplicate (source, target, type).
        Raises KeyError if source_id or target_id references a non-existent Concept."""
        conn = self._get_connection()
        try:
            conn.execute(
                """
                INSERT INTO edges
                    (id, source_id, target_id, edge_type, evidence_type, confidence,
                     metadata, derived_from_code_version, created_at, updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?)
                """,
                self._edge_to_row(edge),
            )
            conn.commit()
        except sqlite3.IntegrityError as exc:
            exc_str = str(exc)
            if "UNIQUE" in exc_str:
                raise ValueError(
                    f"Edge ({edge.source_id}, {edge.target_id}, {edge.edge_type}) already exists"
                ) from exc
            if "FOREIGN KEY" in exc_str:
                raise KeyError(
                    f"Edge references non-existent concept: source={edge.source_id}, "
                    f"target={edge.target_id}"
                ) from exc
            raise
        return edge

    def get_edge(self, edge_id: uuid.UUID) -> Optional[Edge]:
        """Return Edge by id, or None if not found."""
        conn = self._get_connection()
        row = conn.execute(
            "SELECT * FROM edges WHERE id = ?", (str(edge_id),)
        ).fetchone()
        return self._row_to_edge(row) if row else None

    def update_edge(self, edge: Edge) -> Edge:
        """Replace an existing Edge. Raises KeyError if not found."""
        conn = self._get_connection()
        existing = conn.execute(
            "SELECT id FROM edges WHERE id = ?", (str(edge.id),)
        ).fetchone()
        if not existing:
            raise KeyError(f"Edge {edge.id} not found")
        row = self._edge_to_row(edge)
        conn.execute(
            """
            UPDATE edges SET
                source_id=?, target_id=?, edge_type=?, evidence_type=?, confidence=?,
                metadata=?, derived_from_code_version=?, created_at=?, updated_at=?
            WHERE id=?
            """,
            row[1:] + (row[0],),
        )
        conn.commit()
        return edge

    def delete_edge(self, edge_id: uuid.UUID) -> None:
        """Delete an Edge. Raises KeyError if not found."""
        conn = self._get_connection()
        existing = conn.execute(
            "SELECT id FROM edges WHERE id = ?", (str(edge_id),)
        ).fetchone()
        if not existing:
            raise KeyError(f"Edge {edge_id} not found")
        conn.execute("DELETE FROM edges WHERE id = ?", (str(edge_id),))
        conn.commit()

    def list_edges(
        self,
        source_id: Optional[uuid.UUID] = None,
        target_id: Optional[uuid.UUID] = None,
        edge_type: Optional[str] = None,
    ) -> list[Edge]:
        """Return Edges matching the given filters (AND semantics)."""
        conn = self._get_connection()
        clauses: list[str] = []
        params: list[Any] = []
        if source_id is not None:
            clauses.append("source_id = ?")
            params.append(str(source_id))
        if target_id is not None:
            clauses.append("target_id = ?")
            params.append(str(target_id))
        if edge_type is not None:
            clauses.append("edge_type = ?")
            params.append(edge_type)
        sql = "SELECT * FROM edges"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        rows = conn.execute(sql, params).fetchall()
        return [self._row_to_edge(r) for r in rows]

    # -----------------------------------------------------------------------
    # Work Item operations
    # -----------------------------------------------------------------------

    def create_work_item(self, work_item: WorkItem) -> WorkItem:
        """Persist a new WorkItem. Raises ValueError if id already exists."""
        conn = self._get_connection()
        existing = conn.execute(
            "SELECT id FROM work_items WHERE id = ?", (str(work_item.id),)
        ).fetchone()
        if existing:
            raise ValueError(f"WorkItem {work_item.id} already exists")
        conn.execute(
            """
            INSERT INTO work_items
                (id, item_type, concept_id, description, file_path, created_at,
                 resolved_at, failure_count, failure_records, escalated, resolved,
                 base_priority_score)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            self._work_item_to_row(work_item),
        )
        conn.commit()
        return work_item

    def get_work_item(self, work_item_id: uuid.UUID) -> Optional[WorkItem]:
        """Return WorkItem by id, or None if not found."""
        conn = self._get_connection()
        row = conn.execute(
            "SELECT * FROM work_items WHERE id = ?", (str(work_item_id),)
        ).fetchone()
        return self._row_to_work_item(row) if row else None

    def update_work_item(self, work_item: WorkItem) -> WorkItem:
        """Replace an existing WorkItem. Raises KeyError if not found."""
        conn = self._get_connection()
        existing = conn.execute(
            "SELECT id FROM work_items WHERE id = ?", (str(work_item.id),)
        ).fetchone()
        if not existing:
            raise KeyError(f"WorkItem {work_item.id} not found")
        row = self._work_item_to_row(work_item)
        conn.execute(
            """
            UPDATE work_items SET
                item_type=?, concept_id=?, description=?, file_path=?, created_at=?,
                resolved_at=?, failure_count=?, failure_records=?, escalated=?,
                resolved=?, base_priority_score=?
            WHERE id=?
            """,
            row[1:] + (row[0],),
        )
        conn.commit()
        return work_item

    def resolve_work_item(self, work_item_id: uuid.UUID) -> WorkItem:
        """Mark a WorkItem resolved. Raises KeyError if not found."""
        wi = self.get_work_item(work_item_id)
        if wi is None:
            raise KeyError(f"WorkItem {work_item_id} not found")
        updated = wi.model_copy(
            update={"resolved": True, "resolved_at": datetime.now(timezone.utc)}
        )
        return self.update_work_item(updated)

    def get_pending_work_items(self) -> list[WorkItem]:
        """Return all unresolved WorkItems."""
        conn = self._get_connection()
        rows = conn.execute(
            "SELECT * FROM work_items WHERE resolved = 0"
        ).fetchall()
        return [self._row_to_work_item(r) for r in rows]

    def record_failure(
        self, work_item_id: uuid.UUID, record: FailureRecord
    ) -> WorkItem:
        """Append a FailureRecord to a WorkItem. Raises KeyError if not found."""
        wi = self.get_work_item(work_item_id)
        if wi is None:
            raise KeyError(f"WorkItem {work_item_id} not found")
        updated = wi.model_copy(
            update={
                "failure_count": wi.failure_count + 1,
                "failure_records": wi.failure_records + [record],
            }
        )
        return self.update_work_item(updated)

    def escalate_work_item(self, work_item_id: uuid.UUID) -> WorkItem:
        """Mark a WorkItem escalated. Raises KeyError if not found."""
        wi = self.get_work_item(work_item_id)
        if wi is None:
            raise KeyError(f"WorkItem {work_item_id} not found")
        updated = wi.model_copy(update={"escalated": True})
        return self.update_work_item(updated)

    def get_escalated_items(self) -> list[WorkItem]:
        """Return all escalated WorkItems."""
        conn = self._get_connection()
        rows = conn.execute(
            "SELECT * FROM work_items WHERE escalated = 1"
        ).fetchall()
        return [self._row_to_work_item(r) for r in rows]

    def get_work_item_stats(self) -> dict[str, int]:
        """Return aggregate counts for work items by state.

        Returns a dict with keys: total, pending, resolved, escalated.
        """
        conn = self._get_connection()
        total = conn.execute("SELECT COUNT(*) FROM work_items").fetchone()[0]
        pending = conn.execute(
            "SELECT COUNT(*) FROM work_items WHERE resolved = 0"
        ).fetchone()[0]
        resolved = conn.execute(
            "SELECT COUNT(*) FROM work_items WHERE resolved = 1"
        ).fetchone()[0]
        escalated = conn.execute(
            "SELECT COUNT(*) FROM work_items WHERE escalated = 1"
        ).fetchone()[0]
        return {
            "total": total,
            "pending": pending,
            "resolved": resolved,
            "escalated": escalated,
        }

    def delete_old_work_items(self, days: int) -> int:
        """Delete resolved WorkItems whose resolved_at is older than `days` days.

        Args:
            days: Retention period in days. Resolved items with resolved_at
                older than this many days ago are permanently deleted.

        Returns:
            The number of work items deleted.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        conn = self._get_connection()
        cursor = conn.execute(
            "DELETE FROM work_items WHERE resolved = 1 AND resolved_at < ?",
            (self._dt_to_iso(cutoff),),
        )
        conn.commit()
        return cursor.rowcount

    # -----------------------------------------------------------------------
    # Review Outcome operations
    # -----------------------------------------------------------------------

    def create_review_outcome(self, outcome: ReviewOutcome) -> ReviewOutcome:
        """Persist a ReviewOutcome."""
        conn = self._get_connection()
        conn.execute(
            """
            INSERT INTO review_outcomes
                (id, concept_id, reviewer, action, error_type, correction_details, created_at)
            VALUES (?,?,?,?,?,?,?)
            """,
            self._review_outcome_to_row(outcome),
        )
        conn.commit()
        return outcome

    def get_review_outcomes_for_concept(
        self, concept_id: uuid.UUID
    ) -> list[ReviewOutcome]:
        """Return all ReviewOutcomes for a Concept, ordered by created_at."""
        conn = self._get_connection()
        rows = conn.execute(
            "SELECT * FROM review_outcomes WHERE concept_id = ? ORDER BY created_at ASC",
            (str(concept_id),),
        ).fetchall()
        return [self._row_to_review_outcome(r) for r in rows]

    def list_review_outcomes(self) -> list[ReviewOutcome]:
        """Return all ReviewOutcomes."""
        conn = self._get_connection()
        rows = conn.execute("SELECT * FROM review_outcomes").fetchall()
        return [self._row_to_review_outcome(r) for r in rows]

    # -----------------------------------------------------------------------
    # Search — FTS5 keyword search (semantic search deferred to Story 2.5)
    # -----------------------------------------------------------------------

    def search_semantic(
        self, query_embedding: list[float], limit: int = 10
    ) -> list[Concept]:
        """Vector similarity search via sqlite-vec cosine distance.

        Returns up to ``limit`` Concepts ranked by cosine similarity
        (most similar first). Requires embeddings to have been stored via
        create_concept or update_concept with an embedding_service configured.
        """
        serialized = sqlite_vec.serialize_float32(query_embedding)
        conn = self._get_connection()
        rows = conn.execute(
            """
            SELECT c.*
            FROM concepts c
            INNER JOIN (
                SELECT concept_id,
                       vec_distance_cosine(embedding, ?) AS distance
                FROM concept_embeddings
                ORDER BY distance ASC
                LIMIT ?
            ) AS ranked ON c.id = ranked.concept_id
            ORDER BY ranked.distance ASC
            """,
            (serialized, limit),
        ).fetchall()
        return [self._row_to_concept(r) for r in rows]

    def search_keyword(self, query: str, limit: int = 10) -> list[Concept]:
        """FTS5 keyword search on concept name and description."""
        conn = self._get_connection()
        rows = conn.execute(
            """
            SELECT c.* FROM concepts c
            JOIN concepts_fts fts ON c.id = fts.id
            WHERE concepts_fts MATCH ?
            LIMIT ?
            """,
            (query, limit),
        ).fetchall()
        return [self._row_to_concept(r) for r in rows]

    def search_by_file(self, file_path: str) -> list[Concept]:
        """Return Concepts with a CodeReference anchored to the given file path."""
        all_concepts = self.list_concepts()
        return [
            c for c in all_concepts
            if any(ref.file_path == file_path for ref in c.code_references)
        ]

    # -----------------------------------------------------------------------
    # Graph traversal
    # -----------------------------------------------------------------------

    def get_neighbors(
        self,
        concept_id: uuid.UUID,
        edge_type: Optional[str] = None,
        direction: str = "both",
    ) -> list[Concept]:
        """Return Concepts directly connected via Edges."""
        if direction not in ("outgoing", "incoming", "both"):
            raise ValueError(f"direction must be 'outgoing', 'incoming', or 'both'; got {direction!r}")
        conn = self._get_connection()
        neighbor_ids: set[str] = set()
        if direction in ("outgoing", "both"):
            sql = "SELECT target_id FROM edges WHERE source_id = ?"
            params: list[Any] = [str(concept_id)]
            if edge_type:
                sql += " AND edge_type = ?"
                params.append(edge_type)
            for row in conn.execute(sql, params).fetchall():
                neighbor_ids.add(row[0])
        if direction in ("incoming", "both"):
            sql = "SELECT source_id FROM edges WHERE target_id = ?"
            params = [str(concept_id)]
            if edge_type:
                sql += " AND edge_type = ?"
                params.append(edge_type)
            for row in conn.execute(sql, params).fetchall():
                neighbor_ids.add(row[0])
        result = []
        for nid in neighbor_ids:
            c = self.get_concept(uuid.UUID(nid))
            if c is not None:
                result.append(c)
        return result

    def traverse_graph(
        self, start_id: uuid.UUID, max_depth: int = 3
    ) -> list[Concept]:
        """BFS traversal of the graph starting from a Concept."""
        visited: set[str] = set()
        result: list[Concept] = []
        frontier = [str(start_id)]
        depth = 0
        while frontier and depth <= max_depth:
            next_frontier: list[str] = []
            for sid in frontier:
                if sid in visited:
                    continue
                visited.add(sid)
                c = self.get_concept(uuid.UUID(sid))
                if c is not None:
                    result.append(c)
                if depth < max_depth:
                    conn = self._get_connection()
                    for row in conn.execute(
                        "SELECT target_id FROM edges WHERE source_id = ?", (sid,)
                    ).fetchall():
                        tid = row[0]
                        if tid not in visited:
                            next_frontier.append(tid)
            frontier = next_frontier
            depth += 1
        return result

    # -----------------------------------------------------------------------
    # Metrics
    # -----------------------------------------------------------------------

    def get_metrics(self) -> dict[str, Any]:
        """Return aggregate counts for all entity types."""
        conn = self._get_connection()
        return {
            "concept_count": conn.execute("SELECT COUNT(*) FROM concepts").fetchone()[0],
            "edge_count": conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0],
            "work_item_count": conn.execute("SELECT COUNT(*) FROM work_items").fetchone()[0],
            "review_outcome_count": conn.execute("SELECT COUNT(*) FROM review_outcomes").fetchone()[0],
        }

    def count_covered_files(self) -> int:
        """Count distinct file paths referenced by at least one Concept.

        Uses json_each to expand the code_references JSON array in a single
        SQL query (no Python-side iteration).
        """
        conn = self._get_connection()
        row = conn.execute(
            """
            SELECT COUNT(DISTINCT json_extract(j.value, '$.file_path'))
            FROM concepts
            CROSS JOIN json_each(concepts.code_references) AS j
            """
        ).fetchone()
        return int(row[0]) if row and row[0] is not None else 0

    def count_fresh_active_concepts(self, active_days: int = 30) -> tuple[int, int]:
        """Return (fresh_count, active_count) for freshness metric computation.

        Single SQL query with a datetime comparison. active_days is applied
        server-side to avoid Python-side filtering.
        """
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=active_days)
        ).isoformat()
        conn = self._get_connection()
        row = conn.execute(
            """
            SELECT
                COUNT(*) AS active_count,
                SUM(
                    CASE
                        WHEN last_verified IS NOT NULL
                             AND last_verified > updated_at
                        THEN 1
                        ELSE 0
                    END
                ) AS fresh_count
            FROM concepts
            WHERE updated_at >= ?
            """,
            (cutoff,),
        ).fetchone()
        if row is None:
            return 0, 0
        active = int(row[0]) if row[0] is not None else 0
        fresh = int(row[1]) if row[1] is not None else 0
        return fresh, active

    def count_blast_radius_complete(self) -> tuple[int, int]:
        """Return (with_profile_count, total_count) for blast-radius completeness.

        COUNT(impact_profile) counts non-NULL rows without Python iteration.
        """
        conn = self._get_connection()
        row = conn.execute(
            "SELECT COUNT(*) AS total, COUNT(impact_profile) AS with_profile FROM concepts"
        ).fetchone()
        if row is None:
            return 0, 0
        return int(row[1]), int(row[0])

    # -----------------------------------------------------------------------
    # Bulk operations
    # -----------------------------------------------------------------------

    def rebuild_index(self) -> None:
        """Rebuild the FTS5 content table from the concepts table.

        Also re-generates all concept embeddings if an embedding_service is
        configured, ensuring the vec0 index reflects current concept descriptions.
        """
        conn = self._get_connection()
        conn.execute("INSERT INTO concepts_fts(concepts_fts) VALUES('rebuild')")
        conn.commit()
        if self._embedding_service is not None:
            rows = conn.execute("SELECT id, description FROM concepts").fetchall()
            for row in rows:
                concept_id = uuid.UUID(row["id"])
                self._upsert_embedding(concept_id, row["description"])
