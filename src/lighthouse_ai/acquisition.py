"""Iterative web acquisition — the deep-research "acquire as you learn" loop.

Frontier deep-research systems do not fetch once and re-rank forever: they
issue new searches driven by what the intermediate research uncovered. This
module is that loop for Lighthouse. The dispatcher builds one
:class:`Acquirer` per online job; the engines call ``acquire(sub_question)``
whenever a line of inquiry is thin, and the corpus — and therefore every
later retrieval, citation, contradiction check, and provenance record —
grows mid-run.

Everything rides the existing rails, none of which are widened here:

* source selection per sub-question via :func:`skills.recommender.recommend`
  (a sub-question about FDA filings reaches ``regulations_gov`` even when the
  topic-level pick was ``arxiv``);
* fetching via :func:`skills.runner.run_skill` → broker → egress guard →
  politeness gate (non-allowlisted result hosts degrade to snippet docs);
* every chunk is screened by the :class:`~governor.injection_gate.InjectionGate`
  before it can enter the retrievable index (§24.8 — previously the job-corpus
  path skipped this);
* per-tier budgets (:func:`policy_for_tier`) cap total acquisition, and the
  loop guard / wall-clock budgets bound the run as before.

Offline (``gateway=None``) jobs never construct an Acquirer, so offline runs
remain bit-for-bit deterministic.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import structlog

from .governor import InjectionGate

if TYPE_CHECKING:
    from .rag.chunker import Chunk

_log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Per-tier acquisition policy
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AcquisitionPolicy:
    """How much new evidence a run may pull in while it researches.

    ``iterative=False`` (the Quick tier) keeps the historical one-shot
    behavior. ``max_total_docs`` is the hard run-wide cap; the politeness
    layer still rate-limits per-domain underneath it.
    """

    iterative: bool
    skills_per_query: int = 0
    results_per_skill: int = 0
    query_variants: int = 1
    link_follow_budget: int = 0
    max_total_docs: int = 0


_POLICIES: dict[str, AcquisitionPolicy] = {
    "quick": AcquisitionPolicy(iterative=False),
    "standard": AcquisitionPolicy(
        iterative=True,
        skills_per_query=2,
        results_per_skill=5,
        query_variants=1,
        link_follow_budget=0,
        max_total_docs=60,
    ),
    "thorough": AcquisitionPolicy(
        iterative=True,
        skills_per_query=3,
        results_per_skill=5,
        query_variants=2,
        link_follow_budget=0,
        max_total_docs=150,
    ),
    "deep": AcquisitionPolicy(
        iterative=True,
        skills_per_query=3,
        results_per_skill=8,
        query_variants=3,
        link_follow_budget=5,
        max_total_docs=400,
    ),
}


def policy_for_tier(depth: str | None) -> AcquisitionPolicy:
    """Acquisition policy for a depth label (same aliases as the engine knobs)."""
    from .modes.depth import canonical_tier

    return _POLICIES[canonical_tier(depth)]


# ---------------------------------------------------------------------------
# Injection-screened chunking (shared with the dispatcher's upfront corpus)
# ---------------------------------------------------------------------------

_GATE = InjectionGate()  # stateless scorer; safe to share across jobs/threads


def screen_and_chunk(docs: list[dict]) -> tuple[list[Chunk], int]:
    """Chunk ``meta["documents"]``-shaped dicts, dropping injected chunks.

    Mirrors ``pipeline.ingest_text`` (§24.8): a chunk the injection gate flags
    must never silently reach the LLM's retrievable context. Returns
    ``(safe_chunks, blocked_count)``.
    """
    from .rag import Document, chunk_document

    safe: list[Chunk] = []
    blocked = 0
    for i, d in enumerate(docs):
        doc_id = str(d.get("doc_id") or d.get("id") or f"doc{i}")
        text = str(d.get("text", ""))
        if not text.strip():
            continue
        chunks = chunk_document(
            Document(
                id=doc_id,
                text=text,
                metadata={
                    "source": str(d.get("title", doc_id)),
                    **({"skill_id": d["skill_id"]} if d.get("skill_id") else {}),
                    **({"url": d["url"]} if d.get("url") else {}),
                },
            )
        )
        for c in chunks:
            if _GATE.score(c.text).blocked:
                blocked += 1
                continue
            safe.append(c)
    return safe, blocked


# ---------------------------------------------------------------------------
# Query fan-out
# ---------------------------------------------------------------------------


def query_variants(sub_question: str, k: int, gateway: Any | None) -> list[str]:
    """Up to ``k`` diverse search formulations of *sub_question*.

    The original sub-question is always first. With no gateway (or any model
    failure) the list is exactly ``[sub_question]`` — deterministic offline.
    """
    out = [sub_question]
    if gateway is None or k <= 1:
        return out
    prompt = (
        f"Research sub-question: {sub_question}\n\n"
        f"Write {k - 1} alternative web-search queries for it, each probing a "
        "different angle (key entities, mechanisms, counter-evidence, recent "
        "developments). One query per line, no numbering, no commentary."
    )
    try:
        resp = gateway.complete_structured(prompt)
        for line in resp.text.splitlines():
            q = line.strip(" -•*\t")
            if q and q.lower() != sub_question.lower() and q not in out:
                out.append(q)
            if len(out) >= k:
                break
    except Exception:
        pass
    return out[:k]


_URL_RE = re.compile(r"https?://[^\s)\]>\"']+")


def extract_links(texts: list[str], *, limit: int) -> list[str]:
    """The most-referenced outbound URLs across *texts* (citation chasing)."""
    counts: Counter[str] = Counter()
    for t in texts:
        for url in _URL_RE.findall(t or ""):
            counts[url.rstrip(".,;")] += 1
    return [u for u, _n in counts.most_common(limit)]


# ---------------------------------------------------------------------------
# The Acquirer
# ---------------------------------------------------------------------------


@dataclass
class Acquirer:
    """Per-job iterative acquisition engine (online runs only).

    ``acquire(sub_question)`` selects sources for that specific sub-question,
    fans the query out, runs the skills through the broker, screens + indexes
    the new evidence into the run's hybrid, and registers it with the job meta
    so the citation-discipline / contradiction / provenance layers all see it.
    Best-effort by contract: any failure logs and returns 0 — acquisition can
    never crash a research run.
    """

    policy: AcquisitionPolicy
    broker: Any
    gateway: Any
    hybrid: Any
    meta: dict
    mode: str = "investigate"
    depth: str | None = None
    progress: Any = None  # ProgressEmitter | None

    _seen: set[str] = field(default_factory=set, repr=False)
    _followed: set[str] = field(default_factory=set, repr=False)
    total_docs: int = 0
    blocked_chunks: int = 0

    def __post_init__(self) -> None:
        # Seed the dedup ledger with the upfront corpus so re-fetches of the
        # same source cost nothing.
        for d in self.meta.get("documents") or []:
            for key in (d.get("url"), d.get("doc_id"), d.get("id")):
                if key:
                    self._seen.add(str(key))

    # -- core ----------------------------------------------------------------
    def acquire(self, sub_question: str) -> int:
        """Fetch + index new evidence for *sub_question*. Returns new-doc count."""
        if not self.policy.iterative or self.broker is None:
            return 0
        if self.total_docs >= self.policy.max_total_docs:
            return 0
        try:
            return self._acquire(sub_question)
        except Exception as exc:  # never let acquisition crash a run
            _log.warning("acquisition.error", error=repr(exc), sub_question=sub_question[:80])
            return 0

    def _acquire(self, sub_question: str) -> int:
        from .skills import load_skill, run_skill
        from .skills.recommender import recommend

        skill_ids: list[str] = []
        try:
            recs = recommend(sub_question, self.mode, self.depth, gateway=self.gateway)
            skill_ids = [r.skill_id for r in recs[: self.policy.skills_per_query]]
        except Exception:
            skill_ids = []
        if not skill_ids:
            skill_ids = ["general_web"]

        queries = query_variants(sub_question, self.policy.query_variants, self.gateway)

        new_docs: list = []
        sources_hit: set[str] = set()
        for sid in skill_ids:
            try:
                skill = load_skill(sid)
            except Exception:
                continue
            for q in queries:
                if self.total_docs + len(new_docs) >= self.policy.max_total_docs:
                    break
                run = run_skill(
                    skill,
                    q,
                    broker=self.broker,
                    gateway=self.gateway,
                    max_results=self.policy.results_per_skill,
                )
                for doc in run.documents:
                    key = self._doc_key(doc)
                    if key in self._seen:
                        continue
                    self._seen.add(key)
                    new_docs.append(doc)
                if run.documents:
                    sources_hit.add(sid)
        return self._ingest(new_docs, sources_hit, sub_question)

    def follow_links(self) -> int:
        """One-hop citation chase over evidence acquired so far (deep tier).

        Extracts the most-referenced outbound URLs from acquired document text
        and fetches them through the general_web skill context — the same
        broker-gated, egress-guarded path as every other fetch; hosts outside
        the platform allowlist are simply skipped.
        """
        if self.policy.link_follow_budget <= 0 or self.broker is None:
            return 0
        if self.total_docs >= self.policy.max_total_docs:
            return 0
        try:
            return self._follow_links()
        except Exception as exc:
            _log.warning("acquisition.follow_links.error", error=repr(exc))
            return 0

    def _follow_links(self) -> int:
        from .skills import load_skill
        from .skills.capabilities import build_context

        texts = [str(d.get("text", "")) for d in self.meta.get("documents") or []]
        candidates = [
            u
            for u in extract_links(texts, limit=self.policy.link_follow_budget * 4)
            if u not in self._followed and u not in self._seen
        ]
        if not candidates:
            return 0
        try:
            gw = load_skill("general_web")
            ctx = build_context(gw.manifest, broker=self.broker, gateway=self.gateway)
        except Exception:
            return 0
        new_docs: list = []
        for url in candidates:
            if len(new_docs) >= self.policy.link_follow_budget:
                break
            if self.total_docs + len(new_docs) >= self.policy.max_total_docs:
                break
            self._followed.add(url)
            try:
                doc = ctx.fetch_and_document(url, extra_meta={"via": "link_follow"})
            except Exception:  # EgressBlocked / network / broker rejection
                continue
            if doc is None:
                continue
            key = self._doc_key(doc)
            if key in self._seen:
                continue
            self._seen.add(key)
            new_docs.append(doc)
        return self._ingest(new_docs, {"general_web"}, "citation chase")

    # -- plumbing --------------------------------------------------------------
    @staticmethod
    def _doc_key(doc: Any) -> str:
        meta = getattr(doc, "metadata", {}) or {}
        return str(meta.get("url") or meta.get("source") or getattr(doc, "id", "") or id(doc))

    def _ingest(self, docs: list, sources: set[str], label: str) -> int:
        """Screen, index, and register newly acquired documents."""
        if not docs:
            return 0
        from .dispatcher import _SKILL_DOCS_META_KEY, _skill_docs_to_meta

        doc_dicts = _skill_docs_to_meta(docs)
        chunks, blocked = screen_and_chunk(doc_dicts)
        self.blocked_chunks += blocked
        if chunks and self.hybrid is not None:
            self.hybrid.add(chunks)
        # Register with the job meta: meta["documents"] feeds source_count and
        # the provenance manifest; _SKILL_DOCS_META_KEY feeds contradiction
        # detection and the auto-Adjudicate trigger.
        self.meta.setdefault("documents", []).extend(doc_dicts)
        prior = self.meta.get(_SKILL_DOCS_META_KEY) or []
        self.meta[_SKILL_DOCS_META_KEY] = list(prior) + list(docs)
        self.total_docs += len(docs)
        if self.progress is not None:
            try:
                self.progress.emit(
                    "sources",
                    "acquired",
                    f"+{len(docs)} documents from {max(len(sources), 1)} "
                    f"source(s) for: {label[:80]}",
                    30.0,
                    {
                        "new_documents": len(docs),
                        "total_acquired": self.total_docs,
                        "blocked_chunks": blocked,
                        "sources": sorted(sources),
                    },
                )
            except Exception:
                pass
        _log.info(
            "acquisition.ingested",
            new=len(docs),
            total=self.total_docs,
            blocked=blocked,
            label=label[:80],
        )
        return len(docs)
