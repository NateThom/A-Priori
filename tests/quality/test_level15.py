"""Tests for Story 7.4: Level 1.5 Co-Regulation Review.

AC traceability:

AC1: Given a librarian output that passed Level 1, when Level 1.5 runs, then a second
     LLM call is made with the review prompt containing the librarian's output, the
     original code, and the structural context.

AC2: Given a high-quality librarian output, when the co-regulation review evaluates it,
     then all scores are above thresholds and composite_pass = True.

AC3: Given a generic librarian output, when reviewed, then the specificity score is
     below threshold, composite_pass = False, and the feedback field contains actionable
     guidance.

AC4: Given a review failure, when the CoRegulationAssessment is inspected, then the
     feedback field provides guidance specific enough to improve a retry.

AC5: Given quality.co_regulation.enabled = false in config, when Level 1.5 is called,
     then it returns an automatic pass without making an LLM call.

AC6: Given a separate review model is configured, when Level 1.5 runs, then it uses
     the review model (i.e., the adapter passed to check_level15 is the one called).

DoD: Co-regulation review implemented with S-8 prompt. Correctly discriminates good and
     bad output. Feedback is actionable. Configurable enable/disable working. Separate
     review model support working.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from apriori.adapters.base import AnalysisResult, ModelInfo
from apriori.config import QualityCoRegulationConfig
from apriori.models.co_regulation_assessment import CoRegulationAssessment
from apriori.models.librarian_output import ConceptProposal, EdgeProposal, LibrarianOutput
from apriori.quality.level15 import check_level15


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_librarian_output(description: str = "Persists a Concept to SQLite using an UPSERT pattern.") -> LibrarianOutput:
    """High-quality librarian output for positive test cases."""
    return LibrarianOutput(
        concepts=[
            ConceptProposal(
                name="SQLiteStore.save_concept",
                description=description,
                confidence=0.92,
            )
        ],
        edges=[
            EdgeProposal(
                source_name="SQLiteStore.save_concept",
                target_name="sqlite3.Connection.execute",
                edge_type="depends-on",
                confidence=1.0,
                evidence_type="structural",
            )
        ],
    )


def _make_good_llm_response() -> AnalysisResult:
    """Mock LLM response for a high-quality librarian output."""
    payload = {
        "specificity": 0.9,
        "structural_corroboration": 0.85,
        "completeness": 0.80,
        "composite_pass": True,
        "feedback": "",
    }
    return AnalysisResult(
        content=json.dumps(payload),
        model_name="claude-sonnet-4-6",
        tokens_used=400,
        raw_response=None,
    )


def _make_generic_llm_response() -> AnalysisResult:
    """Mock LLM response for a generic/vague librarian output."""
    payload = {
        "specificity": 0.15,
        "structural_corroboration": 0.50,
        "completeness": 0.30,
        "composite_pass": False,
        "feedback": (
            "The description 'handles operations' is circular and applies to any class. "
            "Specify the exact operation, the UPSERT conflict strategy, JSON serialization "
            "of labels, and the StorageError wrapping of sqlite3.IntegrityError."
        ),
    }
    return AnalysisResult(
        content=json.dumps(payload),
        model_name="claude-sonnet-4-6",
        tokens_used=350,
        raw_response=None,
    )


def _make_mock_adapter(response: AnalysisResult) -> AsyncMock:
    """Create a mock LLM adapter that returns the given response."""
    adapter = AsyncMock()
    adapter.analyze.return_value = response
    adapter.get_model_info.return_value = ModelInfo(
        name="claude-sonnet-4-6",
        provider="anthropic",
        context_window=200_000,
        cost_per_token=0.000003,
    )
    return adapter


# ---------------------------------------------------------------------------
# AC1: LLM call made with prompt containing code, librarian output, structural context
# ---------------------------------------------------------------------------

class TestLLMCallMadeWithCorrectContent:
    """AC1: When Level 1.5 runs, a second LLM call is made with the review prompt
    containing the librarian's output, the original code, and the structural context."""

    async def test_llm_call_is_made_when_enabled(self):
        # Given: a librarian output, code snippet, structural context, and enabled config
        librarian_output = _make_librarian_output()
        code_snippet = "class SQLiteStore:\n    def save_concept(self, concept): ..."
        structural_context = "Implements KnowledgeStore protocol"
        adapter = _make_mock_adapter(_make_good_llm_response())

        # When: check_level15 is called
        await check_level15(librarian_output, code_snippet, structural_context, adapter)

        # Then: the adapter's analyze method was called exactly once
        adapter.analyze.assert_called_once()

    async def test_prompt_contains_original_code(self):
        # Given: a distinctive code snippet
        librarian_output = _make_librarian_output()
        code_snippet = "def save_concept_DISTINCTIVE_MARKER(self, concept): ..."
        structural_context = ""
        adapter = _make_mock_adapter(_make_good_llm_response())

        # When: check_level15 is called
        await check_level15(librarian_output, code_snippet, structural_context, adapter)

        # Then: the prompt sent to analyze contains the code snippet
        call_args = adapter.analyze.call_args
        prompt_arg = call_args[0][0] if call_args[0] else call_args[1].get("prompt", "")
        assert "save_concept_DISTINCTIVE_MARKER" in prompt_arg

    async def test_prompt_contains_librarian_output(self):
        # Given: a librarian output with a distinctive concept name
        librarian_output = LibrarianOutput(
            concepts=[
                ConceptProposal(
                    name="DISTINCTIVE_CONCEPT_NAME_XYZ",
                    description="Persists a Concept to SQLite using an UPSERT with ON CONFLICT resolution.",
                    confidence=0.9,
                )
            ]
        )
        adapter = _make_mock_adapter(_make_good_llm_response())

        # When: check_level15 is called
        await check_level15(librarian_output, "code here", "structural context", adapter)

        # Then: the prompt contains the librarian output content
        call_args = adapter.analyze.call_args
        prompt_arg = call_args[0][0] if call_args[0] else call_args[1].get("prompt", "")
        assert "DISTINCTIVE_CONCEPT_NAME_XYZ" in prompt_arg

    async def test_prompt_contains_structural_context(self):
        # Given: a distinctive structural context string
        librarian_output = _make_librarian_output()
        structural_context = "STRUCTURAL_CONTEXT_UNIQUE_MARKER: graph neighbors include ConceptMerger"
        adapter = _make_mock_adapter(_make_good_llm_response())

        # When: check_level15 is called
        await check_level15(librarian_output, "code", structural_context, adapter)

        # Then: the prompt includes the structural context
        call_args = adapter.analyze.call_args
        prompt_arg = call_args[0][0] if call_args[0] else call_args[1].get("prompt", "")
        assert "STRUCTURAL_CONTEXT_UNIQUE_MARKER" in prompt_arg


# ---------------------------------------------------------------------------
# AC2: High-quality output → all scores above thresholds → composite_pass = True
# ---------------------------------------------------------------------------

class TestHighQualityOutputPasses:
    """AC2: A high-quality librarian output results in composite_pass = True."""

    async def test_high_quality_output_passes(self):
        # Given: a high-quality librarian output and an LLM response with high scores
        librarian_output = _make_librarian_output()
        adapter = _make_mock_adapter(_make_good_llm_response())

        # When: check_level15 is called
        assessment, _ = await check_level15(
            librarian_output, "code snippet", "structural context", adapter
        )

        # Then: all scores are above thresholds and composite_pass is True
        assert assessment.specificity >= 0.5
        assert assessment.structural_corroboration >= 0.3
        assert assessment.completeness >= 0.4
        assert assessment.composite_pass is True

    async def test_returns_co_regulation_assessment_instance(self):
        # Given: a configured adapter
        adapter = _make_mock_adapter(_make_good_llm_response())

        # When: check_level15 is called
        assessment, _ = await check_level15(
            _make_librarian_output(), "code", "context", adapter
        )

        # Then: returns a CoRegulationAssessment
        assert isinstance(assessment, CoRegulationAssessment)

    async def test_returns_tokens_used_from_llm_call(self):
        # Given: an adapter whose response reports 400 tokens used
        adapter = _make_mock_adapter(_make_good_llm_response())  # tokens_used=400

        # When: check_level15 is called
        _, tokens_used = await check_level15(
            _make_librarian_output(), "code", "context", adapter
        )

        # Then: tokens_used matches what the adapter reported
        assert tokens_used == 400

    async def test_disabled_config_returns_zero_tokens(self):
        # Given: co-regulation disabled
        config = QualityCoRegulationConfig(enabled=False)
        adapter = _make_mock_adapter(_make_good_llm_response())

        # When: check_level15 is called with disabled config
        _, tokens_used = await check_level15(
            _make_librarian_output(), "code", "context", adapter, config=config
        )

        # Then: no tokens consumed (no LLM call made)
        assert tokens_used == 0


# ---------------------------------------------------------------------------
# AC3 + AC4: Generic output → specificity below threshold, feedback is actionable
# ---------------------------------------------------------------------------

class TestGenericOutputFails:
    """AC3: A generic/vague librarian output results in composite_pass = False with
    actionable feedback.

    AC4: The feedback field provides guidance specific enough to improve a retry.
    """

    async def test_generic_output_fails_with_low_specificity(self):
        # Given: a vague librarian output and an LLM response reflecting poor specificity
        generic_output = _make_librarian_output(
            description="A class that handles operations and manages data."
        )
        adapter = _make_mock_adapter(_make_generic_llm_response())

        # When: check_level15 is called
        assessment, _ = await check_level15(
            generic_output, "code snippet", "structural context", adapter
        )

        # Then: specificity is below threshold and composite_pass is False
        assert assessment.specificity < 0.5
        assert assessment.composite_pass is False

    async def test_failing_assessment_has_non_empty_feedback(self):
        # Given: a vague librarian output
        generic_output = _make_librarian_output(
            description="A class that handles operations and manages data."
        )
        adapter = _make_mock_adapter(_make_generic_llm_response())

        # When: check_level15 is called
        assessment, _ = await check_level15(
            generic_output, "code snippet", "structural context", adapter
        )

        # Then: feedback is non-empty and contains actionable guidance
        assert assessment.composite_pass is False
        assert len(assessment.feedback.strip()) > 0

    async def test_feedback_names_specific_improvement(self):
        # Given: an LLM response with specific improvement guidance
        generic_output = _make_librarian_output(description="Handles stuff.")
        adapter = _make_mock_adapter(_make_generic_llm_response())

        # When: check_level15 is called
        assessment, _ = await check_level15(
            generic_output, "code snippet", "structural context", adapter
        )

        # Then: feedback contains specifics (mentions circular description)
        assert "circular" in assessment.feedback or "specific" in assessment.feedback or "vague" in assessment.feedback.lower() or "UPSERT" in assessment.feedback


# ---------------------------------------------------------------------------
# AC5: enabled=False → auto-pass without LLM call
# ---------------------------------------------------------------------------

class TestDisabledConfigAutoPass:
    """AC5: Given quality.co_regulation.enabled = false, check_level15 returns an
    automatic pass without making an LLM call."""

    async def test_disabled_config_returns_auto_pass(self):
        # Given: config with co_regulation.enabled = False
        config = QualityCoRegulationConfig(enabled=False)
        adapter = _make_mock_adapter(_make_good_llm_response())
        librarian_output = _make_librarian_output()

        # When: check_level15 is called with disabled config
        assessment, _ = await check_level15(
            librarian_output, "code", "context", adapter, config=config
        )

        # Then: returns an automatic pass
        assert assessment.composite_pass is True

    async def test_disabled_config_makes_no_llm_call(self):
        # Given: config with co_regulation.enabled = False
        config = QualityCoRegulationConfig(enabled=False)
        adapter = _make_mock_adapter(_make_good_llm_response())
        librarian_output = _make_librarian_output()

        # When: check_level15 is called with disabled config
        await check_level15(
            librarian_output, "code", "context", adapter, config=config
        )

        # Then: the adapter was NOT called
        adapter.analyze.assert_not_called()

    async def test_enabled_config_default_makes_llm_call(self):
        # Given: default config (enabled=True)
        config = QualityCoRegulationConfig(enabled=True)
        adapter = _make_mock_adapter(_make_good_llm_response())

        # When: check_level15 is called without disabled config
        await check_level15(
            _make_librarian_output(), "code", "context", adapter, config=config
        )

        # Then: the adapter WAS called
        adapter.analyze.assert_called_once()


# ---------------------------------------------------------------------------
# AC6: Separate review model — the adapter passed is the one called
# ---------------------------------------------------------------------------

class TestSeparateReviewModelUsed:
    """AC6: When a separate review adapter is passed, it is used (not any other adapter)."""

    async def test_provided_adapter_is_called(self):
        # Given: two adapters — a primary (not passed) and a review adapter
        primary_adapter = _make_mock_adapter(_make_good_llm_response())
        review_adapter = _make_mock_adapter(_make_good_llm_response())

        # When: check_level15 is called with the review adapter
        await check_level15(
            _make_librarian_output(), "code", "context", review_adapter
        )

        # Then: the review adapter was used
        review_adapter.analyze.assert_called_once()
        # The primary adapter was not called
        primary_adapter.analyze.assert_not_called()


# ---------------------------------------------------------------------------
# Robustness: malformed JSON response → conservative failure
# ---------------------------------------------------------------------------

class TestMalformedResponseConservativeFailure:
    """If the LLM returns invalid JSON, check_level15 returns a failing assessment
    (conservative approach per S-8 implementation notes)."""

    async def test_malformed_json_returns_failing_assessment(self):
        # Given: an LLM response that is not valid JSON
        bad_response = AnalysisResult(
            content="I cannot evaluate this. The code is incomplete.",
            model_name="claude-sonnet-4-6",
            tokens_used=50,
            raw_response=None,
        )
        adapter = _make_mock_adapter(bad_response)

        # When: check_level15 is called
        assessment, _ = await check_level15(
            _make_librarian_output(), "code", "context", adapter
        )

        # Then: returns a failing assessment (conservative)
        assert assessment.composite_pass is False

    async def test_malformed_response_feedback_explains_parse_failure(self):
        # Given: a non-JSON response
        bad_response = AnalysisResult(
            content="The librarian output looks reasonable to me.",
            model_name="claude-sonnet-4-6",
            tokens_used=50,
            raw_response=None,
        )
        adapter = _make_mock_adapter(bad_response)

        # When: check_level15 is called
        assessment, _ = await check_level15(
            _make_librarian_output(), "code", "context", adapter
        )

        # Then: feedback indicates parsing failure
        assert "parse" in assessment.feedback.lower() or "json" in assessment.feedback.lower() or "invalid" in assessment.feedback.lower()
