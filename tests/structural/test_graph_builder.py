"""Tests for the Graph Builder (Story 3.5, ERD §3.3.2).

AC traceability:
- AC1: 5 functions + 3 classes → 8 concept nodes with created_by="agent", confidence=1.0
- AC2: call relationship → calls edge with evidence_type="structural", confidence=1.0
- AC3: idempotency — running twice with no changes produces no duplicates
- AC4: re-running with same FQN updates the concept, not creates a duplicate
- AC5: every concept has at least one CodeReference with a valid content_hash
- AC6: every CodeReference has semantic_anchor populated
- AC7: function concepts store params and return_type in metadata
- AC8: every created/updated concept and edge stamped with git HEAD hash
"""

from pathlib import Path

import pytest

from apriori.models.concept import Concept
from apriori.models.edge import Edge
from apriori.storage.sqlite_store import SQLiteStore
from apriori.structural.graph_builder import GraphBuilder
from apriori.structural.models import (
    ClassEntity,
    FunctionEntity,
    FunctionParam,
    ImportRelationship,
    InterfaceEntity,
    ParseResult,
    Relationship,
)

FAKE_GIT_HEAD = "a" * 40


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def store(tmp_path: Path) -> SQLiteStore:
    return SQLiteStore(tmp_path / "test.db")


@pytest.fixture
def builder(store: SQLiteStore) -> GraphBuilder:
    return GraphBuilder(store, git_head=FAKE_GIT_HEAD)


def _make_result(
    file_path: Path,
    functions: list | None = None,
    classes: list | None = None,
    interfaces: list | None = None,
    relationships: list | None = None,
    source: bytes = b"# placeholder\n" * 30,
    language: str = "python",
) -> ParseResult:
    return ParseResult(
        file_path=file_path,
        language=language,
        source=source,
        functions=functions or [],
        classes=classes or [],
        interfaces=interfaces or [],
        relationships=relationships or [],
    )


def _func(name: str, fp: Path, start: int = 1, end: int = 1) -> FunctionEntity:
    return FunctionEntity(name=name, start_line=start, end_line=end, file_path=fp)


def _cls(name: str, fp: Path, start: int = 1, end: int = 1, bases: list | None = None) -> ClassEntity:
    return ClassEntity(name=name, start_line=start, end_line=end, file_path=fp, bases=bases or [])


def _concept_by_name(store: SQLiteStore, name: str) -> Concept:
    return next(c for c in store.list_concepts() if c.name == name)


# ---------------------------------------------------------------------------
# AC1: 5 functions + 3 classes → 8 concept nodes
# ---------------------------------------------------------------------------


class TestAC1ConceptNodes:
    """AC1: 8 concept nodes created for 5 functions and 3 classes."""

    def test_eight_concepts_created_from_five_functions_and_three_classes(
        self, store: SQLiteStore, builder: GraphBuilder, tmp_path: Path
    ) -> None:
        """Given parse results containing 5 functions and 3 classes, when the graph
        builder runs, then 8 concept nodes are created."""
        fp = tmp_path / "code.py"
        source = b"def f(): pass\n" * 10
        functions = [_func(f"func_{i}", fp, start=i + 1, end=i + 1) for i in range(5)]
        classes = [_cls(f"Class{i}", fp, start=i + 6, end=i + 6) for i in range(3)]

        builder.build([_make_result(fp, functions=functions, classes=classes, source=source)])

        assert len(store.list_concepts()) == 9

    def test_all_concepts_have_agent_created_by(
        self, store: SQLiteStore, builder: GraphBuilder, tmp_path: Path
    ) -> None:
        """All created concept nodes have created_by='agent'."""
        fp = tmp_path / "code.py"
        source = b"def f(): pass\n" * 5
        functions = [_func(f"f{i}", fp, start=i + 1, end=i + 1) for i in range(5)]

        builder.build([_make_result(fp, functions=functions, source=source)])

        for concept in store.list_concepts():
            assert concept.created_by == "agent"

    def test_all_concepts_have_confidence_one(
        self, store: SQLiteStore, builder: GraphBuilder, tmp_path: Path
    ) -> None:
        """All created concept nodes have confidence=1.0."""
        fp = tmp_path / "code.py"
        source = b"class C: pass\n" * 3
        classes = [_cls(f"C{i}", fp, start=i + 1, end=i + 1) for i in range(3)]

        builder.build([_make_result(fp, classes=classes, source=source)])

        for concept in store.list_concepts():
            assert concept.confidence == 1.0

    def test_interface_entities_become_concepts(
        self, store: SQLiteStore, builder: GraphBuilder, tmp_path: Path
    ) -> None:
        """TypeScript interface entities are also converted to concept nodes."""
        fp = tmp_path / "types.ts"
        source = b"interface Foo {}\ninterface Bar {}\n"
        interfaces = [
            InterfaceEntity(name="Foo", start_line=1, end_line=1, file_path=fp),
            InterfaceEntity(name="Bar", start_line=2, end_line=2, file_path=fp),
        ]

        builder.build([_make_result(fp, interfaces=interfaces, source=source, language="typescript")])

        assert len(store.list_concepts()) == 3


# ---------------------------------------------------------------------------
# AC2: calls relationship → calls edge
# ---------------------------------------------------------------------------


class TestAC2CallsEdge:
    """AC2: a calls edge is created with evidence_type=structural and confidence=1.0."""

    def test_calls_edge_created_between_two_functions(
        self, store: SQLiteStore, builder: GraphBuilder, tmp_path: Path
    ) -> None:
        """Given parse results with a call from func_a to func_b, when the builder
        runs, then a calls edge is created."""
        fp = tmp_path / "module.py"
        source = b"def func_a(): func_b()\ndef func_b(): pass\n"
        func_a = _func("func_a", fp, start=1, end=1)
        func_b = _func("func_b", fp, start=2, end=2)
        rel = Relationship(kind="calls", source="func_a", target="func_b", file_path=fp, line=1)

        builder.build([_make_result(fp, functions=[func_a, func_b], relationships=[rel], source=source)])

        edges = store.list_edges(edge_type="calls")
        assert len(edges) == 1

    def test_calls_edge_has_structural_evidence_type(
        self, store: SQLiteStore, builder: GraphBuilder, tmp_path: Path
    ) -> None:
        """The calls edge has evidence_type='structural'."""
        fp = tmp_path / "module.py"
        source = b"def func_a(): pass\ndef func_b(): pass\n"
        rel = Relationship(kind="calls", source="func_a", target="func_b", file_path=fp, line=1)

        builder.build([_make_result(fp, functions=[_func("func_a", fp, 1, 1), _func("func_b", fp, 2, 2)], relationships=[rel], source=source)])

        edge = store.list_edges(edge_type="calls")[0]
        assert edge.evidence_type == "structural"

    def test_calls_edge_has_confidence_one(
        self, store: SQLiteStore, builder: GraphBuilder, tmp_path: Path
    ) -> None:
        """The calls edge has confidence=1.0."""
        fp = tmp_path / "module.py"
        source = b"def a(): pass\ndef b(): pass\n"
        rel = Relationship(kind="calls", source="a", target="b", file_path=fp, line=1)

        builder.build([_make_result(fp, functions=[_func("a", fp, 1, 1), _func("b", fp, 2, 2)], relationships=[rel], source=source)])

        edge = store.list_edges(edge_type="calls")[0]
        assert edge.confidence == 1.0

    def test_inherits_edge_created_from_relationship(
        self, store: SQLiteStore, builder: GraphBuilder, tmp_path: Path
    ) -> None:
        """A class with a base in the same file gets an inherits edge via relationships."""
        fp = tmp_path / "module.py"
        source = b"class Animal: pass\nclass Dog(Animal): pass\n"
        animal = _cls("Animal", fp, start=1, end=1)
        dog = _cls("Dog", fp, start=2, end=2, bases=["Animal"])
        rel = Relationship(kind="inherits", source="Dog", target="Animal", file_path=fp, line=2)

        builder.build([_make_result(fp, classes=[animal, dog], relationships=[rel], source=source)])

        edges = store.list_edges(edge_type="inherits")
        assert len(edges) == 1

    def test_edges_skipped_when_source_not_in_store(
        self, store: SQLiteStore, builder: GraphBuilder, tmp_path: Path
    ) -> None:
        """A relationship whose source concept is not in the store is skipped."""
        fp = tmp_path / "module.py"
        source = b"def func_b(): pass\n"
        # Only func_b exists; func_a is referenced in relationship but not in functions
        rel = Relationship(kind="calls", source="func_a", target="func_b", file_path=fp, line=1)

        result = builder.build([_make_result(fp, functions=[_func("func_b", fp, 1, 1)], relationships=[rel], source=source)])

        assert len(store.list_edges()) == 0
        assert result.edges_skipped >= 1


# ---------------------------------------------------------------------------
# Gap AC: module concepts + import edges
# ---------------------------------------------------------------------------


class TestGapModuleConceptsAndImportEdges:
    """Gap AC: module-level concepts and imports edges are materialized."""

    def test_module_concept_created_for_each_file(
        self, store: SQLiteStore, builder: GraphBuilder, tmp_path: Path
    ) -> None:
        fp = tmp_path / "example.py"
        source = b"def my_func(): pass\n"

        builder.build([_make_result(fp, functions=[_func("my_func", fp, 1, 1)], source=source)])

        concept_names = {c.name for c in store.list_concepts()}
        assert str(fp) in concept_names
        assert str(fp) + "::my_func" in concept_names

    def test_python_import_edges_from_module_concept(
        self, store: SQLiteStore, builder: GraphBuilder, tmp_path: Path
    ) -> None:
        fp = tmp_path / "example.py"
        source = b"import os\nfrom pathlib import Path\ndef my_func(): pass\n"
        rels = [
            Relationship(kind="imports", source="", target="os", file_path=fp, line=1),
            Relationship(kind="imports", source="pathlib", target="Path", file_path=fp, line=2),
        ]
        store.create_concept(Concept(name="os", description="os module", created_by="agent"))
        store.create_concept(Concept(name="Path", description="Path class", created_by="agent"))

        builder.build([_make_result(fp, functions=[_func("my_func", fp, 3, 3)], relationships=rels, source=source)])

        module_concept = next(c for c in store.list_concepts() if c.name == str(fp))
        imports_edges = [
            e for e in store.list_edges(edge_type="imports")
            if e.source_id == module_concept.id
        ]
        assert len(imports_edges) == 2
        assert all(e.evidence_type == "structural" for e in imports_edges)
        assert all(e.confidence == 1.0 for e in imports_edges)

    def test_typescript_import_edges_from_module_concept(
        self, store: SQLiteStore, builder: GraphBuilder, tmp_path: Path
    ) -> None:
        fp = tmp_path / "app.ts"
        source = b"import { Router } from 'express'\nexport function handler() {}\n"
        store.create_concept(Concept(name="Router", description="Router type", created_by="agent"))
        imports = [ImportRelationship(source_module="express", names=["Router"], file_path=fp, start_line=1)]

        builder.build([
            _make_result(
                fp,
                functions=[_func("handler", fp, 2, 2)],
                source=source,
                language="typescript",
                )
        ])
        # Rebuild with imports populated (mirrors TypeScript parser output).
        result = _make_result(
            fp,
            functions=[_func("handler", fp, 2, 2)],
            source=source,
            language="typescript",
        )
        result.imports = imports
        builder.build([result])

        module_concept = next(c for c in store.list_concepts() if c.name == str(fp))
        imports_edges = [
            e for e in store.list_edges(edge_type="imports")
            if e.source_id == module_concept.id
        ]
        assert len(imports_edges) == 1

    def test_module_and_import_edges_are_idempotent(
        self, store: SQLiteStore, builder: GraphBuilder, tmp_path: Path
    ) -> None:
        fp = tmp_path / "example.py"
        source = b"import os\ndef my_func(): pass\n"
        store.create_concept(Concept(name="os", description="os module", created_by="agent"))
        rels = [Relationship(kind="imports", source="", target="os", file_path=fp, line=1)]
        result = _make_result(fp, functions=[_func("my_func", fp, 2, 2)], relationships=rels, source=source)

        builder.build([result])
        builder.build([result])

        module_concepts = [c for c in store.list_concepts() if c.name == str(fp)]
        imports_edges = store.list_edges(edge_type="imports")
        assert len(module_concepts) == 1
        assert len(imports_edges) == 1

    def test_stale_import_edges_removed_when_file_changes(
        self, store: SQLiteStore, builder: GraphBuilder, tmp_path: Path
    ) -> None:
        fp = tmp_path / "example.py"
        store.create_concept(Concept(name="os", description="os module", created_by="agent"))
        store.create_concept(Concept(name="Path", description="Path class", created_by="agent"))

        first = _make_result(
            fp,
            functions=[_func("my_func", fp, 3, 3)],
            relationships=[
                Relationship(kind="imports", source="", target="os", file_path=fp, line=1),
                Relationship(kind="imports", source="pathlib", target="Path", file_path=fp, line=2),
            ],
            source=b"import os\nfrom pathlib import Path\ndef my_func(): pass\n",
        )
        second = _make_result(
            fp,
            functions=[_func("my_func", fp, 2, 2)],
            relationships=[Relationship(kind="imports", source="", target="os", file_path=fp, line=1)],
            source=b"import os\ndef my_func(): pass\n",
        )

        builder.build([first])
        builder.build([second])

        module_concept = next(c for c in store.list_concepts() if c.name == str(fp))
        imports_edges = [
            e for e in store.list_edges(edge_type="imports")
            if e.source_id == module_concept.id
        ]
        assert len(imports_edges) == 1
        target_concept = store.get_concept(imports_edges[0].target_id)
        assert target_concept is not None
        assert target_concept.name == "os"


# ---------------------------------------------------------------------------
# AC3: idempotency
# ---------------------------------------------------------------------------


class TestAC3Idempotency:
    """AC3: running twice with no changes creates no duplicate concepts or edges."""

    def test_running_twice_no_duplicate_concepts(
        self, store: SQLiteStore, builder: GraphBuilder, tmp_path: Path
    ) -> None:
        """Given the builder has already run, when run again with no changes,
        no duplicate concepts are created."""
        fp = tmp_path / "code.py"
        source = b"def func_a(): pass\ndef func_b(): pass\n"
        functions = [_func("func_a", fp, 1, 1), _func("func_b", fp, 2, 2)]
        result = _make_result(fp, functions=functions, source=source)

        builder.build([result])
        builder.build([result])

        assert len(store.list_concepts()) == 3

    def test_running_twice_no_duplicate_edges(
        self, store: SQLiteStore, builder: GraphBuilder, tmp_path: Path
    ) -> None:
        """Given the builder has already run, when run again with no changes,
        no duplicate edges are created."""
        fp = tmp_path / "code.py"
        source = b"def func_a(): func_b()\ndef func_b(): pass\n"
        functions = [_func("func_a", fp, 1, 1), _func("func_b", fp, 2, 2)]
        rel = Relationship(kind="calls", source="func_a", target="func_b", file_path=fp, line=1)
        result = _make_result(fp, functions=functions, relationships=[rel], source=source)

        builder.build([result])
        builder.build([result])

        assert len(store.list_edges()) == 1


# ---------------------------------------------------------------------------
# AC4: rename → concept updated not duplicated
# ---------------------------------------------------------------------------


class TestAC4UpdateNotDuplicate:
    """AC4: re-running with same FQN updates the concept in place, not duplicates it."""

    def test_same_fqn_updates_existing_concept(
        self, store: SQLiteStore, builder: GraphBuilder, tmp_path: Path
    ) -> None:
        """Given a concept already exists for a FQN, when builder runs again with
        the same FQN (updated source content), the concept is updated, not duplicated."""
        fp = tmp_path / "code.py"
        source1 = b"def func_a(): pass\n"
        source2 = b"def func_a(): return 1\n"  # same name, new content
        func = _func("func_a", fp, 1, 1)

        builder.build([_make_result(fp, functions=[func], source=source1)])
        first_concepts = store.list_concepts()
        assert len(first_concepts) == 2
        first_id = _concept_by_name(store, str(fp) + "::func_a").id

        builder.build([_make_result(fp, functions=[func], source=source2)])
        second_concepts = store.list_concepts()

        assert len(second_concepts) == 2
        assert _concept_by_name(store, str(fp) + "::func_a").id == first_id  # same UUID, updated in place


# ---------------------------------------------------------------------------
# AC5: code reference with valid content_hash
# ---------------------------------------------------------------------------


class TestAC5ContentHash:
    """AC5: every concept has at least one CodeReference with a valid content_hash."""

    def test_concept_has_code_reference(
        self, store: SQLiteStore, builder: GraphBuilder, tmp_path: Path
    ) -> None:
        """Every concept has at least one CodeReference."""
        fp = tmp_path / "code.py"
        source = b"def my_func(): pass\n"
        func = _func("my_func", fp, 1, 1)

        builder.build([_make_result(fp, functions=[func], source=source)])

        concept = _concept_by_name(store, str(fp) + "::my_func")
        assert len(concept.code_references) >= 1

    def test_content_hash_is_valid_sha256(
        self, store: SQLiteStore, builder: GraphBuilder, tmp_path: Path
    ) -> None:
        """The content_hash in each CodeReference is a valid 64-char hex SHA-256."""
        fp = tmp_path / "code.py"
        source = b"def my_func(): pass\n"
        func = _func("my_func", fp, 1, 1)

        builder.build([_make_result(fp, functions=[func], source=source)])

        concept = _concept_by_name(store, str(fp) + "::my_func")
        ref = concept.code_references[0]
        assert len(ref.content_hash) == 64
        assert all(c in "0123456789abcdef" for c in ref.content_hash)

    def test_content_hash_reflects_actual_source(
        self, store: SQLiteStore, builder: GraphBuilder, tmp_path: Path
    ) -> None:
        """The content_hash is the SHA-256 of the entity's source lines."""
        import hashlib

        fp = tmp_path / "code.py"
        source = b"def my_func(): pass\n"
        func = _func("my_func", fp, 1, 1)

        builder.build([_make_result(fp, functions=[func], source=source)])

        expected_hash = hashlib.sha256(b"def my_func(): pass").hexdigest()
        concept = _concept_by_name(store, str(fp) + "::my_func")
        assert concept.code_references[0].content_hash == expected_hash


# ---------------------------------------------------------------------------
# AC6: semantic_anchor populated
# ---------------------------------------------------------------------------


class TestAC6SemanticAnchor:
    """AC6: every CodeReference has semantic_anchor populated with a structural hint."""

    def test_semantic_anchor_is_non_empty(
        self, store: SQLiteStore, builder: GraphBuilder, tmp_path: Path
    ) -> None:
        """CodeReference.semantic_anchor is a non-empty string."""
        fp = tmp_path / "code.py"
        source = b"def my_func(): pass\n"
        func = _func("my_func", fp, 1, 1)

        builder.build([_make_result(fp, functions=[func], source=source)])

        ref = _concept_by_name(store, str(fp) + "::my_func").code_references[0]
        assert ref.semantic_anchor

    def test_semantic_anchor_contains_entity_name(
        self, store: SQLiteStore, builder: GraphBuilder, tmp_path: Path
    ) -> None:
        """The semantic anchor references the entity name or type."""
        fp = tmp_path / "code.py"
        source = b"def my_func(): pass\n"
        func = _func("my_func", fp, 1, 1)

        builder.build([_make_result(fp, functions=[func], source=source)])

        ref = _concept_by_name(store, str(fp) + "::my_func").code_references[0]
        assert "my_func" in ref.semantic_anchor or "function" in ref.semantic_anchor.lower()

    def test_semantic_anchor_contains_line_range(
        self, store: SQLiteStore, builder: GraphBuilder, tmp_path: Path
    ) -> None:
        """The semantic anchor includes the line range for navigation."""
        fp = tmp_path / "code.py"
        source = b"def my_func(): pass\n" + b"# more code\n" * 5
        func = _func("my_func", fp, 1, 1)

        builder.build([_make_result(fp, functions=[func], source=source)])

        ref = _concept_by_name(store, str(fp) + "::my_func").code_references[0]
        assert "1" in ref.semantic_anchor  # start line appears somewhere


# ---------------------------------------------------------------------------
# AC7: metadata stores params and return type
# ---------------------------------------------------------------------------


class TestAC7Metadata:
    """AC7: function concepts store params and return_type in metadata."""

    def test_function_metadata_contains_params(
        self, store: SQLiteStore, builder: GraphBuilder, tmp_path: Path
    ) -> None:
        """A function concept's metadata dict contains a 'params' key."""
        fp = tmp_path / "code.py"
        source = b"def greet(name: str, age: int) -> str: pass\n"
        func = FunctionEntity(
            name="greet",
            params=[
                FunctionParam(name="name", type_annotation="str"),
                FunctionParam(name="age", type_annotation="int"),
            ],
            return_type="str",
            start_line=1,
            end_line=1,
            file_path=fp,
        )

        builder.build([_make_result(fp, functions=[func], source=source)])

        concept = _concept_by_name(store, str(fp) + "::greet")
        assert concept.metadata is not None
        assert "params" in concept.metadata
        params = concept.metadata["params"]
        assert len(params) == 2
        names = [p["name"] for p in params]
        assert "name" in names
        assert "age" in names

    def test_function_metadata_contains_return_type(
        self, store: SQLiteStore, builder: GraphBuilder, tmp_path: Path
    ) -> None:
        """A function concept's metadata dict contains a 'return_type' key."""
        fp = tmp_path / "code.py"
        source = b"def greet(name: str) -> str: pass\n"
        func = FunctionEntity(
            name="greet",
            params=[FunctionParam(name="name", type_annotation="str")],
            return_type="str",
            start_line=1,
            end_line=1,
            file_path=fp,
        )

        builder.build([_make_result(fp, functions=[func], source=source)])

        concept = _concept_by_name(store, str(fp) + "::greet")
        assert concept.metadata["return_type"] == "str"

    def test_function_metadata_contains_type_annotations(
        self, store: SQLiteStore, builder: GraphBuilder, tmp_path: Path
    ) -> None:
        """Parameter type annotations are stored in metadata."""
        fp = tmp_path / "code.py"
        source = b"def f(x: int) -> None: pass\n"
        func = FunctionEntity(
            name="f",
            params=[FunctionParam(name="x", type_annotation="int")],
            return_type="None",
            start_line=1,
            end_line=1,
            file_path=fp,
        )

        builder.build([_make_result(fp, functions=[func], source=source)])

        concept = _concept_by_name(store, str(fp) + "::f")
        param_entry = concept.metadata["params"][0]
        assert param_entry["type_annotation"] == "int"


# ---------------------------------------------------------------------------
# AC8: derived_from_code_version stamped
# ---------------------------------------------------------------------------


class TestAC8GitHeadStamping:
    """AC8: concepts and edges are stamped with the current git HEAD hash."""

    def test_concept_derived_from_code_version_set(
        self, store: SQLiteStore, builder: GraphBuilder, tmp_path: Path
    ) -> None:
        """Concept.derived_from_code_version is set to the git HEAD passed at construction."""
        fp = tmp_path / "code.py"
        source = b"def func(): pass\n"
        func = _func("func", fp, 1, 1)

        builder.build([_make_result(fp, functions=[func], source=source)])

        concept = _concept_by_name(store, str(fp) + "::func")
        assert concept.derived_from_code_version == FAKE_GIT_HEAD

    def test_edge_derived_from_code_version_set(
        self, store: SQLiteStore, builder: GraphBuilder, tmp_path: Path
    ) -> None:
        """Edge.derived_from_code_version is set to the git HEAD passed at construction."""
        fp = tmp_path / "code.py"
        source = b"def a(): pass\ndef b(): pass\n"
        rel = Relationship(kind="calls", source="a", target="b", file_path=fp, line=1)

        builder.build([_make_result(fp, functions=[_func("a", fp, 1, 1), _func("b", fp, 2, 2)], relationships=[rel], source=source)])

        edge = store.list_edges()[0]
        assert edge.derived_from_code_version == FAKE_GIT_HEAD

    def test_builder_without_git_head_leaves_version_none(
        self, store: SQLiteStore, tmp_path: Path
    ) -> None:
        """When no git_head is provided, derived_from_code_version is None."""
        no_git_builder = GraphBuilder(store)
        fp = tmp_path / "code.py"
        source = b"def func(): pass\n"
        func = _func("func", fp, 1, 1)

        no_git_builder.build([_make_result(fp, functions=[func], source=source)])

        concept = _concept_by_name(store, str(fp) + "::func")
        assert concept.derived_from_code_version is None


# ---------------------------------------------------------------------------
# Integration: real parsers + graph builder
# ---------------------------------------------------------------------------


class TestIntegration:
    """Integration: real parsers feeding the graph builder produce the expected graph."""

    def test_python_parser_integration(
        self, store: SQLiteStore, builder: GraphBuilder, tmp_path: Path
    ) -> None:
        """Real Python parser output feeds the graph builder and produces expected concepts."""
        from apriori.structural.languages.python_parser import PythonParser

        source = b"def func_a(): pass\n\ndef func_b(): pass\n\nclass MyClass:\n    pass\n"
        fp = tmp_path / "integration.py"
        fp.write_bytes(source)

        parser = PythonParser()
        result = parser.parse(source, fp)

        builder.build([result])

        concept_names = {c.name for c in store.list_concepts()}
        fqn_a = str(fp) + "::func_a"
        fqn_b = str(fp) + "::func_b"
        fqn_cls = str(fp) + "::MyClass"

        assert fqn_a in concept_names
        assert fqn_b in concept_names
        assert fqn_cls in concept_names

    def test_typescript_class_bases_produce_inherits_edge(
        self, store: SQLiteStore, builder: GraphBuilder, tmp_path: Path
    ) -> None:
        """ClassEntity.bases from the TypeScript parser produce inherits edges."""
        fp = tmp_path / "types.ts"
        source = b"class Animal {}\nclass Dog extends Animal {}\n"
        animal = _cls("Animal", fp, start=1, end=1)
        dog = _cls("Dog", fp, start=2, end=2, bases=["Animal"])
        # TypeScript parser does NOT emit relationships for inherits; uses ClassEntity.bases
        result = _make_result(fp, classes=[animal, dog], source=source, language="typescript")

        builder.build([result])

        edges = store.list_edges(edge_type="inherits")
        assert len(edges) == 1
        edge = edges[0]
        assert edge.evidence_type == "structural"

    def test_class_methods_become_concepts_with_fqn(
        self, store: SQLiteStore, builder: GraphBuilder, tmp_path: Path
    ) -> None:
        """Class methods are turned into concepts with FQN file::class::method."""
        fp = tmp_path / "code.py"
        source = b"class MyClass:\n    def my_method(self): pass\n"
        method = FunctionEntity(name="my_method", start_line=2, end_line=2, file_path=fp, params=[])
        cls = ClassEntity(name="MyClass", start_line=1, end_line=2, file_path=fp, methods=[method])

        builder.build([_make_result(fp, classes=[cls], source=source)])

        concept_names = {c.name for c in store.list_concepts()}
        assert str(fp) + "::MyClass::my_method" in concept_names
