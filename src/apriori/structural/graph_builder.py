"""Graph Builder — converts ParseResult objects into concept nodes and structural edges.

Implements ERD §3.3.2. Takes parse results from the structural layer (Layer 0)
and writes concept nodes and structural edges through the KnowledgeStore
(arch:no-raw-sql). All operations are synchronous (arch:sync-first).

Upsert key: fully-qualified symbol name (FQN) = ``file_path::symbol_name`` for
top-level entities, ``file_path::class_name::method_name`` for methods. Running
the builder twice on the same input is idempotent — existing concepts are updated
in place; existing edges are skipped.
"""

from __future__ import annotations

import hashlib
import uuid
from pathlib import Path
from typing import Optional

from pydantic import BaseModel

from apriori.models.concept import Concept, CodeReference
from apriori.models.edge import Edge
from apriori.storage.protocol import KnowledgeStore
from apriori.structural.fqn import module_fqn, symbol_fqn
from apriori.structural.models import FunctionEntity, ParseResult


def _content_hash(source: bytes, start_line: int, end_line: int) -> str:
    """Return the SHA-256 hex digest of the entity's source lines (1-indexed, inclusive)."""
    lines = source.split(b"\n")
    entity_bytes = b"\n".join(lines[start_line - 1 : end_line])
    return hashlib.sha256(entity_bytes).hexdigest()


def _function_metadata(func: FunctionEntity) -> dict:
    """Serialise FunctionEntity signature fields to a metadata dict."""
    return {
        "params": [
            {"name": p.name, "type_annotation": p.type_annotation}
            for p in func.params
        ],
        "return_type": func.return_type,
        "is_exported": func.is_exported,
        "is_async": func.is_async,
    }


# ---------------------------------------------------------------------------
# Result model
# ---------------------------------------------------------------------------


class GraphBuildResult(BaseModel):
    """Statistics returned after a :meth:`GraphBuilder.build` call."""

    concepts_created: int = 0
    concepts_updated: int = 0
    edges_created: int = 0
    edges_skipped: int = 0


# ---------------------------------------------------------------------------
# GraphBuilder
# ---------------------------------------------------------------------------


class GraphBuilder:
    """Converts a list of :class:`ParseResult` objects into graph nodes and edges.

    Writes through :class:`~apriori.storage.protocol.KnowledgeStore`
    (arch:no-raw-sql).  All operations are synchronous (arch:sync-first).

    Args:
        store: The KnowledgeStore to write into.
        git_head: The 40-char hex git commit hash to stamp on all created/updated
            concepts and edges.  Pass ``None`` when git HEAD is unavailable.
    """

    def __init__(
        self,
        store: KnowledgeStore,
        git_head: Optional[str] = None,
    ) -> None:
        self._store = store
        self._git_head = git_head

    # -----------------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------------

    def build(self, results: list[ParseResult]) -> GraphBuildResult:
        """Process *results* and write concepts and edges to the store.

        Args:
            results: ParseResult objects from the structural parsing layer.

        Returns:
            :class:`GraphBuildResult` with counts of created/updated
            concepts and created/skipped edges.
        """
        stats = GraphBuildResult()

        # Load all existing concepts keyed by FQN name for O(1) upsert lookup.
        existing: dict[str, Concept] = {c.name: c for c in self._store.list_concepts()}

        # Phase 1: upsert concept nodes from all parse results.
        for result in results:
            self._process_concepts(result, existing, stats)

        # Phase 2: create structural edges.
        # Snapshot existing edge keys to avoid duplicates without re-querying.
        existing_edge_keys: set[tuple[uuid.UUID, uuid.UUID, str]] = {
            (e.source_id, e.target_id, e.edge_type)
            for e in self._store.list_edges()
        }

        # Simple-name index for resolving base classes that lack a file path.
        simple_to_fqns: dict[str, list[str]] = {}
        for fqn in existing:
            simple = fqn.rsplit("::", 1)[-1]
            simple_to_fqns.setdefault(simple, []).append(fqn)

        for result in results:
            self._process_edges(result, existing, simple_to_fqns, existing_edge_keys, stats)

        return stats

    # -----------------------------------------------------------------------
    # Phase 1: concept nodes
    # -----------------------------------------------------------------------

    def _process_concepts(
        self,
        result: ParseResult,
        existing: dict[str, Concept],
        stats: GraphBuildResult,
    ) -> None:
        module_name = module_fqn(result.file_path)
        module_end_line = max(1, len(result.source.splitlines()))
        module_metadata = {"language": result.language}
        module_concept, module_created = self._upsert_concept(
            module_name,
            result,
            1,
            module_end_line,
            "module",
            module_metadata,
            existing,
        )
        existing[module_name] = module_concept
        if module_created:
            stats.concepts_created += 1
        else:
            stats.concepts_updated += 1

        for func in result.functions:
            fqn = symbol_fqn(result.file_path, func.name)
            concept, created = self._upsert_concept(
                fqn, result, func.start_line, func.end_line, "function",
                _function_metadata(func), existing,
            )
            existing[fqn] = concept
            if created:
                stats.concepts_created += 1
            else:
                stats.concepts_updated += 1

        for cls in result.classes:
            fqn = symbol_fqn(result.file_path, cls.name)
            metadata = {"bases": cls.bases, "is_exported": cls.is_exported}
            concept, created = self._upsert_concept(
                fqn, result, cls.start_line, cls.end_line, "class", metadata, existing,
            )
            existing[fqn] = concept
            if created:
                stats.concepts_created += 1
            else:
                stats.concepts_updated += 1

            # Methods nested in the class become their own concept nodes.
            for method in cls.methods:
                method_fqn = symbol_fqn(result.file_path, cls.name, method.name)
                m_concept, m_created = self._upsert_concept(
                    method_fqn, result, method.start_line, method.end_line, "method",
                    _function_metadata(method), existing,
                )
                existing[method_fqn] = m_concept
                if m_created:
                    stats.concepts_created += 1
                else:
                    stats.concepts_updated += 1

        for iface in result.interfaces:
            fqn = symbol_fqn(result.file_path, iface.name)
            metadata = {"is_exported": iface.is_exported}
            concept, created = self._upsert_concept(
                fqn, result, iface.start_line, iface.end_line, "interface", metadata, existing,
            )
            existing[fqn] = concept
            if created:
                stats.concepts_created += 1
            else:
                stats.concepts_updated += 1

    def _upsert_concept(
        self,
        fqn: str,
        result: ParseResult,
        start_line: int,
        end_line: int,
        entity_type: str,
        metadata: dict,
        existing: dict[str, Concept],
    ) -> tuple[Concept, bool]:
        """Upsert a concept by FQN name.

        Returns:
            ``(concept, was_created)`` — ``was_created`` is ``True`` when the
            concept was newly inserted, ``False`` when it was updated in place.
        """
        simple_name = fqn.rsplit("::", 1)[-1]
        content_hash_val = _content_hash(result.source, start_line, end_line)
        semantic_anchor = (
            f"{result.language} {entity_type} '{simple_name}' "
            f"at {result.file_path}:{start_line}-{end_line}"
        )
        code_ref = CodeReference(
            symbol=fqn,
            file_path=str(result.file_path),
            line_range=(start_line, end_line),
            content_hash=content_hash_val,
            semantic_anchor=semantic_anchor,
            derived_from_code_version=self._git_head,
        )

        if fqn in existing:
            updated = existing[fqn].model_copy(
                update={
                    "code_references": [code_ref],
                    "metadata": metadata,
                    "derived_from_code_version": self._git_head,
                    "confidence": 1.0,
                }
            )
            self._store.update_concept(updated)
            return updated, False

        description = (
            f"{result.language} {entity_type} '{simple_name}' in {result.file_path}"
        )
        concept = Concept(
            name=fqn,
            description=description,
            created_by="agent",
            confidence=1.0,
            code_references=[code_ref],
            derived_from_code_version=self._git_head,
            metadata=metadata,
        )
        self._store.create_concept(concept)
        return concept, True

    # -----------------------------------------------------------------------
    # Phase 2: structural edges
    # -----------------------------------------------------------------------

    def _process_edges(
        self,
        result: ParseResult,
        existing: dict[str, Concept],
        simple_to_fqns: dict[str, list[str]],
        existing_edge_keys: set[tuple[uuid.UUID, uuid.UUID, str]],
        stats: GraphBuildResult,
    ) -> None:
        module_concept = existing.get(module_fqn(result.file_path))
        if module_concept is not None:
            self._remove_existing_import_edges_for_module(
                module_concept.id, existing_edge_keys
            )

        # Edges from ParseResult.relationships (Python parser and others).
        for rel in result.relationships:
            if rel.kind == "imports":
                if module_concept is None:
                    stats.edges_skipped += 1
                    continue
                target_concept = self._resolve_import_target(
                    rel.target, rel.file_path, existing, simple_to_fqns
                )
                if target_concept is None:
                    stats.edges_skipped += 1
                    continue

                key = (module_concept.id, target_concept.id, "imports")
                if key in existing_edge_keys:
                    stats.edges_skipped += 1
                    continue

                self._emit_edge(
                    module_concept.id, target_concept.id, "imports",
                    existing_edge_keys,
                )
                stats.edges_created += 1
                continue

            if rel.kind not in ("calls", "inherits"):
                continue
            if not rel.source:
                # Calls with no known source (attribute-call form) are not useful.
                stats.edges_skipped += 1
                continue

            source_fqn = symbol_fqn(rel.file_path, rel.source)
            target_fqn = symbol_fqn(rel.file_path, rel.target)

            source_concept = existing.get(source_fqn)
            target_concept = existing.get(target_fqn)

            if source_concept is None or target_concept is None:
                stats.edges_skipped += 1
                continue

            key = (source_concept.id, target_concept.id, rel.kind)
            if key in existing_edge_keys:
                stats.edges_skipped += 1
                continue

            self._emit_edge(
                source_concept.id, target_concept.id, rel.kind,
                existing_edge_keys,
            )
            stats.edges_created += 1

        # Edges from ParseResult.imports (TypeScript parser).
        if module_concept is not None:
            for imp in result.imports:
                targets = imp.names if imp.names else [imp.source_module]
                for target_name in targets:
                    target_concept = self._resolve_import_target(
                        target_name, result.file_path, existing, simple_to_fqns
                    )
                    if target_concept is None:
                        stats.edges_skipped += 1
                        continue

                    key = (module_concept.id, target_concept.id, "imports")
                    if key in existing_edge_keys:
                        stats.edges_skipped += 1
                        continue

                    self._emit_edge(
                        module_concept.id, target_concept.id, "imports",
                        existing_edge_keys,
                    )
                    stats.edges_created += 1

        # ClassEntity.bases — handles TypeScript inheritance (no Relationship objects).
        # Python parser also sets bases but also emits Relationship(kind="inherits"),
        # so the existing_edge_keys guard prevents double-creation.
        for cls in result.classes:
            class_fqn = symbol_fqn(result.file_path, cls.name)
            class_concept = existing.get(class_fqn)
            if class_concept is None:
                continue

            for base in cls.bases:
                base_concept = self._resolve_base(
                    base, result.file_path, existing, simple_to_fqns
                )
                if base_concept is None:
                    stats.edges_skipped += 1
                    continue

                key = (class_concept.id, base_concept.id, "inherits")
                if key in existing_edge_keys:
                    stats.edges_skipped += 1
                    continue

                self._emit_edge(
                    class_concept.id, base_concept.id, "inherits",
                    existing_edge_keys,
                )
                stats.edges_created += 1

    def _resolve_base(
        self,
        base_name: str,
        file_path: Path,
        existing: dict[str, Concept],
        simple_to_fqns: dict[str, list[str]],
    ) -> Optional[Concept]:
        """Resolve a base class name to a Concept, trying local FQN then simple name."""
        local_fqn = symbol_fqn(file_path, base_name)
        if local_fqn in existing:
            return existing[local_fqn]
        # If the base is defined in a different file, fall back to simple name.
        fqns = simple_to_fqns.get(base_name, [])
        if len(fqns) == 1:
            return existing.get(fqns[0])
        return None

    def _resolve_import_target(
        self,
        target_name: str,
        file_path: Path,
        existing: dict[str, Concept],
        simple_to_fqns: dict[str, list[str]],
    ) -> Optional[Concept]:
        """Resolve an import target to a Concept.

        Order:
        1. Local symbol FQN in the same file
        2. Exact concept name match (supports external/module placeholders)
        3. Unique simple-name match in the graph
        """
        local_fqn = symbol_fqn(file_path, target_name)
        if local_fqn in existing:
            return existing[local_fqn]

        direct = existing.get(target_name)
        if direct is not None:
            return direct

        fqns = simple_to_fqns.get(target_name, [])
        if len(fqns) == 1:
            return existing.get(fqns[0])

        return None

    def _remove_existing_import_edges_for_module(
        self,
        module_concept_id: uuid.UUID,
        existing_edge_keys: set[tuple[uuid.UUID, uuid.UUID, str]],
    ) -> None:
        """Remove all current imports edges sourced from the module concept."""
        existing_imports = self._store.list_edges(
            source_id=module_concept_id, edge_type="imports"
        )
        for edge in existing_imports:
            self._store.delete_edge(edge.id)
            existing_edge_keys.discard((edge.source_id, edge.target_id, edge.edge_type))

    def _emit_edge(
        self,
        source_id: uuid.UUID,
        target_id: uuid.UUID,
        edge_type: str,
        existing_edge_keys: set[tuple[uuid.UUID, uuid.UUID, str]],
    ) -> None:
        edge = Edge(
            source_id=source_id,
            target_id=target_id,
            edge_type=edge_type,
            evidence_type="structural",
            confidence=1.0,
            derived_from_code_version=self._git_head,
        )
        self._store.create_edge(edge)
        existing_edge_keys.add((source_id, target_id, edge_type))
