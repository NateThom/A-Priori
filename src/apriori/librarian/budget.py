"""TokenBudgetManager — enforces per-run and per-iteration token limits (ERD §4.8).

Budget management prevents unexpected token bills by:
- Halting the librarian loop when cumulative tokens plus the estimated next
  iteration cost would exceed ``max_tokens_per_run``.
- Flagging prompts that exceed ``max_tokens_per_iteration`` so callers can
  truncate graph context before sending to the LLM.

When co-regulation is enabled the cost estimate is doubled, because each
iteration makes two LLM calls (analysis + review).

Token estimation uses a rolling average of the ``token_estimation_window``
most recent iterations. Before any iterations have run, the estimate is 0
(no halt issued until actual cost data is available).
"""

from __future__ import annotations

from collections import deque
from typing import Optional

from apriori.config import BudgetConfig


class TokenBudgetManager:
    """Manages token budget enforcement across librarian loop iterations.

    Args:
        config: Budget configuration (limits, window size).
        co_regulation_enabled: When True, cost estimate per iteration is
            doubled to account for the analysis + review call pair.
    """

    def __init__(
        self,
        config: BudgetConfig,
        *,
        co_regulation_enabled: bool = False,
    ) -> None:
        self._config = config
        self._co_regulation_enabled = co_regulation_enabled
        self._total_tokens: int = 0
        self._history: deque[int] = deque(maxlen=config.token_estimation_window)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def total_tokens(self) -> int:
        """Cumulative tokens consumed across all recorded iterations."""
        return self._total_tokens

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    def record_iteration(self, tokens: int) -> None:
        """Record the tokens consumed by a completed iteration.

        Updates both the cumulative total and the rolling average window.
        """
        self._total_tokens += tokens
        self._history.append(tokens)

    # ------------------------------------------------------------------
    # Estimation
    # ------------------------------------------------------------------

    def estimate_next_iteration_cost(self) -> int:
        """Estimate the token cost of the next iteration.

        Returns the rolling average of recent iterations, doubled when
        co-regulation is enabled. Returns 0 before any iteration has
        been recorded (avoids false halts at run start).
        """
        if not self._history:
            return 0
        avg = sum(self._history) / len(self._history)
        if self._co_regulation_enabled:
            avg *= 2
        return int(avg)

    # ------------------------------------------------------------------
    # Halt check
    # ------------------------------------------------------------------

    def should_halt_before_iteration(self) -> bool:
        """Return True when proceeding would exceed the per-run token limit.

        Halt condition: ``total_tokens + estimated_next_cost > max_tokens_per_run``.
        Always returns False when ``max_tokens_per_run`` is not configured.
        """
        if self._config.max_tokens_per_run is None:
            return False
        estimated = self.estimate_next_iteration_cost()
        return (self._total_tokens + estimated) > self._config.max_tokens_per_run

    # ------------------------------------------------------------------
    # Per-iteration check
    # ------------------------------------------------------------------

    def check_iteration_limit(self, token_count: int) -> bool:
        """Return True when ``token_count`` exceeds the per-iteration limit.

        Callers should respond by truncating graph context (not code) and
        logging a warning. Always returns False when
        ``max_tokens_per_iteration`` is not configured.
        """
        if self._config.max_tokens_per_iteration is None:
            return False
        return token_count > self._config.max_tokens_per_iteration
