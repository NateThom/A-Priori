"""Provider-specific librarian prompt templates and response parsing (Story 10.2)."""

from __future__ import annotations

import json
from typing import Any

from pydantic import ValidationError

from apriori.models.librarian_output import LibrarianOutput
from apriori.models.work_item import WorkItem

_BASE_PROMPT_TEMPLATE = """\
Analyze the following code and produce a structured concept analysis.

Work item type: {item_type}
File: {file_path}

## Source code
```python
{code_content}
```

## Structural context
{structural_context}

## Instructions
- Identify key concepts with concrete behavioral details specific to this code.
- Include meaningful labels for each concept (for example: needs-review, stale, verified).
- Identify relationships between concepts.
- Use this exact JSON schema shape with keys: "concepts" and "relationships".
{failure_context}
## Output schema (JSON only)
{{
  "concepts": [
    {{
      "name": "ExactConceptName",
      "description": "Specific implementation details, constraints, and semantics.",
      "confidence": 0.9,
      "labels": ["needs-review"],
      "code_references": []
    }}
  ],
  "relationships": [
    {{
      "source_name": "ConceptA",
      "target_name": "ConceptB",
      "edge_type": "depends-on",
      "confidence": 0.8,
      "evidence_type": "semantic"
    }}
  ]
}}
"""

_ANTHROPIC_SUFFIX = """\
Return valid JSON only with no prose before or after the object.
"""

_OLLAMA_SUFFIX = """\
Formatting requirements for local models:
- Do not include markdown.
- Do not include code fences.
- The first non-whitespace character must be '{'.
- The final non-whitespace character must be '}'.
- Return exactly one JSON object and nothing else.
"""

_FAILURE_CONTEXT_TEMPLATE = """\

## Previous analysis failures (retry context)
Address each failure directly in this attempt:
{failures}
"""


def build_librarian_prompt(
    *,
    work_item: WorkItem,
    code_content: str,
    structural_context: str,
    provider: str,
    with_failure_context: bool = False,
) -> str:
    """Build a provider-specific prompt for librarian analysis."""
    failure_context = ""
    if with_failure_context and work_item.failure_records:
        lines: list[str] = []
        for idx, fr in enumerate(work_item.failure_records, start=1):
            line = f"- Attempt {idx}: {fr.failure_reason}"
            if fr.reviewer_feedback:
                line += f" | Co-regulation feedback: {fr.reviewer_feedback}"
            lines.append(line)
        failure_context = _FAILURE_CONTEXT_TEMPLATE.format(failures="\n".join(lines))

    prompt = _BASE_PROMPT_TEMPLATE.format(
        item_type=work_item.item_type,
        file_path=work_item.file_path or "(no file)",
        code_content=code_content or "(no code available)",
        structural_context=structural_context or "(no neighboring concepts)",
        failure_context=failure_context,
    )

    if provider.lower() == "ollama":
        return f"{prompt}\n{_OLLAMA_SUFFIX}"
    return f"{prompt}\n{_ANTHROPIC_SUFFIX}"


def parse_librarian_response(content: str) -> dict[str, Any]:
    """Parse an LLM response into canonical output or extracted text fallback.

    Behavior:
    - Parses raw JSON and JSON wrapped in markdown fences.
    - Normalizes ``relationships`` to canonical ``edges``.
    - Validates canonical JSON through ``LibrarianOutput`` when possible.
    - On parse failure, degrades gracefully to text extraction.
    """
    raw = content.strip()
    json_candidate = _extract_json_candidate(raw)

    parsed_obj: Any = None
    if json_candidate is not None:
        parsed_obj = _loads_json_or_none(json_candidate)
    if parsed_obj is None and raw:
        parsed_obj = _loads_json_or_none(raw)

    if not isinstance(parsed_obj, dict):
        return {"extracted_text": raw}

    normalized = _normalize_output_dict(parsed_obj)

    try:
        validated = LibrarianOutput.model_validate(normalized)
        return validated.model_dump()
    except ValidationError:
        return normalized


def _extract_json_candidate(text: str) -> str | None:
    """Extract the likely JSON payload from markdown fences or inline text."""
    stripped = text.strip()
    if not stripped:
        return None

    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if len(lines) <= 1:
            return None
        if lines[-1].strip().startswith("```"):
            return "\n".join(lines[1:-1]).strip()
        return "\n".join(lines[1:]).strip()

    start = stripped.find("{")
    end = stripped.rfind("}")
    if start != -1 and end != -1 and end > start:
        return stripped[start : end + 1]
    return None


def _loads_json_or_none(candidate: str) -> Any | None:
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        return None


def _normalize_output_dict(data: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(data)

    relationships = normalized.get("relationships")
    if "edges" not in normalized and isinstance(relationships, list):
        normalized["edges"] = relationships
    if "edges" not in normalized:
        normalized["edges"] = []

    return normalized
