"""Mode C — Question / Understanding / Conversation (chat mode).

Per design §9.3. A multi-turn conversation that maintains short-term
context, fans out to RAG when the user asks a substantive question, and
returns a written answer with citations. Streaming + interrupt is wired
in a later sprint; here we ship the contract.

The session is stateful but trivially serializable so the supervisor can
checkpoint a paused conversation.

Zone S additions
----------------
* Per-turn skill selection (MODE_SKILL_INTEGRATION §4.2):
  - Implicit top-3 via ``recommend(framed, mode="ask", depth="quick")``.
  - ``/sources`` pin parsing: ``/sources skill_a,skill_b`` overrides the
    recommended set for this turn (and stickily for the session when the
    session's ``pinned_skills`` set is updated).
  - ``@skill`` directive: ``@arxiv`` forces that skill for the next turn.
* Contradiction statement: when retrieved evidence contains cross-source
  contradictions (:func:`~lighthouse_ai.verification.contradiction.detect`),
  they are stated plainly in the answer prefix — never silently smoothed
  (§6.5 / §4 "stated plainly in the answer").
* ``/adjudicate`` directive: when present in the user text, the answer turn
  carries ``adjudicate_flag=True`` so the UI / supervisor can escalate the
  disputed claim.

Gateway=None path is unchanged: the draft string is the same, skill
selection is a no-op.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from ..gateway import Gateway
from ..rag.hybrid import HybridSearch

Role = Literal["user", "assistant", "system"]

# Regex to parse /sources followed by skill identifiers.
# Two formats are accepted:
#   comma-separated:  /sources arxiv,pubmed,openalex  (may have spaces around commas)
#   space-separated:  /sources arxiv pubmed semantic_scholar
# When commas are present we take only the comma-delimited run (stopping before
# any additional query text not separated by a comma).
_SOURCES_COMMA_RE = re.compile(
    r"/sources\s+([a-zA-Z0-9_\-]+(?:\s*,\s*[a-zA-Z0-9_\-]+)+)",
    re.IGNORECASE,
)
_SOURCES_SPACE_RE = re.compile(
    r"/sources\s+((?:[a-zA-Z0-9_\-]+\s*)+?)(?:\s+\S|$)",
    re.IGNORECASE,
)
_AT_SKILL_RE = re.compile(r"@([a-zA-Z0-9_\-]+)")
_ADJUDICATE_RE = re.compile(r"/adjudicate", re.IGNORECASE)


# --------------------------------------------------------------------------- #
# Directive parsing helpers
# --------------------------------------------------------------------------- #

def _parse_sources_pin(text: str) -> list[str] | None:
    """/sources skill_a,skill_b  → [skill_a, skill_b] or None if absent.

    Two formats:
    - Comma-separated (recommended): ``/sources arxiv, pubmed, openalex``
      — takes only the comma-delimited run; stops before additional query text.
    - Space-separated (all on one "word run"): ``/sources arxiv pubmed``
      — takes the full run.

    ``/sources arxiv,pubmed find me papers`` correctly yields
    ``["arxiv", "pubmed"]`` because commas are present.
    ``/sources arxiv pubmed semantic_scholar`` yields all three.
    """
    # Try comma-separated first (more precise stopping rule).
    m = _SOURCES_COMMA_RE.search(text)
    if m:
        raw = m.group(1)
        return [s.strip() for s in re.split(r"\s*,\s*", raw) if s.strip()]

    # Fall back to space-separated: find the /sources token and slurp the
    # immediately following run of identifier-shaped tokens.
    idx = re.search(r"/sources\s+", text, re.IGNORECASE)
    if not idx:
        return None
    rest = text[idx.end():]
    # Collect leading identifier tokens (stop at first non-identifier token).
    tokens = []
    for tok in rest.split():
        if re.fullmatch(r"[a-zA-Z0-9_\-]+", tok):
            tokens.append(tok)
        else:
            break
    return tokens if tokens else None


def _parse_at_skills(text: str) -> list[str]:
    """@skill_name → [skill_name, …]."""
    return _AT_SKILL_RE.findall(text)


def _has_adjudicate(text: str) -> bool:
    """/adjudicate anywhere in the text."""
    return bool(_ADJUDICATE_RE.search(text))


# --------------------------------------------------------------------------- #
# Session + Turn
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class Turn:
    role: Role
    text: str
    citations: list[str] = field(default_factory=list)
    # Zone S additions — present only on assistant turns
    skill_ids_used: list[str] = field(default_factory=list)
    adjudicate_flag: bool = False


@dataclass
class QUCSession:
    id: str
    history: list[Turn] = field(default_factory=list)
    topic: str | None = None
    # Skills pinned via /sources — sticky for the session.
    pinned_skills: list[str] = field(default_factory=list)

    def add(self, role: Role, text: str, citations: list[str] | None = None,
            skill_ids_used: list[str] | None = None,
            adjudicate_flag: bool = False) -> Turn:
        t = Turn(
            role=role,
            text=text,
            citations=list(citations or []),
            skill_ids_used=list(skill_ids_used or []),
            adjudicate_flag=adjudicate_flag,
        )
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


# --------------------------------------------------------------------------- #
# Contradiction statement helper
# --------------------------------------------------------------------------- #

def _contradiction_prefix(
    evidence_chunks,
    *,
    job_id: str,
    detected_at: datetime,
) -> str:
    """Return a short plain-text prefix listing any cross-source contradictions.

    Returns an empty string when no contradictions are found (the common case).
    Never raises — if detection fails for any reason the answer is left clean.
    """
    if not evidence_chunks:
        return ""
    try:
        from ..verification.contradiction import detect
        from ..verification.discipline import Claim as _Claim

        # Build minimal claim objects from chunk text.
        claims = [_Claim(text=getattr(getattr(h, "chunk", h), "text", "")[:200])
                  for h in evidence_chunks]
        contradictions = detect(
            claims,
            [getattr(h, "chunk", h) for h in evidence_chunks],
            job_id=job_id,
            detected_at=detected_at,
        )
        if not contradictions:
            return ""
        lines = []
        for c in contradictions:
            lines.append(
                f"Note: sources disagree on \"{c.claim[:80]}\" "
                f"[{c.detection_layer}, severity={c.severity}]."
            )
        return "\n".join(lines) + "\n\n"
    except Exception:
        return ""


# --------------------------------------------------------------------------- #
# Per-turn skill selection (Zone S, §4.2)
# --------------------------------------------------------------------------- #

def _select_skills(
    user_text: str,
    session: QUCSession,
    *,
    recommended_skills: list[str] | None,
    pinned_skills: list[str] | None,
) -> list[str]:
    """Resolve the effective skill list for this turn.

    Priority order (highest first):
    1. ``@skill`` directives in the user text — overrides everything.
    2. ``/sources`` pin parsed from the user text — sticky, updates session.
    3. ``pinned_skills`` from the session (set by a prior ``/sources`` turn).
    4. ``recommended_skills`` (implicit top-3 from the recommender).
    5. Empty list (gateway=None or recommender returned nothing).
    """
    # @skill directives override all
    at_skills = _parse_at_skills(user_text)
    if at_skills:
        return at_skills

    # /sources pin (sticky)
    sources_pin = _parse_sources_pin(user_text)
    if sources_pin is not None:
        session.pinned_skills = sources_pin
        return sources_pin

    # session-level sticky pin
    if session.pinned_skills:
        return list(session.pinned_skills)

    # explicit caller-supplied pin
    if pinned_skills:
        return list(pinned_skills)

    # implicit recommended top-3
    if recommended_skills:
        return recommended_skills[:3]

    return []


# --------------------------------------------------------------------------- #
# Main entry point
# --------------------------------------------------------------------------- #

def ask(
    session: QUCSession,
    user_text: str,
    *,
    hybrid: HybridSearch | None = None,
    gateway: Gateway | None = None,
    retrieve_threshold: int = 4,
    recommended_skills: list[str] | None = None,
    pinned_skills: list[str] | None = None,
    contradiction_timestamp: datetime | None = None,
) -> Turn:
    """Append the user turn, optionally retrieve evidence, draft an answer.

    Parameters
    ----------
    session:
        The active :class:`QUCSession`.
    user_text:
        The user's message, possibly containing directives (``/sources``,
        ``@skill``, ``/adjudicate``).
    hybrid:
        Optional RAG retriever.  When present and ``user_text`` is long
        enough (``>= retrieve_threshold`` words), evidence is retrieved.
    gateway:
        Optional LLM gateway.  When ``None`` the draft answer is produced
        offline — unchanged behaviour.
    retrieve_threshold:
        Minimum word count to trigger evidence retrieval.
    recommended_skills:
        Implicit top-3 skill ids from the recommender (Zone S §4.2).
        Passed through to the prompt when a gateway is available.
    pinned_skills:
        Explicit user-pinned skill ids (overrides recommended).  Updated
        by ``/sources`` directives in ``user_text``.
    contradiction_timestamp:
        Fixed ``datetime`` for the contradiction detector.  When ``None``
        the contradiction statement step is skipped (keeps the function
        offline-deterministic; callers should supply this).
    """
    session.add("user", user_text)

    # Parse directives before retrieval.
    adjudicate_flag = _has_adjudicate(user_text)

    # Resolve effective skill list (no-op when gateway=None).
    effective_skills = _select_skills(
        user_text,
        session,
        recommended_skills=recommended_skills,
        pinned_skills=pinned_skills,
    )

    citations: list[str] = []
    evidence_block = ""
    hits: list = []

    if hybrid is not None and len(user_text.split()) >= retrieve_threshold:
        hits = hybrid.search(user_text, top_k=4)
        citations = [h.chunk.id for h in hits]
        evidence_block = "\n".join(
            f"[{i+1}] {h.chunk.text[:300]}" for i, h in enumerate(hits)
        )

    history = session.render_history()

    # Contradiction statement (Zone S §4 / §6.5): detect before answer draft.
    contradiction_note = ""
    if hits and contradiction_timestamp is not None:
        contradiction_note = _contradiction_prefix(
            hits,
            job_id=session.id,
            detected_at=contradiction_timestamp,
        )

    if gateway is None:
        answer = (f"[draft] (no LLM bound) — you asked: {user_text}\n"
                  f"Evidence chunks: {len(citations)}")
    else:
        # Build the skill context hint for the planner (§4.2).
        skill_hint = ""
        if effective_skills:
            skill_hint = (
                f"Skills available for this turn: {', '.join(effective_skills)}\n"
            )

        prompt = (
            f"Conversation so far:\n{history}\n\n"
            f"{skill_hint}"
            f"Evidence:\n{evidence_block}\n\n"
            f"USER: {user_text}\n\nDraft a concise answer with [N] citations."
        )
        resp = gateway.complete("researcher", prompt, job_id=session.id)
        answer = resp.text

    # Prepend contradiction note to the answer (always plain, never hidden).
    if contradiction_note:
        answer = contradiction_note + answer

    return session.add(
        "assistant",
        answer,
        citations,
        skill_ids_used=effective_skills,
        adjudicate_flag=adjudicate_flag,
    )
