"""Budget meter — token/cost budgets per task, enforced, never estimated.

A budget of 0 means unlimited (the existing CustomAgent convention).
Usage is only counted when a runner reports it; a runner that reports
``None`` marks usage unknown and the meter refuses to pretend otherwise:
``exceeded`` is False and ``usage_known`` is False, so an unenforceable
budget logs that fact instead of stopping a run on a fabricated number
(same honesty rule as :class:`backend.code_agent.CostMeter`).
"""

from __future__ import annotations

from dataclasses import dataclass


class BudgetExceeded(Exception):
    """Raised when a recorded usage pushes a task over its budget."""


@dataclass
class BudgetMeter:
    token_budget: int = 0
    cost_budget_usd: float = 0.0
    tokens_used: int = 0
    cost_used: float = 0.0
    unknown_usage: bool = False

    @property
    def usage_known(self) -> bool:
        return not self.unknown_usage

    def exceeded(self) -> bool:
        """True only on known usage over a configured budget."""
        if self.token_budget and self.tokens_used > self.token_budget:
            return True
        if self.cost_budget_usd and self.cost_used > self.cost_budget_usd:
            return True
        return False

    def check(self) -> None:
        if self.exceeded():
            raise BudgetExceeded(
                f"budget exceeded: {self.tokens_used}/{self.token_budget} tokens, "
                f"${self.cost_used:.4f}/${self.cost_budget_usd:.4f}")

    def add(self, tokens: int | None, cost_usd: float | None) -> bool:
        """Record one step's reported usage. Returns True if now exceeded.

        ``None`` usage is recorded as unknown (never estimated) and does
        not move the totals.
        """
        if tokens is None and cost_usd is None:
            self.unknown_usage = True
            return False
        if tokens is not None:
            self.tokens_used += max(0, int(tokens))
        if cost_usd is not None:
            self.cost_used += float(cost_usd)
        return self.exceeded()

    def gauge(self) -> dict:
        def pct(used: float, budget: float) -> float | None:
            return round(used / budget * 100.0, 1) if budget else None

        return {
            "tokens_used": self.tokens_used,
            "token_budget": self.token_budget,
            "token_pct": pct(self.tokens_used, self.token_budget),
            "cost_used": round(self.cost_used, 4),
            "cost_budget_usd": self.cost_budget_usd,
            "cost_pct": pct(self.cost_used, self.cost_budget_usd),
            "usage_known": self.usage_known,
            "exceeded": self.exceeded(),
        }
