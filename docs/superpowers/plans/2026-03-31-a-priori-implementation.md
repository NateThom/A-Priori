# A-Priori Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a self-constructing knowledge base that provides fast, precise context retrieval for AI agents working with codebases.

**Architecture:** Hybrid knowledge base with a thin concept graph (fast structural navigation) and rich documents (synthesized understanding). Dedicated librarian agents build and maintain knowledge autonomously. Task agents query via MCP tools. Humans manage via CLI.

**Tech Stack:** Python 3.11+, SQLite + sqlite-vec, MCP Python SDK (FastMCP), OpenAI embeddings, Click CLI, PyYAML, pytest

**Spec:** `docs/superpowers/specs/2026-03-31-a-priori-design.md`

---

## File Structure

```
apriori/
├── __init__.py
├── core/
│   ├── __init__.py
│   ├── models.py          # Concept, Edge, Document, CodeAnchor, CodeReference, QueryLog, ReviewItem
│   ├── config.py          # XDG paths, YAML config loading, workspace registry
│   └── metrics.py         # Deterministic quality gate scoring
├── storage/
│   ├── __init__.py
│   ├── interface.py       # StorageProtocol (abstract)
│   ├── sqlite.py          # SQLite + sqlite-vec implementation
│   └── schema.sql         # DDL for all tables
├── search/
│   ├── __init__.py
│   ├── semantic.py        # Embedding-based vector search
│   ├── keyword.py         # FTS5 full-text search
│   └── engine.py          # Unified search routing by mode
├── embedding/
│   ├── __init__.py
│   ├── interface.py       # EmbeddingProvider protocol
│   └── openai.py          # OpenAI text-embedding-3-small
├── graph/
│   ├── __init__.py
│   └── traversal.py       # BFS/DFS with edge-type filtering
├── librarian/
│   ├── __init__.py
│   ├── agent.py           # Librarian orchestration (bootstrap/deepen/reactive)
│   ├── priorities.py      # Demand metrics computation from query_log
│   ├── quality_gate.py    # Deterministic metric scoring + threshold enforcement
│   └── reviewer.py        # Reviewer agent (LLM-based evaluation)
├── feedback/
│   ├── __init__.py
│   └── logger.py          # Passive query/retrieval logging
├── cli/
│   ├── __init__.py
│   └── main.py            # Click CLI commands
└── mcp/
    ├── __init__.py
    └── server.py          # FastMCP server with read/write tools

tests/
├── conftest.py            # Shared fixtures (tmp db, sample data)
├── core/
│   ├── test_models.py
│   ├── test_config.py
│   └── test_metrics.py
├── storage/
│   └── test_sqlite.py
├── search/
│   ├── test_keyword.py
│   ├── test_semantic.py
│   └── test_engine.py
├── embedding/
│   └── test_openai.py
├── graph/
│   └── test_traversal.py
├── feedback/
│   └── test_logger.py
├── cli/
│   └── test_cli.py
└── mcp/
    └── test_server.py

pyproject.toml
README.md
```

---

### Task 1: Project Scaffolding

**Files:**
- Create: `pyproject.toml`
- Create: `apriori/__init__.py`
- Create: all `__init__.py` files for subpackages
- Create: `tests/conftest.py`

- [ ] **Step 1: Create pyproject.toml**

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "a-priori"
version = "0.1.0"
description = "Self-constructing knowledge base for AI agents"
requires-python = ">=3.11"
dependencies = [
    "pyyaml>=6.0",
    "sqlite-vec>=0.1.6",
    "mcp>=1.12.0",
    "openai>=1.68.0",
    "click>=8.1",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
]

[project.scripts]
apriori = "apriori.cli.main:cli"
apriori-mcp = "apriori.mcp.server:main"
```

- [ ] **Step 2: Create package structure**

Create all `__init__.py` files:

```
apriori/__init__.py
apriori/core/__init__.py
apriori/storage/__init__.py
apriori/search/__init__.py
apriori/embedding/__init__.py
apriori/graph/__init__.py
apriori/librarian/__init__.py
apriori/feedback/__init__.py
apriori/cli/__init__.py
apriori/mcp/__init__.py
tests/__init__.py (empty, not needed — pytest discovers without it)
tests/core/__init__.py (empty)
tests/storage/__init__.py (empty)
tests/search/__init__.py (empty)
tests/embedding/__init__.py (empty)
tests/graph/__init__.py (empty)
tests/feedback/__init__.py (empty)
tests/cli/__init__.py (empty)
tests/mcp/__init__.py (empty)
```

Each `__init__.py` is empty.

- [ ] **Step 3: Create tests/conftest.py with basic fixtures**

```python
import os
import sqlite3
import tempfile
from pathlib import Path

import pytest
import sqlite_vec


@pytest.fixture
def tmp_dir():
    """Provide a temporary directory that is cleaned up after the test."""
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


@pytest.fixture
def db(tmp_dir):
    """Provide a SQLite connection with sqlite-vec loaded."""
    db_path = tmp_dir / "test.db"
    conn = sqlite3.connect(str(db_path))
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    return conn
```

- [ ] **Step 4: Install dev dependencies and verify**

Run: `pip install -e ".[dev]"`
Expected: Clean install, no errors

- [ ] **Step 5: Run pytest to verify empty test suite**

Run: `pytest -v`
Expected: "no tests ran" or similar, no import errors

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml apriori/ tests/
git commit -m "feat: project scaffolding with package structure and dev tooling"
```

---

### Task 2: Core Data Models

**Files:**
- Create: `apriori/core/models.py`
- Create: `tests/core/test_models.py`

- [ ] **Step 1: Write tests for core data models**

```python
import uuid
from datetime import datetime, timezone

from apriori.core.models import (
    CodeAnchor,
    CodeReference,
    Concept,
    Document,
    Edge,
    QueryLog,
    ReviewItem,
)


def test_concept_creation():
    c = Concept(name="Auth Middleware", type="module")
    assert c.name == "Auth Middleware"
    assert c.type == "module"
    assert isinstance(c.id, uuid.UUID)
    assert c.root_id is None
    assert c.code_anchors == []
    assert isinstance(c.created_at, datetime)
    assert isinstance(c.updated_at, datetime)


def test_concept_with_code_anchors():
    anchor = CodeAnchor(
        symbol="validate_token",
        file_path="src/auth/validate.py",
        content_hash="sha256:abc123",
        line_range=(10, 25),
    )
    c = Concept(
        name="Token Validation",
        type="pattern",
        code_anchors=[anchor],
    )
    assert len(c.code_anchors) == 1
    assert c.code_anchors[0].symbol == "validate_token"


def test_edge_creation():
    src = uuid.uuid4()
    tgt = uuid.uuid4()
    e = Edge(source=src, target=tgt, edge_type="depends-on")
    assert e.source == src
    assert e.target == tgt
    assert e.edge_type == "depends-on"
    assert e.metadata is None


def test_edge_valid_types():
    valid_types = ["depends-on", "implements", "owns", "extends", "relates-to", "supersedes"]
    src, tgt = uuid.uuid4(), uuid.uuid4()
    for t in valid_types:
        e = Edge(source=src, target=tgt, edge_type=t)
        assert e.edge_type == t


def test_edge_invalid_type():
    import pytest
    with pytest.raises(ValueError):
        Edge(source=uuid.uuid4(), target=uuid.uuid4(), edge_type="invalid-type")


def test_document_creation():
    concept_id = uuid.uuid4()
    d = Document(
        concept_id=concept_id,
        content="# Auth\nHandles token validation.",
        summary="Token validation for auth middleware",
    )
    assert d.concept_id == concept_id
    assert d.confidence == 1.0
    assert d.staleness_score == 0.0
    assert d.code_references == []


def test_document_with_code_references():
    ref = CodeReference(
        symbol="validate_token",
        file_path="src/auth/validate.py",
        content_hash="sha256:abc123",
        line_range=(10, 25),
    )
    d = Document(
        concept_id=uuid.uuid4(),
        content="Explains validation",
        summary="Validation overview",
        code_references=[ref],
    )
    assert len(d.code_references) == 1


def test_query_log_creation():
    ql = QueryLog(
        query="how does auth work",
        mode="semantic",
        results=[uuid.uuid4()],
    )
    assert ql.query == "how does auth work"
    assert ql.followed_up == []


def test_review_item_creation():
    ri = ReviewItem(
        type="gap",
        context="Searched for rate limiting, found nothing in tracked roots",
        suggested_action="Add rate limiting root or document",
    )
    assert ri.type == "gap"
    assert ri.resolved is False
    assert ri.concept_id is None


def test_review_item_valid_types():
    valid = ["gap", "ambiguous_intent", "conflicting_pattern",
             "domain_knowledge", "stale_unresolvable", "root_recommendation"]
    for t in valid:
        ri = ReviewItem(type=t, context="test", suggested_action="test")
        assert ri.type == t


def test_review_item_invalid_type():
    import pytest
    with pytest.raises(ValueError):
        ReviewItem(type="bad_type", context="test", suggested_action="test")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/core/test_models.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'apriori.core.models'`

- [ ] **Step 3: Implement core data models**

```python
"""Core data models for A-Priori knowledge base."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

VALID_EDGE_TYPES = frozenset(
    ["depends-on", "implements", "owns", "extends", "relates-to", "supersedes"]
)

VALID_REVIEW_TYPES = frozenset(
    ["gap", "ambiguous_intent", "conflicting_pattern",
     "domain_knowledge", "stale_unresolvable", "root_recommendation"]
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _new_id() -> uuid.UUID:
    return uuid.uuid4()


@dataclass
class CodeAnchor:
    symbol: str
    file_path: str
    content_hash: str
    line_range: tuple[int, int] | None = None


@dataclass
class CodeReference:
    symbol: str
    file_path: str
    content_hash: str
    line_range: tuple[int, int] | None = None


@dataclass
class Concept:
    name: str
    type: str
    id: uuid.UUID = field(default_factory=_new_id)
    root_id: uuid.UUID | None = None
    code_anchors: list[CodeAnchor] = field(default_factory=list)
    created_at: datetime = field(default_factory=_utcnow)
    updated_at: datetime = field(default_factory=_utcnow)


@dataclass
class Edge:
    source: uuid.UUID
    target: uuid.UUID
    edge_type: str
    id: uuid.UUID = field(default_factory=_new_id)
    metadata: dict | None = None
    created_at: datetime = field(default_factory=_utcnow)

    def __post_init__(self):
        if self.edge_type not in VALID_EDGE_TYPES:
            raise ValueError(
                f"Invalid edge type '{self.edge_type}'. Must be one of: {sorted(VALID_EDGE_TYPES)}"
            )


@dataclass
class Document:
    concept_id: uuid.UUID
    content: str
    summary: str
    id: uuid.UUID = field(default_factory=_new_id)
    code_references: list[CodeReference] = field(default_factory=list)
    embedding: list[float] | None = None
    confidence: float = 1.0
    staleness_score: float = 0.0
    created_at: datetime = field(default_factory=_utcnow)
    updated_at: datetime = field(default_factory=_utcnow)


@dataclass
class QueryLog:
    query: str
    mode: str
    results: list[uuid.UUID] = field(default_factory=list)
    followed_up: list[uuid.UUID] = field(default_factory=list)
    id: uuid.UUID = field(default_factory=_new_id)
    timestamp: datetime = field(default_factory=_utcnow)


@dataclass
class ReviewItem:
    type: str
    context: str
    suggested_action: str
    id: uuid.UUID = field(default_factory=_new_id)
    concept_id: uuid.UUID | None = None
    resolved: bool = False
    created_at: datetime = field(default_factory=_utcnow)

    def __post_init__(self):
        if self.type not in VALID_REVIEW_TYPES:
            raise ValueError(
                f"Invalid review type '{self.type}'. Must be one of: {sorted(VALID_REVIEW_TYPES)}"
            )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/core/test_models.py -v`
Expected: All 11 tests PASS

- [ ] **Step 5: Commit**

```bash
git add apriori/core/models.py tests/core/test_models.py
git commit -m "feat: core data models for concepts, edges, documents, and feedback"
```

---

### Task 3: Configuration System

**Files:**
- Create: `apriori/core/config.py`
- Create: `tests/core/test_config.py`

- [ ] **Step 1: Write tests for configuration**

```python
import os
from pathlib import Path

from apriori.core.config import (
    AppConfig,
    WorkspaceConfig,
    get_config_dir,
    get_data_dir,
    load_app_config,
    load_workspace_config,
    save_workspace_config,
)


def test_get_config_dir_default(monkeypatch):
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setenv("HOME", "/home/testuser")
    assert get_config_dir() == Path("/home/testuser/.config/a-priori")


def test_get_config_dir_xdg(monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", "/custom/config")
    assert get_config_dir() == Path("/custom/config/a-priori")


def test_get_data_dir_default(monkeypatch):
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.setenv("HOME", "/home/testuser")
    assert get_data_dir() == Path("/home/testuser/.local/share/a-priori")


def test_get_data_dir_xdg(monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", "/custom/data")
    assert get_data_dir() == Path("/custom/data/a-priori")


def test_load_app_config_defaults():
    config = load_app_config(config_path=None)
    assert config.embedding.provider == "openai"
    assert config.embedding.model == "text-embedding-3-small"
    assert config.quality_gate.min_conciseness_ratio == 0.6
    assert config.search.default_limit == 10
    assert config.librarian.review_queue_cap == 10


def test_load_app_config_from_file(tmp_dir):
    config_file = tmp_dir / "config.yaml"
    config_file.write_text(
        "embedding:\n  provider: ollama\n  model: nomic-embed-text\n"
    )
    config = load_app_config(config_path=config_file)
    assert config.embedding.provider == "ollama"
    assert config.embedding.model == "nomic-embed-text"
    # Other defaults still apply
    assert config.quality_gate.min_conciseness_ratio == 0.6


def test_load_app_config_partial_override(tmp_dir):
    config_file = tmp_dir / "config.yaml"
    config_file.write_text("search:\n  default_limit: 25\n")
    config = load_app_config(config_path=config_file)
    assert config.search.default_limit == 25
    assert config.embedding.provider == "openai"


def test_workspace_config_roundtrip(tmp_dir):
    ws = WorkspaceConfig(
        name="mywork",
        path=Path("/home/user/work"),
        roots=[
            {"path": "/home/user/work/api", "added": "2026-03-31"},
            {"path": "/home/user/work/auth", "added": "2026-03-31"},
        ],
    )
    ws_file = tmp_dir / "workspace.yaml"
    save_workspace_config(ws, ws_file)
    loaded = load_workspace_config(ws_file)
    assert loaded.name == "mywork"
    assert str(loaded.path) == "/home/user/work"
    assert len(loaded.roots) == 2
    assert loaded.roots[0]["path"] == "/home/user/work/api"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/core/test_config.py -v`
Expected: FAIL — import errors

- [ ] **Step 3: Implement configuration system**

```python
"""Configuration loading with XDG Base Directory support."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml


def get_config_dir() -> Path:
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        return Path(xdg) / "a-priori"
    return Path.home() / ".config" / "a-priori"


def get_data_dir() -> Path:
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        return Path(xdg) / "a-priori"
    return Path.home() / ".local" / "share" / "a-priori"


@dataclass
class EmbeddingConfig:
    provider: str = "openai"
    model: str = "text-embedding-3-small"


@dataclass
class QualityGateConfig:
    min_conciseness_ratio: float = 0.6
    min_code_grounding_score: float = 0.5
    min_assertion_density: float = 0.4
    max_duplication_similarity: float = 0.85


@dataclass
class LibrarianConfig:
    review_queue_cap: int = 10
    bootstrap_depth: str = "shallow"


@dataclass
class SearchConfig:
    default_limit: int = 10
    semantic_weight: float = 0.7
    keyword_weight: float = 0.3


@dataclass
class AppConfig:
    embedding: EmbeddingConfig = field(default_factory=EmbeddingConfig)
    quality_gate: QualityGateConfig = field(default_factory=QualityGateConfig)
    librarian: LibrarianConfig = field(default_factory=LibrarianConfig)
    search: SearchConfig = field(default_factory=SearchConfig)


@dataclass
class WorkspaceConfig:
    name: str
    path: Path
    roots: list[dict] = field(default_factory=list)


def _merge_dataclass(dc_instance, overrides: dict):
    """Merge a dict of overrides into a dataclass instance."""
    for key, value in overrides.items():
        if hasattr(dc_instance, key):
            setattr(dc_instance, key, value)


def load_app_config(config_path: Path | None = None) -> AppConfig:
    config = AppConfig()
    path = config_path or (get_config_dir() / "config.yaml")
    if path.exists():
        with open(path) as f:
            raw = yaml.safe_load(f) or {}
        if "embedding" in raw:
            _merge_dataclass(config.embedding, raw["embedding"])
        if "quality_gate" in raw:
            _merge_dataclass(config.quality_gate, raw["quality_gate"])
        if "librarian" in raw:
            _merge_dataclass(config.librarian, raw["librarian"])
        if "search" in raw:
            _merge_dataclass(config.search, raw["search"])
    return config


def load_workspace_config(path: Path) -> WorkspaceConfig:
    with open(path) as f:
        raw = yaml.safe_load(f)
    return WorkspaceConfig(
        name=raw["name"],
        path=Path(raw["path"]),
        roots=raw.get("roots", []),
    )


def save_workspace_config(ws: WorkspaceConfig, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "name": ws.name,
        "path": str(ws.path),
        "roots": ws.roots,
    }
    with open(path, "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/core/test_config.py -v`
Expected: All 8 tests PASS

- [ ] **Step 5: Commit**

```bash
git add apriori/core/config.py tests/core/test_config.py
git commit -m "feat: configuration system with XDG paths and YAML loading"
```

---

### Task 4: Storage Interface

**Files:**
- Create: `apriori/storage/interface.py`

- [ ] **Step 1: Define the storage protocol**

```python
"""Abstract storage interface for A-Priori knowledge base."""

from __future__ import annotations

import uuid
from typing import Protocol, runtime_checkable

from apriori.core.models import (
    CodeAnchor,
    CodeReference,
    Concept,
    Document,
    Edge,
    QueryLog,
    ReviewItem,
)


@runtime_checkable
class StorageProtocol(Protocol):
    """All storage implementations must satisfy this interface."""

    # --- Concepts ---
    def create_concept(self, concept: Concept) -> Concept: ...
    def get_concept(self, id_or_name: uuid.UUID | str) -> Concept | None: ...
    def update_concept(self, concept: Concept) -> Concept: ...
    def delete_concept(self, id: uuid.UUID) -> None: ...
    def list_concepts(self) -> list[Concept]: ...
    def search_concepts_by_name(self, query: str) -> list[Concept]: ...

    # --- Edges ---
    def create_edge(self, edge: Edge) -> Edge: ...
    def get_edges(
        self,
        concept_id: uuid.UUID,
        direction: str = "both",
        edge_type: str | None = None,
    ) -> list[Edge]: ...
    def update_edge(self, edge: Edge) -> Edge: ...
    def delete_edge(self, id: uuid.UUID) -> None: ...

    # --- Documents ---
    def create_document(self, document: Document) -> Document: ...
    def get_document(self, id: uuid.UUID) -> Document | None: ...
    def get_documents_for_concept(self, concept_id: uuid.UUID) -> list[Document]: ...
    def update_document(self, document: Document) -> Document: ...
    def delete_document(self, id: uuid.UUID) -> None: ...

    # --- Query Log ---
    def log_query(self, entry: QueryLog) -> None: ...
    def log_followup(self, query_id: uuid.UUID, concept_id: uuid.UUID) -> None: ...
    def get_query_logs(self, limit: int = 100) -> list[QueryLog]: ...

    # --- Review Queue ---
    def create_review_item(self, item: ReviewItem) -> ReviewItem: ...
    def get_review_items(self, resolved: bool = False) -> list[ReviewItem]: ...
    def resolve_review_item(self, id: uuid.UUID) -> None: ...
    def count_review_items(self, resolved: bool = False) -> int: ...

    # --- Roots ---
    def add_root(self, path: str, name: str) -> uuid.UUID: ...
    def get_roots(self) -> list[dict]: ...
    def remove_root(self, id: uuid.UUID) -> None: ...
```

- [ ] **Step 2: Commit**

```bash
git add apriori/storage/interface.py
git commit -m "feat: storage protocol interface for pluggable backends"
```

---

### Task 5: SQLite Schema and Implementation

**Files:**
- Create: `apriori/storage/schema.sql`
- Create: `apriori/storage/sqlite.py`
- Create: `tests/storage/test_sqlite.py`

- [ ] **Step 1: Write the SQL schema**

```sql
-- A-Priori SQLite Schema

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

INSERT OR IGNORE INTO meta (key, value) VALUES ('schema_version', '1');

CREATE TABLE IF NOT EXISTS roots (
    id TEXT PRIMARY KEY,
    path TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    added_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE IF NOT EXISTS concepts (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    type TEXT NOT NULL,
    root_id TEXT REFERENCES roots(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_concepts_name ON concepts(name);
CREATE INDEX IF NOT EXISTS idx_concepts_root ON concepts(root_id);

CREATE TABLE IF NOT EXISTS code_anchors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    concept_id TEXT NOT NULL REFERENCES concepts(id) ON DELETE CASCADE,
    symbol TEXT NOT NULL,
    file_path TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    line_range_start INTEGER,
    line_range_end INTEGER
);

CREATE INDEX IF NOT EXISTS idx_anchors_concept ON code_anchors(concept_id);
CREATE INDEX IF NOT EXISTS idx_anchors_file ON code_anchors(file_path);
CREATE INDEX IF NOT EXISTS idx_anchors_symbol ON code_anchors(symbol);

CREATE TABLE IF NOT EXISTS edges (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL REFERENCES concepts(id) ON DELETE CASCADE,
    target TEXT NOT NULL REFERENCES concepts(id) ON DELETE CASCADE,
    edge_type TEXT NOT NULL,
    metadata TEXT,  -- JSON
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source);
CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target);
CREATE INDEX IF NOT EXISTS idx_edges_type ON edges(edge_type);

CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,
    vec_rowid INTEGER UNIQUE,  -- stable rowid for FTS5 and vec0 joins
    concept_id TEXT NOT NULL REFERENCES concepts(id) ON DELETE CASCADE,
    content TEXT NOT NULL,
    summary TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 1.0,
    staleness_score REAL NOT NULL DEFAULT 0.0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_documents_concept ON documents(concept_id);

CREATE TABLE IF NOT EXISTS code_references (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    symbol TEXT NOT NULL,
    file_path TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    line_range_start INTEGER,
    line_range_end INTEGER
);

CREATE INDEX IF NOT EXISTS idx_refs_document ON code_references(document_id);
CREATE INDEX IF NOT EXISTS idx_refs_file ON code_references(file_path);

CREATE TABLE IF NOT EXISTS query_log (
    id TEXT PRIMARY KEY,
    query TEXT NOT NULL,
    mode TEXT NOT NULL,
    results TEXT NOT NULL,  -- JSON array of concept IDs
    followed_up TEXT NOT NULL DEFAULT '[]',  -- JSON array of concept IDs
    timestamp TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS review_queue (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    context TEXT NOT NULL,
    suggested_action TEXT NOT NULL,
    concept_id TEXT REFERENCES concepts(id) ON DELETE SET NULL,
    resolved INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_review_resolved ON review_queue(resolved);
```

- [ ] **Step 2: Write storage tests**

```python
import uuid

import pytest

from apriori.core.models import (
    CodeAnchor,
    CodeReference,
    Concept,
    Document,
    Edge,
    QueryLog,
    ReviewItem,
)
from apriori.storage.sqlite import SQLiteStorage


@pytest.fixture
def store(tmp_dir):
    return SQLiteStorage(tmp_dir / "test.db")


class TestConcepts:
    def test_create_and_get_by_id(self, store):
        c = Concept(name="Auth", type="module")
        created = store.create_concept(c)
        fetched = store.get_concept(created.id)
        assert fetched is not None
        assert fetched.name == "Auth"
        assert fetched.type == "module"

    def test_get_by_name(self, store):
        c = Concept(name="Auth", type="module")
        store.create_concept(c)
        fetched = store.get_concept("Auth")
        assert fetched is not None
        assert fetched.name == "Auth"

    def test_get_nonexistent_returns_none(self, store):
        assert store.get_concept(uuid.uuid4()) is None
        assert store.get_concept("nonexistent") is None

    def test_create_with_code_anchors(self, store):
        anchor = CodeAnchor(
            symbol="validate", file_path="src/auth.py",
            content_hash="sha256:abc", line_range=(10, 20),
        )
        c = Concept(name="Validation", type="pattern", code_anchors=[anchor])
        store.create_concept(c)
        fetched = store.get_concept("Validation")
        assert len(fetched.code_anchors) == 1
        assert fetched.code_anchors[0].symbol == "validate"
        assert fetched.code_anchors[0].line_range == (10, 20)

    def test_update_concept(self, store):
        c = Concept(name="Auth", type="module")
        created = store.create_concept(c)
        created.type = "subsystem"
        updated = store.update_concept(created)
        assert updated.type == "subsystem"
        fetched = store.get_concept(created.id)
        assert fetched.type == "subsystem"

    def test_delete_concept(self, store):
        c = Concept(name="Auth", type="module")
        created = store.create_concept(c)
        store.delete_concept(created.id)
        assert store.get_concept(created.id) is None

    def test_list_concepts(self, store):
        store.create_concept(Concept(name="A", type="module"))
        store.create_concept(Concept(name="B", type="pattern"))
        concepts = store.list_concepts()
        assert len(concepts) == 2

    def test_search_by_name(self, store):
        store.create_concept(Concept(name="Auth Middleware", type="module"))
        store.create_concept(Concept(name="Payment Auth", type="pattern"))
        store.create_concept(Concept(name="Billing", type="module"))
        results = store.search_concepts_by_name("auth")
        assert len(results) == 2

    def test_duplicate_name_raises(self, store):
        store.create_concept(Concept(name="Auth", type="module"))
        with pytest.raises(Exception):
            store.create_concept(Concept(name="Auth", type="pattern"))


class TestEdges:
    def test_create_and_get(self, store):
        c1 = store.create_concept(Concept(name="A", type="module"))
        c2 = store.create_concept(Concept(name="B", type="module"))
        e = Edge(source=c1.id, target=c2.id, edge_type="depends-on")
        store.create_edge(e)
        edges = store.get_edges(c1.id, direction="outgoing")
        assert len(edges) == 1
        assert edges[0].edge_type == "depends-on"

    def test_get_edges_incoming(self, store):
        c1 = store.create_concept(Concept(name="A", type="module"))
        c2 = store.create_concept(Concept(name="B", type="module"))
        store.create_edge(Edge(source=c1.id, target=c2.id, edge_type="depends-on"))
        edges = store.get_edges(c2.id, direction="incoming")
        assert len(edges) == 1

    def test_get_edges_both(self, store):
        c1 = store.create_concept(Concept(name="A", type="module"))
        c2 = store.create_concept(Concept(name="B", type="module"))
        c3 = store.create_concept(Concept(name="C", type="module"))
        store.create_edge(Edge(source=c1.id, target=c2.id, edge_type="depends-on"))
        store.create_edge(Edge(source=c3.id, target=c2.id, edge_type="owns"))
        edges = store.get_edges(c2.id, direction="both")
        assert len(edges) == 2

    def test_filter_by_edge_type(self, store):
        c1 = store.create_concept(Concept(name="A", type="module"))
        c2 = store.create_concept(Concept(name="B", type="module"))
        store.create_edge(Edge(source=c1.id, target=c2.id, edge_type="depends-on"))
        store.create_edge(Edge(source=c1.id, target=c2.id, edge_type="owns"))
        edges = store.get_edges(c1.id, direction="outgoing", edge_type="depends-on")
        assert len(edges) == 1

    def test_delete_edge(self, store):
        c1 = store.create_concept(Concept(name="A", type="module"))
        c2 = store.create_concept(Concept(name="B", type="module"))
        e = Edge(source=c1.id, target=c2.id, edge_type="depends-on")
        created = store.create_edge(e)
        store.delete_edge(created.id)
        assert store.get_edges(c1.id) == []


class TestDocuments:
    def test_create_and_get(self, store):
        c = store.create_concept(Concept(name="Auth", type="module"))
        d = Document(concept_id=c.id, content="# Auth\nDetails.", summary="Auth overview")
        created = store.create_document(d)
        fetched = store.get_document(created.id)
        assert fetched is not None
        assert fetched.content == "# Auth\nDetails."

    def test_get_documents_for_concept(self, store):
        c = store.create_concept(Concept(name="Auth", type="module"))
        store.create_document(Document(concept_id=c.id, content="Overview", summary="Overview"))
        store.create_document(Document(concept_id=c.id, content="Deep dive", summary="Deep dive"))
        docs = store.get_documents_for_concept(c.id)
        assert len(docs) == 2

    def test_document_with_code_references(self, store):
        c = store.create_concept(Concept(name="Auth", type="module"))
        ref = CodeReference(
            symbol="validate", file_path="src/auth.py",
            content_hash="sha256:abc", line_range=(5, 15),
        )
        d = Document(
            concept_id=c.id, content="Details", summary="Sum",
            code_references=[ref],
        )
        store.create_document(d)
        fetched = store.get_documents_for_concept(c.id)[0]
        assert len(fetched.code_references) == 1
        assert fetched.code_references[0].symbol == "validate"

    def test_update_document(self, store):
        c = store.create_concept(Concept(name="Auth", type="module"))
        d = Document(concept_id=c.id, content="Old", summary="Old sum")
        created = store.create_document(d)
        created.content = "Updated content"
        created.summary = "Updated summary"
        store.update_document(created)
        fetched = store.get_document(created.id)
        assert fetched.content == "Updated content"

    def test_delete_document(self, store):
        c = store.create_concept(Concept(name="Auth", type="module"))
        d = Document(concept_id=c.id, content="Content", summary="Sum")
        created = store.create_document(d)
        store.delete_document(created.id)
        assert store.get_document(created.id) is None


class TestQueryLog:
    def test_log_and_retrieve(self, store):
        ql = QueryLog(query="auth", mode="keyword", results=[uuid.uuid4()])
        store.log_query(ql)
        logs = store.get_query_logs(limit=10)
        assert len(logs) == 1
        assert logs[0].query == "auth"

    def test_log_followup(self, store):
        concept_id = uuid.uuid4()
        ql = QueryLog(query="auth", mode="keyword", results=[concept_id])
        store.log_query(ql)
        store.log_followup(ql.id, concept_id)
        logs = store.get_query_logs()
        assert concept_id in logs[0].followed_up


class TestReviewQueue:
    def test_create_and_list(self, store):
        ri = ReviewItem(type="gap", context="No rate limiting", suggested_action="Add root")
        store.create_review_item(ri)
        items = store.get_review_items()
        assert len(items) == 1
        assert items[0].type == "gap"

    def test_resolve_item(self, store):
        ri = ReviewItem(type="gap", context="test", suggested_action="test")
        created = store.create_review_item(ri)
        store.resolve_review_item(created.id)
        assert store.get_review_items(resolved=False) == []
        assert len(store.get_review_items(resolved=True)) == 1

    def test_count(self, store):
        store.create_review_item(ReviewItem(type="gap", context="a", suggested_action="a"))
        store.create_review_item(ReviewItem(type="gap", context="b", suggested_action="b"))
        assert store.count_review_items() == 2


class TestRoots:
    def test_add_and_list(self, store):
        root_id = store.add_root("/home/user/work/api", "api")
        roots = store.get_roots()
        assert len(roots) == 1
        assert roots[0]["path"] == "/home/user/work/api"
        assert roots[0]["name"] == "api"

    def test_remove_root(self, store):
        root_id = store.add_root("/home/user/work/api", "api")
        store.remove_root(root_id)
        assert store.get_roots() == []
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/storage/test_sqlite.py -v`
Expected: FAIL — import errors

- [ ] **Step 4: Implement SQLiteStorage**

```python
"""SQLite storage implementation with sqlite-vec support."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from importlib.resources import files
from pathlib import Path
from struct import pack

import sqlite_vec

from apriori.core.models import (
    CodeAnchor,
    CodeReference,
    Concept,
    Document,
    Edge,
    QueryLog,
    ReviewItem,
)


def _serialize_f32(vector: list[float]) -> bytes:
    return pack("%sf" % len(vector), *vector)


class SQLiteStorage:
    def __init__(self, db_path: Path):
        self._db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path))
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.row_factory = sqlite3.Row
        self._conn.enable_load_extension(True)
        sqlite_vec.load(self._conn)
        self._conn.enable_load_extension(False)
        self._init_schema()

    def _init_schema(self):
        schema_path = Path(__file__).parent / "schema.sql"
        with open(schema_path) as f:
            self._conn.executescript(f.read())
        # Create vector table for document embeddings (1536 dims for text-embedding-3-small)
        self._conn.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS vec_documents USING vec0(embedding float[1536])"
        )
        # Create FTS5 table for keyword search
        self._conn.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS fts_documents USING fts5(concept_name, summary, content)"
        )
        self._conn.commit()

    def close(self):
        self._conn.close()

    # --- Concepts ---

    def create_concept(self, concept: Concept) -> Concept:
        self._conn.execute(
            "INSERT INTO concepts (id, name, type, root_id, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (str(concept.id), concept.name, concept.type,
             str(concept.root_id) if concept.root_id else None,
             concept.created_at.isoformat(), concept.updated_at.isoformat()),
        )
        for anchor in concept.code_anchors:
            self._conn.execute(
                "INSERT INTO code_anchors (concept_id, symbol, file_path, content_hash, line_range_start, line_range_end) VALUES (?, ?, ?, ?, ?, ?)",
                (str(concept.id), anchor.symbol, anchor.file_path, anchor.content_hash,
                 anchor.line_range[0] if anchor.line_range else None,
                 anchor.line_range[1] if anchor.line_range else None),
            )
        self._conn.commit()
        return concept

    def get_concept(self, id_or_name: uuid.UUID | str) -> Concept | None:
        if isinstance(id_or_name, uuid.UUID):
            row = self._conn.execute(
                "SELECT * FROM concepts WHERE id = ?", (str(id_or_name),)
            ).fetchone()
        else:
            row = self._conn.execute(
                "SELECT * FROM concepts WHERE name = ?", (id_or_name,)
            ).fetchone()
        if not row:
            return None
        return self._row_to_concept(row)

    def update_concept(self, concept: Concept) -> Concept:
        concept.updated_at = datetime.now(timezone.utc)
        self._conn.execute(
            "UPDATE concepts SET name=?, type=?, root_id=?, updated_at=? WHERE id=?",
            (concept.name, concept.type,
             str(concept.root_id) if concept.root_id else None,
             concept.updated_at.isoformat(), str(concept.id)),
        )
        # Replace code anchors
        self._conn.execute("DELETE FROM code_anchors WHERE concept_id=?", (str(concept.id),))
        for anchor in concept.code_anchors:
            self._conn.execute(
                "INSERT INTO code_anchors (concept_id, symbol, file_path, content_hash, line_range_start, line_range_end) VALUES (?, ?, ?, ?, ?, ?)",
                (str(concept.id), anchor.symbol, anchor.file_path, anchor.content_hash,
                 anchor.line_range[0] if anchor.line_range else None,
                 anchor.line_range[1] if anchor.line_range else None),
            )
        self._conn.commit()
        return concept

    def delete_concept(self, id: uuid.UUID) -> None:
        self._conn.execute("DELETE FROM concepts WHERE id=?", (str(id),))
        self._conn.commit()

    def list_concepts(self) -> list[Concept]:
        rows = self._conn.execute("SELECT * FROM concepts ORDER BY name").fetchall()
        return [self._row_to_concept(r) for r in rows]

    def search_concepts_by_name(self, query: str) -> list[Concept]:
        rows = self._conn.execute(
            "SELECT * FROM concepts WHERE name LIKE ? ORDER BY name",
            (f"%{query}%",),
        ).fetchall()
        return [self._row_to_concept(r) for r in rows]

    def _row_to_concept(self, row: sqlite3.Row) -> Concept:
        cid = row["id"]
        anchor_rows = self._conn.execute(
            "SELECT * FROM code_anchors WHERE concept_id=?", (cid,)
        ).fetchall()
        anchors = [
            CodeAnchor(
                symbol=a["symbol"],
                file_path=a["file_path"],
                content_hash=a["content_hash"],
                line_range=(a["line_range_start"], a["line_range_end"])
                if a["line_range_start"] is not None else None,
            )
            for a in anchor_rows
        ]
        return Concept(
            id=uuid.UUID(cid),
            name=row["name"],
            type=row["type"],
            root_id=uuid.UUID(row["root_id"]) if row["root_id"] else None,
            code_anchors=anchors,
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    # --- Edges ---

    def create_edge(self, edge: Edge) -> Edge:
        self._conn.execute(
            "INSERT INTO edges (id, source, target, edge_type, metadata, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (str(edge.id), str(edge.source), str(edge.target), edge.edge_type,
             json.dumps(edge.metadata) if edge.metadata else None,
             edge.created_at.isoformat()),
        )
        self._conn.commit()
        return edge

    def get_edges(
        self,
        concept_id: uuid.UUID,
        direction: str = "both",
        edge_type: str | None = None,
    ) -> list[Edge]:
        cid = str(concept_id)
        if direction == "outgoing":
            sql = "SELECT * FROM edges WHERE source=?"
            params: list = [cid]
        elif direction == "incoming":
            sql = "SELECT * FROM edges WHERE target=?"
            params = [cid]
        else:
            sql = "SELECT * FROM edges WHERE source=? OR target=?"
            params = [cid, cid]
        if edge_type:
            sql += " AND edge_type=?"
            params.append(edge_type)
        rows = self._conn.execute(sql, params).fetchall()
        return [self._row_to_edge(r) for r in rows]

    def update_edge(self, edge: Edge) -> Edge:
        self._conn.execute(
            "UPDATE edges SET source=?, target=?, edge_type=?, metadata=? WHERE id=?",
            (str(edge.source), str(edge.target), edge.edge_type,
             json.dumps(edge.metadata) if edge.metadata else None,
             str(edge.id)),
        )
        self._conn.commit()
        return edge

    def delete_edge(self, id: uuid.UUID) -> None:
        self._conn.execute("DELETE FROM edges WHERE id=?", (str(id),))
        self._conn.commit()

    def _row_to_edge(self, row: sqlite3.Row) -> Edge:
        return Edge(
            id=uuid.UUID(row["id"]),
            source=uuid.UUID(row["source"]),
            target=uuid.UUID(row["target"]),
            edge_type=row["edge_type"],
            metadata=json.loads(row["metadata"]) if row["metadata"] else None,
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    # --- Documents ---

    def create_document(self, document: Document) -> Document:
        # Get a stable integer rowid for FTS5/vec0 virtual table joins
        cursor = self._conn.execute(
            "INSERT INTO documents (id, concept_id, content, summary, confidence, staleness_score, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (str(document.id), str(document.concept_id), document.content,
             document.summary, document.confidence, document.staleness_score,
             document.created_at.isoformat(), document.updated_at.isoformat()),
        )
        vec_rowid = cursor.lastrowid
        self._conn.execute(
            "UPDATE documents SET vec_rowid=? WHERE id=?",
            (vec_rowid, str(document.id)),
        )
        for ref in document.code_references:
            self._conn.execute(
                "INSERT INTO code_references (document_id, symbol, file_path, content_hash, line_range_start, line_range_end) VALUES (?, ?, ?, ?, ?, ?)",
                (str(document.id), ref.symbol, ref.file_path, ref.content_hash,
                 ref.line_range[0] if ref.line_range else None,
                 ref.line_range[1] if ref.line_range else None),
            )
        # Index in FTS using the stable rowid
        concept = self.get_concept(document.concept_id)
        concept_name = concept.name if concept else ""
        self._conn.execute(
            "INSERT INTO fts_documents (rowid, concept_name, summary, content) VALUES (?, ?, ?, ?)",
            (vec_rowid, concept_name, document.summary, document.content),
        )
        # Index embedding if present
        if document.embedding:
            self._conn.execute(
                "INSERT INTO vec_documents (rowid, embedding) VALUES (?, ?)",
                (vec_rowid, _serialize_f32(document.embedding)),
            )
        self._conn.commit()
        return document

    def get_document(self, id: uuid.UUID) -> Document | None:
        row = self._conn.execute(
            "SELECT * FROM documents WHERE id=?", (str(id),)
        ).fetchone()
        if not row:
            return None
        return self._row_to_document(row)

    def get_documents_for_concept(self, concept_id: uuid.UUID) -> list[Document]:
        rows = self._conn.execute(
            "SELECT * FROM documents WHERE concept_id=?", (str(concept_id),)
        ).fetchall()
        return [self._row_to_document(r) for r in rows]

    def update_document(self, document: Document) -> Document:
        document.updated_at = datetime.now(timezone.utc)
        self._conn.execute(
            "UPDATE documents SET content=?, summary=?, confidence=?, staleness_score=?, updated_at=? WHERE id=?",
            (document.content, document.summary, document.confidence,
             document.staleness_score, document.updated_at.isoformat(), str(document.id)),
        )
        # Replace code references
        self._conn.execute("DELETE FROM code_references WHERE document_id=?", (str(document.id),))
        for ref in document.code_references:
            self._conn.execute(
                "INSERT INTO code_references (document_id, symbol, file_path, content_hash, line_range_start, line_range_end) VALUES (?, ?, ?, ?, ?, ?)",
                (str(document.id), ref.symbol, ref.file_path, ref.content_hash,
                 ref.line_range[0] if ref.line_range else None,
                 ref.line_range[1] if ref.line_range else None),
            )
        self._conn.commit()
        return document

    def delete_document(self, id: uuid.UUID) -> None:
        self._conn.execute("DELETE FROM documents WHERE id=?", (str(id),))
        self._conn.commit()

    def _row_to_document(self, row: sqlite3.Row) -> Document:
        did = row["id"]
        ref_rows = self._conn.execute(
            "SELECT * FROM code_references WHERE document_id=?", (did,)
        ).fetchall()
        refs = [
            CodeReference(
                symbol=r["symbol"],
                file_path=r["file_path"],
                content_hash=r["content_hash"],
                line_range=(r["line_range_start"], r["line_range_end"])
                if r["line_range_start"] is not None else None,
            )
            for r in ref_rows
        ]
        return Document(
            id=uuid.UUID(did),
            concept_id=uuid.UUID(row["concept_id"]),
            content=row["content"],
            summary=row["summary"],
            confidence=row["confidence"],
            staleness_score=row["staleness_score"],
            code_references=refs,
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    # --- Query Log ---

    def log_query(self, entry: QueryLog) -> None:
        self._conn.execute(
            "INSERT INTO query_log (id, query, mode, results, followed_up, timestamp) VALUES (?, ?, ?, ?, ?, ?)",
            (str(entry.id), entry.query, entry.mode,
             json.dumps([str(r) for r in entry.results]),
             json.dumps([str(r) for r in entry.followed_up]),
             entry.timestamp.isoformat()),
        )
        self._conn.commit()

    def log_followup(self, query_id: uuid.UUID, concept_id: uuid.UUID) -> None:
        row = self._conn.execute(
            "SELECT followed_up FROM query_log WHERE id=?", (str(query_id),)
        ).fetchone()
        if row:
            followed = json.loads(row["followed_up"])
            followed.append(str(concept_id))
            self._conn.execute(
                "UPDATE query_log SET followed_up=? WHERE id=?",
                (json.dumps(followed), str(query_id)),
            )
            self._conn.commit()

    def get_query_logs(self, limit: int = 100) -> list[QueryLog]:
        rows = self._conn.execute(
            "SELECT * FROM query_log ORDER BY timestamp DESC LIMIT ?", (limit,)
        ).fetchall()
        return [
            QueryLog(
                id=uuid.UUID(r["id"]),
                query=r["query"],
                mode=r["mode"],
                results=[uuid.UUID(x) for x in json.loads(r["results"])],
                followed_up=[uuid.UUID(x) for x in json.loads(r["followed_up"])],
                timestamp=datetime.fromisoformat(r["timestamp"]),
            )
            for r in rows
        ]

    # --- Review Queue ---

    def create_review_item(self, item: ReviewItem) -> ReviewItem:
        self._conn.execute(
            "INSERT INTO review_queue (id, type, context, suggested_action, concept_id, resolved, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (str(item.id), item.type, item.context, item.suggested_action,
             str(item.concept_id) if item.concept_id else None,
             1 if item.resolved else 0, item.created_at.isoformat()),
        )
        self._conn.commit()
        return item

    def get_review_items(self, resolved: bool = False) -> list[ReviewItem]:
        rows = self._conn.execute(
            "SELECT * FROM review_queue WHERE resolved=? ORDER BY created_at DESC",
            (1 if resolved else 0,),
        ).fetchall()
        return [
            ReviewItem(
                id=uuid.UUID(r["id"]),
                type=r["type"],
                context=r["context"],
                suggested_action=r["suggested_action"],
                concept_id=uuid.UUID(r["concept_id"]) if r["concept_id"] else None,
                resolved=bool(r["resolved"]),
                created_at=datetime.fromisoformat(r["created_at"]),
            )
            for r in rows
        ]

    def resolve_review_item(self, id: uuid.UUID) -> None:
        self._conn.execute(
            "UPDATE review_queue SET resolved=1 WHERE id=?", (str(id),)
        )
        self._conn.commit()

    def count_review_items(self, resolved: bool = False) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) as cnt FROM review_queue WHERE resolved=?",
            (1 if resolved else 0,),
        ).fetchone()
        return row["cnt"]

    # --- Roots ---

    def add_root(self, path: str, name: str) -> uuid.UUID:
        root_id = uuid.uuid4()
        self._conn.execute(
            "INSERT INTO roots (id, path, name) VALUES (?, ?, ?)",
            (str(root_id), path, name),
        )
        self._conn.commit()
        return root_id

    def get_roots(self) -> list[dict]:
        rows = self._conn.execute("SELECT * FROM roots ORDER BY name").fetchall()
        return [
            {"id": uuid.UUID(r["id"]), "path": r["path"], "name": r["name"], "added_at": r["added_at"]}
            for r in rows
        ]

    def remove_root(self, id: uuid.UUID) -> None:
        self._conn.execute("DELETE FROM roots WHERE id=?", (str(id),))
        self._conn.commit()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/storage/test_sqlite.py -v`
Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
git add apriori/storage/schema.sql apriori/storage/sqlite.py tests/storage/test_sqlite.py
git commit -m "feat: SQLite storage with sqlite-vec and FTS5 support"
```

---

### Task 6: Graph Traversal

**Files:**
- Create: `apriori/graph/traversal.py`
- Create: `tests/graph/test_traversal.py`

- [ ] **Step 1: Write graph traversal tests**

```python
import uuid

import pytest

from apriori.core.models import Concept, Edge
from apriori.graph.traversal import traverse
from apriori.storage.sqlite import SQLiteStorage


@pytest.fixture
def graph_store(tmp_dir):
    """Create a store with a small graph: A -> B -> C, A -> D"""
    store = SQLiteStorage(tmp_dir / "test.db")
    a = store.create_concept(Concept(name="A", type="module"))
    b = store.create_concept(Concept(name="B", type="module"))
    c = store.create_concept(Concept(name="C", type="module"))
    d = store.create_concept(Concept(name="D", type="module"))
    store.create_edge(Edge(source=a.id, target=b.id, edge_type="depends-on"))
    store.create_edge(Edge(source=b.id, target=c.id, edge_type="depends-on"))
    store.create_edge(Edge(source=a.id, target=d.id, edge_type="owns"))
    return store, a, b, c, d


def test_traverse_bfs_one_hop(graph_store):
    store, a, b, c, d = graph_store
    result = traverse(store, a.id, max_hops=1, strategy="bfs")
    names = {c.name for c in result.concepts}
    assert "A" in names
    assert "B" in names
    assert "D" in names
    assert "C" not in names


def test_traverse_bfs_two_hops(graph_store):
    store, a, b, c, d = graph_store
    result = traverse(store, a.id, max_hops=2, strategy="bfs")
    names = {c.name for c in result.concepts}
    assert names == {"A", "B", "C", "D"}


def test_traverse_dfs(graph_store):
    store, a, b, c, d = graph_store
    result = traverse(store, a.id, max_hops=2, strategy="dfs")
    names = {c.name for c in result.concepts}
    assert names == {"A", "B", "C", "D"}


def test_traverse_edge_type_filter(graph_store):
    store, a, b, c, d = graph_store
    result = traverse(store, a.id, max_hops=2, edge_types=["depends-on"])
    names = {c.name for c in result.concepts}
    assert "D" not in names
    assert "B" in names
    assert "C" in names


def test_traverse_max_nodes(graph_store):
    store, a, b, c, d = graph_store
    result = traverse(store, a.id, max_hops=10, max_nodes=2)
    assert len(result.concepts) <= 2


def test_traverse_handles_cycles(tmp_dir):
    store = SQLiteStorage(tmp_dir / "test.db")
    a = store.create_concept(Concept(name="X", type="module"))
    b = store.create_concept(Concept(name="Y", type="module"))
    store.create_edge(Edge(source=a.id, target=b.id, edge_type="depends-on"))
    store.create_edge(Edge(source=b.id, target=a.id, edge_type="depends-on"))
    result = traverse(store, a.id, max_hops=10)
    assert len(result.concepts) == 2


def test_traverse_direction(graph_store):
    store, a, b, c, d = graph_store
    result = traverse(store, b.id, max_hops=1, direction="incoming")
    names = {c.name for c in result.concepts}
    assert "A" in names
    assert "C" not in names
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/graph/test_traversal.py -v`
Expected: FAIL — import error

- [ ] **Step 3: Implement graph traversal**

```python
"""BFS/DFS graph traversal with edge-type filtering."""

from __future__ import annotations

import uuid
from collections import deque
from dataclasses import dataclass, field

from apriori.core.models import Concept, Edge
from apriori.storage.interface import StorageProtocol


@dataclass
class TraversalResult:
    concepts: list[Concept] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)


def traverse(
    store: StorageProtocol,
    start_id: uuid.UUID,
    max_hops: int = 2,
    max_nodes: int | None = None,
    edge_types: list[str] | None = None,
    strategy: str = "bfs",
    direction: str = "outgoing",
) -> TraversalResult:
    start = store.get_concept(start_id)
    if not start:
        return TraversalResult()

    visited_ids: set[uuid.UUID] = {start_id}
    result_concepts: list[Concept] = [start]
    result_edges: list[Edge] = []

    if strategy == "bfs":
        _bfs(store, start_id, max_hops, max_nodes, edge_types, direction,
             visited_ids, result_concepts, result_edges)
    else:
        _dfs(store, start_id, 0, max_hops, max_nodes, edge_types, direction,
             visited_ids, result_concepts, result_edges)

    return TraversalResult(concepts=result_concepts, edges=result_edges)


def _bfs(
    store, start_id, max_hops, max_nodes, edge_types, direction,
    visited, concepts, edges,
):
    queue: deque[tuple[uuid.UUID, int]] = deque([(start_id, 0)])
    while queue:
        if max_nodes and len(concepts) >= max_nodes:
            break
        current_id, depth = queue.popleft()
        if depth >= max_hops:
            continue
        for edge in _get_filtered_edges(store, current_id, edge_types, direction):
            neighbor_id = _get_neighbor(edge, current_id, direction)
            if neighbor_id not in visited:
                if max_nodes and len(concepts) >= max_nodes:
                    break
                visited.add(neighbor_id)
                neighbor = store.get_concept(neighbor_id)
                if neighbor:
                    concepts.append(neighbor)
                    edges.append(edge)
                    queue.append((neighbor_id, depth + 1))


def _dfs(
    store, current_id, depth, max_hops, max_nodes, edge_types, direction,
    visited, concepts, edges,
):
    if depth >= max_hops:
        return
    if max_nodes and len(concepts) >= max_nodes:
        return
    for edge in _get_filtered_edges(store, current_id, edge_types, direction):
        neighbor_id = _get_neighbor(edge, current_id, direction)
        if neighbor_id not in visited:
            if max_nodes and len(concepts) >= max_nodes:
                return
            visited.add(neighbor_id)
            neighbor = store.get_concept(neighbor_id)
            if neighbor:
                concepts.append(neighbor)
                edges.append(edge)
                _dfs(store, neighbor_id, depth + 1, max_hops, max_nodes,
                     edge_types, direction, visited, concepts, edges)


def _get_filtered_edges(store, concept_id, edge_types, direction):
    all_edges = store.get_edges(concept_id, direction=direction)
    if edge_types:
        return [e for e in all_edges if e.edge_type in edge_types]
    return all_edges


def _get_neighbor(edge: Edge, current_id: uuid.UUID, direction: str) -> uuid.UUID:
    if direction == "incoming":
        return edge.source
    if direction == "outgoing":
        return edge.target
    # "both" — return whichever side isn't current
    return edge.target if edge.source == current_id else edge.source
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/graph/test_traversal.py -v`
Expected: All 7 tests PASS

- [ ] **Step 5: Commit**

```bash
git add apriori/graph/traversal.py tests/graph/test_traversal.py
git commit -m "feat: BFS/DFS graph traversal with edge-type filtering"
```

---

### Task 7: Embedding Interface and OpenAI Implementation

**Files:**
- Create: `apriori/embedding/interface.py`
- Create: `apriori/embedding/openai.py`
- Create: `tests/embedding/test_openai.py`

- [ ] **Step 1: Define embedding protocol**

```python
"""Abstract embedding provider interface."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class EmbeddingProvider(Protocol):
    def embed(self, text: str) -> list[float]: ...
    def embed_batch(self, texts: list[str]) -> list[list[float]]: ...
    @property
    def dimensions(self) -> int: ...
```

- [ ] **Step 2: Write tests for OpenAI embedding provider**

```python
from unittest.mock import MagicMock, patch

from apriori.embedding.openai import OpenAIEmbeddingProvider


def test_embed_single():
    mock_response = MagicMock()
    mock_response.data = [MagicMock(embedding=[0.1] * 1536)]
    with patch("apriori.embedding.openai.OpenAI") as MockClient:
        MockClient.return_value.embeddings.create.return_value = mock_response
        provider = OpenAIEmbeddingProvider()
        result = provider.embed("test text")
        assert len(result) == 1536
        MockClient.return_value.embeddings.create.assert_called_once_with(
            model="text-embedding-3-small", input="test text",
        )


def test_embed_batch():
    mock_response = MagicMock()
    mock_response.data = [
        MagicMock(embedding=[0.1] * 1536),
        MagicMock(embedding=[0.2] * 1536),
    ]
    with patch("apriori.embedding.openai.OpenAI") as MockClient:
        MockClient.return_value.embeddings.create.return_value = mock_response
        provider = OpenAIEmbeddingProvider()
        results = provider.embed_batch(["text 1", "text 2"])
        assert len(results) == 2
        assert len(results[0]) == 1536


def test_dimensions():
    with patch("apriori.embedding.openai.OpenAI"):
        provider = OpenAIEmbeddingProvider()
        assert provider.dimensions == 1536


def test_custom_model():
    with patch("apriori.embedding.openai.OpenAI") as MockClient:
        mock_response = MagicMock()
        mock_response.data = [MagicMock(embedding=[0.1] * 3072)]
        MockClient.return_value.embeddings.create.return_value = mock_response
        provider = OpenAIEmbeddingProvider(model="text-embedding-3-large", dimensions=3072)
        result = provider.embed("test")
        assert len(result) == 3072
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/embedding/test_openai.py -v`
Expected: FAIL — import error

- [ ] **Step 4: Implement OpenAI embedding provider**

```python
"""OpenAI embedding provider."""

from __future__ import annotations

from openai import OpenAI


class OpenAIEmbeddingProvider:
    def __init__(self, model: str = "text-embedding-3-small", dimensions: int = 1536):
        self._model = model
        self._dimensions = dimensions
        self._client = OpenAI()

    def embed(self, text: str) -> list[float]:
        response = self._client.embeddings.create(model=self._model, input=text)
        return response.data[0].embedding

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        response = self._client.embeddings.create(model=self._model, input=texts)
        return [item.embedding for item in response.data]

    @property
    def dimensions(self) -> int:
        return self._dimensions
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/embedding/test_openai.py -v`
Expected: All 4 tests PASS

- [ ] **Step 6: Commit**

```bash
git add apriori/embedding/interface.py apriori/embedding/openai.py tests/embedding/test_openai.py
git commit -m "feat: embedding provider interface with OpenAI implementation"
```

---

### Task 8: Keyword Search

**Files:**
- Create: `apriori/search/keyword.py`
- Create: `tests/search/test_keyword.py`

- [ ] **Step 1: Write keyword search tests**

```python
import pytest

from apriori.core.models import Concept, Document
from apriori.search.keyword import keyword_search
from apriori.storage.sqlite import SQLiteStorage


@pytest.fixture
def search_store(tmp_dir):
    store = SQLiteStorage(tmp_dir / "test.db")
    auth = store.create_concept(Concept(name="Auth Middleware", type="module"))
    store.create_document(Document(
        concept_id=auth.id,
        content="Handles JWT token validation and refresh logic.",
        summary="JWT auth middleware for API requests",
    ))
    billing = store.create_concept(Concept(name="Billing Engine", type="subsystem"))
    store.create_document(Document(
        concept_id=billing.id,
        content="Processes payments via Stripe integration.",
        summary="Payment processing through Stripe",
    ))
    return store


def test_keyword_search_finds_match(search_store):
    results = keyword_search(search_store, "JWT token")
    assert len(results) >= 1
    assert any(r["concept_name"] == "Auth Middleware" for r in results)


def test_keyword_search_no_match(search_store):
    results = keyword_search(search_store, "kubernetes deployment")
    assert len(results) == 0


def test_keyword_search_partial_match(search_store):
    results = keyword_search(search_store, "Stripe")
    assert len(results) >= 1
    assert any(r["concept_name"] == "Billing Engine" for r in results)


def test_keyword_search_limit(search_store):
    results = keyword_search(search_store, "middleware OR payments", limit=1)
    assert len(results) <= 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/search/test_keyword.py -v`
Expected: FAIL — import error

- [ ] **Step 3: Implement keyword search**

```python
"""FTS5-based keyword search over documents and concept names."""

from __future__ import annotations

from apriori.storage.sqlite import SQLiteStorage


def keyword_search(
    store: SQLiteStorage,
    query: str,
    limit: int = 10,
) -> list[dict]:
    """Search documents using SQLite FTS5 full-text search.

    Returns list of dicts with concept_name, summary, document_id, rank.
    """
    # FTS5 query — escape double quotes in user input
    safe_query = query.replace('"', '""')
    rows = store._conn.execute(
        """
        SELECT
            fts_documents.concept_name,
            fts_documents.summary,
            d.id as document_id,
            d.concept_id,
            rank
        FROM fts_documents
        JOIN documents d ON d.vec_rowid = fts_documents.rowid
        WHERE fts_documents MATCH ?
        ORDER BY rank
        LIMIT ?
        """,
        (safe_query, limit),
    ).fetchall()

    return [
        {
            "concept_name": r["concept_name"],
            "summary": r["summary"],
            "document_id": r["document_id"],
            "concept_id": r["concept_id"],
            "rank": r["rank"],
        }
        for r in rows
    ]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/search/test_keyword.py -v`
Expected: All 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add apriori/search/keyword.py tests/search/test_keyword.py
git commit -m "feat: FTS5 keyword search over documents"
```

---

### Task 9: Semantic Search

**Files:**
- Create: `apriori/search/semantic.py`
- Create: `tests/search/test_semantic.py`

- [ ] **Step 1: Write semantic search tests**

```python
import struct
from unittest.mock import MagicMock

import pytest

from apriori.core.models import Concept, Document
from apriori.search.semantic import semantic_search
from apriori.storage.sqlite import SQLiteStorage


def _fake_embedding(seed: float) -> list[float]:
    """Generate a deterministic 1536-dim embedding for testing."""
    return [seed + (i * 0.001) for i in range(1536)]


@pytest.fixture
def semantic_store(tmp_dir):
    store = SQLiteStorage(tmp_dir / "test.db")
    auth = store.create_concept(Concept(name="Auth", type="module"))
    store.create_document(Document(
        concept_id=auth.id,
        content="Auth details",
        summary="JWT authentication middleware",
        embedding=_fake_embedding(0.1),
    ))
    billing = store.create_concept(Concept(name="Billing", type="module"))
    store.create_document(Document(
        concept_id=billing.id,
        content="Billing details",
        summary="Payment processing via Stripe",
        embedding=_fake_embedding(0.9),
    ))
    return store


def test_semantic_search_returns_results(semantic_store):
    # Query embedding close to auth (0.1 seed)
    query_vec = _fake_embedding(0.1)
    results = semantic_search(semantic_store, query_vec, limit=2)
    assert len(results) == 2
    # Auth should be closer
    assert results[0]["concept_name"] == "Auth"


def test_semantic_search_limit(semantic_store):
    query_vec = _fake_embedding(0.5)
    results = semantic_search(semantic_store, query_vec, limit=1)
    assert len(results) == 1


def test_semantic_search_empty_db(tmp_dir):
    store = SQLiteStorage(tmp_dir / "test.db")
    query_vec = _fake_embedding(0.5)
    results = semantic_search(store, query_vec, limit=5)
    assert results == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/search/test_semantic.py -v`
Expected: FAIL — import error

- [ ] **Step 3: Implement semantic search**

```python
"""Embedding-based semantic search using sqlite-vec."""

from __future__ import annotations

from struct import pack

from apriori.storage.sqlite import SQLiteStorage


def _serialize_f32(vector: list[float]) -> bytes:
    return pack("%sf" % len(vector), *vector)


def semantic_search(
    store: SQLiteStorage,
    query_embedding: list[float],
    limit: int = 10,
) -> list[dict]:
    """Search documents by embedding similarity.

    Returns list of dicts with concept_name, summary, document_id, distance.
    """
    rows = store._conn.execute(
        """
        SELECT
            v.rowid,
            v.distance,
            d.id as document_id,
            d.concept_id,
            d.summary,
            c.name as concept_name
        FROM vec_documents v
        JOIN documents d ON d.vec_rowid = v.rowid
        JOIN concepts c ON c.id = d.concept_id
        WHERE v.embedding MATCH ?
          AND k = ?
        ORDER BY v.distance
        """,
        (_serialize_f32(query_embedding), limit),
    ).fetchall()

    return [
        {
            "concept_name": r["concept_name"],
            "summary": r["summary"],
            "document_id": r["document_id"],
            "concept_id": r["concept_id"],
            "distance": r["distance"],
        }
        for r in rows
    ]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/search/test_semantic.py -v`
Expected: All 3 tests PASS

- [ ] **Step 5: Commit**

```bash
git add apriori/search/semantic.py tests/search/test_semantic.py
git commit -m "feat: semantic vector search using sqlite-vec"
```

---

### Task 10: Unified Search Engine

**Files:**
- Create: `apriori/search/engine.py`
- Create: `tests/search/test_engine.py`

- [ ] **Step 1: Write unified search engine tests**

```python
from unittest.mock import MagicMock, patch

import pytest

from apriori.core.models import Concept, Document
from apriori.search.engine import SearchEngine
from apriori.storage.sqlite import SQLiteStorage


@pytest.fixture
def engine(tmp_dir):
    store = SQLiteStorage(tmp_dir / "test.db")
    mock_embedder = MagicMock()
    mock_embedder.embed.return_value = [0.1] * 1536
    auth = store.create_concept(Concept(name="Auth Middleware", type="module"))
    store.create_document(Document(
        concept_id=auth.id,
        content="JWT token validation",
        summary="Auth middleware for JWT",
        embedding=[0.1] * 1536,
    ))
    return SearchEngine(store=store, embedder=mock_embedder)


def test_search_keyword_mode(engine):
    results = engine.search("JWT", mode="keyword")
    assert len(results) >= 1


def test_search_semantic_mode(engine):
    results = engine.search("authentication", mode="semantic")
    assert len(results) >= 1


def test_search_code_mode(tmp_dir):
    store = SQLiteStorage(tmp_dir / "test.db")
    from apriori.core.models import CodeAnchor
    c = store.create_concept(Concept(
        name="Validator", type="module",
        code_anchors=[CodeAnchor(symbol="validate", file_path="src/auth.py", content_hash="abc")],
    ))
    store.create_document(Document(concept_id=c.id, content="Details", summary="Sum"))
    engine = SearchEngine(store=store, embedder=MagicMock())
    results = engine.search("src/auth.py", mode="code")
    assert len(results) >= 1


def test_search_default_mode_is_semantic(engine):
    results = engine.search("auth")
    assert isinstance(results, list)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/search/test_engine.py -v`
Expected: FAIL — import error

- [ ] **Step 3: Implement search engine**

```python
"""Unified search engine with mode routing."""

from __future__ import annotations

import uuid

from apriori.embedding.interface import EmbeddingProvider
from apriori.search.keyword import keyword_search
from apriori.search.semantic import semantic_search
from apriori.storage.sqlite import SQLiteStorage


class SearchEngine:
    def __init__(self, store: SQLiteStorage, embedder: EmbeddingProvider):
        self._store = store
        self._embedder = embedder

    def search(
        self,
        query: str,
        mode: str = "semantic",
        limit: int = 10,
    ) -> list[dict]:
        if mode == "keyword":
            return keyword_search(self._store, query, limit=limit)
        elif mode == "semantic":
            embedding = self._embedder.embed(query)
            return semantic_search(self._store, embedding, limit=limit)
        elif mode == "code":
            return self._code_search(query, limit=limit)
        else:
            raise ValueError(f"Unknown search mode: {mode}")

    def _code_search(self, query: str, limit: int = 10) -> list[dict]:
        """Find concepts anchored to a file path or symbol."""
        rows = self._store._conn.execute(
            """
            SELECT DISTINCT c.id, c.name, c.type
            FROM code_anchors ca
            JOIN concepts c ON c.id = ca.concept_id
            WHERE ca.file_path LIKE ? OR ca.symbol LIKE ?
            LIMIT ?
            """,
            (f"%{query}%", f"%{query}%", limit),
        ).fetchall()

        results = []
        for r in rows:
            concept_id = r["id"]
            docs = self._store.get_documents_for_concept(uuid.UUID(concept_id))
            summary = docs[0].summary if docs else ""
            results.append({
                "concept_name": r["name"],
                "concept_id": concept_id,
                "summary": summary,
            })
        return results
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/search/test_engine.py -v`
Expected: All 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add apriori/search/engine.py tests/search/test_engine.py
git commit -m "feat: unified search engine with keyword, semantic, and code modes"
```

---

### Task 11: Feedback Logger

**Files:**
- Create: `apriori/feedback/logger.py`
- Create: `tests/feedback/test_logger.py`

- [ ] **Step 1: Write feedback logger tests**

```python
import uuid

import pytest

from apriori.core.models import Concept, Document
from apriori.feedback.logger import FeedbackLogger
from apriori.storage.sqlite import SQLiteStorage


@pytest.fixture
def logger(tmp_dir):
    store = SQLiteStorage(tmp_dir / "test.db")
    return FeedbackLogger(store), store


def test_log_search(logger):
    fl, store = logger
    concept_ids = [uuid.uuid4(), uuid.uuid4()]
    query_id = fl.log_search("how does auth work", "semantic", concept_ids)
    logs = store.get_query_logs()
    assert len(logs) == 1
    assert logs[0].query == "how does auth work"
    assert logs[0].mode == "semantic"


def test_log_followup(logger):
    fl, store = logger
    concept_id = uuid.uuid4()
    query_id = fl.log_search("auth", "keyword", [concept_id])
    fl.log_followup(query_id, concept_id)
    logs = store.get_query_logs()
    assert concept_id in logs[0].followed_up


def test_get_demand_metrics(logger):
    fl, store = logger
    cid1 = uuid.uuid4()
    cid2 = uuid.uuid4()
    # 3 searches, 2 follow-ups on cid1, 0 on cid2
    qid1 = fl.log_search("auth", "semantic", [cid1, cid2])
    fl.log_followup(qid1, cid1)
    qid2 = fl.log_search("auth tokens", "keyword", [cid1])
    fl.log_followup(qid2, cid1)
    qid3 = fl.log_search("payments", "semantic", [])  # gap — no results
    metrics = fl.get_demand_metrics()
    assert metrics["total_queries"] == 3
    assert metrics["queries_with_no_results"] >= 1
    assert cid1 in [m["concept_id"] for m in metrics["most_accessed"]]


def test_get_gaps(logger):
    fl, store = logger
    fl.log_search("rate limiting", "semantic", [])
    fl.log_search("rate limiting", "keyword", [])
    gaps = fl.get_gaps()
    assert len(gaps) >= 1
    assert any("rate limiting" in g["query"] for g in gaps)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/feedback/test_logger.py -v`
Expected: FAIL — import error

- [ ] **Step 3: Implement feedback logger**

```python
"""Passive feedback logging and demand metric computation."""

from __future__ import annotations

import uuid
from collections import Counter

from apriori.core.models import QueryLog
from apriori.storage.sqlite import SQLiteStorage


class FeedbackLogger:
    def __init__(self, store: SQLiteStorage):
        self._store = store

    def log_search(
        self, query: str, mode: str, result_concept_ids: list[uuid.UUID],
    ) -> uuid.UUID:
        entry = QueryLog(query=query, mode=mode, results=result_concept_ids)
        self._store.log_query(entry)
        return entry.id

    def log_followup(self, query_id: uuid.UUID, concept_id: uuid.UUID) -> None:
        self._store.log_followup(query_id, concept_id)

    def get_demand_metrics(self, limit: int = 500) -> dict:
        logs = self._store.get_query_logs(limit=limit)
        total = len(logs)
        no_results = sum(1 for l in logs if len(l.results) == 0)

        # Count follow-ups per concept
        followup_counts: Counter[uuid.UUID] = Counter()
        for log in logs:
            for cid in log.followed_up:
                followup_counts[cid] += 1

        most_accessed = [
            {"concept_id": cid, "followup_count": count}
            for cid, count in followup_counts.most_common(20)
        ]

        # Searches with results but no follow-up (low-quality matches)
        no_followup = sum(
            1 for l in logs if len(l.results) > 0 and len(l.followed_up) == 0
        )

        return {
            "total_queries": total,
            "queries_with_no_results": no_results,
            "queries_with_no_followup": no_followup,
            "most_accessed": most_accessed,
        }

    def get_gaps(self, limit: int = 500) -> list[dict]:
        """Find queries that returned no results (knowledge gaps)."""
        logs = self._store.get_query_logs(limit=limit)
        gap_queries: Counter[str] = Counter()
        for log in logs:
            if len(log.results) == 0:
                gap_queries[log.query] += 1

        return [
            {"query": q, "count": c}
            for q, c in gap_queries.most_common(20)
        ]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/feedback/test_logger.py -v`
Expected: All 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add apriori/feedback/logger.py tests/feedback/test_logger.py
git commit -m "feat: passive feedback logger with demand metrics and gap detection"
```

---

### Task 12: Quality Gate Metrics

**Files:**
- Create: `apriori/core/metrics.py`
- Create: `tests/core/test_metrics.py`

- [ ] **Step 1: Write quality gate tests**

```python
import uuid

import pytest

from apriori.core.metrics import (
    compute_assertion_density,
    compute_code_grounding_score,
    compute_conciseness_ratio,
    compute_report_card,
)
from apriori.core.models import CodeAnchor, CodeReference, Concept, Document


def test_conciseness_ratio_short_doc():
    doc = Document(
        concept_id=uuid.uuid4(),
        content="Validates JWT tokens using RS256 algorithm.",
        summary="JWT validation",
        code_references=[
            CodeReference(symbol="validate_jwt", file_path="auth.py", content_hash="abc"),
        ],
    )
    ratio = compute_conciseness_ratio(doc)
    assert ratio > 0.5  # Short doc with references is concise


def test_conciseness_ratio_bloated_doc():
    bloat = "This is a very important part of the system. " * 100
    doc = Document(
        concept_id=uuid.uuid4(),
        content=bloat,
        summary="Something",
        code_references=[
            CodeReference(symbol="func", file_path="a.py", content_hash="abc"),
        ],
    )
    ratio = compute_conciseness_ratio(doc)
    assert ratio < 0.5  # Bloated doc scores low


def test_assertion_density_specific():
    content = (
        "validate_jwt() in src/auth.py checks the RS256 signature. "
        "It rejects expired tokens by comparing exp claim to current UTC time. "
        "On failure, it returns HTTP 401 with error code AUTH_EXPIRED."
    )
    density = compute_assertion_density(content)
    assert density > 0.5


def test_assertion_density_vague():
    content = (
        "This is an important part of the system. "
        "It helps with various things. "
        "It is used for processing. "
        "This module is responsible for handling stuff."
    )
    density = compute_assertion_density(content)
    assert density < 0.4


def test_code_grounding_score():
    doc = Document(
        concept_id=uuid.uuid4(),
        content="validate_jwt() checks tokens. process_payment() handles billing.",
        summary="Auth and billing",
        code_references=[
            CodeReference(symbol="validate_jwt", file_path="auth.py", content_hash="abc"),
        ],
    )
    score = compute_code_grounding_score(doc)
    assert 0.0 <= score <= 1.0
    assert score > 0.0  # At least one reference


def test_code_grounding_score_no_refs():
    doc = Document(
        concept_id=uuid.uuid4(),
        content="This does auth things.",
        summary="Auth",
    )
    score = compute_code_grounding_score(doc)
    assert score == 0.0


def test_report_card_structure():
    doc = Document(
        concept_id=uuid.uuid4(),
        content="validate_jwt() checks RS256 tokens in src/auth.py.",
        summary="JWT validation",
        code_references=[
            CodeReference(symbol="validate_jwt", file_path="auth.py", content_hash="abc"),
        ],
    )
    card = compute_report_card(doc)
    assert "conciseness_ratio" in card
    assert "assertion_density" in card
    assert "code_grounding_score" in card
    assert all(isinstance(v, float) for v in card.values())
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/core/test_metrics.py -v`
Expected: FAIL — import error

- [ ] **Step 3: Implement quality gate metrics**

```python
"""Deterministic quality gate metrics for librarian output."""

from __future__ import annotations

import re

from apriori.core.models import Document

# Vague phrases that indicate low assertion density
_VAGUE_PATTERNS = [
    r"\bimportant part of\b",
    r"\bhelps with\b",
    r"\bis used for\b",
    r"\bis responsible for\b",
    r"\bhandles? various\b",
    r"\bvarious things\b",
    r"\bin general\b",
    r"\bbasically\b",
    r"\bstuff\b",
    r"\bthings\b",
    r"\betc\.?\b",
    r"\band so on\b",
    r"\band more\b",
    r"\bmain purpose\b",
    r"\bkey component\b",
    r"\bplays a role\b",
    r"\bworks with\b",
]

# Specific patterns that indicate concrete assertions
_SPECIFIC_PATTERNS = [
    r"\b\w+\(\)",                          # function calls: validate_jwt()
    r"\b\w+\.\w+",                         # dotted paths: auth.validate
    r"src/\S+",                            # file paths
    r"\b[A-Z][A-Z_]{2,}\b",               # constants: AUTH_EXPIRED, HTTP_401
    r"\bHTTP \d{3}\b",                     # HTTP status codes
    r"\breturns?\b",                       # concrete behavior
    r"\braises?\b",                        # concrete behavior
    r"\bcalls?\b",                         # concrete behavior
    r"\bimports?\b",                       # concrete dependency
    r"\b\d+\b",                            # numbers (specific values)
]


def compute_conciseness_ratio(doc: Document) -> float:
    """Ratio of code references to token count. Higher = more concise.

    A document with many references relative to its length is dense with
    grounded information. Returns 0.0-1.0.
    """
    word_count = len(doc.content.split())
    if word_count == 0:
        return 0.0
    ref_count = max(len(doc.code_references), 1)
    # Target: ~100 words per code reference is ideal (ratio = 1.0)
    # 500+ words per reference is bloated (ratio approaches 0)
    words_per_ref = word_count / ref_count
    ratio = max(0.0, min(1.0, 1.0 - (words_per_ref - 100) / 400))
    return round(ratio, 3)


def compute_assertion_density(content: str) -> float:
    """Ratio of specific vs vague sentences. Higher = more concrete.

    Uses heuristic regex patterns. Returns 0.0-1.0.
    """
    sentences = [s.strip() for s in re.split(r'[.!?]+', content) if s.strip()]
    if not sentences:
        return 0.0

    specific_count = 0
    vague_count = 0
    for sentence in sentences:
        is_vague = any(re.search(p, sentence, re.IGNORECASE) for p in _VAGUE_PATTERNS)
        is_specific = any(re.search(p, sentence) for p in _SPECIFIC_PATTERNS)
        if is_specific and not is_vague:
            specific_count += 1
        elif is_vague and not is_specific:
            vague_count += 1
        # Mixed or neither: neutral, don't count

    total_scored = specific_count + vague_count
    if total_scored == 0:
        return 0.5  # No strong signal either way
    return round(specific_count / total_scored, 3)


def compute_code_grounding_score(doc: Document) -> float:
    """Fraction of document that is backed by code references.

    Simple heuristic: are there code references at all, and how many
    relative to the document size?
    """
    if not doc.code_references:
        return 0.0
    word_count = len(doc.content.split())
    if word_count == 0:
        return 0.0
    # Each code reference "grounds" roughly 50-100 words of content
    grounded_words = len(doc.code_references) * 75
    return round(min(1.0, grounded_words / word_count), 3)


def compute_report_card(doc: Document) -> dict[str, float]:
    """Compute all deterministic metrics for a document."""
    return {
        "conciseness_ratio": compute_conciseness_ratio(doc),
        "assertion_density": compute_assertion_density(doc.content),
        "code_grounding_score": compute_code_grounding_score(doc),
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/core/test_metrics.py -v`
Expected: All 7 tests PASS

- [ ] **Step 5: Commit**

```bash
git add apriori/core/metrics.py tests/core/test_metrics.py
git commit -m "feat: deterministic quality gate metrics for librarian output"
```

---

### Task 13: CLI

**Files:**
- Create: `apriori/cli/main.py`
- Create: `tests/cli/test_cli.py`

- [ ] **Step 1: Write CLI tests**

```python
from pathlib import Path

from click.testing import CliRunner

from apriori.cli.main import cli


@pytest.fixture
def runner(tmp_dir, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_dir / "data"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_dir / "config"))
    return CliRunner()


import pytest


def test_init_creates_workspace(runner, tmp_dir):
    workspace_path = tmp_dir / "myproject"
    workspace_path.mkdir()
    result = runner.invoke(cli, ["init", str(workspace_path), "--name", "myproject"])
    assert result.exit_code == 0
    assert "Workspace 'myproject' created" in result.output


def test_add_root(runner, tmp_dir):
    workspace_path = tmp_dir / "myproject"
    workspace_path.mkdir()
    root_path = workspace_path / "src"
    root_path.mkdir()
    runner.invoke(cli, ["init", str(workspace_path), "--name", "myproject"])
    result = runner.invoke(cli, ["add", str(root_path), "--workspace", "myproject"])
    assert result.exit_code == 0
    assert "Root added" in result.output


def test_roots_list(runner, tmp_dir):
    workspace_path = tmp_dir / "myproject"
    workspace_path.mkdir()
    root_path = workspace_path / "src"
    root_path.mkdir()
    runner.invoke(cli, ["init", str(workspace_path), "--name", "myproject"])
    runner.invoke(cli, ["add", str(root_path), "--workspace", "myproject"])
    result = runner.invoke(cli, ["roots", "--workspace", "myproject"])
    assert result.exit_code == 0
    assert "src" in result.output


def test_status(runner, tmp_dir):
    workspace_path = tmp_dir / "myproject"
    workspace_path.mkdir()
    runner.invoke(cli, ["init", str(workspace_path), "--name", "myproject"])
    result = runner.invoke(cli, ["status", "--workspace", "myproject"])
    assert result.exit_code == 0
    assert "Concepts:" in result.output
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/cli/test_cli.py -v`
Expected: FAIL — import error

- [ ] **Step 3: Implement CLI**

```python
"""A-Priori CLI — workspace management, search, and inspection."""

from __future__ import annotations

from pathlib import Path

import click

from apriori.core.config import (
    WorkspaceConfig,
    get_data_dir,
    load_workspace_config,
    save_workspace_config,
)
from apriori.storage.sqlite import SQLiteStorage


def _get_workspace_dir(name: str) -> Path:
    return get_data_dir() / "workspaces" / name


def _get_store(workspace_name: str) -> SQLiteStorage:
    ws_dir = _get_workspace_dir(workspace_name)
    return SQLiteStorage(ws_dir / "apriori.db")


@click.group()
def cli():
    """A-Priori: Self-constructing knowledge base for AI agents."""
    pass


@cli.command()
@click.argument("path", type=click.Path(exists=True))
@click.option("--name", required=True, help="Workspace name")
def init(path: str, name: str):
    """Create a workspace pointing at a directory."""
    ws_dir = _get_workspace_dir(name)
    ws_dir.mkdir(parents=True, exist_ok=True)
    ws = WorkspaceConfig(name=name, path=Path(path).resolve())
    save_workspace_config(ws, ws_dir / "workspace.yaml")
    # Initialize the database
    store = SQLiteStorage(ws_dir / "apriori.db")
    store.close()
    click.echo(f"Workspace '{name}' created at {ws_dir}")


@cli.command()
@click.argument("path", type=click.Path(exists=True))
@click.option("--workspace", required=True, help="Workspace name")
def add(path: str, workspace: str):
    """Add a root directory to track."""
    resolved = Path(path).resolve()
    store = _get_store(workspace)
    root_name = resolved.name
    store.add_root(str(resolved), root_name)
    store.close()
    click.echo(f"Root added: {root_name} ({resolved})")


@cli.command()
@click.option("--workspace", required=True, help="Workspace name")
def roots(workspace: str):
    """List tracked roots."""
    store = _get_store(workspace)
    root_list = store.get_roots()
    store.close()
    if not root_list:
        click.echo("No roots tracked.")
        return
    for r in root_list:
        click.echo(f"  {r['name']}: {r['path']}")


@cli.command()
@click.option("--workspace", required=True, help="Workspace name")
def status(workspace: str):
    """Show workspace status."""
    store = _get_store(workspace)
    concepts = store.list_concepts()
    roots_list = store.get_roots()
    review_count = store.count_review_items()
    store.close()
    click.echo(f"Workspace: {workspace}")
    click.echo(f"Roots: {len(roots_list)}")
    click.echo(f"Concepts: {len(concepts)}")
    click.echo(f"Pending reviews: {review_count}")


@cli.command()
@click.option("--workspace", required=True, help="Workspace name")
def reviews(workspace: str):
    """Show items in the human review queue."""
    store = _get_store(workspace)
    items = store.get_review_items(resolved=False)
    store.close()
    if not items:
        click.echo("No pending review items.")
        return
    for item in items:
        click.echo(f"  [{item.type}] {item.context[:80]}")
        click.echo(f"    Suggested: {item.suggested_action[:80]}")
        click.echo()


@cli.command()
@click.argument("query")
@click.option("--workspace", required=True, help="Workspace name")
@click.option("--mode", default="semantic", type=click.Choice(["keyword", "semantic", "code"]))
@click.option("--limit", default=10)
def search(query: str, workspace: str, mode: str, limit: int):
    """Search the knowledge base."""
    from apriori.search.engine import SearchEngine

    store = _get_store(workspace)
    if mode == "semantic":
        from apriori.core.config import load_app_config
        from apriori.embedding.openai import OpenAIEmbeddingProvider
        config = load_app_config()
        embedder = OpenAIEmbeddingProvider(model=config.embedding.model)
    else:
        embedder = None  # Not needed for keyword/code

    engine = SearchEngine(store=store, embedder=embedder)
    results = engine.search(query, mode=mode, limit=limit)
    store.close()

    if not results:
        click.echo("No results found.")
        return
    for r in results:
        click.echo(f"  {r.get('concept_name', 'Unknown')}: {r.get('summary', '')[:80]}")


@cli.command()
@click.argument("concept_name")
@click.option("--workspace", required=True, help="Workspace name")
def inspect(concept_name: str, workspace: str):
    """View a concept, its edges, and document summaries."""
    store = _get_store(workspace)
    concept = store.get_concept(concept_name)
    if not concept:
        click.echo(f"Concept '{concept_name}' not found.")
        store.close()
        return

    click.echo(f"Concept: {concept.name} ({concept.type})")
    click.echo(f"ID: {concept.id}")

    edges = store.get_edges(concept.id)
    if edges:
        click.echo(f"\nEdges ({len(edges)}):")
        for e in edges:
            other_id = e.target if e.source == concept.id else e.source
            other = store.get_concept(other_id)
            other_name = other.name if other else str(other_id)
            direction = "->" if e.source == concept.id else "<-"
            click.echo(f"  {direction} {e.edge_type} {other_name}")

    docs = store.get_documents_for_concept(concept.id)
    if docs:
        click.echo(f"\nDocuments ({len(docs)}):")
        for d in docs:
            click.echo(f"  [{d.confidence:.1f}] {d.summary[:80]}")

    store.close()


if __name__ == "__main__":
    cli()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/cli/test_cli.py -v`
Expected: All 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add apriori/cli/main.py tests/cli/test_cli.py
git commit -m "feat: CLI for workspace management, search, and inspection"
```

---

### Task 14: MCP Server

**Files:**
- Create: `apriori/mcp/server.py`
- Create: `tests/mcp/test_server.py`

- [ ] **Step 1: Write MCP server tests**

```python
import uuid
from unittest.mock import MagicMock, patch

import pytest

from apriori.core.models import CodeAnchor, Concept, Document, Edge
from apriori.storage.sqlite import SQLiteStorage


@pytest.fixture
def mcp_store(tmp_dir):
    store = SQLiteStorage(tmp_dir / "test.db")
    auth = store.create_concept(Concept(name="Auth", type="module"))
    store.create_document(Document(
        concept_id=auth.id,
        content="JWT validation details.",
        summary="JWT auth middleware",
        embedding=[0.1] * 1536,
    ))
    return store, auth


def test_server_imports():
    """Verify the server module can be imported without errors."""
    from apriori.mcp.server import create_server
    assert callable(create_server)


def test_server_has_search_tool(mcp_store):
    from apriori.mcp.server import create_server
    store, _ = mcp_store
    server = create_server(store=store, embedder=MagicMock())
    # FastMCP registers tools — verify search is registered
    tool_names = [t.name for t in server._tool_manager.list_tools()]
    assert "search" in tool_names


def test_server_has_get_document_tool(mcp_store):
    from apriori.mcp.server import create_server
    store, _ = mcp_store
    server = create_server(store=store, embedder=MagicMock())
    tool_names = [t.name for t in server._tool_manager.list_tools()]
    assert "get_document" in tool_names


def test_server_has_traverse_tool(mcp_store):
    from apriori.mcp.server import create_server
    store, _ = mcp_store
    server = create_server(store=store, embedder=MagicMock())
    tool_names = [t.name for t in server._tool_manager.list_tools()]
    assert "traverse" in tool_names


def test_server_has_write_tools(mcp_store):
    from apriori.mcp.server import create_server
    store, _ = mcp_store
    server = create_server(store=store, embedder=MagicMock())
    tool_names = [t.name for t in server._tool_manager.list_tools()]
    for expected in ["create_concept", "create_edge", "create_document", "flag_stale",
                      "update_concept", "update_document", "delete_concept",
                      "delete_document", "delete_edge", "update_edge"]:
        assert expected in tool_names, f"Missing tool: {expected}"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/mcp/test_server.py -v`
Expected: FAIL — import error

- [ ] **Step 3: Implement MCP server**

```python
"""A-Priori MCP server exposing knowledge base tools for agents."""

from __future__ import annotations

import json
import uuid

from mcp.server.fastmcp import FastMCP

from apriori.core.models import (
    CodeAnchor,
    CodeReference,
    Concept,
    Document,
    Edge,
    ReviewItem,
)
from apriori.embedding.interface import EmbeddingProvider
from apriori.feedback.logger import FeedbackLogger
from apriori.graph.traversal import traverse as graph_traverse
from apriori.search.engine import SearchEngine
from apriori.storage.sqlite import SQLiteStorage


def create_server(
    store: SQLiteStorage,
    embedder: EmbeddingProvider,
) -> FastMCP:
    mcp = FastMCP(
        "A-Priori",
        description="Self-constructing knowledge base for AI agents. "
        "Provides fast, precise context retrieval for codebases.",
    )

    feedback = FeedbackLogger(store)
    engine = SearchEngine(store=store, embedder=embedder)

    # --- Read Tools ---

    @mcp.tool()
    def search(
        query: str,
        mode: str = "semantic",
        limit: int = 10,
    ) -> str:
        """Search the knowledge base for concepts and documents.

        USE THIS TOOL WHEN: You need to find information about a codebase concept,
        pattern, or subsystem. This is your primary entry point for discovering
        what A-Priori knows.

        MODES:
        - "semantic" (default): Natural language queries. "how does auth work?"
        - "keyword": Exact term matching. "validateToken", "JWT"
        - "code": Find concepts by file path or symbol. "src/auth/validate.py"

        RETURNS: A list of matching concepts with short summaries. Scan these to
        find what you need, then call get_document() for the full explanation.

        DO NOT USE FOR: Graph traversal (use traverse instead), or when you
        already know the exact concept name (use get_concept instead).
        """
        results = engine.search(query, mode=mode, limit=limit)
        concept_ids = [
            uuid.UUID(r["concept_id"]) for r in results if "concept_id" in r
        ]
        feedback.log_search(query, mode, concept_ids)
        return json.dumps(results, default=str)

    @mcp.tool()
    def get_document(concept_name: str, doc_id: str | None = None) -> str:
        """Fetch the full document for a concept.

        USE THIS TOOL WHEN: You found a relevant concept via search() and need
        the full explanation. This is the "deep read" after a search.

        RETURNS: Full markdown document content with code references.
        If the concept has multiple documents, returns the first unless
        doc_id is specified.

        IMPORTANT: Calling this tool signals that the search result was useful,
        which helps prioritize knowledge maintenance.
        """
        concept = store.get_concept(concept_name)
        if not concept:
            return json.dumps({"error": f"Concept '{concept_name}' not found"})
        docs = store.get_documents_for_concept(concept.id)
        if not docs:
            return json.dumps({"error": f"No documents for concept '{concept_name}'"})
        if doc_id:
            doc = next((d for d in docs if str(d.id) == doc_id), None)
            if not doc:
                return json.dumps({"error": f"Document {doc_id} not found"})
        else:
            doc = docs[0]
        # Log follow-up
        logs = store.get_query_logs(limit=5)
        for log in logs:
            if concept.id in [uuid.UUID(str(r)) for r in log.results]:
                feedback.log_followup(log.id, concept.id)
                break
        return json.dumps({
            "concept": concept.name,
            "document_id": str(doc.id),
            "content": doc.content,
            "summary": doc.summary,
            "confidence": doc.confidence,
            "code_references": [
                {"symbol": r.symbol, "file_path": r.file_path}
                for r in doc.code_references
            ],
        })

    @mcp.tool()
    def get_concept(name_or_id: str) -> str:
        """Fetch a single concept with its edges and document summaries.

        USE THIS TOOL WHEN: You know the exact concept name or ID and want
        to see its structure — what it connects to and what documents exist.

        RETURNS: Concept details, list of edges with neighbor names,
        and document summaries (not full content — use get_document for that).
        """
        concept = store.get_concept(name_or_id)
        if not concept:
            try:
                concept = store.get_concept(uuid.UUID(name_or_id))
            except ValueError:
                pass
        if not concept:
            return json.dumps({"error": f"Concept '{name_or_id}' not found"})

        edges = store.get_edges(concept.id)
        edge_data = []
        for e in edges:
            other_id = e.target if e.source == concept.id else e.source
            other = store.get_concept(other_id)
            direction = "outgoing" if e.source == concept.id else "incoming"
            edge_data.append({
                "edge_type": e.edge_type,
                "direction": direction,
                "neighbor": other.name if other else str(other_id),
            })

        docs = store.get_documents_for_concept(concept.id)
        doc_summaries = [
            {"id": str(d.id), "summary": d.summary, "confidence": d.confidence}
            for d in docs
        ]

        return json.dumps({
            "name": concept.name,
            "type": concept.type,
            "id": str(concept.id),
            "edges": edge_data,
            "documents": doc_summaries,
            "code_anchors": [
                {"symbol": a.symbol, "file_path": a.file_path}
                for a in concept.code_anchors
            ],
        })

    @mcp.tool()
    def traverse(
        start: str,
        edge_types: str | None = None,
        max_hops: int = 2,
        direction: str = "outgoing",
    ) -> str:
        """Walk the knowledge graph from a concept.

        USE THIS TOOL WHEN: You know a concept and want to understand what's
        around it — its dependencies, what it owns, what implements it.

        PARAMETERS:
        - start: Concept name or ID
        - edge_types: Comma-separated list to filter (e.g., "depends-on,owns")
        - max_hops: How far to walk (default 2)
        - direction: "outgoing", "incoming", or "both"

        RETURNS: Connected concepts with summaries and the edges between them.
        """
        concept = store.get_concept(start)
        if not concept:
            return json.dumps({"error": f"Concept '{start}' not found"})

        type_list = edge_types.split(",") if edge_types else None
        result = graph_traverse(
            store, concept.id,
            max_hops=max_hops, edge_types=type_list, direction=direction,
        )

        concepts_data = []
        for c in result.concepts:
            docs = store.get_documents_for_concept(c.id)
            summary = docs[0].summary if docs else ""
            concepts_data.append({
                "name": c.name, "type": c.type, "summary": summary,
            })

        edges_data = [
            {
                "source": str(e.source), "target": str(e.target),
                "edge_type": e.edge_type,
            }
            for e in result.edges
        ]

        return json.dumps({"concepts": concepts_data, "edges": edges_data})

    # --- Write Tools ---

    @mcp.tool()
    def create_concept(
        name: str,
        type: str,
        root_id: str | None = None,
        code_anchors: str | None = None,
    ) -> str:
        """Create a new concept node in the knowledge graph.

        USE THIS TOOL WHEN: You've identified a distinct concept in the codebase
        that should be tracked — a module, pattern, subsystem, or design decision.

        PARAMETERS:
        - name: Human-readable, unique name
        - type: module, pattern, subsystem, decision, utility, etc.
        - code_anchors: JSON array of {symbol, file_path, content_hash} objects
        """
        anchors = []
        if code_anchors:
            for a in json.loads(code_anchors):
                anchors.append(CodeAnchor(
                    symbol=a["symbol"], file_path=a["file_path"],
                    content_hash=a["content_hash"],
                    line_range=tuple(a["line_range"]) if a.get("line_range") else None,
                ))
        concept = Concept(
            name=name, type=type,
            root_id=uuid.UUID(root_id) if root_id else None,
            code_anchors=anchors,
        )
        created = store.create_concept(concept)
        return json.dumps({"id": str(created.id), "name": created.name})

    @mcp.tool()
    def create_edge(
        source: str, target: str, edge_type: str,
        metadata: str | None = None,
    ) -> str:
        """Create a typed edge between two concepts.

        EDGE TYPES: depends-on, implements, owns, extends, relates-to, supersedes
        Source and target are concept names or IDs.
        """
        src = store.get_concept(source)
        tgt = store.get_concept(target)
        if not src:
            return json.dumps({"error": f"Source concept '{source}' not found"})
        if not tgt:
            return json.dumps({"error": f"Target concept '{target}' not found"})
        edge = Edge(
            source=src.id, target=tgt.id, edge_type=edge_type,
            metadata=json.loads(metadata) if metadata else None,
        )
        created = store.create_edge(edge)
        return json.dumps({"id": str(created.id)})

    @mcp.tool()
    def create_document(
        concept_name: str,
        content: str,
        summary: str,
        code_references: str | None = None,
        confidence: float = 1.0,
    ) -> str:
        """Create a knowledge document attached to a concept.

        This is the primary deliverable of librarian work. The document should
        explain what the concept is, how it works, and why it's built that way.

        PARAMETERS:
        - concept_name: The concept this document explains
        - content: Markdown content — be specific, reference code, avoid vague filler
        - summary: Short abstract (1-2 sentences) for search results
        - code_references: JSON array of {symbol, file_path, content_hash}
        - confidence: 0.0-1.0, your confidence in the document's accuracy
        """
        concept = store.get_concept(concept_name)
        if not concept:
            return json.dumps({"error": f"Concept '{concept_name}' not found"})

        refs = []
        if code_references:
            for r in json.loads(code_references):
                refs.append(CodeReference(
                    symbol=r["symbol"], file_path=r["file_path"],
                    content_hash=r["content_hash"],
                    line_range=tuple(r["line_range"]) if r.get("line_range") else None,
                ))

        # Generate embedding for the summary
        try:
            embedding = embedder.embed(summary)
        except Exception:
            embedding = None

        doc = Document(
            concept_id=concept.id, content=content, summary=summary,
            code_references=refs, embedding=embedding, confidence=confidence,
        )
        created = store.create_document(doc)
        return json.dumps({"id": str(created.id), "concept": concept.name})

    @mcp.tool()
    def flag_stale(concept_name: str, reason: str) -> str:
        """Mark a concept as needing review.

        USE THIS TOOL WHEN: You notice that a concept's information may be
        outdated — the code has changed, the description doesn't match reality,
        or the document seems wrong.
        """
        concept = store.get_concept(concept_name)
        if not concept:
            return json.dumps({"error": f"Concept '{concept_name}' not found"})
        docs = store.get_documents_for_concept(concept.id)
        for doc in docs:
            doc.staleness_score = 1.0
            store.update_document(doc)
        return json.dumps({"flagged": concept_name, "reason": reason})

    @mcp.tool()
    def update_concept(name_or_id: str, new_name: str | None = None, new_type: str | None = None) -> str:
        """Update an existing concept's name or type."""
        concept = store.get_concept(name_or_id)
        if not concept:
            return json.dumps({"error": f"Concept '{name_or_id}' not found"})
        if new_name:
            concept.name = new_name
        if new_type:
            concept.type = new_type
        store.update_concept(concept)
        return json.dumps({"id": str(concept.id), "name": concept.name})

    @mcp.tool()
    def update_document(doc_id: str, content: str | None = None, summary: str | None = None) -> str:
        """Update a document's content or summary."""
        doc = store.get_document(uuid.UUID(doc_id))
        if not doc:
            return json.dumps({"error": f"Document '{doc_id}' not found"})
        if content:
            doc.content = content
        if summary:
            doc.summary = summary
            try:
                doc.embedding = embedder.embed(summary)
            except Exception:
                pass
        store.update_document(doc)
        return json.dumps({"id": str(doc.id)})

    @mcp.tool()
    def delete_concept(name_or_id: str) -> str:
        """Delete a concept and its associated documents and edges."""
        concept = store.get_concept(name_or_id)
        if not concept:
            return json.dumps({"error": f"Concept '{name_or_id}' not found"})
        store.delete_concept(concept.id)
        return json.dumps({"deleted": name_or_id})

    @mcp.tool()
    def delete_document(doc_id: str) -> str:
        """Delete a document."""
        store.delete_document(uuid.UUID(doc_id))
        return json.dumps({"deleted": doc_id})

    @mcp.tool()
    def delete_edge(edge_id: str) -> str:
        """Delete an edge between concepts."""
        store.delete_edge(uuid.UUID(edge_id))
        return json.dumps({"deleted": edge_id})

    @mcp.tool()
    def update_edge(edge_id: str, edge_type: str | None = None, metadata: str | None = None) -> str:
        """Update an edge's type or metadata."""
        edges = store._conn.execute("SELECT * FROM edges WHERE id=?", (edge_id,)).fetchone()
        if not edges:
            return json.dumps({"error": f"Edge '{edge_id}' not found"})
        edge = Edge(
            id=uuid.UUID(edges["id"]), source=uuid.UUID(edges["source"]),
            target=uuid.UUID(edges["target"]), edge_type=edges["edge_type"],
        )
        if edge_type:
            edge.edge_type = edge_type
        if metadata:
            edge.metadata = json.loads(metadata)
        store.update_edge(edge)
        return json.dumps({"id": str(edge.id)})

    return mcp


def main():
    """Entry point for apriori-mcp command."""
    import sys

    from apriori.core.config import load_app_config, get_data_dir
    from apriori.embedding.openai import OpenAIEmbeddingProvider

    # Determine workspace from args or env
    workspace = sys.argv[1] if len(sys.argv) > 1 else "default"
    config = load_app_config()
    db_path = get_data_dir() / "workspaces" / workspace / "apriori.db"

    if not db_path.parent.exists():
        print(f"Workspace '{workspace}' not found. Run 'apriori init' first.", file=sys.stderr)
        sys.exit(1)

    store = SQLiteStorage(db_path)
    embedder = OpenAIEmbeddingProvider(model=config.embedding.model)
    server = create_server(store=store, embedder=embedder)
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/mcp/test_server.py -v`
Expected: All 5 tests PASS. Note: the `_tool_manager.list_tools()` accessor may differ depending on the MCP SDK version. If it fails, check the FastMCP API and adjust the test to use the correct method for listing registered tools.

- [ ] **Step 5: Commit**

```bash
git add apriori/mcp/server.py tests/mcp/test_server.py
git commit -m "feat: MCP server with read and write tools for agents"
```

---

### Task 15: Librarian Priorities

**Files:**
- Create: `apriori/librarian/priorities.py`
- Create: `tests/librarian/test_priorities.py` (create `tests/librarian/__init__.py` too)

- [ ] **Step 1: Write priority computation tests**

```python
import uuid

import pytest

from apriori.core.models import Concept, Document, QueryLog
from apriori.feedback.logger import FeedbackLogger
from apriori.librarian.priorities import compute_priorities
from apriori.storage.sqlite import SQLiteStorage


@pytest.fixture
def priority_store(tmp_dir):
    store = SQLiteStorage(tmp_dir / "test.db")
    feedback = FeedbackLogger(store)
    return store, feedback


def test_gaps_are_highest_priority(priority_store):
    store, feedback = priority_store
    # Create a gap — search with no results
    feedback.log_search("rate limiting", "semantic", [])
    feedback.log_search("rate limiting", "keyword", [])
    priorities = compute_priorities(store)
    assert len(priorities) > 0
    assert priorities[0]["type"] == "gap"
    assert "rate limiting" in priorities[0]["query"]


def test_stale_concepts_prioritized(priority_store):
    store, feedback = priority_store
    c = store.create_concept(Concept(name="Auth", type="module"))
    doc = Document(
        concept_id=c.id, content="Old info", summary="Auth",
        staleness_score=1.0,
    )
    store.create_document(doc)
    # Also make it high-demand
    feedback.log_search("auth", "keyword", [c.id])
    feedback.log_followup(store.get_query_logs()[0].id, c.id)

    priorities = compute_priorities(store)
    stale_items = [p for p in priorities if p["type"] == "stale"]
    assert len(stale_items) > 0


def test_high_demand_without_documents(priority_store):
    store, feedback = priority_store
    c = store.create_concept(Concept(name="Auth", type="module"))
    # Concept exists but has no documents
    feedback.log_search("auth", "keyword", [c.id])
    priorities = compute_priorities(store)
    shallow_items = [p for p in priorities if p["type"] == "shallow"]
    assert len(shallow_items) > 0


def test_empty_system_returns_empty(priority_store):
    store, _ = priority_store
    priorities = compute_priorities(store)
    assert priorities == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/librarian/test_priorities.py -v`
Expected: FAIL — import error

- [ ] **Step 3: Implement priority computation**

```python
"""Pre-computed demand metrics for librarian work prioritization."""

from __future__ import annotations

from collections import Counter

from apriori.feedback.logger import FeedbackLogger
from apriori.storage.sqlite import SQLiteStorage


def compute_priorities(store: SQLiteStorage) -> list[dict]:
    """Compute a prioritized work list for the librarian.

    Priority order:
    1. Gaps — searches with no results (knowledge doesn't exist)
    2. Stale + high-demand — concepts with stale docs that agents use
    3. Shallow — concepts with no documents that agents reference
    4. Low-quality — results returned but not followed up on
    """
    feedback = FeedbackLogger(store)
    priorities: list[dict] = []

    # 1. Gaps
    gaps = feedback.get_gaps()
    for gap in gaps:
        priorities.append({
            "type": "gap",
            "priority": 1.0,
            "query": gap["query"],
            "search_count": gap["count"],
            "description": f"Agents searched for '{gap['query']}' {gap['count']} time(s) with no results",
        })

    # 2. Stale concepts
    concepts = store.list_concepts()
    for concept in concepts:
        docs = store.get_documents_for_concept(concept.id)
        stale_docs = [d for d in docs if d.staleness_score > 0.5]
        if stale_docs:
            priorities.append({
                "type": "stale",
                "priority": 0.8,
                "concept_id": str(concept.id),
                "concept_name": concept.name,
                "description": f"Concept '{concept.name}' has {len(stale_docs)} stale document(s)",
            })

    # 3. Shallow concepts (no documents)
    for concept in concepts:
        docs = store.get_documents_for_concept(concept.id)
        if not docs:
            priorities.append({
                "type": "shallow",
                "priority": 0.6,
                "concept_id": str(concept.id),
                "concept_name": concept.name,
                "description": f"Concept '{concept.name}' has no documents",
            })

    # Sort by priority descending
    priorities.sort(key=lambda p: p["priority"], reverse=True)
    return priorities
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/librarian/test_priorities.py -v`
Expected: All 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add apriori/librarian/priorities.py tests/librarian/test_priorities.py tests/librarian/__init__.py
git commit -m "feat: librarian priority computation from feedback metrics"
```

---

### Task 16: Quality Gate

**Files:**
- Create: `apriori/librarian/quality_gate.py`
- Create: `tests/librarian/test_quality_gate.py`

- [ ] **Step 1: Write quality gate tests**

```python
import uuid

import pytest

from apriori.core.config import QualityGateConfig
from apriori.core.models import CodeReference, Document
from apriori.librarian.quality_gate import evaluate_document


def test_passing_document():
    doc = Document(
        concept_id=uuid.uuid4(),
        content="validate_jwt() in src/auth.py checks RS256 signatures. "
                "It returns HTTP 401 for expired tokens.",
        summary="JWT validation logic",
        code_references=[
            CodeReference(symbol="validate_jwt", file_path="src/auth.py", content_hash="abc"),
        ],
    )
    result = evaluate_document(doc, QualityGateConfig())
    assert result["passed"] is True
    assert "report_card" in result


def test_failing_document_no_refs():
    doc = Document(
        concept_id=uuid.uuid4(),
        content="This is an important part of the system. It helps with various things. "
                "It is used for processing. " * 20,
        summary="Something",
    )
    result = evaluate_document(doc, QualityGateConfig())
    assert result["passed"] is False
    assert len(result["failures"]) > 0


def test_custom_thresholds():
    doc = Document(
        concept_id=uuid.uuid4(),
        content="validate() checks things.",
        summary="Validation",
        code_references=[
            CodeReference(symbol="validate", file_path="a.py", content_hash="abc"),
        ],
    )
    strict = QualityGateConfig(
        min_conciseness_ratio=0.99,
        min_code_grounding_score=0.99,
        min_assertion_density=0.99,
    )
    result = evaluate_document(doc, strict)
    assert result["passed"] is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/librarian/test_quality_gate.py -v`
Expected: FAIL — import error

- [ ] **Step 3: Implement quality gate**

```python
"""Quality gate — evaluates librarian output against deterministic thresholds."""

from __future__ import annotations

from apriori.core.config import QualityGateConfig
from apriori.core.metrics import compute_report_card
from apriori.core.models import Document


def evaluate_document(doc: Document, config: QualityGateConfig) -> dict:
    """Evaluate a document against quality thresholds.

    Returns dict with:
    - passed: bool
    - report_card: dict of metric scores
    - failures: list of metrics that failed threshold
    """
    card = compute_report_card(doc)
    failures = []

    checks = [
        ("conciseness_ratio", card["conciseness_ratio"], config.min_conciseness_ratio),
        ("assertion_density", card["assertion_density"], config.min_assertion_density),
        ("code_grounding_score", card["code_grounding_score"], config.min_code_grounding_score),
    ]

    for name, score, threshold in checks:
        if score < threshold:
            failures.append({
                "metric": name,
                "score": score,
                "threshold": threshold,
                "gap": round(threshold - score, 3),
            })

    return {
        "passed": len(failures) == 0,
        "report_card": card,
        "failures": failures,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/librarian/test_quality_gate.py -v`
Expected: All 3 tests PASS

- [ ] **Step 5: Commit**

```bash
git add apriori/librarian/quality_gate.py tests/librarian/test_quality_gate.py
git commit -m "feat: quality gate evaluating documents against configurable thresholds"
```

---

### Task 17: Librarian Agent Orchestration

**Files:**
- Create: `apriori/librarian/agent.py`
- Create: `apriori/librarian/reviewer.py`

This task creates the librarian orchestration and reviewer stubs. These are LLM-powered agents that will be invoked via the OpenAI or Anthropic API. The full agent loop involves prompt engineering that should be iterated on with real codebases. This task creates the structural framework.

- [ ] **Step 1: Implement librarian agent orchestration**

```python
"""Librarian agent orchestration — bootstrap, deepen, and reactive modes."""

from __future__ import annotations

import json
from pathlib import Path

from apriori.core.config import AppConfig, load_app_config
from apriori.librarian.priorities import compute_priorities
from apriori.librarian.quality_gate import evaluate_document
from apriori.storage.sqlite import SQLiteStorage


class LibrarianAgent:
    """Orchestrates librarian work cycles.

    This class manages the librarian's workflow: fetching priorities,
    loading local context, and coordinating the quality gate pipeline.
    The actual LLM calls for research and document writing are delegated
    to the caller (CLI command or automation harness).
    """

    def __init__(self, store: SQLiteStorage, config: AppConfig | None = None):
        self._store = store
        self._config = config or load_app_config()

    def get_next_work_item(self) -> dict | None:
        """Fetch the highest-priority work item."""
        priorities = compute_priorities(self._store)
        return priorities[0] if priorities else None

    def get_local_context(self, concept_name: str | None = None) -> dict:
        """Load context for the librarian to work with.

        Returns:
        - concept_list: all concept names and types
        - neighborhood: concepts and edges within 2 hops (if concept_name given)
        - document_summaries: summaries for neighborhood concepts
        """
        concepts = self._store.list_concepts()
        concept_list = [{"name": c.name, "type": c.type} for c in concepts]

        neighborhood = None
        doc_summaries = []
        if concept_name:
            concept = self._store.get_concept(concept_name)
            if concept:
                from apriori.graph.traversal import traverse
                result = traverse(self._store, concept.id, max_hops=2)
                neighborhood = {
                    "concepts": [{"name": c.name, "type": c.type} for c in result.concepts],
                    "edges": [
                        {"source": str(e.source), "target": str(e.target), "type": e.edge_type}
                        for e in result.edges
                    ],
                }
                for c in result.concepts:
                    docs = self._store.get_documents_for_concept(c.id)
                    for d in docs:
                        doc_summaries.append({
                            "concept": c.name,
                            "summary": d.summary,
                            "confidence": d.confidence,
                            "staleness": d.staleness_score,
                        })

        return {
            "concept_list": concept_list,
            "neighborhood": neighborhood,
            "document_summaries": doc_summaries,
        }

    def validate_document(self, document) -> dict:
        """Run quality gate on a document. Returns evaluation result."""
        return evaluate_document(document, self._config.quality_gate)

    def get_review_queue_space(self) -> int:
        """How many more items can be added to the review queue."""
        current = self._store.count_review_items(resolved=False)
        return max(0, self._config.librarian.review_queue_cap - current)
```

- [ ] **Step 2: Implement reviewer agent stub**

```python
"""Reviewer agent — evaluates librarian output that passes the quality gate.

This is a stub that defines the interface. The actual LLM evaluation
will be implemented when integrating with an LLM provider for the
review pass.
"""

from __future__ import annotations

from apriori.core.models import Document


class ReviewResult:
    def __init__(self, approved: bool, feedback: str = ""):
        self.approved = approved
        self.feedback = feedback


def review_document(
    document: Document,
    report_card: dict[str, float],
    context: dict | None = None,
) -> ReviewResult:
    """Review a document that has passed the quality gate.

    This function will be backed by an LLM call that evaluates:
    - Does the document accurately describe the code?
    - Would this help an agent do its job?
    - Does it duplicate or contradict existing knowledge?

    For now, auto-approves. The LLM integration is a configuration
    concern that depends on the deployment environment.
    """
    # TODO: Replace with actual LLM-based review when integrating
    # with an LLM provider. For MVP, auto-approve documents that
    # pass the deterministic quality gate.
    return ReviewResult(approved=True, feedback="Auto-approved (reviewer not yet configured)")
```

- [ ] **Step 3: Add deepen command to CLI**

Add to `apriori/cli/main.py`:

```python
@cli.command()
@click.option("--workspace", required=True, help="Workspace name")
@click.option("--mode", default="deepen", type=click.Choice(["bootstrap", "deepen"]))
def deepen(workspace: str, mode: str):
    """Kick off a librarian work cycle."""
    from apriori.librarian.agent import LibrarianAgent

    store = _get_store(workspace)
    agent = LibrarianAgent(store)
    work_item = agent.get_next_work_item()

    if not work_item:
        click.echo("No work items found. Knowledge base is up to date.")
        store.close()
        return

    click.echo(f"Next work item [{work_item['type']}]:")
    click.echo(f"  {work_item['description']}")
    click.echo(f"  Priority: {work_item['priority']}")

    if work_item.get("concept_name"):
        ctx = agent.get_local_context(work_item["concept_name"])
        click.echo(f"\nLocal context: {len(ctx['concept_list'])} concepts in graph")
        if ctx["neighborhood"]:
            click.echo(f"  Neighborhood: {len(ctx['neighborhood']['concepts'])} concepts, {len(ctx['neighborhood']['edges'])} edges")

    store.close()
```

- [ ] **Step 4: Run full test suite**

Run: `pytest -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add apriori/librarian/agent.py apriori/librarian/reviewer.py apriori/cli/main.py
git commit -m "feat: librarian agent orchestration with quality gate pipeline"
```

---

### Task 18: Integration Test

**Files:**
- Create: `tests/test_integration.py`

- [ ] **Step 1: Write end-to-end integration test**

```python
"""End-to-end integration test: create workspace, add knowledge, search it."""

import uuid
from unittest.mock import MagicMock

import pytest

from apriori.core.models import CodeAnchor, CodeReference, Concept, Document, Edge
from apriori.feedback.logger import FeedbackLogger
from apriori.graph.traversal import traverse
from apriori.librarian.agent import LibrarianAgent
from apriori.librarian.quality_gate import evaluate_document
from apriori.core.config import QualityGateConfig
from apriori.search.engine import SearchEngine
from apriori.storage.sqlite import SQLiteStorage


@pytest.fixture
def workspace(tmp_dir):
    store = SQLiteStorage(tmp_dir / "apriori.db")
    store.add_root("/home/user/work/api", "api")
    mock_embedder = MagicMock()
    mock_embedder.embed.return_value = [0.1] * 1536
    return store, mock_embedder


def test_full_lifecycle(workspace):
    store, embedder = workspace

    # 1. Librarian creates concepts
    auth = store.create_concept(Concept(
        name="Auth Middleware", type="module",
        code_anchors=[
            CodeAnchor(symbol="validate_jwt", file_path="src/auth/jwt.py",
                       content_hash="sha256:abc123", line_range=(10, 50)),
        ],
    ))
    billing = store.create_concept(Concept(name="Billing Engine", type="subsystem"))

    # 2. Librarian creates edges
    store.create_edge(Edge(source=billing.id, target=auth.id, edge_type="depends-on"))

    # 3. Librarian writes documents
    doc = Document(
        concept_id=auth.id,
        content="validate_jwt() in src/auth/jwt.py checks RS256 signatures. "
                "It reads the public key from config and verifies exp, iss, and aud claims. "
                "Returns HTTP 401 with AUTH_EXPIRED code for expired tokens.",
        summary="JWT validation middleware for API authentication",
        code_references=[
            CodeReference(symbol="validate_jwt", file_path="src/auth/jwt.py",
                          content_hash="sha256:abc123"),
        ],
        embedding=embedder.embed("JWT validation"),
    )

    # 4. Quality gate passes
    result = evaluate_document(doc, QualityGateConfig())
    assert result["passed"], f"Quality gate failed: {result['failures']}"

    store.create_document(doc)

    # 5. Task agent searches
    engine = SearchEngine(store=store, embedder=embedder)
    feedback = FeedbackLogger(store)

    results = engine.search("JWT", mode="keyword")
    assert len(results) >= 1
    assert results[0]["concept_name"] == "Auth Middleware"

    # Log the search
    concept_ids = [uuid.UUID(r["concept_id"]) for r in results]
    query_id = feedback.log_search("JWT", "keyword", concept_ids)

    # 6. Task agent fetches document
    docs = store.get_documents_for_concept(auth.id)
    assert len(docs) == 1
    assert "validate_jwt()" in docs[0].content
    feedback.log_followup(query_id, auth.id)

    # 7. Graph traversal
    result = traverse(store, billing.id, max_hops=1, direction="outgoing")
    neighbor_names = {c.name for c in result.concepts}
    assert "Auth Middleware" in neighbor_names

    # 8. Priorities reflect the activity
    agent = LibrarianAgent(store)
    # Billing has no docs — should show as shallow
    priorities = agent.get_next_work_item()
    assert priorities is not None

    # 9. Local context works
    ctx = agent.get_local_context("Auth Middleware")
    assert len(ctx["concept_list"]) == 2
    assert ctx["neighborhood"] is not None
```

- [ ] **Step 2: Run the integration test**

Run: `pytest tests/test_integration.py -v`
Expected: PASS

- [ ] **Step 3: Run full test suite**

Run: `pytest -v`
Expected: All tests PASS

- [ ] **Step 4: Commit**

```bash
git add tests/test_integration.py
git commit -m "test: end-to-end integration test for full knowledge base lifecycle"
```

---

### Task 19: Final Cleanup and README

**Files:**
- Modify: `README.md`
- Modify: `.gitignore`

- [ ] **Step 1: Update README**

```markdown
# A-Priori

Self-constructing knowledge base for AI agents working with codebases.

## What It Does

A-Priori builds and maintains a knowledge base about your codebase through dedicated "librarian" agents. Task agents query it via MCP tools for fast, pre-digested context — turning exploration into retrieval.

## Quick Start

```bash
pip install -e ".[dev]"

# Create a workspace
apriori init ~/work --name mywork

# Add directories to track
apriori add ~/work/api-service --workspace mywork

# Check status
apriori status --workspace mywork

# Search
apriori search "authentication" --workspace mywork --mode keyword
```

## MCP Server

```bash
apriori-mcp mywork
```

Add to your MCP client config:

```json
{
  "mcpServers": {
    "a-priori": {
      "command": "apriori-mcp",
      "args": ["mywork"]
    }
  }
}
```

## Architecture

- **Thin concept graph** — fast structural navigation (what exists, how it connects)
- **Rich documents** — synthesized knowledge (what it does, how it works, why)
- **Librarian agents** — build and maintain knowledge autonomously
- **Passive feedback** — task agent queries drive librarian priorities
- **Quality gate** — deterministic metrics enforce content standards

## Development

```bash
pip install -e ".[dev]"
pytest -v
```
```

- [ ] **Step 2: Update .gitignore**

```gitignore
.superpowers/
__pycache__/
*.pyc
*.egg-info/
dist/
build/
.pytest_cache/
*.db
```

- [ ] **Step 3: Run final test suite**

Run: `pytest -v`
Expected: All tests PASS

- [ ] **Step 4: Commit**

```bash
git add README.md .gitignore
git commit -m "docs: update README with quick start and architecture overview"
```
