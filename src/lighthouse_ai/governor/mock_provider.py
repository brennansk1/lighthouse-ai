"""Mock model provider — deterministic outputs and recorded token counts.

Wired through the Governor so Sprint 3 tests can exercise spend math
without depending on any real LLM. Each ``complete`` call asks the Governor
for a quota first; if denied, raises :class:`BudgetTripped` so callers can
distinguish budget pressure from provider failures.

The real Model Gateway in Sprint 4 follows the same shape but talks to
litellm; downstream code shouldn't care which provider is plugged in.
"""

from __future__ import annotations

from dataclasses import dataclass

from .buckets import Governor


@dataclass(frozen=True)
class MockResponse:
    text: str
    prompt_tokens: int
    completion_tokens: int
    usd: float


class MockProvider:
    """Deterministic provider: output is a function of input + token counts."""

    def __init__(self, governor: Governor, *, usd_per_1k_tokens: float = 0.0,
                 completion_tokens: int = 16):
        self.governor = governor
        self.usd_per_1k = usd_per_1k_tokens
        self.completion_tokens = completion_tokens

    def complete(self, prompt: str, *, job_id: str | None = None) -> MockResponse:
        prompt_tokens = max(1, len(prompt.split()))
        total_tokens = prompt_tokens + self.completion_tokens
        usd = (total_tokens / 1000.0) * self.usd_per_1k
        decision = self.governor.try_spend(
            usd=usd, tool_calls=1, tokens=total_tokens, job_id=job_id,
        )
        if not decision.allowed:
            from .buckets import BudgetTripped
            raise BudgetTripped(decision.reason)
        text = f"[mock {prompt_tokens}p+{self.completion_tokens}c] {prompt[:40]!r}"
        return MockResponse(text=text, prompt_tokens=prompt_tokens,
                            completion_tokens=self.completion_tokens, usd=usd)
