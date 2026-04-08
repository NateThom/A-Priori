"""Structural parsing layer — Layer 0 (ERD §3.3).

Provides the file-tree walking Orchestrator and language-agnostic ParseResult
model. Language-specific parsers (Python, TypeScript) live in
``apriori.structural.languages``.
"""

from apriori.structural.models import ParseResult
from apriori.structural.orchestrator import Orchestrator, OrchestratorConfig, detect_language
from apriori.structural.protocol import LanguageParser

__all__ = [
    "Orchestrator",
    "OrchestratorConfig",
    "ParseResult",
    "LanguageParser",
    "detect_language",
]
