# A-Priori MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an agent-first MCP knowledge base that maintains a concept graph for a codebase, with local storage, unified search, and a self-directing deepening agent.

**Architecture:** Core Python library (`apriori`) with thin shells for MCP server and deepening agent. Local SQLite + sqlite-vec for queries, flat YAML files as portable source of truth. Storage abstraction protocol enables future backend swaps.

**Tech Stack:** Python 3.11+, SQLite + sqlite-vec, PyYAML, MCP Python SDK (`mcp`), OpenAI API (embeddings), pytest

**Spec:** `docs/superpowers/specs/2026-03-25-a-priori-system-design.md`

---

## File Structure

```
apriori/
├── __init__.py
├── core/
│   ├── __init__.py
│   ├── models.py              — Concept, Edge, CodeReference, WorkItem, Subgraph dataclasses
│   ├── store.py               — KnowledgeStore protocol (abstract interface)
│   └── config.py              — Config loading, defaults, validation
├── graph/
│   ├── __init__.py
│   ├── engine.py              — BFS/DFS traversal, subgraph extraction
│   └── query.py               — Unified search: mode routing, filter composition
├── embedding/
│   ├── __init__.py
│   ├── engine.py              — EmbeddingEngine protocol
│   └── openai.py              — OpenAI implementation
├── storage/
│   ├── __init__.py
│   ├── local.py               — LocalStore (SQLite + sqlite-vec)
│   ├── flatfile.py            — YAML flat file read/write
│   └── schema.sql             — SQLite schema DDL
├── references/
│   ├── __init__.py
│   └── resolver.py            — Code reference repair chain
├── maintenance/
│   ├── __init__.py
│   ├── backlog.py             — Work item CRUD, priority scoring
│   ├── differ.py              — Git diff → work items
│   └── bootstrap.py           — Initial repo crawl
└── shells/
    ├── __init__.py
    ├── mcp_server.py          — MCP server shell
    └── deepening_agent.py     — Deepening loop shell

tests/
├── conftest.py                — Shared fixtures (tmp dirs, sample concepts, store instances)
├── core/
│   ├── test_models.py
│   └── test_config.py
├── storage/
│   ├── test_flatfile.py
│   └── test_local.py
├── graph/
│   ├── test_engine.py
│   └── test_query.py
├── embedding/
│   └── test_openai.py
├── references/
│   └── test_resolver.py
├── maintenance/
│   ├── test_backlog.py
│   ├── test_differ.py
│   └── test_bootstrap.py
└── shells/
    └── test_mcp_server.py

pyproject.toml                 — Project metadata, dependencies, entry points
apriori.config.yaml            — Default config (used for development)
prompts/
└── deepen.md                  — Default deepening agent system prompt
```

---

### Task 1: Project Scaffolding

**Files:**
- Create: `pyproject.toml`
- Create: `apriori/__init__.py`
- Create: `tests/conftest.py`

- [ ] **Step 1: Create pyproject.toml**

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "a-priori"
version = "0.1.0"
description = "Agent-first MCP knowledge base for codebases"
requires-python = ">=3.11"
dependencies = [
    "pyyaml>=6.0",
    "sqlite-vec>=0.1.6",
    "mcp>=1.0.0",
    "openai>=1.0.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
]

[project.scripts]
apriori-mcp = "apriori.shells.mcp_server:main"
apriori-deepen = "apriori.shells.deepening_agent:main"
```

- [ ] **Step 2: Create package init**

```python
# apriori/__init__.py
"""A-Priori: Agent-first MCP knowledge base for codebases."""
```

- [ ] **Step 3: Create directory structure with __init__.py files**

Create empty `__init__.py` in each subpackage: `core/`, `graph/`, `embedding/`, `storage/`, `references/`, `maintenance/`, `shells/`. Also create `tests/` with empty `__init__.py` files mirroring the structure.

- [ ] **Step 4: Create tests/conftest.py with basic fixtures**

```python
# tests/conftest.py
import os
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def tmp_store_path(tmp_path):
    """Temporary directory for knowledge store files."""
    store_dir = tmp_path / "store"
    store_dir.mkdir()
    (store_dir / "graph").mkdir()
    return store_dir


@pytest.fixture
def sample_repo(tmp_path):
    """Temporary git repo with sample files for testing."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "src").mkdir()
    (repo / "src" / "main.py").write_text(
        "def hello():\n    return 'world'\n"
    )
    (repo / "src" / "utils.py").write_text(
        "def add(a, b):\n    return a + b\n"
    )
    return repo
```

- [ ] **Step 5: Install in dev mode and verify**

Run: `pip install -e ".[dev]"`
Expected: Installs successfully

- [ ] **Step 6: Run pytest to verify empty test suite works**

Run: `pytest -v`
Expected: "no tests ran" or 0 tests collected, exit code 5 (no tests) — no errors

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml apriori/ tests/
git commit -m "feat: scaffold A-Priori project structure"
```

---

### Task 2: Core Data Models

**Files:**
- Create: `apriori/core/models.py`
- Create: `tests/core/test_models.py`

- [ ] **Step 1: Write tests for data models**

```python
# tests/core/test_models.py
import uuid
from datetime import datetime, timezone

from apriori.core.models import (
    CodeReference,
    Concept,
    Edge,
    Subgraph,
    WorkItem,
    WorkItemType,
)


class TestCodeReference:
    def test_create_code_reference(self):
        ref = CodeReference(
            symbol="validate_amount",
            file_path="src/payments/validate.py",
            content_hash="sha256:abc123",
            semantic_anchor="Validates payment amounts against limits",
            line_range=(45, 80),
        )
        assert ref.symbol == "validate_amount"
        assert ref.file_path == "src/payments/validate.py"
        assert ref.content_hash == "sha256:abc123"
        assert ref.line_range == (45, 80)

    def test_code_reference_optional_line_range(self):
        ref = CodeReference(
            symbol="foo",
            file_path="src/foo.py",
            content_hash="sha256:def456",
            semantic_anchor="Does foo things",
        )
        assert ref.line_range is None


class TestConcept:
    def test_create_concept(self):
        concept = Concept(
            name="Payment Validation",
            description="Validates incoming payment requests.",
        )
        assert concept.name == "Payment Validation"
        assert isinstance(concept.id, uuid.UUID)
        assert concept.labels == set()
        assert concept.code_references == []
        assert concept.created_by == "agent"
        assert concept.verified_by is None
        assert isinstance(concept.created_at, datetime)

    def test_concept_with_labels(self):
        concept = Concept(
            name="Auth Flow",
            description="Authentication flow.",
            labels={"auto-generated", "needs-review"},
        )
        assert "auto-generated" in concept.labels
        assert "needs-review" in concept.labels

    def test_concept_slug(self):
        concept = Concept(
            name="Payment Validation",
            description="Test",
        )
        assert concept.slug == "payment-validation"

    def test_concept_slug_special_chars(self):
        concept = Concept(
            name="OAuth 2.0 / OIDC Integration",
            description="Test",
        )
        slug = concept.slug
        assert " " not in slug
        assert "/" not in slug
        assert "." not in slug


class TestEdge:
    def test_create_edge(self):
        source_id = uuid.uuid4()
        target_id = uuid.uuid4()
        edge = Edge(
            source=source_id,
            target=target_id,
            edge_type="depends-on",
        )
        assert edge.source == source_id
        assert edge.target == target_id
        assert edge.edge_type == "depends-on"
        assert edge.metadata is None

    def test_edge_with_metadata(self):
        edge = Edge(
            source=uuid.uuid4(),
            target=uuid.uuid4(),
            edge_type="relates-to",
            metadata={"confidence": 0.85},
        )
        assert edge.metadata["confidence"] == 0.85


class TestWorkItem:
    def test_create_work_item(self):
        item = WorkItem(
            item_type=WorkItemType.VERIFY_CONCEPT,
            description="Re-verify Auth Flow concept",
            concept_id=uuid.uuid4(),
        )
        assert item.item_type == WorkItemType.VERIFY_CONCEPT
        assert item.priority_score == 0.0
        assert item.resolved is False


class TestSubgraph:
    def test_empty_subgraph(self):
        sg = Subgraph(concepts=[], edges=[])
        assert len(sg.concepts) == 0
        assert len(sg.edges) == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/core/test_models.py -v`
Expected: FAIL — cannot import `apriori.core.models`

- [ ] **Step 3: Implement data models**

```python
# apriori/core/models.py
"""Core data models for A-Priori knowledge graph."""

import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _new_id() -> uuid.UUID:
    return uuid.uuid4()


def _slugify(name: str) -> str:
    slug = name.lower()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"[\s]+", "-", slug).strip("-")
    slug = re.sub(r"-+", "-", slug)
    return slug


@dataclass
class CodeReference:
    symbol: str
    file_path: str
    content_hash: str
    semantic_anchor: str
    line_range: Optional[tuple[int, int]] = None


@dataclass
class Concept:
    name: str
    description: str
    id: uuid.UUID = field(default_factory=_new_id)
    labels: set[str] = field(default_factory=set)
    code_references: list[CodeReference] = field(default_factory=list)
    created_by: str = "agent"
    verified_by: Optional[str] = None
    last_verified: Optional[datetime] = None
    created_at: datetime = field(default_factory=_now)
    updated_at: datetime = field(default_factory=_now)

    @property
    def slug(self) -> str:
        return _slugify(self.name)


@dataclass
class Edge:
    source: uuid.UUID
    target: uuid.UUID
    edge_type: str
    id: uuid.UUID = field(default_factory=_new_id)
    metadata: Optional[dict] = None
    created_at: datetime = field(default_factory=_now)


class WorkItemType(Enum):
    INVESTIGATE_FILE = "investigate_file"
    VERIFY_CONCEPT = "verify_concept"
    EVALUATE_RELATIONSHIP = "evaluate_relationship"
    REPORTED_GAP = "reported_gap"
    REVIEW_CONCEPT = "review_concept"


@dataclass
class WorkItem:
    item_type: WorkItemType
    description: str
    id: uuid.UUID = field(default_factory=_new_id)
    concept_id: Optional[uuid.UUID] = None
    file_path: Optional[str] = None
    priority_score: float = 0.0
    resolved: bool = False
    created_at: datetime = field(default_factory=_now)


@dataclass
class Subgraph:
    concepts: list[Concept]
    edges: list[Edge]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/core/test_models.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add apriori/core/models.py tests/core/test_models.py
git commit -m "feat: add core data models (Concept, Edge, CodeReference, WorkItem)"
```

---

### Task 3: Configuration System

**Files:**
- Create: `apriori/core/config.py`
- Create: `apriori.config.yaml`
- Create: `tests/core/test_config.py`

- [ ] **Step 1: Write tests for configuration**

```python
# tests/core/test_config.py
from pathlib import Path

from apriori.core.config import AprioriConfig, load_config


class TestAprioriConfig:
    def test_default_config(self):
        config = AprioriConfig()
        assert config.project.name == ""
        assert config.storage.backend == "local"
        assert len(config.graph.edge_types) == 6
        assert config.embeddings.provider == "openai"
        assert config.priority_weights.staleness == 0.3

    def test_edge_type_names(self):
        config = AprioriConfig()
        names = [et.name for et in config.graph.edge_types]
        assert "depends-on" in names
        assert "implements" in names
        assert "relates-to" in names
        assert "owned-by" in names
        assert "supersedes" in names
        assert "extends" in names

    def test_valid_edge_type_check(self):
        config = AprioriConfig()
        assert config.is_valid_edge_type("depends-on") is True
        assert config.is_valid_edge_type("nonexistent") is False


class TestLoadConfig:
    def test_load_from_yaml(self, tmp_path):
        config_file = tmp_path / "apriori.config.yaml"
        config_file.write_text(
            "project:\n  name: test-project\n  repo_path: .\n"
        )
        config = load_config(config_file)
        assert config.project.name == "test-project"

    def test_load_missing_file_returns_defaults(self, tmp_path):
        config = load_config(tmp_path / "nonexistent.yaml")
        assert config.project.name == ""
        assert config.storage.backend == "local"

    def test_partial_override(self, tmp_path):
        config_file = tmp_path / "apriori.config.yaml"
        config_file.write_text(
            "priority_weights:\n  staleness: 0.5\n"
        )
        config = load_config(config_file)
        assert config.priority_weights.staleness == 0.5
        # Other defaults preserved
        assert config.priority_weights.needs_review == 0.25
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/core/test_config.py -v`
Expected: FAIL — cannot import `apriori.core.config`

- [ ] **Step 3: Implement configuration**

```python
# apriori/core/config.py
"""Configuration loading and defaults for A-Priori."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml


@dataclass
class EdgeTypeConfig:
    name: str
    description: str


DEFAULT_EDGE_TYPES = [
    EdgeTypeConfig("depends-on", "X requires Y to function"),
    EdgeTypeConfig("implements", "X is the concrete realization of Y"),
    EdgeTypeConfig("relates-to", "Generic association"),
    EdgeTypeConfig("owned-by", "Person or team responsible"),
    EdgeTypeConfig("supersedes", "X replaced Y"),
    EdgeTypeConfig("extends", "X builds on or specializes Y"),
]


@dataclass
class ProjectConfig:
    name: str = ""
    repo_path: str = "."
    store_path: str = ""


@dataclass
class StorageConfig:
    backend: str = "local"


@dataclass
class GraphConfig:
    edge_types: list[EdgeTypeConfig] = field(
        default_factory=lambda: list(DEFAULT_EDGE_TYPES)
    )


@dataclass
class EmbeddingsConfig:
    provider: str = "openai"
    model: str = "text-embedding-3-small"


@dataclass
class SchedulingConfig:
    diff_check: str = "*/30 * * * *"
    deepening_loop: str = "0 */4 * * *"


@dataclass
class PriorityWeightsConfig:
    staleness: float = 0.3
    needs_review: float = 0.25
    coverage_gap: float = 0.25
    git_activity: float = 0.1
    semantic_graph_delta: float = 0.1


@dataclass
class DeepeningAgentConfig:
    max_iterations_per_run: int = 10
    system_prompt_path: str = "prompts/deepen.md"


@dataclass
class AprioriConfig:
    project: ProjectConfig = field(default_factory=ProjectConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)
    graph: GraphConfig = field(default_factory=GraphConfig)
    embeddings: EmbeddingsConfig = field(default_factory=EmbeddingsConfig)
    scheduling: SchedulingConfig = field(default_factory=SchedulingConfig)
    priority_weights: PriorityWeightsConfig = field(
        default_factory=PriorityWeightsConfig
    )
    deepening_agent: DeepeningAgentConfig = field(
        default_factory=DeepeningAgentConfig
    )

    def is_valid_edge_type(self, name: str) -> bool:
        return any(et.name == name for et in self.graph.edge_types)


def _merge_dict(base: dict, override: dict) -> dict:
    """Recursively merge override into base."""
    result = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _merge_dict(result[key], value)
        else:
            result[key] = value
    return result


def _dict_to_config(data: dict) -> AprioriConfig:
    """Build AprioriConfig from a flat dict, applying only present keys."""
    config = AprioriConfig()

    if "project" in data:
        for k, v in data["project"].items():
            setattr(config.project, k, v)

    if "storage" in data:
        for k, v in data["storage"].items():
            setattr(config.storage, k, v)

    if "graph" in data and "edge_types" in data["graph"]:
        config.graph.edge_types = [
            EdgeTypeConfig(name=et["name"], description=et["description"])
            for et in data["graph"]["edge_types"]
        ]

    if "embeddings" in data:
        for k, v in data["embeddings"].items():
            setattr(config.embeddings, k, v)

    if "scheduling" in data:
        for k, v in data["scheduling"].items():
            setattr(config.scheduling, k, v)

    if "priority_weights" in data:
        for k, v in data["priority_weights"].items():
            setattr(config.priority_weights, k, v)

    if "deepening_agent" in data:
        for k, v in data["deepening_agent"].items():
            setattr(config.deepening_agent, k, v)

    return config


def load_config(path: Path) -> AprioriConfig:
    """Load config from YAML file. Missing file returns defaults."""
    if not path.exists():
        return AprioriConfig()

    with open(path) as f:
        data = yaml.safe_load(f) or {}

    return _dict_to_config(data)
```

- [ ] **Step 4: Create default config file**

```yaml
# apriori.config.yaml — A-Priori default configuration
# Every field has a default. This file can be empty and the system works.

project:
  name: "a-priori"
  repo_path: "."
  store_path: "~/.a-priori/a-priori"

storage:
  backend: "local"

graph:
  edge_types:
    - name: "depends-on"
      description: "X requires Y to function"
    - name: "implements"
      description: "X is the concrete realization of Y"
    - name: "relates-to"
      description: "Generic association"
    - name: "owned-by"
      description: "Person or team responsible"
    - name: "supersedes"
      description: "X replaced Y"
    - name: "extends"
      description: "X builds on or specializes Y"

embeddings:
  provider: "openai"
  model: "text-embedding-3-small"

scheduling:
  diff_check: "*/30 * * * *"
  deepening_loop: "0 */4 * * *"

priority_weights:
  staleness: 0.3
  needs_review: 0.25
  coverage_gap: 0.25
  git_activity: 0.1
  semantic_graph_delta: 0.1

deepening_agent:
  max_iterations_per_run: 10
  system_prompt_path: "prompts/deepen.md"
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/core/test_config.py -v`
Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
git add apriori/core/config.py apriori.config.yaml tests/core/test_config.py
git commit -m "feat: add configuration system with YAML loading and defaults"
```

---

### Task 4: Flat File Storage (YAML Read/Write)

**Files:**
- Create: `apriori/storage/flatfile.py`
- Create: `tests/storage/test_flatfile.py`

- [ ] **Step 1: Write tests for flat file operations**

```python
# tests/storage/test_flatfile.py
import uuid
from datetime import datetime, timezone
from pathlib import Path

from apriori.core.models import CodeReference, Concept, Edge
from apriori.storage.flatfile import (
    concept_to_yaml,
    yaml_to_concept,
    read_concept_file,
    write_concept_file,
    read_all_concepts,
)


class TestConceptSerialization:
    def test_round_trip(self):
        concept = Concept(
            name="Payment Validation",
            description="Validates payments.",
            labels={"auto-generated"},
            code_references=[
                CodeReference(
                    symbol="validate_amount",
                    file_path="src/pay.py",
                    content_hash="sha256:abc",
                    semantic_anchor="Validates amounts",
                    line_range=(10, 20),
                )
            ],
        )
        edges = [
            Edge(
                source=concept.id,
                target=uuid.uuid4(),
                edge_type="depends-on",
            )
        ]
        yaml_str = concept_to_yaml(concept, edges)
        restored_concept, restored_edges = yaml_to_concept(yaml_str)

        assert restored_concept.name == concept.name
        assert restored_concept.id == concept.id
        assert restored_concept.description == concept.description
        assert "auto-generated" in restored_concept.labels
        assert len(restored_concept.code_references) == 1
        assert restored_concept.code_references[0].symbol == "validate_amount"
        assert len(restored_edges) == 1
        assert restored_edges[0].edge_type == "depends-on"

    def test_concept_without_optional_fields(self):
        concept = Concept(name="Simple", description="A simple concept.")
        yaml_str = concept_to_yaml(concept, [])
        restored, edges = yaml_to_concept(yaml_str)
        assert restored.name == "Simple"
        assert restored.labels == set()
        assert restored.code_references == []
        assert edges == []


class TestFileOperations:
    def test_write_and_read(self, tmp_store_path):
        graph_dir = tmp_store_path / "graph"
        concept = Concept(
            name="Auth Flow",
            description="Authentication flow.",
        )
        edges = []
        write_concept_file(graph_dir, concept, edges)

        file_path = graph_dir / "auth-flow.yaml"
        assert file_path.exists()

        restored, restored_edges = read_concept_file(file_path)
        assert restored.name == "Auth Flow"
        assert restored.id == concept.id

    def test_read_all_concepts(self, tmp_store_path):
        graph_dir = tmp_store_path / "graph"
        c1 = Concept(name="Concept A", description="First")
        c2 = Concept(name="Concept B", description="Second")
        write_concept_file(graph_dir, c1, [])
        write_concept_file(graph_dir, c2, [])

        all_concepts = read_all_concepts(graph_dir)
        names = {c.name for c, _ in all_concepts}
        assert names == {"Concept A", "Concept B"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/storage/test_flatfile.py -v`
Expected: FAIL — cannot import `apriori.storage.flatfile`

- [ ] **Step 3: Implement flat file storage**

```python
# apriori/storage/flatfile.py
"""YAML flat file read/write for concept graph."""

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import yaml

from apriori.core.models import CodeReference, Concept, Edge


def concept_to_yaml(concept: Concept, edges: list[Edge]) -> str:
    """Serialize a Concept and its outgoing edges to YAML."""
    data = {
        "id": str(concept.id),
        "name": concept.name,
        "description": concept.description,
        "labels": sorted(concept.labels) if concept.labels else [],
        "created_by": concept.created_by,
        "verified_by": concept.verified_by,
        "last_verified": (
            concept.last_verified.isoformat() if concept.last_verified else None
        ),
        "created_at": concept.created_at.isoformat(),
        "updated_at": concept.updated_at.isoformat(),
        "code_references": [
            {
                "symbol": ref.symbol,
                "file_path": ref.file_path,
                "content_hash": ref.content_hash,
                "semantic_anchor": ref.semantic_anchor,
                "line_range": list(ref.line_range) if ref.line_range else None,
            }
            for ref in concept.code_references
        ],
        "edges": [
            {
                "id": str(e.id),
                "target": str(e.target),
                "target_slug": None,  # Populated during write if name lookup available
                "edge_type": e.edge_type,
                "metadata": e.metadata,
                "created_at": e.created_at.isoformat(),
            }
            for e in edges
        ],
    }
    return yaml.dump(data, default_flow_style=False, sort_keys=False)


def concept_to_yaml_with_names(
    concept: Concept, edges: list[Edge], id_to_slug: dict[str, str]
) -> str:
    """Serialize with human-readable slug names for edge targets.
    Falls back to UUID if slug not found."""
    data = {
        "id": str(concept.id),
        "name": concept.name,
        "description": concept.description,
        "labels": sorted(concept.labels) if concept.labels else [],
        "created_by": concept.created_by,
        "verified_by": concept.verified_by,
        "last_verified": (
            concept.last_verified.isoformat() if concept.last_verified else None
        ),
        "created_at": concept.created_at.isoformat(),
        "updated_at": concept.updated_at.isoformat(),
        "code_references": [
            {
                "symbol": ref.symbol,
                "file_path": ref.file_path,
                "content_hash": ref.content_hash,
                "semantic_anchor": ref.semantic_anchor,
                "line_range": list(ref.line_range) if ref.line_range else None,
            }
            for ref in concept.code_references
        ],
        "edges": [
            {
                "id": str(e.id),
                "target": id_to_slug.get(str(e.target), str(e.target)),
                "edge_type": e.edge_type,
                "metadata": e.metadata,
                "created_at": e.created_at.isoformat(),
            }
            for e in edges
        ],
    }
    return yaml.dump(data, default_flow_style=False, sort_keys=False)


def _parse_datetime(value: Optional[str]) -> Optional[datetime]:
    if value is None:
        return None
    return datetime.fromisoformat(value)


def _parse_target(value: str) -> str:
    """Parse edge target — could be a UUID string or a slug.
    Returns the raw string; resolution to UUID happens during index rebuild."""
    return value


def yaml_to_concept(yaml_str: str) -> tuple[Concept, list[Edge]]:
    """Deserialize YAML string to a Concept and its outgoing edges.
    Edge targets may be UUIDs or slugified names — callers must resolve slugs."""
    data = yaml.safe_load(yaml_str)
    concept_id = uuid.UUID(data["id"])

    code_refs = [
        CodeReference(
            symbol=ref["symbol"],
            file_path=ref["file_path"],
            content_hash=ref["content_hash"],
            semantic_anchor=ref["semantic_anchor"],
            line_range=tuple(ref["line_range"]) if ref.get("line_range") else None,
        )
        for ref in (data.get("code_references") or [])
    ]

    concept = Concept(
        id=concept_id,
        name=data["name"],
        description=data["description"],
        labels=set(data.get("labels") or []),
        code_references=code_refs,
        created_by=data.get("created_by", "agent"),
        verified_by=data.get("verified_by"),
        last_verified=_parse_datetime(data.get("last_verified")),
        created_at=_parse_datetime(data["created_at"]),
        updated_at=_parse_datetime(data["updated_at"]),
    )

    edges_raw = []
    for e in (data.get("edges") or []):
        target_str = str(e["target"])
        # Try parsing as UUID; if it fails, store as slug for later resolution
        try:
            target_id = uuid.UUID(target_str)
        except ValueError:
            # Slug reference — store a placeholder UUID(0) and the slug
            # Caller (rebuild_index) must resolve slugs to real UUIDs
            target_id = None
        edges_raw.append((e, target_id, target_str))

    edges = [
        Edge(
            id=uuid.UUID(e["id"]),
            source=concept_id,
            target=target_id if target_id else uuid.UUID(int=0),
            edge_type=e["edge_type"],
            metadata=e.get("metadata"),
            created_at=_parse_datetime(e["created_at"]),
        )
        for e, target_id, _ in edges_raw
    ]

    # Attach raw target strings for slug resolution
    for edge, (_, target_id, target_str) in zip(edges, edges_raw):
        edge._raw_target = target_str  # type: ignore

    return concept, edges


def write_concept_file(
    graph_dir: Path, concept: Concept, edges: list[Edge]
) -> Path:
    """Write a concept and its edges to a YAML file. Returns the file path."""
    graph_dir.mkdir(parents=True, exist_ok=True)
    file_path = graph_dir / f"{concept.slug}.yaml"
    yaml_str = concept_to_yaml(concept, edges)
    file_path.write_text(yaml_str)
    return file_path


def read_concept_file(file_path: Path) -> tuple[Concept, list[Edge]]:
    """Read a concept and its edges from a YAML file."""
    yaml_str = file_path.read_text()
    return yaml_to_concept(yaml_str)


def read_all_concepts(
    graph_dir: Path,
) -> list[tuple[Concept, list[Edge]]]:
    """Read all concept files from the graph directory."""
    results = []
    if not graph_dir.exists():
        return results
    for file_path in sorted(graph_dir.glob("*.yaml")):
        concept, edges = read_concept_file(file_path)
        results.append((concept, edges))
    return results
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/storage/test_flatfile.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add apriori/storage/flatfile.py tests/storage/test_flatfile.py
git commit -m "feat: add YAML flat file read/write for concept graph"
```

---

### Task 5: KnowledgeStore Protocol and SQLite Schema

**Files:**
- Create: `apriori/core/store.py`
- Create: `apriori/storage/schema.sql`

- [ ] **Step 1: Define the KnowledgeStore protocol**

```python
# apriori/core/store.py
"""Abstract storage interface for A-Priori knowledge graph."""

from typing import Optional, Protocol, runtime_checkable
from uuid import UUID

from apriori.core.models import (
    Concept,
    Edge,
    RankedResult,
    Subgraph,
    WorkItem,
)


@runtime_checkable
class KnowledgeStore(Protocol):
    # Concept CRUD
    def create_concept(self, concept: Concept) -> Concept: ...
    def get_concept(self, id_or_name: str) -> Optional[Concept]: ...
    def update_concept(self, id_or_name: str, **changes) -> Concept: ...
    def delete_concept(self, id_or_name: str) -> bool: ...

    # Edge CRUD
    def create_edge(self, edge: Edge) -> Edge: ...
    def get_edges(
        self,
        concept_id: UUID,
        edge_types: Optional[list[str]] = None,
        direction: str = "both",
    ) -> list[Edge]: ...
    def update_edge(self, edge_id: UUID, **changes) -> Edge: ...
    def delete_edge(self, edge_id: UUID) -> bool: ...

    # Traversal
    def traverse(
        self,
        start_id: UUID,
        edge_types: Optional[list[str]] = None,
        max_hops: int = 3,
        max_nodes: int = 50,
        strategy: str = "bfs",
    ) -> Subgraph: ...

    # Search
    def semantic_search(
        self,
        query: str,
        filters: Optional[dict] = None,
        limit: int = 10,
    ) -> list[RankedResult]: ...

    # Maintenance
    def get_stale_concepts(self, threshold_seconds: int) -> list[Concept]: ...
    def get_concepts_by_label(self, label: str) -> list[Concept]: ...
    def get_concepts_by_file(self, file_path: str) -> list[Concept]: ...

    # Index management
    def rebuild_index(self) -> None: ...
```

Note: Add `RankedResult` to models.py:

```python
# Add to apriori/core/models.py

@dataclass
class RankedResult:
    concept: Concept
    score: float
    match_mode: str  # "semantic", "keyword", "exact", "file"
```

- [ ] **Step 2: Create SQLite schema**

```sql
-- apriori/storage/schema.sql
-- SQLite schema for A-Priori knowledge graph index.
-- This is a derived index; flat YAML files are the source of truth.

PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS concepts (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    slug TEXT NOT NULL UNIQUE,
    description TEXT NOT NULL,
    labels TEXT NOT NULL DEFAULT '[]',       -- JSON array of strings
    created_by TEXT NOT NULL DEFAULT 'agent',
    verified_by TEXT,
    last_verified TEXT,                       -- ISO datetime
    created_at TEXT NOT NULL,                 -- ISO datetime
    updated_at TEXT NOT NULL                  -- ISO datetime
);

CREATE TABLE IF NOT EXISTS code_references (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    concept_id TEXT NOT NULL REFERENCES concepts(id) ON DELETE CASCADE,
    symbol TEXT NOT NULL,
    file_path TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    semantic_anchor TEXT NOT NULL,
    line_start INTEGER,
    line_end INTEGER
);

CREATE TABLE IF NOT EXISTS edges (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL REFERENCES concepts(id) ON DELETE CASCADE,
    target TEXT NOT NULL REFERENCES concepts(id) ON DELETE CASCADE,
    edge_type TEXT NOT NULL,
    metadata TEXT,                            -- JSON
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS work_items (
    id TEXT PRIMARY KEY,
    item_type TEXT NOT NULL,
    description TEXT NOT NULL,
    concept_id TEXT REFERENCES concepts(id) ON DELETE SET NULL,
    file_path TEXT,
    priority_score REAL NOT NULL DEFAULT 0.0,
    resolved INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_code_refs_concept ON code_references(concept_id);
CREATE INDEX IF NOT EXISTS idx_code_refs_file ON code_references(file_path);
CREATE INDEX IF NOT EXISTS idx_code_refs_symbol ON code_references(symbol);
CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source);
CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target);
CREATE INDEX IF NOT EXISTS idx_edges_type ON edges(edge_type);
CREATE INDEX IF NOT EXISTS idx_concepts_slug ON concepts(slug);
CREATE INDEX IF NOT EXISTS idx_work_items_resolved ON work_items(resolved);
CREATE INDEX IF NOT EXISTS idx_work_items_type ON work_items(item_type);
```

- [ ] **Step 3: Commit**

```bash
git add apriori/core/store.py apriori/core/models.py apriori/storage/schema.sql
git commit -m "feat: add KnowledgeStore protocol and SQLite schema"
```

---

### Task 6: LocalStore Implementation — Concept CRUD

**Files:**
- Create: `apriori/storage/local.py`
- Create: `tests/storage/test_local.py`

- [ ] **Step 1: Write tests for concept CRUD**

```python
# tests/storage/test_local.py
import pytest

from apriori.core.models import CodeReference, Concept
from apriori.storage.local import LocalStore


@pytest.fixture
def store(tmp_store_path):
    """Create a LocalStore backed by temporary directories."""
    return LocalStore(store_path=tmp_store_path)


class TestConceptCRUD:
    def test_create_and_get_concept(self, store):
        concept = Concept(
            name="Auth Flow",
            description="Authentication flow for the API.",
        )
        created = store.create_concept(concept)
        assert created.name == "Auth Flow"

        retrieved = store.get_concept("Auth Flow")
        assert retrieved is not None
        assert retrieved.name == "Auth Flow"
        assert retrieved.id == concept.id

    def test_get_concept_by_id(self, store):
        concept = Concept(name="Test", description="Test concept.")
        store.create_concept(concept)

        retrieved = store.get_concept(str(concept.id))
        assert retrieved is not None
        assert retrieved.name == "Test"

    def test_get_nonexistent_concept(self, store):
        assert store.get_concept("nonexistent") is None

    def test_update_concept(self, store):
        concept = Concept(name="Old Name", description="Old desc.")
        store.create_concept(concept)

        updated = store.update_concept("Old Name", description="New desc.")
        assert updated.description == "New desc."

        retrieved = store.get_concept("Old Name")
        assert retrieved.description == "New desc."

    def test_update_concept_labels(self, store):
        concept = Concept(name="Test", description="Test.")
        store.create_concept(concept)

        updated = store.update_concept("Test", labels={"needs-review"})
        assert "needs-review" in updated.labels

    def test_delete_concept(self, store):
        concept = Concept(name="ToDelete", description="Gone soon.")
        store.create_concept(concept)

        assert store.delete_concept("ToDelete") is True
        assert store.get_concept("ToDelete") is None

    def test_delete_nonexistent(self, store):
        assert store.delete_concept("nope") is False

    def test_create_concept_with_code_refs(self, store):
        concept = Concept(
            name="With Refs",
            description="Has code references.",
            code_references=[
                CodeReference(
                    symbol="foo",
                    file_path="src/foo.py",
                    content_hash="sha256:abc",
                    semantic_anchor="Does foo",
                )
            ],
        )
        store.create_concept(concept)

        retrieved = store.get_concept("With Refs")
        assert len(retrieved.code_references) == 1
        assert retrieved.code_references[0].symbol == "foo"

    def test_get_concepts_by_file(self, store):
        c1 = Concept(
            name="C1", description="First",
            code_references=[
                CodeReference(
                    symbol="a", file_path="src/shared.py",
                    content_hash="sha256:x", semantic_anchor="A",
                )
            ],
        )
        c2 = Concept(name="C2", description="Second")
        store.create_concept(c1)
        store.create_concept(c2)

        results = store.get_concepts_by_file("src/shared.py")
        assert len(results) == 1
        assert results[0].name == "C1"

    def test_get_concepts_by_label(self, store):
        c1 = Concept(
            name="Labeled", description="Has label",
            labels={"needs-review"},
        )
        c2 = Concept(name="Clean", description="No label")
        store.create_concept(c1)
        store.create_concept(c2)

        results = store.get_concepts_by_label("needs-review")
        assert len(results) == 1
        assert results[0].name == "Labeled"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/storage/test_local.py -v`
Expected: FAIL — cannot import `apriori.storage.local`

- [ ] **Step 3: Implement LocalStore with concept CRUD**

```python
# apriori/storage/local.py
"""Local storage implementation using SQLite + flat YAML files."""

import json
import sqlite3
from pathlib import Path
from typing import Optional
from uuid import UUID

from apriori.core.models import (
    CodeReference,
    Concept,
    Edge,
    RankedResult,
    Subgraph,
    WorkItem,
)
from apriori.storage.flatfile import (
    read_all_concepts,
    read_concept_file,
    write_concept_file,
)


class LocalStore:
    def __init__(self, store_path: Path):
        self._store_path = Path(store_path)
        self._graph_dir = self._store_path / "graph"
        self._graph_dir.mkdir(parents=True, exist_ok=True)
        self._db_path = self._store_path / "index.db"
        self._conn = self._init_db()

    def _init_db(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        schema_path = Path(__file__).parent / "schema.sql"
        schema = schema_path.read_text()
        # Execute each statement individually (skip PRAGMA journal_mode
        # since we already set it)
        for statement in schema.split(";"):
            statement = statement.strip()
            if statement and not statement.startswith("PRAGMA"):
                conn.execute(statement)
        conn.commit()
        return conn

    def _concept_from_row(self, row: sqlite3.Row) -> Concept:
        concept_id = row["id"]
        refs = self._conn.execute(
            "SELECT * FROM code_references WHERE concept_id = ?",
            (concept_id,),
        ).fetchall()

        code_references = [
            CodeReference(
                symbol=r["symbol"],
                file_path=r["file_path"],
                content_hash=r["content_hash"],
                semantic_anchor=r["semantic_anchor"],
                line_range=(
                    (r["line_start"], r["line_end"])
                    if r["line_start"] is not None
                    else None
                ),
            )
            for r in refs
        ]

        from datetime import datetime

        return Concept(
            id=UUID(row["id"]),
            name=row["name"],
            description=row["description"],
            labels=set(json.loads(row["labels"])),
            code_references=code_references,
            created_by=row["created_by"],
            verified_by=row["verified_by"],
            last_verified=(
                datetime.fromisoformat(row["last_verified"])
                if row["last_verified"]
                else None
            ),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    def _index_concept(self, concept: Concept) -> None:
        self._conn.execute(
            """INSERT OR REPLACE INTO concepts
               (id, name, slug, description, labels, created_by,
                verified_by, last_verified, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                str(concept.id),
                concept.name,
                concept.slug,
                concept.description,
                json.dumps(sorted(concept.labels)),
                concept.created_by,
                concept.verified_by,
                concept.last_verified.isoformat() if concept.last_verified else None,
                concept.created_at.isoformat(),
                concept.updated_at.isoformat(),
            ),
        )
        # Re-index code references
        self._conn.execute(
            "DELETE FROM code_references WHERE concept_id = ?",
            (str(concept.id),),
        )
        for ref in concept.code_references:
            self._conn.execute(
                """INSERT INTO code_references
                   (concept_id, symbol, file_path, content_hash,
                    semantic_anchor, line_start, line_end)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    str(concept.id),
                    ref.symbol,
                    ref.file_path,
                    ref.content_hash,
                    ref.semantic_anchor,
                    ref.line_range[0] if ref.line_range else None,
                    ref.line_range[1] if ref.line_range else None,
                ),
            )
        self._conn.commit()

    def create_concept(self, concept: Concept) -> Concept:
        # Write flat file first (source of truth)
        write_concept_file(self._graph_dir, concept, [])
        # Index in SQLite
        self._index_concept(concept)
        return concept

    def get_concept(self, id_or_name: str) -> Optional[Concept]:
        self._conn.row_factory = sqlite3.Row
        row = self._conn.execute(
            "SELECT * FROM concepts WHERE name = ? OR id = ?",
            (id_or_name, id_or_name),
        ).fetchone()
        if row is None:
            return None
        return self._concept_from_row(row)

    def update_concept(self, id_or_name: str, **changes) -> Concept:
        concept = self.get_concept(id_or_name)
        if concept is None:
            raise ValueError(f"Concept not found: {id_or_name}")

        from datetime import datetime, timezone

        for key, value in changes.items():
            if hasattr(concept, key):
                setattr(concept, key, value)
        concept.updated_at = datetime.now(timezone.utc)

        # Get existing edges from flat file
        file_path = self._graph_dir / f"{concept.slug}.yaml"
        if file_path.exists():
            _, edges = read_concept_file(file_path)
        else:
            edges = []

        # Write updated flat file and re-index
        write_concept_file(self._graph_dir, concept, edges)
        self._index_concept(concept)
        return concept

    def delete_concept(self, id_or_name: str) -> bool:
        concept = self.get_concept(id_or_name)
        if concept is None:
            return False

        # Delete flat file
        file_path = self._graph_dir / f"{concept.slug}.yaml"
        if file_path.exists():
            file_path.unlink()

        # Delete from index
        self._conn.execute(
            "DELETE FROM concepts WHERE id = ?", (str(concept.id),)
        )
        self._conn.commit()
        return True

    def get_concepts_by_file(self, file_path: str) -> list[Concept]:
        self._conn.row_factory = sqlite3.Row
        rows = self._conn.execute(
            """SELECT DISTINCT c.* FROM concepts c
               JOIN code_references cr ON c.id = cr.concept_id
               WHERE cr.file_path = ?""",
            (file_path,),
        ).fetchall()
        return [self._concept_from_row(r) for r in rows]

    def get_concepts_by_label(self, label: str) -> list[Concept]:
        self._conn.row_factory = sqlite3.Row
        # labels stored as JSON array; use LIKE for simple matching
        rows = self._conn.execute(
            """SELECT * FROM concepts
               WHERE labels LIKE ?""",
            (f'%"{label}"%',),
        ).fetchall()
        return [self._concept_from_row(r) for r in rows]

    # --- Stubs for methods implemented in later tasks ---

    def create_edge(self, edge: Edge) -> Edge:
        raise NotImplementedError

    def get_edges(self, concept_id, edge_types=None, direction="both"):
        raise NotImplementedError

    def update_edge(self, edge_id, **changes):
        raise NotImplementedError

    def delete_edge(self, edge_id):
        raise NotImplementedError

    def traverse(self, start_id, edge_types=None, max_hops=3,
                 max_nodes=50, strategy="bfs"):
        raise NotImplementedError

    def semantic_search(self, query, filters=None, limit=10):
        raise NotImplementedError

    def get_stale_concepts(self, threshold_seconds):
        raise NotImplementedError

    def rebuild_index(self):
        raise NotImplementedError
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/storage/test_local.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add apriori/storage/local.py tests/storage/test_local.py
git commit -m "feat: add LocalStore with concept CRUD (SQLite + flat files)"
```

---

### Task 7: LocalStore — Edge CRUD

**Files:**
- Modify: `apriori/storage/local.py`
- Modify: `tests/storage/test_local.py`

- [ ] **Step 1: Write tests for edge CRUD**

Add to `tests/storage/test_local.py`:

```python
class TestEdgeCRUD:
    def test_create_and_get_edge(self, store):
        c1 = Concept(name="Source", description="Source concept")
        c2 = Concept(name="Target", description="Target concept")
        store.create_concept(c1)
        store.create_concept(c2)

        edge = Edge(source=c1.id, target=c2.id, edge_type="depends-on")
        created = store.create_edge(edge)
        assert created.edge_type == "depends-on"

        edges = store.get_edges(c1.id)
        assert len(edges) == 1
        assert edges[0].target == c2.id

    def test_get_edges_by_direction(self, store):
        c1 = Concept(name="A", description="A")
        c2 = Concept(name="B", description="B")
        store.create_concept(c1)
        store.create_concept(c2)

        edge = Edge(source=c1.id, target=c2.id, edge_type="depends-on")
        store.create_edge(edge)

        outgoing = store.get_edges(c1.id, direction="outgoing")
        assert len(outgoing) == 1

        incoming = store.get_edges(c1.id, direction="incoming")
        assert len(incoming) == 0

        incoming_b = store.get_edges(c2.id, direction="incoming")
        assert len(incoming_b) == 1

    def test_get_edges_filtered_by_type(self, store):
        c1 = Concept(name="X", description="X")
        c2 = Concept(name="Y", description="Y")
        store.create_concept(c1)
        store.create_concept(c2)

        store.create_edge(Edge(source=c1.id, target=c2.id, edge_type="depends-on"))
        store.create_edge(Edge(source=c1.id, target=c2.id, edge_type="relates-to"))

        deps = store.get_edges(c1.id, edge_types=["depends-on"])
        assert len(deps) == 1
        assert deps[0].edge_type == "depends-on"

    def test_update_edge(self, store):
        c1 = Concept(name="E1", description="E1")
        c2 = Concept(name="E2", description="E2")
        store.create_concept(c1)
        store.create_concept(c2)

        edge = Edge(source=c1.id, target=c2.id, edge_type="relates-to")
        store.create_edge(edge)

        updated = store.update_edge(edge.id, edge_type="depends-on")
        assert updated.edge_type == "depends-on"

    def test_delete_edge(self, store):
        c1 = Concept(name="D1", description="D1")
        c2 = Concept(name="D2", description="D2")
        store.create_concept(c1)
        store.create_concept(c2)

        edge = Edge(source=c1.id, target=c2.id, edge_type="depends-on")
        store.create_edge(edge)

        assert store.delete_edge(edge.id) is True
        assert store.get_edges(c1.id) == []
```

- [ ] **Step 2: Run tests to verify new tests fail**

Run: `pytest tests/storage/test_local.py::TestEdgeCRUD -v`
Expected: FAIL — NotImplementedError

- [ ] **Step 3: Implement edge CRUD in LocalStore**

Replace the edge stubs in `apriori/storage/local.py` with full implementations. Key behaviors:
- `create_edge`: Insert into SQLite `edges` table, also update the source concept's flat file to include the edge.
- `get_edges`: Query SQLite with optional direction and edge_type filters.
- `update_edge`: Update SQLite row and re-write the flat file.
- `delete_edge`: Remove from SQLite and re-write the flat file.

```python
    def create_edge(self, edge: Edge) -> Edge:
        self._conn.execute(
            """INSERT INTO edges (id, source, target, edge_type, metadata, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                str(edge.id),
                str(edge.source),
                str(edge.target),
                edge.edge_type,
                json.dumps(edge.metadata) if edge.metadata else None,
                edge.created_at.isoformat(),
            ),
        )
        self._conn.commit()
        self._sync_edges_to_flatfile(edge.source)
        return edge

    def get_edges(
        self,
        concept_id: UUID,
        edge_types: Optional[list[str]] = None,
        direction: str = "both",
    ) -> list[Edge]:
        self._conn.row_factory = sqlite3.Row
        conditions = []
        params = []

        if direction == "outgoing":
            conditions.append("source = ?")
            params.append(str(concept_id))
        elif direction == "incoming":
            conditions.append("target = ?")
            params.append(str(concept_id))
        else:
            conditions.append("(source = ? OR target = ?)")
            params.extend([str(concept_id), str(concept_id)])

        if edge_types:
            placeholders = ",".join("?" * len(edge_types))
            conditions.append(f"edge_type IN ({placeholders})")
            params.extend(edge_types)

        where = " AND ".join(conditions)
        rows = self._conn.execute(
            f"SELECT * FROM edges WHERE {where}", params
        ).fetchall()

        from datetime import datetime
        return [
            Edge(
                id=UUID(r["id"]),
                source=UUID(r["source"]),
                target=UUID(r["target"]),
                edge_type=r["edge_type"],
                metadata=json.loads(r["metadata"]) if r["metadata"] else None,
                created_at=datetime.fromisoformat(r["created_at"]),
            )
            for r in rows
        ]

    def update_edge(self, edge_id: UUID, **changes) -> Edge:
        self._conn.row_factory = sqlite3.Row
        row = self._conn.execute(
            "SELECT * FROM edges WHERE id = ?", (str(edge_id),)
        ).fetchone()
        if row is None:
            raise ValueError(f"Edge not found: {edge_id}")

        updates = {}
        if "edge_type" in changes:
            updates["edge_type"] = changes["edge_type"]
        if "metadata" in changes:
            updates["metadata"] = json.dumps(changes["metadata"])

        if updates:
            set_clause = ", ".join(f"{k} = ?" for k in updates)
            self._conn.execute(
                f"UPDATE edges SET {set_clause} WHERE id = ?",
                (*updates.values(), str(edge_id)),
            )
            self._conn.commit()

        self._sync_edges_to_flatfile(UUID(row["source"]))

        updated_row = self._conn.execute(
            "SELECT * FROM edges WHERE id = ?", (str(edge_id),)
        ).fetchone()
        from datetime import datetime
        return Edge(
            id=UUID(updated_row["id"]),
            source=UUID(updated_row["source"]),
            target=UUID(updated_row["target"]),
            edge_type=updated_row["edge_type"],
            metadata=(
                json.loads(updated_row["metadata"])
                if updated_row["metadata"]
                else None
            ),
            created_at=datetime.fromisoformat(updated_row["created_at"]),
        )

    def delete_edge(self, edge_id: UUID) -> bool:
        self._conn.row_factory = sqlite3.Row
        row = self._conn.execute(
            "SELECT * FROM edges WHERE id = ?", (str(edge_id),)
        ).fetchone()
        if row is None:
            return False

        source_id = UUID(row["source"])
        self._conn.execute("DELETE FROM edges WHERE id = ?", (str(edge_id),))
        self._conn.commit()
        self._sync_edges_to_flatfile(source_id)
        return True

    def _sync_edges_to_flatfile(self, concept_id: UUID) -> None:
        """Re-write the flat file for a concept to reflect current edges."""
        concept = self.get_concept(str(concept_id))
        if concept is None:
            return
        edges = self.get_edges(concept_id, direction="outgoing")
        write_concept_file(self._graph_dir, concept, edges)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/storage/test_local.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add apriori/storage/local.py tests/storage/test_local.py
git commit -m "feat: add edge CRUD to LocalStore with flat file sync"
```

---

### Task 8: Graph Traversal Engine

**Files:**
- Create: `apriori/graph/engine.py`
- Create: `tests/graph/test_engine.py`
- Modify: `apriori/storage/local.py` (wire traverse to engine)

- [ ] **Step 1: Write tests for BFS and DFS traversal**

```python
# tests/graph/test_engine.py
import uuid

from apriori.core.models import Concept, Edge
from apriori.graph.engine import traverse_graph


def _make_concept(name):
    return Concept(name=name, description=f"{name} concept")


def _make_edge(source_id, target_id, edge_type="relates-to"):
    return Edge(source=source_id, target=target_id, edge_type=edge_type)


class TestTraverseGraph:
    def _build_chain(self):
        """A -> B -> C -> D"""
        a, b, c, d = [_make_concept(n) for n in ["A", "B", "C", "D"]]
        concepts = {c.id: c for c in [a, b, c, d]}
        edges = [
            _make_edge(a.id, b.id),
            _make_edge(b.id, c.id),
            _make_edge(c.id, d.id),
        ]
        return a, concepts, edges

    def test_bfs_full_traversal(self):
        a, concepts, edges = self._build_chain()
        result = traverse_graph(
            start_id=a.id,
            get_concept=lambda id: concepts[id],
            get_edges=lambda id, types: [e for e in edges if e.source == id],
            max_hops=10,
            max_nodes=10,
            strategy="bfs",
        )
        assert len(result.concepts) == 4

    def test_bfs_limited_hops(self):
        a, concepts, edges = self._build_chain()
        result = traverse_graph(
            start_id=a.id,
            get_concept=lambda id: concepts[id],
            get_edges=lambda id, types: [e for e in edges if e.source == id],
            max_hops=1,
            max_nodes=10,
            strategy="bfs",
        )
        # A + B (1 hop)
        assert len(result.concepts) == 2

    def test_bfs_limited_nodes(self):
        a, concepts, edges = self._build_chain()
        result = traverse_graph(
            start_id=a.id,
            get_concept=lambda id: concepts[id],
            get_edges=lambda id, types: [e for e in edges if e.source == id],
            max_hops=10,
            max_nodes=3,
            strategy="bfs",
        )
        assert len(result.concepts) == 3

    def test_dfs_traversal(self):
        a, concepts, edges = self._build_chain()
        result = traverse_graph(
            start_id=a.id,
            get_concept=lambda id: concepts[id],
            get_edges=lambda id, types: [e for e in edges if e.source == id],
            max_hops=10,
            max_nodes=10,
            strategy="dfs",
        )
        assert len(result.concepts) == 4

    def test_edge_type_filter(self):
        a = _make_concept("A")
        b = _make_concept("B")
        c = _make_concept("C")
        concepts = {x.id: x for x in [a, b, c]}
        edges = [
            _make_edge(a.id, b.id, "depends-on"),
            _make_edge(a.id, c.id, "relates-to"),
        ]
        result = traverse_graph(
            start_id=a.id,
            get_concept=lambda id: concepts[id],
            get_edges=lambda id, types: [
                e for e in edges
                if e.source == id and (types is None or e.edge_type in types)
            ],
            edge_types=["depends-on"],
            max_hops=10,
            max_nodes=10,
            strategy="bfs",
        )
        names = {c.name for c in result.concepts}
        assert "B" in names
        assert "C" not in names

    def test_handles_cycles(self):
        a = _make_concept("A")
        b = _make_concept("B")
        concepts = {x.id: x for x in [a, b]}
        edges = [
            _make_edge(a.id, b.id),
            _make_edge(b.id, a.id),
        ]
        result = traverse_graph(
            start_id=a.id,
            get_concept=lambda id: concepts[id],
            get_edges=lambda id, types: [e for e in edges if e.source == id],
            max_hops=10,
            max_nodes=10,
            strategy="bfs",
        )
        assert len(result.concepts) == 2  # No infinite loop
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/graph/test_engine.py -v`
Expected: FAIL — cannot import `apriori.graph.engine`

- [ ] **Step 3: Implement traversal engine**

```python
# apriori/graph/engine.py
"""Graph traversal engine — BFS and DFS with configurable limits."""

from collections import deque
from typing import Callable, Optional
from uuid import UUID

from apriori.core.models import Concept, Edge, Subgraph


def traverse_graph(
    start_id: UUID,
    get_concept: Callable[[UUID], Concept],
    get_edges: Callable[[UUID, Optional[list[str]]], list[Edge]],
    edge_types: Optional[list[str]] = None,
    max_hops: int = 3,
    max_nodes: int = 50,
    strategy: str = "bfs",
) -> Subgraph:
    """Traverse the graph from a starting concept.

    Args:
        start_id: UUID of the starting concept.
        get_concept: Callable to fetch a concept by ID.
        get_edges: Callable to fetch outgoing edges, optionally filtered by type.
        edge_types: Only follow these edge types (None = all).
        max_hops: Maximum traversal depth.
        max_nodes: Maximum number of nodes to visit.
        strategy: "bfs" or "dfs".

    Returns:
        Subgraph containing visited concepts and traversed edges.
    """
    visited_ids: set[UUID] = set()
    result_concepts: list[Concept] = []
    result_edges: list[Edge] = []

    # Queue/stack entries: (concept_id, current_depth)
    frontier: deque[tuple[UUID, int]] = deque()
    frontier.append((start_id, 0))

    while frontier and len(result_concepts) < max_nodes:
        if strategy == "bfs":
            current_id, depth = frontier.popleft()
        else:
            current_id, depth = frontier.pop()

        if current_id in visited_ids:
            continue
        visited_ids.add(current_id)

        concept = get_concept(current_id)
        result_concepts.append(concept)

        if depth < max_hops:
            edges = get_edges(current_id, edge_types)
            for edge in edges:
                result_edges.append(edge)
                if edge.target not in visited_ids:
                    frontier.append((edge.target, depth + 1))

    return Subgraph(concepts=result_concepts, edges=result_edges)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/graph/test_engine.py -v`
Expected: All tests PASS

- [ ] **Step 5: Wire traverse into LocalStore**

Replace the `traverse` stub in `local.py`:

```python
    def traverse(
        self,
        start_id: UUID,
        edge_types: Optional[list[str]] = None,
        max_hops: int = 3,
        max_nodes: int = 50,
        strategy: str = "bfs",
    ) -> Subgraph:
        from apriori.graph.engine import traverse_graph

        def _get_concept(id: UUID) -> Concept:
            c = self.get_concept(str(id))
            if c is None:
                raise ValueError(f"Concept not found: {id}")
            return c

        def _get_edges(id: UUID, types: Optional[list[str]]) -> list[Edge]:
            return self.get_edges(id, edge_types=types, direction="outgoing")

        return traverse_graph(
            start_id=start_id,
            get_concept=_get_concept,
            get_edges=_get_edges,
            edge_types=edge_types,
            max_hops=max_hops,
            max_nodes=max_nodes,
            strategy=strategy,
        )
```

- [ ] **Step 6: Run all tests**

Run: `pytest -v`
Expected: All tests PASS

- [ ] **Step 7: Commit**

```bash
git add apriori/graph/engine.py apriori/storage/local.py tests/graph/test_engine.py
git commit -m "feat: add BFS/DFS graph traversal engine"
```

---

### Task 9: Embedding Engine and Semantic Search

**Files:**
- Create: `apriori/embedding/engine.py`
- Create: `apriori/embedding/openai.py`
- Create: `tests/embedding/test_openai.py`
- Modify: `apriori/storage/local.py` (add vector indexing and semantic search)
- Modify: `tests/storage/test_local.py` (add semantic search tests)

- [ ] **Step 1: Write embedding protocol and a fake implementation for testing**

```python
# apriori/embedding/engine.py
"""Embedding engine protocol."""

from typing import Protocol


class EmbeddingEngine(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...

    @property
    def dimensions(self) -> int: ...


class FakeEmbeddingEngine:
    """Deterministic embedding engine for testing.
    Produces simple hash-based vectors."""

    def __init__(self, dims: int = 64):
        self._dims = dims

    @property
    def dimensions(self) -> int:
        return self._dims

    def embed(self, texts: list[str]) -> list[list[float]]:
        results = []
        for text in texts:
            # Simple deterministic pseudo-embedding from text hash
            h = hash(text)
            vec = []
            for i in range(self._dims):
                val = ((h + i * 31) % 1000) / 1000.0
                vec.append(val)
            # Normalize
            norm = sum(v * v for v in vec) ** 0.5
            vec = [v / norm for v in vec] if norm > 0 else vec
            results.append(vec)
        return results
```

- [ ] **Step 2: Write OpenAI embedding implementation**

```python
# apriori/embedding/openai.py
"""OpenAI embedding engine implementation."""

from openai import OpenAI

from apriori.embedding.engine import EmbeddingEngine


class OpenAIEmbeddingEngine:
    def __init__(self, model: str = "text-embedding-3-small", api_key: str | None = None):
        self._model = model
        self._client = OpenAI(api_key=api_key) if api_key else OpenAI()
        self._dims = 1536  # text-embedding-3-small default

    @property
    def dimensions(self) -> int:
        return self._dims

    def embed(self, texts: list[str]) -> list[list[float]]:
        response = self._client.embeddings.create(
            model=self._model,
            input=texts,
        )
        return [item.embedding for item in response.data]
```

- [ ] **Step 3: Write tests for semantic search via LocalStore**

Add to `tests/storage/test_local.py`:

```python
from apriori.embedding.engine import FakeEmbeddingEngine


@pytest.fixture
def store_with_embeddings(tmp_store_path):
    """LocalStore with fake embedding engine for semantic search tests."""
    engine = FakeEmbeddingEngine(dims=64)
    return LocalStore(store_path=tmp_store_path, embedding_engine=engine)


class TestSemanticSearch:
    def test_search_returns_results(self, store_with_embeddings):
        store = store_with_embeddings
        store.create_concept(
            Concept(name="Auth Flow", description="Authentication using JWT tokens")
        )
        store.create_concept(
            Concept(name="Payment", description="Payment processing with Stripe")
        )

        results = store.semantic_search("authentication")
        assert len(results) > 0
        assert all(hasattr(r, "score") for r in results)

    def test_search_with_limit(self, store_with_embeddings):
        store = store_with_embeddings
        for i in range(5):
            store.create_concept(
                Concept(name=f"Concept {i}", description=f"Description {i}")
            )

        results = store.semantic_search("concept", limit=2)
        assert len(results) <= 2

    def test_search_exact_mode(self, store_with_embeddings):
        store = store_with_embeddings
        store.create_concept(
            Concept(name="Auth Flow", description="Auth stuff")
        )

        results = store.semantic_search("Auth Flow", filters={"mode": "exact"})
        assert len(results) == 1
        assert results[0].concept.name == "Auth Flow"

    def test_search_keyword_mode(self, store_with_embeddings):
        store = store_with_embeddings
        store.create_concept(
            Concept(name="Auth Flow", description="JWT token authentication")
        )
        store.create_concept(
            Concept(name="Payment", description="Stripe payment processing")
        )

        results = store.semantic_search(
            "JWT", filters={"mode": "keyword"}
        )
        assert len(results) >= 1
        assert any(r.concept.name == "Auth Flow" for r in results)

    def test_search_with_label_filter(self, store_with_embeddings):
        store = store_with_embeddings
        store.create_concept(
            Concept(
                name="Stale",
                description="Stale concept",
                labels={"needs-review"},
            )
        )
        store.create_concept(
            Concept(name="Fresh", description="Fresh concept")
        )

        results = store.semantic_search(
            "concept", filters={"labels": ["needs-review"]}
        )
        assert len(results) == 1
        assert results[0].concept.name == "Stale"
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `pytest tests/storage/test_local.py::TestSemanticSearch -v`
Expected: FAIL — LocalStore doesn't accept `embedding_engine` parameter yet

- [ ] **Step 5: Add vector indexing and semantic search to LocalStore**

Modify `LocalStore.__init__` to accept an optional `EmbeddingEngine` and create the vector virtual table:

```python
# In LocalStore.__init__, after self._init_db():
self._embedding_engine = embedding_engine
if embedding_engine:
    self._conn.execute(
        f"""CREATE VIRTUAL TABLE IF NOT EXISTS concept_vectors
            USING vec0(
                concept_id TEXT PRIMARY KEY,
                embedding float[{embedding_engine.dimensions}]
            )"""
    )
    self._conn.commit()
```

Modify `_index_concept` to also store the embedding:

```python
# At the end of _index_concept, after committing concept/refs:
if self._embedding_engine:
    text = f"{concept.name}. {concept.description}"
    vectors = self._embedding_engine.embed([text])
    import struct
    blob = struct.pack(f"{len(vectors[0])}f", *vectors[0])
    self._conn.execute(
        "DELETE FROM concept_vectors WHERE concept_id = ?",
        (str(concept.id),),
    )
    self._conn.execute(
        "INSERT INTO concept_vectors (concept_id, embedding) VALUES (?, ?)",
        (str(concept.id), blob),
    )
    self._conn.commit()
```

Implement `semantic_search` with mode routing:

```python
def semantic_search(self, query, filters=None, limit=10):
    import struct
    from apriori.core.models import RankedResult

    filters = filters or {}
    mode = filters.pop("mode", "semantic")

    if mode == "exact":
        concept = self.get_concept(query)
        if concept is None:
            return []
        return [RankedResult(concept=concept, score=1.0, match_mode="exact")]

    if mode == "keyword":
        self._conn.row_factory = sqlite3.Row
        rows = self._conn.execute(
            """SELECT * FROM concepts
               WHERE name LIKE ? OR description LIKE ?
               LIMIT ?""",
            (f"%{query}%", f"%{query}%", limit),
        ).fetchall()
        results = [
            RankedResult(
                concept=self._concept_from_row(r),
                score=0.5,
                match_mode="keyword",
            )
            for r in rows
        ]
        return self._apply_label_filter(results, filters)

    # Default: semantic mode using sqlite-vec
    if not self._embedding_engine:
        return []

    query_vec = self._embedding_engine.embed([query])[0]
    blob = struct.pack(f"{len(query_vec)}f", *query_vec)
    self._conn.row_factory = sqlite3.Row
    rows = self._conn.execute(
        """SELECT concept_id, distance
           FROM concept_vectors
           WHERE embedding MATCH ?
           ORDER BY distance
           LIMIT ?""",
        (blob, limit),
    ).fetchall()

    results = []
    for row in rows:
        concept = self.get_concept(row["concept_id"])
        if concept:
            results.append(RankedResult(
                concept=concept,
                score=1.0 - row["distance"],
                match_mode="semantic",
            ))
    return self._apply_label_filter(results, filters)

def _apply_label_filter(self, results, filters):
    if "labels" in filters:
        required = set(filters["labels"])
        results = [r for r in results if required.issubset(r.concept.labels)]
    return results

def _rebuild_vectors(self):
    """Rebuild all vector embeddings from concept data."""
    if not self._embedding_engine:
        return
    import struct
    self._conn.execute("DELETE FROM concept_vectors")
    self._conn.row_factory = sqlite3.Row
    rows = self._conn.execute("SELECT id, name, description FROM concepts").fetchall()
    for row in rows:
        text = f"{row['name']}. {row['description']}"
        vectors = self._embedding_engine.embed([text])
        blob = struct.pack(f"{len(vectors[0])}f", *vectors[0])
        self._conn.execute(
            "INSERT INTO concept_vectors (concept_id, embedding) VALUES (?, ?)",
            (row["id"], blob),
        )
    self._conn.commit()
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/storage/test_local.py -v`
Expected: All tests PASS

- [ ] **Step 7: Commit**

```bash
git add apriori/embedding/ apriori/storage/local.py tests/embedding/ tests/storage/test_local.py
git commit -m "feat: add embedding engine and semantic search to LocalStore"
```

---

### Task 10: Unified Search (Query Engine)

**Files:**
- Create: `apriori/graph/query.py`
- Create: `tests/graph/test_query.py`

- [ ] **Step 1: Write tests for unified search with composable filters**

```python
# tests/graph/test_query.py
import uuid
from datetime import datetime, timezone, timedelta

from apriori.core.models import Concept, Edge, CodeReference
from apriori.graph.query import UnifiedSearch
from apriori.storage.local import LocalStore
from apriori.embedding.engine import FakeEmbeddingEngine

import pytest


@pytest.fixture
def search_store(tmp_store_path):
    engine = FakeEmbeddingEngine(dims=64)
    store = LocalStore(store_path=tmp_store_path, embedding_engine=engine)

    # Seed with test data
    auth = Concept(
        name="Auth Flow",
        description="JWT authentication flow",
        labels={"auto-generated"},
        created_by="agent",
        code_references=[
            CodeReference(
                symbol="authenticate",
                file_path="src/auth.py",
                content_hash="sha256:abc",
                semantic_anchor="Auth function",
            )
        ],
    )
    payment = Concept(
        name="Payment Processing",
        description="Stripe payment integration",
        labels={"needs-review"},
        created_by="human",
    )
    store.create_concept(auth)
    store.create_concept(payment)
    store.create_edge(
        Edge(source=auth.id, target=payment.id, edge_type="depends-on")
    )
    return store, auth, payment


class TestUnifiedSearch:
    def test_semantic_mode(self, search_store):
        store, _, _ = search_store
        search = UnifiedSearch(store)
        results = search.execute("authentication tokens")
        assert len(results) > 0

    def test_exact_mode(self, search_store):
        store, _, _ = search_store
        search = UnifiedSearch(store)
        results = search.execute("Auth Flow", mode="exact")
        assert len(results) == 1
        assert results[0].concept.name == "Auth Flow"

    def test_keyword_mode(self, search_store):
        store, _, _ = search_store
        search = UnifiedSearch(store)
        results = search.execute("Stripe", mode="keyword")
        assert len(results) >= 1
        assert any(r.concept.name == "Payment Processing" for r in results)

    def test_file_mode(self, search_store):
        store, _, _ = search_store
        search = UnifiedSearch(store)
        results = search.execute("src/auth.py", mode="file")
        assert len(results) == 1
        assert results[0].concept.name == "Auth Flow"

    def test_filter_by_labels(self, search_store):
        store, _, _ = search_store
        search = UnifiedSearch(store)
        results = search.execute(
            "concept", filters={"labels": ["needs-review"]}
        )
        assert all("needs-review" in r.concept.labels for r in results)

    def test_filter_by_created_by(self, search_store):
        store, _, _ = search_store
        search = UnifiedSearch(store)
        results = search.execute(
            "concept", filters={"created_by": "human"}
        )
        assert all(r.concept.created_by == "human" for r in results)

    def test_filter_has_edge_type(self, search_store):
        store, auth, _ = search_store
        search = UnifiedSearch(store)
        results = search.execute(
            "concept", filters={"has_edge_type": "depends-on"}
        )
        names = {r.concept.name for r in results}
        assert "Auth Flow" in names

    def test_filter_references_file(self, search_store):
        store, _, _ = search_store
        search = UnifiedSearch(store)
        results = search.execute(
            "concept", filters={"references_file": "src/auth.py"}
        )
        assert len(results) == 1
        assert results[0].concept.name == "Auth Flow"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/graph/test_query.py -v`
Expected: FAIL — cannot import `apriori.graph.query`

- [ ] **Step 3: Implement UnifiedSearch**

```python
# apriori/graph/query.py
"""Unified search with mode routing and composable filters."""

from typing import Optional

from apriori.core.models import RankedResult
from apriori.storage.local import LocalStore


class UnifiedSearch:
    def __init__(self, store: LocalStore):
        self._store = store

    def execute(
        self,
        query: str,
        mode: str = "semantic",
        filters: Optional[dict] = None,
        limit: int = 10,
    ) -> list[RankedResult]:
        filters = filters or {}

        # Mode routing
        if mode == "exact":
            results = self._exact_search(query)
        elif mode == "keyword":
            results = self._keyword_search(query, limit)
        elif mode == "file":
            results = self._file_search(query)
        else:
            merged_filters = {**filters, "mode": "semantic"}
            results = self._store.semantic_search(query, filters=merged_filters, limit=limit)

        # Apply post-filters
        results = self._apply_filters(results, filters)
        return results[:limit]

    def _exact_search(self, query: str) -> list[RankedResult]:
        concept = self._store.get_concept(query)
        if concept is None:
            return []
        return [RankedResult(concept=concept, score=1.0, match_mode="exact")]

    def _keyword_search(self, query: str, limit: int) -> list[RankedResult]:
        return self._store.semantic_search(
            query, filters={"mode": "keyword"}, limit=limit
        )

    def _file_search(self, query: str) -> list[RankedResult]:
        concepts = self._store.get_concepts_by_file(query)
        return [
            RankedResult(concept=c, score=1.0, match_mode="file")
            for c in concepts
        ]

    def _apply_filters(
        self, results: list[RankedResult], filters: dict
    ) -> list[RankedResult]:
        filtered = results

        if "labels" in filters:
            required = set(filters["labels"])
            filtered = [
                r for r in filtered
                if required.issubset(r.concept.labels)
            ]

        if "exclude_labels" in filters:
            excluded = set(filters["exclude_labels"])
            filtered = [
                r for r in filtered
                if not excluded.intersection(r.concept.labels)
            ]

        if "created_by" in filters:
            filtered = [
                r for r in filtered
                if r.concept.created_by == filters["created_by"]
            ]

        if "has_edge_type" in filters:
            edge_type = filters["has_edge_type"]
            filtered = [
                r for r in filtered
                if self._store.get_edges(
                    r.concept.id, edge_types=[edge_type], direction="outgoing"
                )
            ]

        if "references_file" in filters:
            file_path = filters["references_file"]
            filtered = [
                r for r in filtered
                if any(
                    ref.file_path == file_path
                    for ref in r.concept.code_references
                )
            ]

        return filtered
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/graph/test_query.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add apriori/graph/query.py tests/graph/test_query.py
git commit -m "feat: add unified search with mode routing and composable filters"
```

---

### Task 11: Code Reference Resolver

**Files:**
- Create: `apriori/references/resolver.py`
- Create: `tests/references/test_resolver.py`

- [ ] **Step 1: Write tests for the repair chain**

```python
# tests/references/test_resolver.py
import hashlib
from pathlib import Path

from apriori.core.models import CodeReference
from apriori.references.resolver import (
    resolve_reference,
    compute_content_hash,
    ReferenceStatus,
)


def _write_file(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


class TestComputeContentHash:
    def test_hash_matches_content(self, tmp_path):
        code = "def validate_amount():\n    pass\n"
        file_path = tmp_path / "src" / "pay.py"
        _write_file(file_path, code)

        h = compute_content_hash(file_path, (1, 2))
        assert h.startswith("sha256:")
        assert len(h) > 10


class TestResolveReference:
    def test_symbol_found_hash_matches(self, tmp_path):
        code = "def validate_amount():\n    return True\n"
        file_path = tmp_path / "src" / "pay.py"
        _write_file(file_path, code)

        content_hash = compute_content_hash(file_path, (1, 2))
        ref = CodeReference(
            symbol="validate_amount",
            file_path="src/pay.py",
            content_hash=content_hash,
            semantic_anchor="Validates payment amounts",
            line_range=(1, 2),
        )
        status = resolve_reference(ref, repo_root=tmp_path)
        assert status == ReferenceStatus.VALID

    def test_symbol_found_hash_mismatch(self, tmp_path):
        file_path = tmp_path / "src" / "pay.py"
        _write_file(file_path, "def validate_amount():\n    return True\n")

        ref = CodeReference(
            symbol="validate_amount",
            file_path="src/pay.py",
            content_hash="sha256:old_hash_that_wont_match",
            semantic_anchor="Validates payment amounts",
            line_range=(1, 2),
        )
        status = resolve_reference(ref, repo_root=tmp_path)
        assert status == ReferenceStatus.STALE

    def test_symbol_not_found(self, tmp_path):
        file_path = tmp_path / "src" / "pay.py"
        _write_file(file_path, "def other_function():\n    pass\n")

        ref = CodeReference(
            symbol="validate_amount",
            file_path="src/pay.py",
            content_hash="sha256:whatever",
            semantic_anchor="Validates payment amounts",
            line_range=(1, 2),
        )
        status = resolve_reference(ref, repo_root=tmp_path)
        assert status == ReferenceStatus.BROKEN

    def test_file_not_found(self, tmp_path):
        ref = CodeReference(
            symbol="validate_amount",
            file_path="src/nonexistent.py",
            content_hash="sha256:whatever",
            semantic_anchor="Validates payment amounts",
        )
        status = resolve_reference(ref, repo_root=tmp_path)
        assert status == ReferenceStatus.BROKEN
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/references/test_resolver.py -v`
Expected: FAIL — cannot import `apriori.references.resolver`

- [ ] **Step 3: Implement the resolver**

```python
# apriori/references/resolver.py
"""Code reference repair chain: symbol → hash → semantic."""

import hashlib
import re
from enum import Enum
from pathlib import Path

from apriori.core.models import CodeReference


class ReferenceStatus(Enum):
    VALID = "valid"          # Symbol found, hash matches
    STALE = "stale"          # Symbol found, hash changed — needs review
    BROKEN = "broken"        # Symbol not found — needs semantic repair


def compute_content_hash(file_path: Path, line_range: tuple[int, int] | None = None) -> str:
    """Compute SHA256 hash of file content (or a line range within it)."""
    content = file_path.read_text()
    if line_range:
        lines = content.splitlines(keepends=True)
        start, end = line_range
        content = "".join(lines[start - 1 : end])
    h = hashlib.sha256(content.encode()).hexdigest()
    return f"sha256:{h}"


def _symbol_exists_in_file(file_path: Path, symbol: str) -> bool:
    """Check if a symbol (function/class/variable name) exists in a file."""
    content = file_path.read_text()
    # Match common Python definitions: def symbol, class symbol, symbol =
    pattern = rf"\b(def|class)\s+{re.escape(symbol)}\b|^{re.escape(symbol)}\s*="
    return bool(re.search(pattern, content, re.MULTILINE))


def resolve_reference(ref: CodeReference, repo_root: Path) -> ReferenceStatus:
    """Resolve a code reference using the repair chain.

    1. Check if file exists
    2. Check if symbol exists in file
    3. If symbol found, check content hash

    Returns:
        VALID — symbol found, hash matches (knowledge is current)
        STALE — symbol found, hash differs (code changed, concept may be outdated)
        BROKEN — symbol or file not found (needs semantic anchor repair)
    """
    file_path = repo_root / ref.file_path

    # Step 1: File exists?
    if not file_path.exists():
        return ReferenceStatus.BROKEN

    # Step 2: Symbol exists?
    if not _symbol_exists_in_file(file_path, ref.symbol):
        return ReferenceStatus.BROKEN

    # Step 3: Content hash matches?
    current_hash = compute_content_hash(file_path, ref.line_range)
    if current_hash != ref.content_hash:
        return ReferenceStatus.STALE

    return ReferenceStatus.VALID
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/references/test_resolver.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add apriori/references/ tests/references/
git commit -m "feat: add code reference resolver with repair chain"
```

---

### Task 12: Maintenance Backlog

**Files:**
- Create: `apriori/maintenance/backlog.py`
- Create: `tests/maintenance/test_backlog.py`

- [ ] **Step 1: Write tests for work item management and priority scoring**

```python
# tests/maintenance/test_backlog.py
import uuid

from apriori.core.config import AprioriConfig
from apriori.core.models import WorkItem, WorkItemType
from apriori.maintenance.backlog import Backlog
from apriori.storage.local import LocalStore
from apriori.embedding.engine import FakeEmbeddingEngine

import pytest


@pytest.fixture
def backlog(tmp_store_path):
    engine = FakeEmbeddingEngine(dims=64)
    store = LocalStore(store_path=tmp_store_path, embedding_engine=engine)
    config = AprioriConfig()
    return Backlog(store=store, config=config)


class TestBacklog:
    def test_add_work_item(self, backlog):
        item = WorkItem(
            item_type=WorkItemType.REPORTED_GAP,
            description="Missing docs for retry behavior",
        )
        added = backlog.add(item)
        assert added.id == item.id

    def test_list_unresolved(self, backlog):
        backlog.add(WorkItem(
            item_type=WorkItemType.REPORTED_GAP,
            description="Gap 1",
        ))
        backlog.add(WorkItem(
            item_type=WorkItemType.VERIFY_CONCEPT,
            description="Verify auth",
        ))

        items = backlog.list_unresolved()
        assert len(items) == 2

    def test_resolve_item(self, backlog):
        item = WorkItem(
            item_type=WorkItemType.REPORTED_GAP,
            description="Gap",
        )
        backlog.add(item)
        backlog.resolve(item.id)

        items = backlog.list_unresolved()
        assert len(items) == 0

    def test_priority_score_computed(self, backlog):
        item = WorkItem(
            item_type=WorkItemType.VERIFY_CONCEPT,
            description="Re-verify",
            priority_score=0.0,
        )
        backlog.add(item)
        backlog.compute_priorities()

        items = backlog.list_unresolved()
        # Score should be set (exact value depends on scoring logic)
        assert isinstance(items[0].priority_score, float)

    def test_items_sorted_by_priority(self, backlog):
        low = WorkItem(
            item_type=WorkItemType.INVESTIGATE_FILE,
            description="Low priority",
            priority_score=0.1,
        )
        high = WorkItem(
            item_type=WorkItemType.REPORTED_GAP,
            description="High priority",
            priority_score=0.9,
        )
        backlog.add(low)
        backlog.add(high)

        items = backlog.list_unresolved()
        assert items[0].priority_score >= items[1].priority_score
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/maintenance/test_backlog.py -v`
Expected: FAIL — cannot import

- [ ] **Step 3: Implement Backlog**

```python
# apriori/maintenance/backlog.py
"""Work item backlog management and priority scoring."""

import json
from typing import Optional
from uuid import UUID

from apriori.core.config import AprioriConfig
from apriori.core.models import WorkItem, WorkItemType


class Backlog:
    def __init__(self, store, config: AprioriConfig):
        self._store = store
        self._config = config
        self._conn = store._conn  # Share the SQLite connection

    def add(self, item: WorkItem) -> WorkItem:
        self._conn.execute(
            """INSERT INTO work_items
               (id, item_type, description, concept_id, file_path,
                priority_score, resolved, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                str(item.id),
                item.item_type.value,
                item.description,
                str(item.concept_id) if item.concept_id else None,
                item.file_path,
                item.priority_score,
                0,
                item.created_at.isoformat(),
            ),
        )
        self._conn.commit()
        return item

    def list_unresolved(self) -> list[WorkItem]:
        import sqlite3
        self._conn.row_factory = sqlite3.Row
        rows = self._conn.execute(
            """SELECT * FROM work_items
               WHERE resolved = 0
               ORDER BY priority_score DESC"""
        ).fetchall()
        return [self._row_to_item(r) for r in rows]

    def resolve(self, item_id: UUID) -> None:
        self._conn.execute(
            "UPDATE work_items SET resolved = 1 WHERE id = ?",
            (str(item_id),),
        )
        self._conn.commit()

    def compute_priorities(self) -> None:
        """Recompute priority scores for all unresolved items.

        Uses configured weights. For MVP, scoring is simplified:
        - REPORTED_GAP and REVIEW_CONCEPT get needs_review weight
        - VERIFY_CONCEPT gets staleness weight
        - INVESTIGATE_FILE gets coverage_gap weight
        - EVALUATE_RELATIONSHIP gets semantic_graph_delta weight
        """
        weights = self._config.priority_weights
        import sqlite3
        self._conn.row_factory = sqlite3.Row
        rows = self._conn.execute(
            "SELECT * FROM work_items WHERE resolved = 0"
        ).fetchall()

        for row in rows:
            item_type = row["item_type"]
            score = 0.0

            if item_type in (
                WorkItemType.REPORTED_GAP.value,
                WorkItemType.REVIEW_CONCEPT.value,
            ):
                score = weights.needs_review
            elif item_type == WorkItemType.VERIFY_CONCEPT.value:
                score = weights.staleness
            elif item_type == WorkItemType.INVESTIGATE_FILE.value:
                score = weights.coverage_gap
            elif item_type == WorkItemType.EVALUATE_RELATIONSHIP.value:
                score = weights.semantic_graph_delta

            self._conn.execute(
                "UPDATE work_items SET priority_score = ? WHERE id = ?",
                (score, row["id"]),
            )

        self._conn.commit()

    def _row_to_item(self, row) -> WorkItem:
        from datetime import datetime

        return WorkItem(
            id=UUID(row["id"]),
            item_type=WorkItemType(row["item_type"]),
            description=row["description"],
            concept_id=UUID(row["concept_id"]) if row["concept_id"] else None,
            file_path=row["file_path"],
            priority_score=row["priority_score"],
            resolved=bool(row["resolved"]),
            created_at=datetime.fromisoformat(row["created_at"]),
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/maintenance/test_backlog.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add apriori/maintenance/backlog.py tests/maintenance/test_backlog.py
git commit -m "feat: add maintenance backlog with priority scoring"
```

---

### Task 13: Git Diff Watcher

**Files:**
- Create: `apriori/maintenance/differ.py`
- Create: `tests/maintenance/test_differ.py`

- [ ] **Step 1: Write tests for diff-based work item generation**

```python
# tests/maintenance/test_differ.py
import subprocess
from pathlib import Path

import pytest

from apriori.core.models import Concept, CodeReference, WorkItemType
from apriori.maintenance.differ import DiffWatcher
from apriori.maintenance.backlog import Backlog
from apriori.storage.local import LocalStore
from apriori.embedding.engine import FakeEmbeddingEngine
from apriori.core.config import AprioriConfig


@pytest.fixture
def git_repo(tmp_path):
    """Create a real git repo for diff testing."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=repo, capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=repo, capture_output=True,
    )
    # Initial file and commit
    (repo / "src").mkdir()
    (repo / "src" / "auth.py").write_text("def login():\n    pass\n")
    subprocess.run(["git", "add", "."], cwd=repo, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "initial"],
        cwd=repo, capture_output=True,
    )
    return repo


class TestDiffWatcher:
    def test_detects_changed_file(self, git_repo, tmp_path):
        store_path = tmp_path / "store"
        engine = FakeEmbeddingEngine(dims=64)
        store = LocalStore(store_path=store_path, embedding_engine=engine)
        config = AprioriConfig()
        backlog = Backlog(store=store, config=config)

        # Create a concept referencing the file
        concept = Concept(
            name="Auth",
            description="Auth system",
            code_references=[
                CodeReference(
                    symbol="login",
                    file_path="src/auth.py",
                    content_hash="sha256:old",
                    semantic_anchor="Login function",
                )
            ],
        )
        store.create_concept(concept)

        # Get the initial commit hash
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=git_repo, capture_output=True, text=True,
        )
        base_commit = result.stdout.strip()

        # Modify the file and commit
        (git_repo / "src" / "auth.py").write_text(
            "def login():\n    return True\n"
        )
        subprocess.run(["git", "add", "."], cwd=git_repo, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "update auth"],
            cwd=git_repo, capture_output=True,
        )

        watcher = DiffWatcher(
            repo_path=git_repo, store=store, backlog=backlog
        )
        items = watcher.check_since(base_commit)

        assert len(items) >= 1
        assert any(i.item_type == WorkItemType.VERIFY_CONCEPT for i in items)

    def test_ignores_untracked_files(self, git_repo, tmp_path):
        store_path = tmp_path / "store"
        engine = FakeEmbeddingEngine(dims=64)
        store = LocalStore(store_path=store_path, embedding_engine=engine)
        config = AprioriConfig()
        backlog = Backlog(store=store, config=config)

        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=git_repo, capture_output=True, text=True,
        )
        base_commit = result.stdout.strip()

        # Add a new file that no concept references
        (git_repo / "src" / "new.py").write_text("# new\n")
        subprocess.run(["git", "add", "."], cwd=git_repo, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "add new"],
            cwd=git_repo, capture_output=True,
        )

        watcher = DiffWatcher(
            repo_path=git_repo, store=store, backlog=backlog
        )
        items = watcher.check_since(base_commit)

        # No verify_concept items since no concept references new.py
        verify_items = [
            i for i in items if i.item_type == WorkItemType.VERIFY_CONCEPT
        ]
        assert len(verify_items) == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/maintenance/test_differ.py -v`
Expected: FAIL — cannot import

- [ ] **Step 3: Implement DiffWatcher**

```python
# apriori/maintenance/differ.py
"""Git diff analysis → work item generation."""

import subprocess
from pathlib import Path

from apriori.core.models import WorkItem, WorkItemType
from apriori.maintenance.backlog import Backlog


class DiffWatcher:
    def __init__(self, repo_path: Path, store, backlog: Backlog):
        self._repo_path = Path(repo_path)
        self._store = store
        self._backlog = backlog

    def _get_changed_files(self, since_commit: str) -> list[str]:
        """Get list of files changed since a given commit."""
        result = subprocess.run(
            ["git", "diff", "--name-only", since_commit, "HEAD"],
            cwd=self._repo_path,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return []
        return [f.strip() for f in result.stdout.strip().split("\n") if f.strip()]

    def check_since(self, since_commit: str) -> list[WorkItem]:
        """Check for changes since a commit and generate work items."""
        changed_files = self._get_changed_files(since_commit)
        items = []

        for file_path in changed_files:
            concepts = self._store.get_concepts_by_file(file_path)
            for concept in concepts:
                item = WorkItem(
                    item_type=WorkItemType.VERIFY_CONCEPT,
                    description=f"Code changed in {file_path} — re-verify concept '{concept.name}'",
                    concept_id=concept.id,
                    file_path=file_path,
                )
                self._backlog.add(item)
                items.append(item)

        return items

    def get_current_commit(self) -> str:
        """Get the current HEAD commit hash."""
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=self._repo_path,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/maintenance/test_differ.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add apriori/maintenance/differ.py tests/maintenance/test_differ.py
git commit -m "feat: add git diff watcher for maintenance backlog"
```

---

### Task 14: MCP Server Shell

**Files:**
- Create: `apriori/shells/mcp_server.py`
- Create: `tests/shells/test_mcp_server.py`

- [ ] **Step 1: Write tests for MCP tool handlers**

```python
# tests/shells/test_mcp_server.py
"""Tests for MCP server tool handlers (unit tests, no MCP transport)."""

import pytest

from apriori.core.models import Concept, Edge
from apriori.embedding.engine import FakeEmbeddingEngine
from apriori.storage.local import LocalStore
from apriori.shells.mcp_server import AprioriMCPHandlers
from apriori.core.config import AprioriConfig


@pytest.fixture
def handlers(tmp_store_path):
    engine = FakeEmbeddingEngine(dims=64)
    store = LocalStore(store_path=tmp_store_path, embedding_engine=engine)
    config = AprioriConfig()
    return AprioriMCPHandlers(store=store, config=config)


class TestMCPHandlers:
    def test_create_concept(self, handlers):
        result = handlers.create_concept(
            name="Auth Flow",
            description="Authentication flow",
        )
        assert result["name"] == "Auth Flow"
        assert "id" in result

    def test_get_concept(self, handlers):
        handlers.create_concept(name="Test", description="Test concept")
        result = handlers.get_concept(id_or_name="Test")
        assert result["name"] == "Test"

    def test_get_concept_not_found(self, handlers):
        result = handlers.get_concept(id_or_name="nonexistent")
        assert result is None

    def test_update_concept(self, handlers):
        handlers.create_concept(name="Old", description="Old desc")
        result = handlers.update_concept(
            id_or_name="Old", description="New desc"
        )
        assert result["description"] == "New desc"

    def test_delete_concept(self, handlers):
        handlers.create_concept(name="Gone", description="Will be deleted")
        result = handlers.delete_concept(id_or_name="Gone")
        assert result["deleted"] is True

    def test_create_and_get_edge(self, handlers):
        c1 = handlers.create_concept(name="A", description="A")
        c2 = handlers.create_concept(name="B", description="B")
        edge = handlers.create_edge(
            source="A", target="B", edge_type="depends-on"
        )
        assert edge["edge_type"] == "depends-on"

    def test_search(self, handlers):
        handlers.create_concept(
            name="Auth", description="JWT authentication"
        )
        results = handlers.search(query="authentication")
        assert len(results) > 0

    def test_traverse(self, handlers):
        handlers.create_concept(name="Root", description="Root concept")
        handlers.create_concept(name="Child", description="Child concept")
        handlers.create_edge(
            source="Root", target="Child", edge_type="depends-on"
        )
        result = handlers.traverse(start="Root", max_hops=1)
        assert len(result["concepts"]) == 2

    def test_list_edge_types(self, handlers):
        types = handlers.list_edge_types()
        names = [t["name"] for t in types]
        assert "depends-on" in names

    def test_report_gap(self, handlers):
        result = handlers.report_gap(
            description="No docs for retry behavior"
        )
        assert "id" in result
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/shells/test_mcp_server.py -v`
Expected: FAIL — cannot import

- [ ] **Step 3: Implement MCP handlers and server**

```python
# apriori/shells/mcp_server.py
"""MCP server shell for A-Priori."""

from pathlib import Path
from typing import Optional
from uuid import UUID

from apriori.core.config import AprioriConfig, load_config
from apriori.core.models import (
    CodeReference,
    Concept,
    Edge,
    WorkItem,
    WorkItemType,
)
from apriori.graph.query import UnifiedSearch
from apriori.maintenance.backlog import Backlog
from apriori.storage.local import LocalStore


class AprioriMCPHandlers:
    """Tool handler implementations — decoupled from MCP transport."""

    def __init__(self, store: LocalStore, config: AprioriConfig):
        self._store = store
        self._config = config
        self._search = UnifiedSearch(store)
        self._backlog = Backlog(store=store, config=config)

    def create_concept(
        self,
        name: str,
        description: str,
        labels: Optional[list[str]] = None,
        code_references: Optional[list[dict]] = None,
    ) -> dict:
        refs = [
            CodeReference(**ref) for ref in (code_references or [])
        ]
        concept = Concept(
            name=name,
            description=description,
            labels=set(labels) if labels else set(),
            code_references=refs,
        )
        created = self._store.create_concept(concept)
        return {"id": str(created.id), "name": created.name}

    def get_concept(self, id_or_name: str) -> Optional[dict]:
        concept = self._store.get_concept(id_or_name)
        if concept is None:
            return None
        edges = self._store.get_edges(concept.id)
        return self._concept_to_dict(concept, edges)

    def update_concept(self, id_or_name: str, **changes) -> dict:
        if "labels" in changes and isinstance(changes["labels"], list):
            changes["labels"] = set(changes["labels"])
        updated = self._store.update_concept(id_or_name, **changes)
        return {"id": str(updated.id), "name": updated.name,
                "description": updated.description}

    def delete_concept(self, id_or_name: str) -> dict:
        result = self._store.delete_concept(id_or_name)
        return {"deleted": result}

    def create_edge(
        self,
        source: str,
        target: str,
        edge_type: str,
        metadata: Optional[dict] = None,
    ) -> dict:
        source_concept = self._store.get_concept(source)
        target_concept = self._store.get_concept(target)
        if not source_concept or not target_concept:
            raise ValueError("Source or target concept not found")

        edge = Edge(
            source=source_concept.id,
            target=target_concept.id,
            edge_type=edge_type,
            metadata=metadata,
        )
        created = self._store.create_edge(edge)
        return {
            "id": str(created.id),
            "edge_type": created.edge_type,
            "source": source,
            "target": target,
        }

    def update_edge(self, edge_id: str, **changes) -> dict:
        updated = self._store.update_edge(UUID(edge_id), **changes)
        return {"id": str(updated.id), "edge_type": updated.edge_type}

    def delete_edge(self, edge_id: str) -> dict:
        result = self._store.delete_edge(UUID(edge_id))
        return {"deleted": result}

    def search(
        self,
        query: str,
        mode: str = "semantic",
        filters: Optional[dict] = None,
        limit: int = 10,
    ) -> list[dict]:
        results = self._search.execute(
            query=query, mode=mode, filters=filters, limit=limit
        )
        return [
            {
                "name": r.concept.name,
                "description": r.concept.description[:200],
                "score": r.score,
                "match_mode": r.match_mode,
            }
            for r in results
        ]

    def traverse(
        self,
        start: str,
        edge_types: Optional[list[str]] = None,
        max_hops: int = 3,
        max_nodes: int = 50,
        strategy: str = "bfs",
    ) -> dict:
        concept = self._store.get_concept(start)
        if concept is None:
            raise ValueError(f"Concept not found: {start}")

        subgraph = self._store.traverse(
            start_id=concept.id,
            edge_types=edge_types,
            max_hops=max_hops,
            max_nodes=max_nodes,
            strategy=strategy,
        )
        return {
            "concepts": [
                {"name": c.name, "description": c.description[:200]}
                for c in subgraph.concepts
            ],
            "edges": [
                {
                    "source": str(e.source),
                    "target": str(e.target),
                    "edge_type": e.edge_type,
                }
                for e in subgraph.edges
            ],
        }

    def list_edge_types(self) -> list[dict]:
        return [
            {"name": et.name, "description": et.description}
            for et in self._config.graph.edge_types
        ]

    def report_gap(
        self, description: str, context: Optional[str] = None
    ) -> dict:
        item = WorkItem(
            item_type=WorkItemType.REPORTED_GAP,
            description=description,
        )
        self._backlog.add(item)
        return {"id": str(item.id), "description": description}

    def _concept_to_dict(self, concept: Concept, edges: list[Edge]) -> dict:
        return {
            "id": str(concept.id),
            "name": concept.name,
            "description": concept.description,
            "labels": sorted(concept.labels),
            "created_by": concept.created_by,
            "verified_by": concept.verified_by,
            "code_references": [
                {
                    "symbol": r.symbol,
                    "file_path": r.file_path,
                    "content_hash": r.content_hash,
                    "semantic_anchor": r.semantic_anchor,
                }
                for r in concept.code_references
            ],
            "edges": [
                {
                    "id": str(e.id),
                    "source": str(e.source),
                    "target": str(e.target),
                    "edge_type": e.edge_type,
                }
                for e in edges
            ],
        }


def main():
    """Entry point for the MCP server."""
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    import asyncio

    config = load_config(Path("apriori.config.yaml"))
    store_path = Path(config.project.store_path).expanduser()

    from apriori.embedding.openai import OpenAIEmbeddingEngine
    embedding_engine = OpenAIEmbeddingEngine(model=config.embeddings.model)
    store = LocalStore(store_path=store_path, embedding_engine=embedding_engine)
    handlers = AprioriMCPHandlers(store=store, config=config)

    server = Server("a-priori")

    @server.tool()
    async def search(query: str, mode: str = "semantic",
                     filters: dict | None = None, limit: int = 10):
        """Search the knowledge graph. Modes: semantic, keyword, exact, file."""
        return handlers.search(query=query, mode=mode, filters=filters, limit=limit)

    @server.tool()
    async def get_concept(id_or_name: str):
        """Get a concept by name or ID with all edges and code references."""
        return handlers.get_concept(id_or_name=id_or_name)

    @server.tool()
    async def traverse(start: str, edge_types: list[str] | None = None,
                       max_hops: int = 3, max_nodes: int = 50,
                       strategy: str = "bfs"):
        """Traverse the graph from a starting concept."""
        return handlers.traverse(start=start, edge_types=edge_types,
                                 max_hops=max_hops, max_nodes=max_nodes,
                                 strategy=strategy)

    @server.tool()
    async def list_edge_types():
        """List the edge type vocabulary."""
        return handlers.list_edge_types()

    @server.tool()
    async def create_concept(name: str, description: str,
                             labels: list[str] | None = None,
                             code_references: list[dict] | None = None):
        """Create a new concept node."""
        return handlers.create_concept(name=name, description=description,
                                       labels=labels, code_references=code_references)

    @server.tool()
    async def update_concept(id_or_name: str, **changes):
        """Update a concept's fields."""
        return handlers.update_concept(id_or_name=id_or_name, **changes)

    @server.tool()
    async def delete_concept(id_or_name: str):
        """Delete a concept."""
        return handlers.delete_concept(id_or_name=id_or_name)

    @server.tool()
    async def create_edge(source: str, target: str, edge_type: str,
                          metadata: dict | None = None):
        """Create an edge between two concepts (by name or ID)."""
        return handlers.create_edge(source=source, target=target,
                                    edge_type=edge_type, metadata=metadata)

    @server.tool()
    async def update_edge(edge_id: str, **changes):
        """Update an edge."""
        return handlers.update_edge(edge_id=edge_id, **changes)

    @server.tool()
    async def delete_edge(edge_id: str):
        """Delete an edge."""
        return handlers.delete_edge(edge_id=edge_id)

    @server.tool()
    async def report_gap(description: str, context: str | None = None):
        """Report a gap in the knowledge base for investigation."""
        return handlers.report_gap(description=description, context=context)

    asyncio.run(stdio_server(server))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/shells/test_mcp_server.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add apriori/shells/mcp_server.py tests/shells/test_mcp_server.py
git commit -m "feat: add MCP server shell with all tool handlers"
```

---

### Task 15: Deepening Agent Shell

**Files:**
- Create: `apriori/shells/deepening_agent.py`
- Create: `prompts/deepen.md`

- [ ] **Step 1: Create the default deepening agent system prompt**

```markdown
# prompts/deepen.md

You are the A-Priori deepening agent. Your job is to maintain and expand
a knowledge graph that describes a codebase.

## Your backlog

You will be presented with a prioritized list of work items. Each item
has a type, description, priority score, and optional context.

Priority scores are **advisory** — they reflect automated analysis of
what might be most important. Use your judgment to decide what to work on.

## Work item types

- **investigate_file**: A source file has no concepts referencing it. Read
  the file, understand what it does, and create concept(s) for it.
- **verify_concept**: Code referenced by a concept has changed. Re-read
  the code and update the concept description if needed. Update
  `last_verified`.
- **evaluate_relationship**: Two concepts are semantically similar but
  have no edge between them. Determine if an edge should exist and what
  type it should be.
- **reported_gap**: Another agent flagged missing documentation. Investigate
  and create or update concepts as needed.
- **review_concept**: A concept is flagged for review. Check its accuracy
  and clear the flag if it looks correct.

## Guidelines

- Create concepts at the right level of abstraction — not too granular
  (individual functions) or too broad (entire subsystems).
- Use typed edges precisely. `depends-on` means X cannot function without
  Y. `relates-to` is the fallback when the relationship is real but
  doesn't fit a specific type.
- When creating code references, always include a meaningful semantic
  anchor that would help relocate the code after a refactor.
- Mark your work: update `last_verified`, clear `needs-review` labels,
  and resolve work items when done.
```

- [ ] **Step 2: Implement the deepening agent shell**

```python
# apriori/shells/deepening_agent.py
"""Deepening agent shell — presents backlog to LLM, lets it decide what to work on."""

import sys
from pathlib import Path

from apriori.core.config import AprioriConfig, load_config
from apriori.maintenance.backlog import Backlog
from apriori.storage.local import LocalStore


def format_backlog_for_agent(backlog: Backlog) -> str:
    """Format the unresolved backlog as a text prompt for the LLM."""
    items = backlog.list_unresolved()
    if not items:
        return "No work items in the backlog. The knowledge base is up to date."

    lines = ["## Current Backlog\n"]
    for i, item in enumerate(items, 1):
        lines.append(
            f"{i}. **[{item.item_type.value}]** (priority: {item.priority_score:.2f})"
        )
        lines.append(f"   {item.description}")
        if item.file_path:
            lines.append(f"   File: `{item.file_path}`")
        if item.concept_id:
            lines.append(f"   Concept ID: `{item.concept_id}`")
        lines.append("")

    return "\n".join(lines)


def load_system_prompt(config: AprioriConfig) -> str:
    """Load the deepening agent system prompt from the configured path."""
    prompt_path = Path(config.deepening_agent.system_prompt_path)
    if prompt_path.exists():
        return prompt_path.read_text()
    return "You are the A-Priori deepening agent. Maintain the knowledge graph."


def main():
    """Entry point for the deepening agent.

    This shell:
    1. Loads config and initializes the store
    2. Computes priority scores
    3. Formats the backlog
    4. Prints the system prompt + backlog for the calling agent/LLM
    """
    config = load_config(Path("apriori.config.yaml"))
    store_path = Path(config.project.store_path).expanduser()

    from apriori.embedding.openai import OpenAIEmbeddingEngine
    embedding_engine = OpenAIEmbeddingEngine(model=config.embeddings.model)
    store = LocalStore(store_path=store_path, embedding_engine=embedding_engine)
    backlog = Backlog(store=store, config=config)

    # Recompute priorities before presenting
    backlog.compute_priorities()

    system_prompt = load_system_prompt(config)
    backlog_text = format_backlog_for_agent(backlog)

    max_iterations = config.deepening_agent.max_iterations_per_run

    print(f"=== A-Priori Deepening Agent ===")
    print(f"Max iterations: {max_iterations}")
    print(f"\n{system_prompt}")
    print(f"\n{backlog_text}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Commit**

```bash
git add apriori/shells/deepening_agent.py prompts/deepen.md
git commit -m "feat: add deepening agent shell with configurable system prompt"
```

---

### Task 16: Bootstrap Crawl

**Files:**
- Create: `apriori/maintenance/bootstrap.py`
- Create: `tests/maintenance/test_bootstrap.py`

- [ ] **Step 1: Write tests for bootstrap**

```python
# tests/maintenance/test_bootstrap.py
from pathlib import Path

import pytest

from apriori.core.config import AprioriConfig
from apriori.core.models import WorkItemType
from apriori.embedding.engine import FakeEmbeddingEngine
from apriori.maintenance.backlog import Backlog
from apriori.maintenance.bootstrap import BootstrapCrawler
from apriori.storage.local import LocalStore


@pytest.fixture
def bootstrap_env(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "src").mkdir()
    (repo / "src" / "main.py").write_text("def main():\n    pass\n")
    (repo / "src" / "utils.py").write_text("def helper():\n    pass\n")
    (repo / "README.md").write_text("# Project\n")
    (repo / ".git").mkdir()  # Should be ignored

    store_path = tmp_path / "store"
    engine = FakeEmbeddingEngine(dims=64)
    store = LocalStore(store_path=store_path, embedding_engine=engine)
    config = AprioriConfig()
    backlog = Backlog(store=store, config=config)

    return repo, store, backlog, config


class TestBootstrapCrawler:
    def test_generates_work_items_for_source_files(self, bootstrap_env):
        repo, store, backlog, config = bootstrap_env
        crawler = BootstrapCrawler(
            repo_path=repo, store=store, backlog=backlog
        )
        items = crawler.crawl()

        # Should have work items for .py files, not README or .git
        types = [i.item_type for i in items]
        assert all(t == WorkItemType.INVESTIGATE_FILE for t in types)
        paths = [i.file_path for i in items]
        assert "src/main.py" in paths
        assert "src/utils.py" in paths
        assert "README.md" not in paths

    def test_skips_already_covered_files(self, bootstrap_env):
        repo, store, backlog, config = bootstrap_env
        from apriori.core.models import Concept, CodeReference
        store.create_concept(Concept(
            name="Main",
            description="Main module",
            code_references=[
                CodeReference(
                    symbol="main",
                    file_path="src/main.py",
                    content_hash="sha256:x",
                    semantic_anchor="Main function",
                )
            ],
        ))

        crawler = BootstrapCrawler(
            repo_path=repo, store=store, backlog=backlog
        )
        items = crawler.crawl()

        paths = [i.file_path for i in items]
        assert "src/main.py" not in paths
        assert "src/utils.py" in paths
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/maintenance/test_bootstrap.py -v`
Expected: FAIL — cannot import

- [ ] **Step 3: Implement BootstrapCrawler**

```python
# apriori/maintenance/bootstrap.py
"""Initial repo crawl — generates investigate_file work items."""

from pathlib import Path

from apriori.core.models import WorkItem, WorkItemType
from apriori.maintenance.backlog import Backlog


# File extensions to crawl (source code)
SOURCE_EXTENSIONS = {
    ".py", ".js", ".ts", ".tsx", ".jsx",
    ".go", ".rs", ".java", ".kt",
    ".c", ".cpp", ".h", ".hpp",
    ".rb", ".php", ".swift", ".scala",
}

# Directories to skip
SKIP_DIRS = {
    ".git", "__pycache__", "node_modules", ".venv", "venv",
    ".tox", ".mypy_cache", ".pytest_cache", "dist", "build",
    ".eggs", "*.egg-info",
}


class BootstrapCrawler:
    def __init__(self, repo_path: Path, store, backlog: Backlog):
        self._repo_path = Path(repo_path)
        self._store = store
        self._backlog = backlog

    def _get_covered_files(self) -> set[str]:
        """Get all file paths that are referenced by existing concepts."""
        covered = set()
        # Walk all concepts and collect their code reference file paths
        import sqlite3
        self._store._conn.row_factory = sqlite3.Row
        rows = self._store._conn.execute(
            "SELECT DISTINCT file_path FROM code_references"
        ).fetchall()
        for row in rows:
            covered.add(row["file_path"])
        return covered

    def _find_source_files(self) -> list[str]:
        """Walk the repo and find all source files."""
        files = []
        for path in self._repo_path.rglob("*"):
            if path.is_file() and path.suffix in SOURCE_EXTENSIONS:
                # Check if any parent dir should be skipped
                parts = path.relative_to(self._repo_path).parts
                if any(part in SKIP_DIRS for part in parts):
                    continue
                rel_path = str(path.relative_to(self._repo_path))
                files.append(rel_path)
        return sorted(files)

    def crawl(self) -> list[WorkItem]:
        """Crawl the repo and generate work items for uncovered files."""
        covered = self._get_covered_files()
        source_files = self._find_source_files()
        items = []

        for file_path in source_files:
            if file_path not in covered:
                item = WorkItem(
                    item_type=WorkItemType.INVESTIGATE_FILE,
                    description=f"Investigate uncovered file: {file_path}",
                    file_path=file_path,
                )
                self._backlog.add(item)
                items.append(item)

        return items
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/maintenance/test_bootstrap.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add apriori/maintenance/bootstrap.py tests/maintenance/test_bootstrap.py
git commit -m "feat: add bootstrap crawler for initial repo indexing"
```

---

### Task 17: LocalStore rebuild_index and get_stale_concepts

**Files:**
- Modify: `apriori/storage/local.py`
- Modify: `tests/storage/test_local.py`

- [ ] **Step 1: Write tests for rebuild_index and get_stale_concepts**

Add to `tests/storage/test_local.py`:

```python
from datetime import timedelta


class TestStaleAndRebuild:
    def test_get_stale_concepts(self, store_with_embeddings):
        store = store_with_embeddings
        from datetime import datetime, timezone
        old_time = datetime(2020, 1, 1, tzinfo=timezone.utc)
        concept = Concept(
            name="Old",
            description="Old concept",
            last_verified=old_time,
        )
        store.create_concept(concept)
        store.create_concept(
            Concept(name="Fresh", description="Fresh concept",
                    last_verified=datetime.now(timezone.utc))
        )

        # Stale if not verified in last hour
        stale = store.get_stale_concepts(threshold_seconds=3600)
        names = [c.name for c in stale]
        assert "Old" in names
        assert "Fresh" not in names

    def test_rebuild_index(self, tmp_store_path):
        engine = FakeEmbeddingEngine(dims=64)
        store = LocalStore(store_path=tmp_store_path, embedding_engine=engine)

        store.create_concept(
            Concept(name="Alpha", description="First concept")
        )
        store.create_concept(
            Concept(name="Beta", description="Second concept")
        )

        # Wipe the SQLite database
        store._conn.execute("DELETE FROM concepts")
        store._conn.commit()
        assert store.get_concept("Alpha") is None

        # Rebuild from flat files
        store.rebuild_index()
        assert store.get_concept("Alpha") is not None
        assert store.get_concept("Beta") is not None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/storage/test_local.py::TestStaleAndRebuild -v`
Expected: FAIL — NotImplementedError

- [ ] **Step 3: Implement rebuild_index and get_stale_concepts**

```python
    def get_stale_concepts(self, threshold_seconds: int) -> list[Concept]:
        from datetime import datetime, timezone, timedelta
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=threshold_seconds)
        self._conn.row_factory = sqlite3.Row
        rows = self._conn.execute(
            """SELECT * FROM concepts
               WHERE last_verified IS NOT NULL
               AND last_verified < ?""",
            (cutoff.isoformat(),),
        ).fetchall()
        return [self._concept_from_row(r) for r in rows]

    def rebuild_index(self) -> None:
        """Rebuild the SQLite index from flat YAML files."""
        from apriori.storage.flatfile import read_all_concepts

        # Clear existing index data
        self._conn.execute("DELETE FROM code_references")
        self._conn.execute("DELETE FROM edges")
        self._conn.execute("DELETE FROM concepts")
        self._conn.commit()

        # Re-read all flat files
        all_data = read_all_concepts(self._graph_dir)
        for concept, edges in all_data:
            self._index_concept(concept)
            for edge in edges:
                self._conn.execute(
                    """INSERT OR REPLACE INTO edges
                       (id, source, target, edge_type, metadata, created_at)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        str(edge.id),
                        str(edge.source),
                        str(edge.target),
                        str(edge.edge_type),
                        json.dumps(edge.metadata) if edge.metadata else None,
                        edge.created_at.isoformat(),
                    ),
                )
        self._conn.commit()

        # Rebuild vector index if embedding engine is available
        if self._embedding_engine:
            self._rebuild_vectors()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/storage/test_local.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add apriori/storage/local.py tests/storage/test_local.py
git commit -m "feat: add rebuild_index and get_stale_concepts to LocalStore"
```

---

### Task 18: Integration Test — Full Workflow

**Files:**
- Create: `tests/test_integration.py`

- [ ] **Step 1: Write end-to-end integration test**

```python
# tests/test_integration.py
"""Integration test: full workflow from concept creation through search and traversal."""

import pytest

from apriori.core.config import AprioriConfig
from apriori.core.models import Concept, CodeReference, Edge, WorkItemType
from apriori.embedding.engine import FakeEmbeddingEngine
from apriori.graph.query import UnifiedSearch
from apriori.maintenance.backlog import Backlog
from apriori.shells.mcp_server import AprioriMCPHandlers
from apriori.storage.local import LocalStore


@pytest.fixture
def full_system(tmp_store_path):
    engine = FakeEmbeddingEngine(dims=64)
    store = LocalStore(store_path=tmp_store_path, embedding_engine=engine)
    config = AprioriConfig()
    handlers = AprioriMCPHandlers(store=store, config=config)
    return handlers, store, config


class TestFullWorkflow:
    def test_create_concepts_search_traverse(self, full_system):
        handlers, store, config = full_system

        # Create concepts
        auth = handlers.create_concept(
            name="Authentication",
            description="JWT-based authentication system",
        )
        sessions = handlers.create_concept(
            name="Session Management",
            description="User session handling with Redis",
        )
        users = handlers.create_concept(
            name="User Model",
            description="Core user data model and CRUD",
        )

        # Create edges
        handlers.create_edge(
            source="Authentication",
            target="Session Management",
            edge_type="depends-on",
        )
        handlers.create_edge(
            source="Authentication",
            target="User Model",
            edge_type="depends-on",
        )
        handlers.create_edge(
            source="Session Management",
            target="User Model",
            edge_type="relates-to",
        )

        # Search
        results = handlers.search(query="authentication JWT")
        assert len(results) > 0

        # Traverse from Authentication
        subgraph = handlers.traverse(
            start="Authentication", max_hops=1
        )
        concept_names = {c["name"] for c in subgraph["concepts"]}
        assert "Authentication" in concept_names
        assert "Session Management" in concept_names
        assert "User Model" in concept_names

        # Traverse with edge type filter
        deps_only = handlers.traverse(
            start="Authentication",
            edge_types=["depends-on"],
            max_hops=1,
        )
        dep_names = {c["name"] for c in deps_only["concepts"]}
        assert "Session Management" in dep_names
        assert "User Model" in dep_names

        # Report a gap
        gap = handlers.report_gap(
            description="No documentation for password hashing strategy"
        )
        assert "id" in gap

        # Verify gap is in backlog
        backlog = Backlog(store=store, config=config)
        items = backlog.list_unresolved()
        assert any(
            i.item_type == WorkItemType.REPORTED_GAP
            for i in items
        )

    def test_rebuild_preserves_all_data(self, full_system):
        handlers, store, config = full_system

        handlers.create_concept(
            name="Concept A", description="First"
        )
        handlers.create_concept(
            name="Concept B", description="Second"
        )
        handlers.create_edge(
            source="Concept A",
            target="Concept B",
            edge_type="depends-on",
        )

        # Rebuild index from flat files
        store.rebuild_index()

        # Verify everything survived
        a = handlers.get_concept(id_or_name="Concept A")
        assert a is not None
        b = handlers.get_concept(id_or_name="Concept B")
        assert b is not None

        subgraph = handlers.traverse(start="Concept A", max_hops=1)
        assert len(subgraph["concepts"]) == 2
```

- [ ] **Step 2: Run integration test**

Run: `pytest tests/test_integration.py -v`
Expected: All tests PASS

- [ ] **Step 3: Run the full test suite**

Run: `pytest -v`
Expected: All tests PASS

- [ ] **Step 4: Commit**

```bash
git add tests/test_integration.py
git commit -m "test: add full workflow integration tests"
```

---

### Task 19: Add .gitignore and Final Cleanup

**Files:**
- Create: `.gitignore`
- Modify: `README.md`

- [ ] **Step 1: Create .gitignore**

```
# Python
__pycache__/
*.pyc
*.egg-info/
dist/
build/
.eggs/
*.egg

# Virtual environment
.venv/
venv/

# IDE
.idea/
.vscode/
*.swp

# A-Priori data (local knowledge store)
.a-priori/

# Superpowers (brainstorm artifacts)
.superpowers/

# Testing
.pytest_cache/
.coverage
htmlcov/
```

- [ ] **Step 2: Update README.md**

```markdown
# A-Priori

Define your ontology.

An agent-first, MCP-enabled knowledge base that automatically builds and
maintains a concept graph for your codebase.

## Quick Start

```bash
pip install -e ".[dev]"
```

## Architecture

See [System Design](docs/superpowers/specs/2026-03-25-a-priori-system-design.md)
for the full specification.

## Usage

### MCP Server

```bash
apriori-mcp
```

### Deepening Agent

```bash
apriori-deepen
```

### Configuration

Copy and customize `apriori.config.yaml`. All fields have sensible defaults.
```

- [ ] **Step 3: Run the full test suite one final time**

Run: `pytest -v`
Expected: All tests PASS

- [ ] **Step 4: Commit**

```bash
git add .gitignore README.md
git commit -m "chore: add .gitignore and update README"
```
