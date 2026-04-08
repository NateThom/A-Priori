"""Level 1.5 Co-Regulation Review (ERD §4.4.2).

Uses the adversarial-framing + rubric-anchor prompt selected in spike S-8 to
evaluate the librarian's output before it enters the knowledge graph.

A second LLM call is made with the S-8 winning prompt.  The response is parsed
into a :class:`CoRegulationAssessment`.  If parsing fails the result is a
conservative failure (no hallucinated data enters the graph).

When ``config.enabled`` is False the review is skipped and an automatic pass
is returned — no LLM call is made.

Usage::

    from apriori.quality.level15 import check_level15

    assessment = await check_level15(
        librarian_output=level1_result.adjusted_output,
        code_snippet=original_source,
        structural_context=graph_neighbourhood,
        adapter=llm_adapter,
    )
    if not assessment.composite_pass:
        # retry logic uses assessment.feedback
        ...
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from apriori.adapters.base import LLMAdapter
from apriori.config import QualityCoRegulationConfig
from apriori.models.co_regulation_assessment import CoRegulationAssessment
from apriori.models.librarian_output import LibrarianOutput

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# S-8 winning prompt: Prompt B+ (Adversarial with rubric anchors)
# ---------------------------------------------------------------------------

_REVIEW_PROMPT_TEMPLATE = """\
You are a critical code reviewer. Your job is to find weaknesses in a librarian agent's\
 analysis — NOT to confirm its quality. Assume the librarian may have:
- Hallucinated relationships, imports, or algorithms not present in the code
- Used the wrong relationship type (e.g., "inherits" for a composition, "calls" for an import)
- Written a vague description that could match any similar module
- Missed key behaviors: error paths, return value semantics, parameter constraints

Evaluate three dimensions. The burden of proof is on the librarian. If a claim is\
 unverifiable from the provided code, score the relevant dimension below its threshold.

**specificity (threshold: 0.5):** Could this description apply to any similar class/function,\
 or does it describe THIS specific code? Penalize generic language. Require specific parameter\
 behaviors, error conditions, return value semantics.
  - 0.0: Generic/circular  |  0.5: Key operation identified with moderate detail
  - 1.0: Exact semantics with specific parameters, error conditions, return values

**structural_corroboration (threshold: 0.3):** Is every stated relationship and dependency\
 directly visible in the provided code? Penalize hallucinated dependencies, wrong relationship\
 types (composition labeled as "inherits"), or "structural" evidence that doesn't appear in\
 the code.
  - 0.0: Relationships contradict the code  |  0.5: Mostly correct, minor imprecision
  - 1.0: All relationships correctly typed with explicit structural evidence

**completeness (threshold: 0.4):** Does the analysis cover all significant behaviors?\
 Penalize: missing error handling that is clearly present, omitted callees, ignoring key\
 return value semantics.
  - 0.0: <25% of significant behaviors  |  0.5: ~70% coverage, some gaps
  - 1.0: All significant behaviors, error paths, and outputs captured

composite_pass = (specificity >= 0.5) AND (structural_corroboration >= 0.3) AND (completeness >= 0.4)

On failure, the feedback field MUST be specific and actionable. Not: "The description is\
 vague." Instead: "The description does not mention the UPSERT pattern, the JSON\
 serialization of labels and code_references, or the immediate commit after each save.\
 The StorageError wrapping of sqlite3.IntegrityError is also absent."

Respond with JSON only. No preamble:
{{
  "specificity": <0.0-1.0>,
  "structural_corroboration": <0.0-1.0>,
  "completeness": <0.0-1.0>,
  "composite_pass": <true/false>,
  "feedback": "<specific actionable improvement instructions, or empty string>"
}}

Original code:
```
{code}
```

Librarian output:
```
{librarian_output}
```"""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _build_prompt(
    librarian_output: LibrarianOutput,
    code_snippet: str,
    structural_context: str,
) -> str:
    """Format the S-8 review prompt.

    Structural context is embedded in the librarian_output section per S-8
    implementation notes: "include in {librarian_output} as additional context."
    """
    librarian_section = librarian_output.model_dump_json(indent=2)
    if structural_context:
        librarian_section = f"{librarian_section}\n\nStructural context:\n{structural_context}"

    return _REVIEW_PROMPT_TEMPLATE.format(
        code=code_snippet,
        librarian_output=librarian_section,
    )


def _parse_response(content: str) -> CoRegulationAssessment:
    """Parse the LLM's JSON response into a CoRegulationAssessment.

    On parse failure returns a conservative failing assessment (no data enters
    the graph) with feedback explaining the failure.
    """
    try:
        data = json.loads(content)
        return CoRegulationAssessment(
            specificity=float(data["specificity"]),
            structural_corroboration=float(data["structural_corroboration"]),
            completeness=float(data["completeness"]),
            feedback=str(data.get("feedback", "")),
        )
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        logger.warning("Level 1.5: failed to parse LLM response: %s", exc)
        return CoRegulationAssessment(
            specificity=0.0,
            structural_corroboration=0.0,
            completeness=0.0,
            feedback=f"Level 1.5: failed to parse review response (json/invalid): {exc}",
        )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

_AUTO_PASS = CoRegulationAssessment(
    specificity=1.0,
    structural_corroboration=1.0,
    completeness=1.0,
    feedback="",
)


async def check_level15(
    librarian_output: LibrarianOutput,
    code_snippet: str,
    structural_context: str,
    adapter: LLMAdapter,
    config: Optional[QualityCoRegulationConfig] = None,
) -> CoRegulationAssessment:
    """Run the Level 1.5 co-regulation review.

    Makes a second LLM call using the adversarial-framing prompt from S-8.
    Returns a :class:`CoRegulationAssessment` with scores and optional feedback.

    When ``config.enabled`` is False, skips the LLM call and returns an
    automatic pass (:attr:`CoRegulationAssessment.composite_pass` = True).

    Args:
        librarian_output: The Level 1-approved LibrarianOutput to review.
        code_snippet: The original source code the librarian analysed.
        structural_context: Graph neighbourhood / structural context to include
            in the review prompt (per S-8 implementation notes).
        adapter: LLM adapter to use for the review call.  Callers supply the
            appropriate adapter — use a dedicated review adapter when a separate
            review model is configured.
        config: Co-regulation configuration.  Defaults to enabled with standard
            thresholds when None.

    Returns:
        A :class:`CoRegulationAssessment` instance.  Check
        :attr:`CoRegulationAssessment.composite_pass` to determine whether the
        librarian output is approved for graph integration.
    """
    if config is not None and not config.enabled:
        return _AUTO_PASS

    prompt = _build_prompt(librarian_output, code_snippet, structural_context)
    result = await adapter.analyze(prompt, context="")
    return _parse_response(result.content)
