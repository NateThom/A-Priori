"""Tests for Story 10.2: Prompt Template System.

AC traceability:
AC-1: investigate_file prompt includes source code, structural context, and JSON instructions.
AC-2: with_failure_context mode includes failure history with reason + co-regulation feedback.
AC-3: Anthropic template requests structured JSON with concepts, relationships, and labels.
AC-4: Ollama template keeps same schema and adds stricter JSON formatting instructions.
AC-5: Response parser extracts JSON from raw JSON and markdown JSON fences.
AC-6: Invalid JSON degrades gracefully to text extraction.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from apriori.models.work_item import FailureRecord, WorkItem


def _make_work_item(
    *,
    failures: list[FailureRecord] | None = None,
) -> WorkItem:
    return WorkItem(
        item_type="investigate_file",
        concept_id=uuid.uuid4(),
        description="Investigate file behavior",
        file_path="src/apriori/librarian/loop.py",
        failure_records=failures or [],
        failure_count=len(failures or []),
    )


class TestPromptTemplates:
    """AC-1..AC-4 for provider-specific prompt construction."""

    def test_investigate_file_prompt_includes_code_context_and_json_schema(self):
        """AC-1: Prompt includes source code, structural context, and JSON output instruction."""
        from apriori.librarian.prompt_templates import build_librarian_prompt

        work_item = _make_work_item()
        code_content = "def analyze_file(path: str) -> dict:\n    return {}"
        structural_context = "Graph neighbors of FileAnalyzer: PromptTemplateBuilder, ResponseParser"

        prompt = build_librarian_prompt(
            work_item=work_item,
            code_content=code_content,
            structural_context=structural_context,
            provider="anthropic",
            with_failure_context=False,
        )

        assert "Analyze the following code" in prompt
        assert code_content in prompt
        assert structural_context in prompt
        assert "valid JSON" in prompt

    def test_failure_context_mode_includes_reason_and_feedback_per_attempt(self):
        """AC-2: Failure history includes each attempt's reason and reviewer feedback."""
        from apriori.librarian.prompt_templates import build_librarian_prompt

        failures = [
            FailureRecord(
                attempted_at=datetime.now(timezone.utc),
                model_used="claude-3-5-sonnet",
                prompt_template="investigate_file_anthropic_v1",
                failure_reason="Level 1: generic description",
                reviewer_feedback="Include exact parameter constraints.",
            ),
            FailureRecord(
                attempted_at=datetime.now(timezone.utc),
                model_used="claude-3-5-sonnet",
                prompt_template="investigate_file_anthropic_v1",
                failure_reason="Level 1.5: co-regulation failed",
                reviewer_feedback="Call out UPSERT semantics and error wrapping.",
            ),
        ]
        work_item = _make_work_item(failures=failures)

        prompt = build_librarian_prompt(
            work_item=work_item,
            code_content="def f():\n    pass",
            structural_context="Graph neighbors of X: Y, Z",
            provider="anthropic",
            with_failure_context=True,
        )

        assert "Attempt 1" in prompt
        assert "Level 1: generic description" in prompt
        assert "Include exact parameter constraints." in prompt
        assert "Attempt 2" in prompt
        assert "Level 1.5: co-regulation failed" in prompt
        assert "UPSERT semantics" in prompt

    def test_anthropic_template_requests_concepts_relationships_and_labels(self):
        """AC-3: Anthropic prompt asks for structured JSON schema fields."""
        from apriori.librarian.prompt_templates import build_librarian_prompt

        prompt = build_librarian_prompt(
            work_item=_make_work_item(),
            code_content="def g():\n    pass",
            structural_context="Graph neighbors of G: H",
            provider="anthropic",
            with_failure_context=False,
        )

        assert '"concepts"' in prompt
        assert '"relationships"' in prompt
        assert '"labels"' in prompt

    def test_ollama_template_uses_same_schema_with_stricter_json_formatting(self):
        """AC-4: Ollama prompt retains schema and adds explicit JSON-only formatting."""
        from apriori.librarian.prompt_templates import build_librarian_prompt

        prompt = build_librarian_prompt(
            work_item=_make_work_item(),
            code_content="def g():\n    pass",
            structural_context="Graph neighbors of G: H",
            provider="ollama",
            with_failure_context=False,
        )

        assert '"concepts"' in prompt
        assert '"relationships"' in prompt
        assert '"labels"' in prompt
        assert "Do not include markdown" in prompt
        assert "first non-whitespace character must be '{'" in prompt


class TestResponseParser:
    """AC-5..AC-6 for response parsing behavior."""

    def test_parser_extracts_json_from_plain_json_response(self):
        """AC-5: Plain JSON is parsed and normalized to canonical schema."""
        from apriori.librarian.prompt_templates import parse_librarian_response

        raw = """{
          "concepts": [
            {
              "name": "FileAnalyzer",
              "description": "Analyzes repository files and extracts structural patterns with explicit behavior details for queueing and processing.",
              "confidence": 0.91,
              "labels": ["needs-review"],
              "code_references": []
            }
          ],
          "relationships": []
        }"""

        parsed = parse_librarian_response(raw)

        assert "concepts" in parsed
        assert "edges" in parsed
        assert len(parsed["concepts"]) == 1
        assert parsed["concepts"][0]["name"] == "FileAnalyzer"

    def test_parser_extracts_json_from_markdown_fenced_response(self):
        """AC-5: JSON within markdown fences is extracted and parsed."""
        from apriori.librarian.prompt_templates import parse_librarian_response

        raw = """```json
        {
          "concepts": [
            {
              "name": "PromptTemplateBuilder",
              "description": "Builds provider-specific prompt strings with structural and retry context to improve output quality.",
              "confidence": 0.88,
              "labels": ["verified"],
              "code_references": []
            }
          ],
          "relationships": []
        }
        ```"""

        parsed = parse_librarian_response(raw)
        assert parsed["concepts"][0]["name"] == "PromptTemplateBuilder"
        assert parsed["edges"] == []

    def test_parser_degrades_to_text_extraction_for_invalid_json(self):
        """AC-6: Invalid JSON returns extracted text payload instead of raising."""
        from apriori.librarian.prompt_templates import parse_librarian_response

        raw = "The module probably handles retries and stores failures, but output is not JSON."
        parsed = parse_librarian_response(raw)

        assert "extracted_text" in parsed
        assert "handles retries" in parsed["extracted_text"]
        assert "concepts" not in parsed
