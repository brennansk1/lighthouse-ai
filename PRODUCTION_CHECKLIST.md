# Lighthouse — Production Readiness Checklist

Status snapshot: **86 Python modules · ~12,400 source lines · 625 tests (622 pass, 3 opt-in skips)**.
Legend: ✅ done & tested · 🟡 built but stubbed/needs-real-backend · 🔌 built, needs runtime wiring · ⬜ not started.

A "vertical slice" of the product works **end-to-end, locally, today**: ingest documents → frame the question → retrieve with real `bge-m3` embeddings → synthesize with a real local LLM (Ollama) → enforce citation discipline → record calibration positions → stage a draft → approve it in the dashboard → export to Logseq. Everything below tracks the gap from that slice to full production.

---

## Stage 0 — Foundations & durability

- ✅ Python package (`uv`, `pyproject.toml`, MIT, src layout)
- ✅ `lighthouse` CLI (typer + rich): init, start, stop, status, doctor, pause, resume
- ✅ Supervisor process + FastAPI control plane (127.0.0.1:8765) with `/health`
- ✅ SQLite spine with §26.1 PRAGMA discipline (WAL, busy_timeout, synchronous=NORMAL, FK on)
- ✅ Schema migrations (5 DBs: state, audit, intents, positions, hypotheses)
- ✅ Outbox + Saga compensation + Effector (idempotent, retry/backoff, dead-letter)
- ✅ Governor: hierarchical token buckets, degradation tiers, trip/reset, cost report
- 🟡 Litestream replication — config + lag reporting + `LitestreamRunner` built; **binary not installed**, replication not started
- 🔌 restic backup (`backup.py`) + integrity job (`recovery.py`) — built & tested, **not wired into supervisor/cron**
- ⬜ 24-hour soak test; cross-platform (Linux systemd) validation

## Stage 1 — Hardware adaptation, models, RAG, sandbox

- ✅ Hardware probe (platform/arch/RAM/GPU/backends/tier) + `chosen_models.yaml` writer
- ✅ Model Gateway: role routing, fingerprinting, drift detection, **real Ollama dispatch**, mock fallback
- ✅ Budget-aware model selection (§5.2) + **MoE-paging awareness** + **runtime RAM guard** (won't OOM)
- ✅ Model pull preflight (disk-safety: refuses pulls that would fill the disk)
- ✅ `lighthouse models {list,pull,info,prune,bind}` — resolves capability-classes → real installed tags
- ✅ RAG: semantic chunker, BM25, RRF fusion, hybrid search, contextual-retrieval helper
- ✅ Real embeddings via **`bge-m3` (Ollama, 1024-dim)** — verified, semantics correct
- 🟡 Vector store: `InMemoryStore` (real) + **`QdrantStore` (code-complete, Qdrant not running)** — `docker compose up` to enable
- 🟡 Reranker: `ScoreReranker` stub — real **Qwen3-Reranker-0.6b (FlagEmbedding)** not wired
- ✅ Sandbox broker + quarantine + scanners (EICAR, PDF-JS, HTML-script, zip-bomb) + redteam
- 🟡 Real sandbox: pure-Python scanners only — **bubblewrap/sandbox-exec isolation, ClamAV, YARA, qpdf, oletools** not wired
- 🟡 Document ingestion (`ingest.py`): sandbox-first HTML/PDF/text extraction — **trafilatura/pypdf optional, not installed** (regex fallback active)

## Stage 2 — Question framing + adaptive RAG

- ✅ Framing pipeline: question typing, critique, frame multiplication, decomposition, load-bearing detection
- ✅ Adaptive RAG router (vector / agentic / graph / recency / none)
- 🟡 Classifiers are rule-based — **ML question classifier (DistilBERT)** not trained
- ⬜ Question Library (golden-set framings) lookup

## Stage 3 — Deep-Dive (TTD-DR backbone)

- ✅ Skeleton → researcher fan-out → denoiser → discovery-progress termination
- ✅ ReSum-style `compact()` (structured) — 🟡 naive truncation, not the full recipe
- ⬜ Adversarial search / ACH, FActScore atomic verification, argument-graph inference
- ⬜ LangGraph runtime (currently plain-Python orchestration; no checkpoint/stream/resume)

## Stage 4 — Verification, calibration, compounding knowledge

- ✅ WEP bands, Brier scoring, Position Registry, hypothesis tracking, skills storage
- ✅ HMAC-chained audit log (append, seal, verify)
- ✅ **Quality discipline gate** (§12): claim extraction, citation coverage, two-source rule, WEP downgrade
- ✅ **Calibration loop closed** — research emits Positions; `lighthouse positions-due`
- 🔌 Reproducibility: `replay.py` (job replay + drift verify) + `provenance.py` (PROV-O) — built, **`lighthouse replay` CLI not wired**
- ⬜ Re-verification scheduler; track-record-based prior adjustment; A-MEM auto-linking / dossiers

## Stage 5 — Web dashboard (production)

- ✅ 7 pages: Home, Jobs, Drafts, Topics, Positions, Health, Settings (React + babel-standalone, served by FastAPI)
- ✅ Component library (skeletons, modals, side panes, toasts, accessible tables), hash router, **Cmd-K palette**, **error boundary**, **light/dark theme**, SSE live updates
- ✅ JSON API (~25 endpoints) + SSE event bus
- ⬜ **Browser render verification** (static checks pass: Babel compile, shared-scope no-collision, serving, symbol contract — but no visual QA yet)

## Stage 6 — TUI + remaining modes

- ✅ Textual TUI: 7 screens, themed (coastal light/dark), widgets, command palette, flat keymap, offline-graceful (34 tests)
- ✅ Mode A Monitor (RSS, live) · Mode C QUC · Mode D Digest · Mode E Debate
- 🟡 Modes simplified: Debate judge, Digest scheduling/notification, Monitor novelty/retraction-watch not deep

## Cross-cutting subsystems (built in parallel sprints)

- 🔌 Governor guards: `loop_detector`, `injection_gate` (heuristic), `egress_proxy` — built & tested, **not called from the runtime/gateway yet**
- 🔌 Notifications (`notify/`): desktop / Discord / email channels + dispatcher — built & tested, **not fired on events yet**
- ✅ Source adapters: RSS, **arXiv**, **OpenAlex** (real public APIs)
- ✅ Logseq export (filesystem markdown) — `lighthouse export <draft> --logseq <dir>`
- ⬜ Integrations: Zotero, Telegram bot, Obsidian/Notion, menu-bar app
- ⬜ Specialty adapters: PubMed, SEC EDGAR, CourtListener, USPTO, SearXNG web search
- ⬜ Cloud escalation (litellm + PII strip + cost preview)
- ⬜ Injection gate ML model (ProtectAI deBERTa); Spotlighting wired into prompt construction

---

## Pending test / verification passes (gates to "production")

- [ ] **Browser render QA** of all 7 webapp pages (manual + ideally Playwright)
- [ ] **Real-backend integration suite** run green with `LIGHTHOUSE_REAL_BACKEND=1` (Ollama + Qdrant up)
- [ ] **Wire the 🔌 modules** (governor guards, notifications, replay, restic/integrity, ingestion) into runtime + CLI, with tests
- [ ] **Coverage target** (design: ≥80% on persistence/supervisor — currently met there; raise overall)
- [ ] **Lint + type-check clean**: `ruff check` and `mypy` with no errors
- [ ] **Cross-platform**: Linux (systemd unit, bubblewrap, /var paths) validated
- [ ] **24-hour supervisor soak** (no OOM, no leak) + disaster-recovery drill (kill mid-write → restore)
- [ ] **Sandbox redteam in CI** (weekly), real ClamAV/YARA enabled
- [ ] **Security review** of the egress/injection/sandbox boundary
- [ ] **Packaging**: PyPI publish flow, Homebrew tap / signed macOS app, launchd/systemd install verified
- [ ] **Replay determinism** check (byte-exact where digests match; structural otherwise)

## Definition of done (v1.0)

A researcher can `pip install lighthouse-ai`, run `lighthouse init && lighthouse start`, point it at sources, and get **honest, cited, calibrated** research — running entirely on their own hardware — with the dashboard/TUI for control, durable storage with automatic recovery, and every claim traceable through a tamper-evident audit log.
