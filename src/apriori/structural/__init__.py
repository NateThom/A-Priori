"""Structural parsing layer — Layer 0 (ERD §3.3).

Provides the file-tree walking Orchestrator and language-agnostic ParseResult
model. Language-specific parsers (Python, TypeScript) live in
``apriori.structural.languages``.
"""

from apriori.structural.languages.typescript import TypeScriptParser
from apriori.structural.models import (
    ClassEntity,
    FunctionEntity,
    FunctionParam,
    ImportRelationship,
    InterfaceEntity,
    ParseResult,
    ReExport,
    Relationship,
)
from apriori.structural.orchestrator import Orchestrator, OrchestratorConfig, detect_language
from apriori.structural.protocol import LanguageParser

__all__ = [
    "Orchestrator",
    "OrchestratorConfig",
    "ParseResult",
    "FunctionEntity",
    "FunctionParam",
    "ClassEntity",
    "InterfaceEntity",
    "ImportRelationship",
    "ReExport",
    "Relationship",
    "LanguageParser",
    "TypeScriptParser",
    "detect_language",
]
