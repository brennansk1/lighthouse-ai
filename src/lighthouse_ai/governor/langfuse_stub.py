"""Optional Langfuse client wrapper — used when self-hosted Langfuse is up.

Skipped silently when the SDK isn't installed or the URL is unreachable so
that local-only installs don't break.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class LangfuseConfig:
    url: str | None = None
    api_key: str | None = None


def from_env() -> LangfuseConfig:
    return LangfuseConfig(
        url=os.environ.get("LANGFUSE_URL"),
        api_key=os.environ.get("LANGFUSE_API_KEY"),
    )


class LangfuseClient:
    """No-op stub when SDK missing; real client when present."""

    def __init__(self, config: LangfuseConfig | None = None):
        self.config = config or from_env()
        self._client = None
        if self.config.url and self.config.api_key:
            try:  # pragma: no cover - optional dep
                from langfuse import Langfuse  # type: ignore

                self._client = Langfuse(
                    host=self.config.url,
                    public_key=self.config.api_key,
                    secret_key=self.config.api_key,
                )
            except ImportError:
                self._client = None

    @property
    def enabled(self) -> bool:
        return self._client is not None

    def record_call(
        self,
        *,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        usd: float,
        metadata: dict | None = None,
    ) -> None:
        if self._client is None:
            return
        try:  # pragma: no cover - optional dep
            self._client.generation(
                name="lighthouse-model-call",
                model=model,
                usage={"input": prompt_tokens, "output": completion_tokens},
                metadata={**(metadata or {}), "usd": usd},
            )
        except Exception:
            pass
