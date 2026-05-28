"""Mode A — Monitor.

Per design §9.1: continuous polling of named sources, dedupe, classify,
score salience, surface high-salience items as alerts, batch the rest into
a digest. The mode is a thin orchestrator: the heavy lifting (fetching,
sandboxing, embedding) is done by the subsystems built earlier.

The orchestrator is *idempotent over (source, item_id)*: feeding the same
item twice yields one record, not two. We use the SHA-256 of the item URL
as the dedup key.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from ..gateway import Gateway
from ..rag.embedder import cosine


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

    Production replaces this with a small LLM call (`aux_context` role)
    that scores relative to the user's stated interest in the topic.
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
    embed_titles: Callable[[Iterable[str]], list[list[float]]] | None = None,
) -> MonitorReport:
    """Run one polling cycle of Mode A.

    The function is pure (no I/O) except via ``gateway`` and ``embed_titles``
    if supplied; those are the seams Sprint 5/4 modules plug into.
    """
    st = state or MonitorState()
    items_list = list(items)
    total = len(items_list)

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
        salience, category = salience_fn(it)
        classified.append(ClassifiedItem(item=it, salience=salience,
                                         category=category, embedding=emb))

    # 4. split into alerts vs digest.
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
