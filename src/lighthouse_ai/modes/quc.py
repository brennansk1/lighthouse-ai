"""Mode C — Question / Understanding / Conversation (chat mode).

Per design §9.3. A multi-turn conversation that maintains short-term
context, fans out to RAG when the user asks a substantive question, and
returns a written answer with citations. Streaming + interrupt is wired
in a later sprint; here we ship the contract.

The session is stateful but trivially serializable so the supervisor can
checkpoint a paused conversation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from ..gateway import Gateway
from ..rag.hybrid import HybridSearch

Role = Literal["user", "assistant", "system"]


@dataclass(frozen=True)
class Turn:
    role: Role
    text: str
    citations: list[str] = field(default_factory=list)


@dataclass
class QUCSession:
    id: str
    history: list[Turn] = field(default_factory=list)
    topic: str | None = None

    def add(self, role: Role, text: str, citations: list[str] | None = None) -> Turn:
        t = Turn(role=role, text=text, citations=list(citations or []))
        self.history.append(t)
        return t

    def render_history(self, *, max_chars: int = 4000) -> str:
        """Render the conversation as a transcript chunk for the model.

        Truncates the oldest turns when the budget is exceeded — production
        replaces this with the ReSum compaction primitive (§14.11).
        """
        parts: list[str] = []
        running = 0
        for t in reversed(self.history):
            seg = f"{t.role.upper()}: {t.text}"
            if running + len(seg) > max_chars:
                break
            parts.append(seg)
            running += len(seg) + 1
        return "\n\n".join(reversed(parts))


def ask(session: QUCSession, user_text: str, *,
        hybrid: HybridSearch | None = None,
        gateway: Gateway | None = None,
        retrieve_threshold: int = 4) -> Turn:
    """Append the user turn, optionally retrieve evidence, draft an answer."""
    session.add("user", user_text)
    citations: list[str] = []
    evidence_block = ""
    if hybrid is not None and len(user_text.split()) >= retrieve_threshold:
        hits = hybrid.search(user_text, top_k=4)
        citations = [h.chunk.id for h in hits]
        evidence_block = "\n".join(
            f"[{i+1}] {h.chunk.text[:300]}" for i, h in enumerate(hits)
        )
    history = session.render_history()
    if gateway is None:
        answer = (f"[draft] (no LLM bound) — you asked: {user_text}\n"
                  f"Evidence chunks: {len(citations)}")
    else:
        prompt = (
            f"Conversation so far:\n{history}\n\n"
            f"Evidence:\n{evidence_block}\n\n"
            f"USER: {user_text}\n\nDraft a concise answer with [N] citations."
        )
        resp = gateway.complete("researcher", prompt, job_id=session.id)
        answer = resp.text
    return session.add("assistant", answer, citations)
