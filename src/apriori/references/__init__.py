"""References module — code reference repair chain (PRD §5.2).

Exports the public resolution API:
- ``resolve_code_reference``: single code reference via three-step repair chain
- ``resolve_concept_references``: all code references on a concept, with store updates
- ``ResolutionMethod``: enum of resolution outcomes (for telemetry)
- ``ResolutionResult``: structured result returned by the resolver
"""

from apriori.references.resolver import (
    ResolutionMethod,
    ResolutionResult,
    resolve_code_reference,
    resolve_concept_references,
)

__all__ = [
    "ResolutionMethod",
    "ResolutionResult",
    "resolve_code_reference",
    "resolve_concept_references",
]
