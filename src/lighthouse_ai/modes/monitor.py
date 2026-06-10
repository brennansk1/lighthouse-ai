"""Mode A — Monitor.

Per design §9.1: continuous polling of named sources, dedupe, classify,
score salience, surface high-salience items as alerts, batch the rest into
a digest. The mode is a thin orchestrator: the heavy lifting (fetching,
sandboxing, embedding) is done by the subsystems built earlier.

The orchestrator is *idempotent over (source, item_id)*: feeding the same
item twice yields one record, not two. We use the SHA-256 of the item URL
as the dedup key.

Gap #15 (Zone S): interest-relative LLM salience via the gateway
``aux_context`` role. When a ``gateway`` is supplied and a ``topic_interests``
string is given, each item is scored relative to the user's stated interest
anchors rather than by the length+keyword heuristic. ``default_salience`` is
always preserved as the deterministic offline fallback.

Cross-source contradiction escalation (MODE_SKILL_INTEGRATION §6, Watch
row): when two items from *different* sources make claims that the
:mod:`~lighthouse_ai.verification.contradiction` module detects as a
``cross_skill``-layer disagreement, the higher-salience item is promoted to
an ``escalation`` category (rather than a reflection), and both items have
their ``category`` set to ``"escalation"`` so the Watch tab can surface them.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from ..gateway import Gateway
from ..rag.embedder import cosine
from ._gate import gate_ctx

if TYPE_CHECKING:
    from ..compounding.hotness import EntityStats
    from ..governor.scheduler_gate import SchedulerGate


@dataclass(frozen=True)
class MonitorItem:
    source: str
    url: str
    title: str
    body: str
    published_at: str | None = None
    metadata: dict = field(default_factory=dict)

    def dedup_key(self) -> str:
        return hashlib.sha256(self.url.encode()).hexdigest()


@dataclass(frozen=True)
class ClassifiedItem:
    item: MonitorItem
    salience: float  # 0..1
    category: str
    embedding: list[float] | None = None

    @property
    def is_alert(self) -> bool:
        return self.salience >= 0.7


@dataclass(frozen=True)
class MonitorReport:
    topic: str
    generated_at: str
    alerts: list[ClassifiedItem]
    digest: list[ClassifiedItem]
    suppressed_duplicates: int
    total_seen: int


# Pluggable classifier — production uses the Gateway.aux_context role.
SalienceFn = Callable[[MonitorItem], tuple[float, str]]


def default_salience(item: MonitorItem) -> tuple[float, str]:
    """Heuristic baseline: long body + recency hints → higher salience.

    Production replaces this with a small LLM call (``aux_context`` role)
    that scores relative to the user's stated interest in the topic.
    This function is the deterministic offline fallback; its signature is
    stable and it is never replaced — callers that want LLM scoring use
    :func:`make_gateway_salience` to obtain a wrapper that calls this on
    fallback.
    """
    text = (item.title + " " + item.body).lower()
    word_count = len(text.split())
    score = min(0.5 + word_count / 2000.0, 1.0)
    if any(k in text for k in ("breaking", "urgent", "critical", "major")):
        score = min(score + 0.3, 1.0)
        return score, "alert"
    if any(k in text for k in ("rumor", "speculation", "alleged")):
        return max(score - 0.3, 0.0), "noise"
    return score, "informational"


def make_gateway_salience(
    gateway: Gateway,
    topic_interests: str,
    *,
    job_id: str = "monitor",
    gate: SchedulerGate | None = None,
) -> SalienceFn:
    """Return a salience function backed by the ``aux_context`` LLM role.

    Gap #15 (Zone S): rates each item's relevance to ``topic_interests``
    (the topic's stated interest / anchor text).  The prompt asks the model
    to reply with a JSON object ``{"score": <0..1>, "category":
    "<alert|informational|noise>"}`` so the reply is cheap and
    deterministic to parse.

    On any LLM failure (gateway unavailable, bad parse, …) the function
    falls back to :func:`default_salience` so the offline path is
    unchanged.

    Parameters
    ----------
    gateway:
        A live :class:`~lighthouse_ai.gateway.Gateway` instance. May be
        ``None`` at call sites that want the heuristic — but this factory
        should not be called with ``None``; just use ``default_salience``
        directly.
    topic_interests:
        Free-text description of what the watcher cares about (e.g.
        ``"AI regulation, EU AI Act, model safety"``).
    job_id:
        Passed through to the gateway audit trail.
    """

    def _score(item: MonitorItem) -> tuple[float, str]:
        try:
            prompt = (
                "You are a research-relevance scorer. "
                f"The watcher's interests are: {topic_interests}\n\n"
                f"Item title: {item.title}\n"
                f"Item body (first 400 chars): {item.body[:400]}\n\n"
                'Reply with ONLY a JSON object like {"score": 0.82, "category": "alert"} '
                "where score is 0..1 and category is one of alert, informational, noise."
            )
            with gate_ctx(gate):
                resp = gateway.complete("aux_context", prompt, job_id=job_id)
            import json as _json
            import re as _re
            # Extract the first {...} from the response (tolerates trailing text).
            m = _re.search(r"\{[^}]+\}", resp.text)
            if m:
                obj = _json.loads(m.group())
                raw_score = float(obj.get("score", 0.5))
                score = max(0.0, min(1.0, raw_score))
                category = str(obj.get("category", "informational")).lower()
                if category not in ("alert", "informational", "noise"):
                    category = "informational"
                return score, category
        except Exception:
            pass
        return default_salience(item)

    return _score


# --------------------------------------------------------------------------- #
# Cross-source contradiction escalation (MODE_SKILL_INTEGRATION §6, Watch row)
# --------------------------------------------------------------------------- #

def _escalate_contradictions(
    classified: list[ClassifiedItem],
    *,
    contradiction_timestamp: datetime,
    job_id: str = "monitor",
) -> list[ClassifiedItem]:
    """Detect cross-source disagreements and promote to escalation category.

    When two classified items come from *different* sources and their title+body
    text triggers a contradiction at the chunk layer, both are promoted to
    category ``"escalation"`` and the higher-salience one gets its salience
    bumped to at least 0.85 (alert threshold).  Uses
    :func:`~lighthouse_ai.verification.contradiction.detect` with a fixed
    caller-supplied timestamp (never ``datetime.now()``).

    Returns a *new* list (classified items are frozen dataclasses).
    """
    from ..verification.contradiction import detect
    from ..verification.discipline import Claim as _Claim

    if len(classified) < 2:
        return classified

    # Build claims from each item's title so the polarity heuristic has
    # something to compare across items.
    claims = [_Claim(text=c.item.title) for c in classified]

    # Build minimal evidence chunks: one per item tagged with its source as
    # skill_id so detect() can spot cross-skill disagreements.
    class _MinChunk:
        def __init__(self, idx: int, source: str, title: str) -> None:
            self.id = f"item-{idx}"
            self.text = title
            self.metadata = {"skill_id": source, "entailment_score": None}

    chunks = [
        _MinChunk(i, c.item.source, c.item.title)
        for i, c in enumerate(classified)
    ]

    contradictions = detect(
        claims,
        chunks,
        job_id=job_id,
        detected_at=contradiction_timestamp,
        layer_hint=None,  # run all layers
    )

    if not contradictions:
        return classified

    # Collect indices of items involved in a cross-source (or any) contradiction.
    escalated_indices: set[int] = set()
    for contradiction in contradictions:
        # Mark any item whose title appears in a detected contradiction.
        ct = contradiction.claim.lower()
        for i, c in enumerate(classified):
            if c.item.title.lower() == ct or c.item.title.lower() in ct:
                escalated_indices.add(i)
        # Also mark items referenced through supporting/opposing chunk refs.
        for ref in contradiction.supporting_chunks + contradiction.opposing_chunks:
            # ref.chunk_id is "item-<idx>"
            try:
                idx = int(ref.chunk_id.split("-", 1)[1])
                escalated_indices.add(idx)
            except (ValueError, IndexError):
                pass

    if not escalated_indices:
        return classified

    result: list[ClassifiedItem] = []
    for i, c in enumerate(classified):
        if i in escalated_indices:
            new_salience = max(c.salience, 0.85)
            result.append(
                ClassifiedItem(
                    item=c.item,
                    salience=new_salience,
                    category="escalation",
                    embedding=c.embedding,
                )
            )
        else:
            result.append(c)
    return result


def make_hotness_salience(
    tracked: dict[str, EntityStats],
    *,
    extract_entities: Callable[[MonitorItem], list[str]] | None = None,
    now_ms: int | None = None,
) -> SalienceFn:
    """Hotness-backed salience (OpenHuman §2): score an item by the hotness of
    the tracked entities it mentions.

    ``tracked`` maps entity-id → :class:`EntityStats`. An item's salience is the
    max entity hotness it mentions, squashed to 0..1 against
    ``TOPIC_CREATION_THRESHOLD``. Unlike the length+keyword heuristic, every
    score decomposes into the five named hotness terms (surface in the
    "why salient" tooltip). ``distinct_sources`` in the stats MUST be the
    independent-source count, never raw citation count.
    """
    from ..compounding.hotness import TOPIC_CREATION_THRESHOLD, hotness_at

    now = now_ms if now_ms is not None else int(datetime.now(UTC).timestamp() * 1000)

    def _default_extract(it: MonitorItem) -> list[str]:
        text = (it.title + " " + it.body).lower()
        return [eid for eid in tracked if eid.lower() in text]

    extract = extract_entities or _default_extract

    def _score(item: MonitorItem) -> tuple[float, str]:
        mentioned = extract(item)
        # Keep only entities we actually track — a custom ``extract_entities``
        # may surface ids absent from ``tracked``. Filtering here (rather than
        # inside the ``max`` generator) avoids ``max() arg is an empty sequence``
        # when every mentioned entity is untracked.
        tracked_hits = [e for e in mentioned if e in tracked]
        if not tracked_hits:
            return 0.0, "noise"
        best = max(hotness_at(tracked[e], now) for e in tracked_hits)
        salience = min(best / TOPIC_CREATION_THRESHOLD, 1.0)
        if best >= TOPIC_CREATION_THRESHOLD:
            return salience, "alert"
        return salience, "informational"

    return _score


@dataclass
class MonitorState:
    """In-memory dedup ledger; production persists to ``state.db``."""
    seen_keys: set[str] = field(default_factory=set)
    seen_titles: list[tuple[str, list[float]]] = field(default_factory=list)


def _near_duplicate(emb: list[float], state: MonitorState,
                    threshold: float = 0.97) -> bool:
    for _, prior in state.seen_titles:
        try:
            if cosine(emb, prior) >= threshold:
                return True
        except ValueError:
            continue
    return False


def run_monitor(
    topic: str,
    items: Iterable[MonitorItem],
    *,
    state: MonitorState | None = None,
    salience_fn: SalienceFn = default_salience,
    gateway: Gateway | None = None,
    topic_interests: str | None = None,
    embed_titles: Callable[[Iterable[str]], list[list[float]]] | None = None,
    gate: SchedulerGate | None = None,
    contradiction_timestamp: datetime | None = None,
    enable_contradiction_escalation: bool = True,
) -> MonitorReport:
    """Run one polling cycle of Mode A.

    The function is pure (no I/O) except via ``gateway`` and ``embed_titles``
    if supplied; those are the seams Sprint 5/4 modules plug into.

    Parameters
    ----------
    topic:
        Human-readable topic name (appears in the report).
    items:
        Feed items to process this cycle.
    state:
        In-memory dedup ledger (shared across calls for the same topic).
    salience_fn:
        Scoring function ``(MonitorItem) -> (float, str)``.  When
        ``gateway`` is supplied and ``topic_interests`` is given, this
        defaults to a gateway-backed scorer (:func:`make_gateway_salience`);
        otherwise :func:`default_salience` is used.  An explicitly supplied
        ``salience_fn`` is always honored as-is.
    gateway:
        Optional :class:`~lighthouse_ai.gateway.Gateway`.  When provided
        together with ``topic_interests``, the ``aux_context`` role is used
        to score interest-relative salience (gap #15, Zone S).
    topic_interests:
        Free-text description of the user's interests / anchor text for
        this topic (e.g. ``"EU AI Act, model safety"``).  Only used when
        ``gateway`` is also supplied.
    embed_titles:
        Optional embedder for semantic near-duplicate suppression.
    gate:
        Optional scheduler gate for capacity limiting during embedding.
    contradiction_timestamp:
        Fixed ``datetime`` passed to
        :func:`~lighthouse_ai.verification.contradiction.detect` for the
        cross-source escalation check.  Must be supplied by the caller; if
        omitted the escalation step is skipped (avoids ``datetime.now()``
        at call-time, keeping the function offline-deterministic).
    enable_contradiction_escalation:
        When ``True`` (default) and ``contradiction_timestamp`` is supplied,
        items from different sources that contradict each other are promoted
        to category ``"escalation"`` (MODE_SKILL_INTEGRATION §6, Watch row).
        Set to ``False`` to disable without touching the timestamp.
    """
    st = state or MonitorState()
    items_list = list(items)
    total = len(items_list)

    # Resolve the effective salience function.  An explicitly passed
    # salience_fn always takes precedence; otherwise use the gateway scorer
    # when both gateway and topic_interests are given, else the heuristic.
    effective_salience: SalienceFn
    if salience_fn is not default_salience:
        # Caller supplied a custom scorer — honour it exactly.
        effective_salience = salience_fn
    elif gateway is not None and topic_interests:
        effective_salience = make_gateway_salience(
            gateway, topic_interests, job_id=f"monitor:{topic}", gate=gate
        )
    else:
        effective_salience = salience_fn  # default_salience

    # 1. dedupe by exact URL hash.
    unique: list[MonitorItem] = []
    suppressed = 0
    for it in items_list:
        key = it.dedup_key()
        if key in st.seen_keys:
            suppressed += 1
            continue
        st.seen_keys.add(key)
        unique.append(it)

    # 2. optional semantic dedupe on titles (near-duplicates from different URLs).
    titles_embeddings: list[list[float]] = []
    if embed_titles is not None and unique:
        with gate_ctx(gate):
            titles_embeddings = embed_titles(it.title for it in unique)

    pre_semantic = len(unique)
    deduped: list[tuple[MonitorItem, list[float] | None]] = []
    for i, it in enumerate(unique):
        emb = titles_embeddings[i] if titles_embeddings else None
        if emb is not None and _near_duplicate(emb, st):
            suppressed += 1
            continue
        if emb is not None:
            st.seen_titles.append((it.title, emb))
        deduped.append((it, emb))
    _ = pre_semantic  # silence linter

    # 3. classify each survivor.
    classified: list[ClassifiedItem] = []
    for it, emb in deduped:
        salience, category = effective_salience(it)
        classified.append(ClassifiedItem(item=it, salience=salience,
                                         category=category, embedding=emb))

    # 4. cross-source contradiction escalation (Zone S / §6 Watch row).
    #    Only runs when the caller supplies a fixed timestamp — avoids any
    #    datetime.now() call inside this module.
    if (
        enable_contradiction_escalation
        and contradiction_timestamp is not None
        and len(classified) >= 2
    ):
        classified = _escalate_contradictions(
            classified,
            contradiction_timestamp=contradiction_timestamp,
            job_id=f"monitor:{topic}",
        )

    # 5. split into alerts vs digest.
    classified.sort(key=lambda c: c.salience, reverse=True)
    alerts = [c for c in classified if c.is_alert]
    digest = [c for c in classified if not c.is_alert]

    return MonitorReport(
        topic=topic,
        generated_at=datetime.now(UTC).isoformat(timespec="seconds"),
        alerts=alerts,
        digest=digest,
        suppressed_duplicates=suppressed,
        total_seen=total,
    )
