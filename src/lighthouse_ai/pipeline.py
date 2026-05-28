"""Research pipeline — the wiring that makes the research features runnable
end-to-end with real backends (Ollama LLM + bge-m3 embeddings + Qdrant), or
with stubs when those aren't available / ``offline=True``.

This is the seam that ties together everything built in Sprints 1–23:
framing → RAG retrieval → a mode (Deep-Dive / QUC) → a staged draft that
shows up in the dashboard Drafts page and the audit log.

Backend selection is "prefer real, fall back to stub":
  * embedder   : bge-m3 via Ollama (1024-dim) → else HashEmbedder
  * vector store: Qdrant (if reachable)        → else InMemoryStore
  * gateway    : real Ollama dispatch (resolved tags) → else mock provider

Nothing here loads a model by itself; the Gateway loads lazily on the first
real completion, gated by the Governor budget. ``offline=True`` guarantees no
model load at all (pure stubs) — used by tests and for dry runs.
"""

from __future__ import annotations

import importlib
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import structlog

from .compounding.hotness_store import EntityHotnessStore
from .gateway import Gateway, resolve_against_installed
from .governor import BUDGET_DEFAULTS, Governor
from .hardware import HardwareProfile, probe
from .modes.deepdive import DraftReport, run_deepdive
from .modes.quc import QUCSession
from .modes.quc import ask as quc_ask
from .output.html import render_html_document
from .paths import Paths
from .persistence import open_db
from .rag import (
    BM25Index,
    Document,
    HashEmbedder,
    HybridSearch,
    InMemoryStore,
    chunk_document,
    make_reranker,
)

_log = structlog.get_logger(__name__)


def _source_domain(source: str) -> str:
    """Extract a normalised domain key from a source URL or path (for hotness dedup)."""
    from urllib.parse import urlparse
    parsed = urlparse(source)
    return parsed.netloc or source.split("/")[0] or source


# ── backend factories ──────────────────────────────────────────────────

def _ollama_installed_tags() -> list[str]:
    try:
        from .backends.ollama import OllamaBackend
        b = OllamaBackend()
        if not b.available():
            return []
        return [m.name for m in b.list_models()]
    except Exception:
        return []


def make_embedder(*, offline: bool = False, installed: list[str] | None = None):
    """bge-m3 via Ollama (1024-dim) when available, else the HashEmbedder stub.

    Returns a 3-tuple: (embedder, name, warns).
    """
    warns: list[str] = []
    if offline:
        return HashEmbedder(dim=256), "hash-stub", warns
    installed = installed if installed is not None else _ollama_installed_tags()
    embed_tag = next((t for t in installed if t.split(":")[0] == "bge-m3"), None)
    if embed_tag is None:
        embed_tag = next((t for t in installed
                          if "embed" in t or t.split(":")[0] == "nomic-embed-text"), None)
    if embed_tag:
        try:
            from .rag.ollama_embedder import OllamaEmbedder
            dim = 1024 if "bge-m3" in embed_tag else 768
            emb = OllamaEmbedder(model=embed_tag, dim=dim)
            if emb.available():
                return emb, embed_tag, warns
        except Exception as exc:
            msg = f"embedder fallback to hash-stub: {exc!r}"
            warns.append(msg)
            _log.warning(msg)
    if not embed_tag:
        msg = "no embedding model found in Ollama; falling back to hash-stub (retrieval will be non-semantic)"
        warns.append(msg)
        _log.warning(msg)
    return HashEmbedder(dim=256), "hash-stub", warns


def make_vector_store(dim: int, *, offline: bool = False):
    """Qdrant if reachable, else the in-memory store.

    Returns a 3-tuple: (store, name, warns).
    """
    warns: list[str] = []
    if offline:
        return InMemoryStore(), "in-memory", warns
    try:
        from .rag.qdrant_store import QdrantStore
        store = QdrantStore(dim=dim, collection="lighthouse_corpus")
        if store.available():
            return store, "qdrant", warns
    except Exception:
        pass
    msg = "Qdrant not reachable; falling back to in-memory store (not persistent across restarts)"
    warns.append(msg)
    _log.warning(msg)
    return InMemoryStore(), "in-memory", warns


def make_gateway(paths: Paths, profile: HardwareProfile, *,
                 offline: bool = False, installed: list[str] | None = None) -> Gateway:
    """Gateway with capability-classes resolved to real installed tags.

    ``offline=True`` forces the mock provider (no model load). Otherwise the
    Gateway uses real Ollama dispatch and we override the catalog's
    capability-class names with the best-fitting installed tags.
    """
    gov = Governor(paths.state_db, BUDGET_DEFAULTS)
    if offline:
        return Gateway(gov, paths.audit_db, profile=profile, prefer_real_backends=False)
    installed = installed if installed is not None else _ollama_installed_tags()
    overrides = resolve_against_installed(profile, installed) if installed else {}
    return Gateway(gov, paths.audit_db, profile=profile,
                   prefer_real_backends=True, overrides=overrides)


# ── pipeline ────────────────────────────────────────────────────────────

@dataclass
class PipelineConfig:
    offline: bool = False
    mode: str = "deep-dive"        # deep-dive | quc
    max_rounds: int = 3            # TTD-DR iterates a few rounds; 3 is the floor
    top_k: int = 5
    auto_fetch_sources: bool = True    # auto-fetch from arXiv/OpenAlex when corpus is empty
    auto_fetch_max_results: int = 5    # max papers per source


@dataclass
class ResearchResult:
    draft_id: str
    question: str
    mode: str
    backends: dict[str, str]
    sections: int
    chunks_ingested: int
    report: DraftReport | None = None
    answer: str | None = None
    discipline: dict | None = None
    warnings: list[str] = field(default_factory=list)


class ResearchPipeline:
    """Assembles real-or-stub backends and runs a research job end-to-end."""

    def __init__(self, paths: Paths, *, profile: HardwareProfile | None = None,
                 config: PipelineConfig | None = None,
                 gateway: Gateway | None = None):
        self.paths = paths
        self.profile = profile or probe()
        self.config = config or PipelineConfig()
        installed = [] if self.config.offline else _ollama_installed_tags()
        self.embedder, emb_name, emb_warns = make_embedder(offline=self.config.offline,
                                                            installed=installed)
        self.store, store_name, store_warns = make_vector_store(self.embedder.dim,
                                                                offline=self.config.offline)
        # Real cross-encoder (BAAI/bge-reranker-v2-m3) when FlagEmbedding is
        # installed; otherwise a score-passthrough that preserves fusion order.
        # `available()` probes via find_spec, so this never imports torch or
        # downloads a model on its own (§Sprint 28 step 1).
        self.reranker = make_reranker(prefer_real=True)
        self.hybrid = HybridSearch(self.store, self.embedder, BM25Index(),
                                   reranker=self.reranker)
        self.gateway = gateway or make_gateway(
            paths, self.profile, offline=self.config.offline, installed=installed)
        self.backends = {
            "embedder": emb_name, "vector_store": store_name,
            "gateway": "mock" if self.config.offline else "ollama",
        }
        self._backend_warnings: list[str] = emb_warns + store_warns
        self._chunks_ingested = 0
        self._blocked_chunks = 0
        self._compaction_saved_tokens = 0
        from .governor import InjectionGate
        self._injection_gate = InjectionGate()
        self.hotness_store = EntityHotnessStore(paths.data_dir / "entity_hotness.db")
        self._tracked_entities: set[str] = set()
        # Host-courtesy gate on real LLM calls only — offline uses a free mock,
        # so throttling it is pointless (and would slow tests). The gate samples
        # power/CPU and serialises/sleeps when the host is busy or on battery.
        from .governor.scheduler_gate import SchedulerGate, SchedulerGateConfig
        self.scheduler_gate = (
            None
            if self.config.offline
            else SchedulerGate(SchedulerGateConfig.from_config_file(self.paths.config_file))
        )

    # --- ingestion ---
    def ingest_text(self, doc_id: str, text: str, *, metadata: dict | None = None) -> int:
        """Chunk + index text, screening each chunk for prompt-injection (§24.8).

        Chunks the injection gate flags are NOT added to the retrievable corpus
        — injected instructions must never reach the LLM's context silently.
        Blocked chunks are counted (surfaced in the result) so the user can see
        a source was partially withheld.

        Each chunk is enriched with a contextual preamble before indexing
        (Anthropic Contextual Retrieval, §14.3). When the gateway is live and
        not in offline mode, an LLM-generated 1-sentence context locator is
        used; otherwise the deterministic metadata-based preamble is used.
        """
        from .rag.compaction import compact, looks_like_html
        from .rag.contextual import default_preamble, llm_preamble_fn, prepend_context

        # Deterministic pre-context compaction of fetched HTML sources (§5):
        # strip tags/boilerplate/dup-lines before chunking. Plain text is left
        # byte-identical so only verbose web payloads pay (and benefit).
        meta = metadata or {}
        ct = str(meta.get("content_type", ""))
        if ct.startswith("text/html") or looks_like_html(text):
            text, cstats = compact(text, source=str(meta.get("source", "")),
                                   content_type=ct or "text/html")
            self._compaction_saved_tokens += max(
                0, cstats.orig_tokens - cstats.new_tokens)

        doc = Document(id=doc_id, text=text, metadata=meta)
        chunks = chunk_document(doc)

        # --- contextual preamble ---
        if self.gateway is not None and not self.config.offline:
            preamble_fn = llm_preamble_fn(
                self.gateway, document_text=text, gate=self.scheduler_gate
            )
        else:
            preamble_fn = default_preamble
        chunks = prepend_context(chunks, preamble_fn=preamble_fn)

        safe = []
        for c in chunks:
            verdict = self._injection_gate.score(c.text)
            if verdict.blocked:
                self._blocked_chunks += 1
                continue
            safe.append(c)
        self.hybrid.add(safe)
        self._chunks_ingested += len(safe)

        # Record entity mentions for any tracked entities present in this document (§2).
        if self._tracked_entities:
            source_key = _source_domain(meta.get("source", ""))
            text_lower = text.lower()
            for entity_id in self._tracked_entities:
                if entity_id.lower() in text_lower:
                    self.hotness_store.record_mention(entity_id, source=source_key)

        return len(safe)

    def track_entity(self, entity_id: str) -> None:
        """Register an entity to monitor for hotness across ingested documents (§2)."""
        self._tracked_entities.add(entity_id)

    def ingest_path(self, path: Path) -> int:
        text = Path(path).read_text(errors="replace")
        return self.ingest_text(Path(path).name, text,
                                metadata={"source": str(path)})

    def _auto_fetch(self, question: str) -> None:
        """Fetch from arXiv and OpenAlex when the corpus is empty.

        Each source is tried independently. Uses dynamic import so these deps
        are only loaded when actually needed. Failed fetches are logged and
        counted in backend warnings, not raised.
        """
        n = self.config.auto_fetch_max_results
        fetched = 0
        for source_name, module_path, fn_name in [
            ("arxiv",    "lighthouse_ai.sources.arxiv",    "search_arxiv"),
            ("openalex", "lighthouse_ai.sources.openalex",  "search_openalex"),
        ]:
            try:
                mod = importlib.import_module(module_path)
                fn = getattr(mod, fn_name)
                docs = fn(question, max_results=n)
                for doc in docs:
                    self.ingest_text(doc.id, doc.text, metadata=doc.metadata)
                fetched += len(docs)
                _log.info("auto_fetch.done", source=source_name, n=len(docs))
            except Exception as exc:
                _log.warning("auto_fetch.failed", source=source_name, error=repr(exc))
        if fetched == 0:
            msg = (
                "corpus was empty and auto-fetch returned 0 documents "
                f"(question: {question[:60]!r}); LLM will draw on parametric memory"
            )
            self._backend_warnings.append(msg)

    # --- run ---
    def research(self, question: str, *, job_id: str | None = None) -> ResearchResult:
        job_id = job_id or uuid.uuid4().hex[:8]
        # Auto-fetch from academic sources when corpus is empty and not in offline mode.
        # The `not offline` gate is the test isolation guarantee — all tests use offline=True.
        if (self._chunks_ingested == 0
                and not self.config.offline
                and self.config.auto_fetch_sources):
            self._auto_fetch(question)
        if self.config.mode == "quc":
            session = QUCSession(id=job_id, topic=question)
            turn = quc_ask(session, question, hybrid=self.hybrid, gateway=self.gateway)
            synthesis = turn.text
            body_html = f"<p>{_escape(synthesis)}</p>"
            source_count = len(turn.citations)
            sections = 1
            report = None
            answer = synthesis
        else:  # deep-dive
            # With a real cross-encoder, retrieve a wide pool and rerank down
            # (50 → rerank → 8). With the passthrough stub, keep the narrow
            # top_k so stub behavior is unchanged (§Sprint 28 step 1).
            real_rerank = type(self.reranker).__name__ == "FlagReranker"
            dd_top_k = 8 if real_rerank else self.config.top_k
            dd_candidates = 50 if real_rerank else None
            report = run_deepdive(question, hybrid=self.hybrid, gateway=self.gateway,
                                  max_rounds=self.config.max_rounds,
                                  top_k=dd_top_k, rerank_candidates=dd_candidates,
                                  job_id=job_id, gate=self.scheduler_gate)
            synthesis = "\n\n".join(s.body for s in report.sections)
            body_html = _report_to_html(report)
            source_count = len({c for s in report.sections for c in s.citations})
            sections = len(report.sections)
            answer = None

        # --- quality discipline gate + calibration (§12, §22) ---
        from .verification.discipline import check as discipline_check
        from .verification.discipline import downgrade_wep
        rep = discipline_check(synthesis)
        # source diversity — how many independent source domains were cited
        from .verification.discipline import check_source_diversity as _check_div
        _evidence = getattr(report, "evidence_chunks", []) if report is not None else []
        distinct_sources = _check_div(_evidence)
        # Stated confidence starts at "likely" (0.75); discipline downgrades it.
        band = downgrade_wep(0.75, rep)
        disc_summary = {
            "claims": len(rep.claims), "sourced": rep.sourced,
            "unsourced": rep.unsourced, "coverage": rep.citation_coverage,
            "passed": rep.passed, "notes": rep.notes,
            "distinct_sources": distinct_sources,
        }
        draft_id = self._persist_draft(
            question=question, title=question, body_html=body_html,
            source_count=source_count, job_id=job_id,
            wep_phrase=band.label, wep_band=band.name,
            confidence=round(0.75 * max(rep.citation_coverage, 0.1), 3))
        # record each claim as a Position so the calibration loop has data
        n_positions = self._record_positions(rep, band)

        self._audit("discipline.checked", {"draft_id": draft_id, **disc_summary,
                                           "positions_recorded": n_positions})

        # Record query hits for tracked entities that appear in the answer/synthesis (§2).
        if self._tracked_entities and synthesis:
            syn_lower = synthesis.lower()
            for entity_id in self._tracked_entities:
                if entity_id.lower() in syn_lower:
                    self.hotness_store.record_query_hit(entity_id)

        # Emit SSE event for newly hot entities
        if self._tracked_entities and hasattr(self, 'hotness_store'):
            try:
                hot = self.hotness_store.hot_entities()
                for entity_id, _score in hot:
                    if entity_id in self._tracked_entities:
                        _log.info("hotness.entity_hot", entity_id=entity_id)
            except Exception:
                pass  # non-fatal; hotness events are advisory

        return ResearchResult(draft_id=draft_id, question=question,
                              mode=self.config.mode, backends=self.backends,
                              sections=sections, chunks_ingested=self._chunks_ingested,
                              report=report, answer=answer, discipline=disc_summary,
                              warnings=self._backend_warnings)

    def _record_positions(self, report, band) -> int:
        """Record each extracted claim as a Position (claim + WEP + resolve-by)."""
        from .verification.positions import record_position
        n = 0
        for claim in report.claims:
            # only register substantive, sourced-or-not claims as positions
            try:
                record_position(self.paths.positions_db, claim=claim.text,
                                probability=0.75 if claim.is_sourced else 0.5)
                n += 1
            except Exception:
                pass
        return n

    # --- persistence ---
    def _persist_draft(self, *, question: str, title: str, body_html: str,
                       source_count: int, job_id: str,
                       wep_phrase: str | None = None,
                       wep_band: str | None = None,
                       confidence: float | None = None) -> str:
        draft_id = "d-" + uuid.uuid4().hex[:6]
        conn = open_db(self.paths.state_db)
        try:
            # record the job too, so it shows in /api/jobs and the dashboard
            conn.execute(
                "INSERT OR IGNORE INTO jobs (id, mode, status, metadata_json) "
                "VALUES (?, ?, 'review', ?)",
                (job_id, self.config.mode, _json({"topic": question, "progress": 1.0,
                                                  "eta": "staged"})))
            conn.execute(
                "INSERT INTO drafts (id, job_id, topic, title, body_html, wep_band, "
                "wep_phrase, confidence, source_count, status) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'staged')",
                (draft_id, job_id, question[:60], title, body_html, wep_band,
                 wep_phrase, confidence, source_count))
        finally:
            conn.close()
        self._audit("draft.staged", {"draft_id": draft_id, "question": question,
                                     "backends": self.backends})
        return draft_id

    def _audit(self, event_type: str, payload: dict) -> None:
        if not self.paths.audit_db.exists():
            return
        try:
            from .verification.audit_chain import append_event
            append_event(self.paths.audit_db, actor="pipeline",
                         event_type=event_type, payload=payload,
                         data_dir=self.paths.data_dir)
        except Exception:
            pass


# ── helpers ──────────────────────────────────────────────────────────────

def _escape(s: str) -> str:
    import html
    return html.escape(s or "")


def _report_to_html(report: DraftReport) -> str:
    parts = [f"<p class='meta'>{report.rounds_used} round(s) · "
             f"{len(report.sections)} sections · framing: "
             f"{report.framing.question_type.value}</p>"]
    for s in report.sections:
        parts.append(f"<h2>{_escape(s.title)}</h2>")
        parts.append(f"<p>{_escape(s.body)}</p>")
        if s.citations:
            parts.append(f"<p class='meta'>sources: {len(s.citations)}</p>")
    if report.open_questions:
        parts.append("<h2>Open questions</h2><ul>"
                     + "".join(f"<li>{_escape(q)}</li>" for q in report.open_questions)
                     + "</ul>")
    return render_html_document(title=report.question, subtitle="staged draft",
                                body_html="".join(parts))


def _json(obj: object) -> str:
    import json
    return json.dumps(obj, sort_keys=True, default=str)
