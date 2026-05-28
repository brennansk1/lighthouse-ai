# Lighthouse — Production Readiness Checklist

Status snapshot: **87 Python modules · ~12,800 source lines · 817 tests (814 pass, 3 opt-in skips)**.
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
- ✅ restic backup + integrity job — wired: `lighthouse backup`, `lighthouse integrity` (§26.3/§26.5). 🟡 not yet on a cron/supervisor schedule.
- ⬜ 24-hour soak test; cross-platform (Linux systemd) validation

## Stage 1 — Hardware adaptation, models, RAG, sandbox

- ✅ Hardware probe (platform/arch/RAM/GPU/backends/tier) + `chosen_models.yaml` writer
- ✅ Model Gateway: role routing, fingerprinting, drift detection, **real Ollama dispatch**, mock fallback
- ✅ Budget-aware model selection (§5.2) + **MoE-paging awareness** + **runtime RAM guard** (won't OOM)
- ✅ Model pull preflight (disk-safety: refuses pulls that would fill the disk)
- ✅ `lighthouse models {list,pull,info,prune,bind}` — resolves capability-classes → real installed tags
- ✅ RAG: semantic chunker, BM25, RRF fusion, hybrid search, contextual-retrieval helper
- ✅ **Contextual Retrieval**: LLM-generated 1-sentence preamble prepended to each chunk at ingest (Anthropic pattern)
- ✅ Real embeddings via **`bge-m3` (Ollama, 1024-dim)** — verified, semantics correct
- ✅ **Reranker always-on** (`prefer_real=True`): **FlagReranker (`bge-reranker-v2-m3`)** active when FlagEmbedding installed; `ScoreReranker` fallback otherwise
- 🟡 Vector store: `InMemoryStore` (real) + **`QdrantStore` (code-complete, Qdrant not running)** — `docker compose up` to enable
- ✅ Sandbox broker + quarantine + scanners (EICAR, PDF-JS, HTML-script, zip-bomb) + redteam
- 🟡 Real sandbox: pure-Python scanners only — **bubblewrap/sandbox-exec isolation, ClamAV, YARA, qpdf, oletools** not wired
- ✅ Document ingestion (`ingest.py`) wired into `research --url` (fetch → sandbox → extract → corpus). 🟡 trafilatura/pypdf optional (regex/text fallback active until installed).

## Stage 2 — Question framing + adaptive RAG

- ✅ Framing pipeline: question typing, critique, frame multiplication, decomposition, load-bearing detection — **LLM-powered** (planner role, keyword baseline fallback)
- ✅ Adaptive RAG router (vector / agentic / graph / recency / none)
- 🟡 Classifiers are rule-based — **ML question classifier (DistilBERT)** not trained
- ⬜ Question Library (golden-set framings) lookup

## Stage 3 — Deep-Dive (TTD-DR backbone)

- ✅ Skeleton → researcher fan-out → denoiser → discovery-progress termination
- ✅ **IterResearch shared scratchpad**: `CompactedContext` injected into each round's researcher prompts
- ✅ **Real denoiser**: synthesizer LLM resolves contradictions, emits `[CONTRADICTION]` / `[GAP]` markers
- ✅ **Debate auto-wiring**: fires `run_debate()` on load-bearing `[CONTRADICTION]` sections; adds crux as new sub-question
- ✅ **Entailment gate** (`verification/entailment.py`): lazy MiniCheck/HHEM — 🔌 `minicheck` PyPI package absent; gate degrades gracefully to 1.0 (no-penalty) without it
- ✅ **Auto web retrieval**: fetches arXiv + OpenAlex when corpus is empty at research start (CRAG-style pre-loop) — 🔌 SearXNG mid-loop fetch seam exists, SearXNG integration not yet wired
- ✅ ReSum-style `compact()` (structured) — 🟡 naive truncation, not the full recipe
- ⬜ Adversarial search / ACH, FActScore atomic verification, argument-graph inference
- ⬜ LangGraph runtime (currently plain-Python orchestration; no checkpoint/stream/resume)

## Stage 4 — Verification, calibration, compounding knowledge

- ✅ WEP bands (ICD-203), Brier scoring, Position Registry, hypothesis tracking, skills storage
- ✅ HMAC-chained audit log (append, seal, verify)
- ✅ **Quality discipline gate** (§12): claim extraction, citation coverage, two-source rule, WEP downgrade
- ✅ **Calibration loop closed** — research emits Positions; `lighthouse positions-due`; 90-day positions with auto-resolve
- ✅ **Auto-resolver** (`verification/resolver.py`): Halawi et al. style — machine-resolvable positions auto-resolved at deadline; `lighthouse resolver run` CLI
- ✅ **Citation source diversity**: distinct source domains counted per report
- ✅ **Backend fallback warnings**: silent fallbacks logged and surfaced to user
- ✅ Reproducibility: `lighthouse replay <job_id>` wired (reconstructs the model-call trace + drift verify against installed digests, §27.8); `provenance.py` PROV-O emitter built. 🔌 PROV-O sidecar not yet emitted per research run.
- ⬜ Re-verification scheduler; track-record-based prior adjustment; A-MEM auto-linking / dossiers

## Stage 5 — Web dashboard (production)

- ✅ 7 pages: Home, Jobs, Drafts, Topics, Positions, Health, Settings (React + babel-standalone, served by FastAPI)
- ✅ Component library (skeletons, modals, side panes, toasts, accessible tables), hash router, **Cmd-K palette**, **error boundary**, **light/dark theme**, SSE live updates
- ✅ **Editable research plan**: `PlanPreview` shown before each run, user can edit before confirming
- ✅ **Elicit-style extraction table** in draft reader
- ✅ JSON API (~25 endpoints) + SSE event bus
- ⬜ **Browser render verification** (static checks pass: Babel compile, shared-scope no-collision, serving, symbol contract — but no visual QA yet)

## Stage 6 — TUI + remaining modes

- ✅ Textual TUI: 7 screens, themed (coastal light/dark), widgets, command palette, flat keymap, offline-graceful (34 tests)
- ✅ Mode A Monitor (RSS, live) · Mode C QUC · Mode D Digest · Mode E Debate
- 🟡 Modes simplified: Debate judge, Digest scheduling/notification, Monitor novelty/retraction-watch not deep

## Cross-cutting subsystems (built in parallel sprints)

- ✅ Governor guards wired: **loop detector** in the Gateway (raises `LoopTripped` on runaway), **injection gate** screens every ingested chunk (injected content never enters the corpus). 🔌 `egress_proxy` built+tested but not yet on the fetch path.
- ✅ Notifications (`notify/`): desktop / Discord / email + dispatcher; fired on `draft_ready` from the research command. 🔌 not yet fired on `budget_trip` / `monitor_alert` from the Governor/modes.
- ✅ Source adapters: RSS, **arXiv**, **OpenAlex**, **PubMed**, **Crossref** (all return `Document` objects)
- ✅ Logseq export (filesystem markdown) — `lighthouse export <draft> --logseq <dir>`
- ✅ **`lighthouse audit-egress` CLI command**
- ⬜ Integrations: Zotero, Telegram bot, Obsidian/Notion, menu-bar app (adapters exist, not wired into main flow)
- ⬜ Specialty adapters: SEC EDGAR, CourtListener, USPTO, SearXNG web search
- ⬜ Cloud escalation (litellm + PII strip + cost preview)
- ⬜ Injection gate ML model (ProtectAI deBERTa); Spotlighting wired into prompt construction

---

## Pending test / verification passes (gates to "production")

- [ ] **Browser render QA** of all 7 webapp pages (manual + ideally Playwright)
- [ ] **Real-backend integration suite** run green with `LIGHTHOUSE_REAL_BACKEND=1` (Ollama + Qdrant up)
- [x] ~~Wire replay, restic/integrity, ingestion, notifications into the CLI~~ (done — `replay`/`backup`/`integrity`/`research --url`/draft_ready notify)
- [x] ~~Wire the Governor guards (loop detection, injection gate) into the gateway + research loop~~ (done — egress proxy built+tested, not yet on fetch path)
- [ ] Wire egress proxy into the fetch path; emit PROV-O sidecar per run; schedule backup+integrity on a cadence
- [ ] Fire notifications on `budget_trip` / `monitor_alert`
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

---

# Acceptance criteria & test standards

This section is the bar each feature must clear before we call it production-ready.
Every row lists the **tests required**, the **standard (pass threshold)**, and the
current **status**: ✅ met · 🟡 partial / not yet measured · ⬜ not tested.
Thresholds come from the design doc's per-sprint testing requirements where stated;
otherwise they are set here.

Test-type legend: **U** unit · **I** integration (real deps, skip-if-absent) ·
**E** end-to-end · **P** property-based (Hypothesis) · **Chaos** fault-injection ·
**Perf** latency/throughput · **Sec** adversarial.

## 1. Persistence & durability

| Feature | Tests required | Standard to pass | Status |
|---|---|---|---|
| SQLite PRAGMA discipline | U: every `.db` opens with all §26.1 PRAGMAs; readback asserts | 100% of opens pass PRAGMA assertions; WAL on every on-disk db | ✅ |
| Migrations | U: forward apply, idempotent re-run, CHECK constraints reject bad rows | re-run is a no-op; bad inserts raise | ✅ |
| Outbox / saga | U+P+Chaos: idempotency by key; kill effector mid-drain | **zero** duplicate or orphaned writes after recovery | ✅ (chaos at 50 intents; ⬜ scale to 1000) |
| Litestream replication | I: start replicate, write, restore to fresh path, integrity ok | replica lag **<10s** sustained; restore integrity `ok` | 🟡 binary not installed in CI |
| restic backup | I: init → backup → check → snapshots | `restic check` clean; restore RTO **<1 min** for state.db | 🟡 wired, not yet I-tested with real restic |
| Disaster recovery | E: kill supervisor mid-write → restore → schema intact | in-flight jobs marked `interrupted`; no corruption | 🟡 sqlite-backup variant ✅; full litestream drill ⬜ |
| 24h soak | Perf: supervisor runs 24h under load | no OOM, no fd/conn leak, RSS stable | ⬜ |

## 2. Hardware adaptation & model gateway

| Feature | Tests required | Standard | Status |
|---|---|---|---|
| Hardware probe | U: tier classification across RAM/VRAM/GPU matrix | correct tier for every floor/ceiling case | ✅ |
| Budget-aware selection | U: every tier floor fits its model under §5.2 math | no dense model over-commits its tier floor; MoE may page | ✅ |
| Runtime RAM guard | U: refuse load when `need + margin > available`; I: real low-RAM | never loads a model that would swap; falls back to mock | ✅ U; 🟡 real low-RAM observed manually |
| Pull preflight | U: refuse pull that breaches disk margin; CLI never starts download | leaves **≥5 GB** free; oversized pull → exit 1, no `/api/pull` call | ✅ |
| Fingerprint + drift | U: digest capture; drift refuses byte-replay without `--allow-drift` | mismatch flagged; replay refused unless override | ✅ |
| Real LLM round-trip | I (`LIGHTHOUSE_REAL_BACKEND=1`): one real Ollama completion | non-mock text; tokens > 0; deterministic at temp 0 (± kernel) | 🟡 verified manually, not in CI |

## 3. RAG / retrieval

| Feature | Tests required | Standard | Status |
|---|---|---|---|
| Chunker | U: boundary, overlap, code-block preservation, metadata propagation | 100-token overlap present; code blocks intact | ✅ |
| Hybrid search (dense+BM25+RRF) | I: ingest 10 papers, known queries | **top-5 precision ≥ 80%** (design §14) | ⬜ needs a golden set |
| Contextual retrieval | I: recall vs no-context baseline | **≥10% recall lift** (Anthropic pattern) | ⬜ |
| Reranker | I: MRR vs hybrid baseline | **≥5% MRR lift** over hybrid | ⬜ (stub reranker only) |
| Faithfulness (ragas) | E: 20-pair golden set | **faithfulness ≥ 0.7** | ⬜ |
| Retrieval latency | Perf: 1000-chunk corpus | ingest <60s on T2; query **p95 <300ms** | ⬜ |
| Real embeddings (bge-m3) | I: 1024-dim, similar>dissimilar cosine | dim correct; semantic ordering holds | ✅ verified |

## 4. Sandbox & ingestion security

| Feature | Tests required | Standard | Status |
|---|---|---|---|
| Scanner verdicts | U: EICAR, zip-bomb, JS-PDF, script-HTML, SVG-script | each correctly reject/quarantine | ✅ |
| Redteam suite | Sec (weekly CI): all known-hostile artifacts | **100% blocked**, 0 escapes | ✅ mini suite; ⬜ ClamAV/YARA real corpus |
| Injection gate | U+Sec: known injection prompts; ingest screening | injected chunks **never** enter corpus; FP rate measured | ✅ U + wired at ingest; 🟡 FP rate on real text ⬜ |
| Quarantine quota/eviction | I: fill to quota, evict, WORM preserved | eviction triggers; WORM-tagged files survive | 🟡 manifest ✅; quota/eviction ⬜ |
| Real isolation | I: bubblewrap/sandbox-exec download of hostile file | escape attempts contained at OS level | ⬜ (pure-Python scanners only) |

## 5. Honesty: discipline, calibration, audit

| Feature | Tests required | Standard | Status |
|---|---|---|---|
| Claim extraction + citation gate | U: coverage, two-source rule, WEP downgrade | coverage floor enforced; unsourced → lower band | ✅ |
| Calibration loop | U+E: research emits Positions; resolve → Brier | every run records positions; Brier computed on resolve | ✅ |
| Brier / reliability | I: scored over a resolved golden set | reliability diagram tracks diagonal; calibration error reported | 🟡 plumbing ✅; real track-record ⬜ |
| HMAC audit chain | U+Sec: append/verify; tamper any row → chain breaks | tamper detected at exact seq; wrong key fails all | ✅ |
| Provenance / replay | U+E: PROV-O round-trip; `replay` reconstructs trace + drift | trace order exact; drift flagged; refuse byte-replay on drift | ✅ U/E; 🟡 PROV-O sidecar per run ⬜ |

## 6. Governor & cost control

| Feature | Tests required | Standard | Status |
|---|---|---|---|
| Token buckets | U+P+Concurrency: hierarchical debit; 10-thread race | sum never negative; math exact under concurrency | ✅ |
| Degradation tiers | U: thresholds 50/70/85/95/100% | correct tier at each boundary | ✅ |
| Loop detection | U: per-job/per-node caps, recursion, repeat; gateway raises | trips at cap; `LoopTripped` from gateway on runaway | ✅ U + gateway-wired |
| Egress proxy | U: allowlist + privacy tiers + log | PRIVATE blocked; non-allowlisted blocked; all conns logged | 🟡 built+U; ⬜ not wired into fetch path |
| Kill switch | I: `kill` drains then stops; Telegram-confirm | graceful drain, no cross-store corruption | 🟡 API kill ✅; Telegram-confirm ⬜ |

## 7. Surfaces (web + TUI)

| Feature | Tests required | Standard | Status |
|---|---|---|---|
| API endpoints | U: every `/api/*` returns expected shape | 200 + schema for all ~25 endpoints | ✅ |
| SSE event bus | U: publish/subscribe, drop on full queue | events delivered; no unbounded growth | ✅ |
| Webapp JS integrity | U: each file compiles; combined-scope no redeclaration; symbol contract | Babel clean; no global collision; consumed symbols exported | ✅ |
| Webapp render | E (Playwright): 7 pages render, no console errors, a11y audit | 0 console errors; axe a11y pass; keyboard reachable | ⬜ **no browser QA yet** |
| TUI screens | U (Textual pilot): boot, 7-page nav, per-screen data, modals, offline | screens render seeded data; offline degrades, no crash | ✅ (34 tests) |
| Responsive/theme | E: light/dark toggle, narrow viewport | no layout break; theme persists | ⬜ |

## 8. Research modes (end-to-end)

| Feature | Tests required | Standard | Status |
|---|---|---|---|
| QUC | E offline + I real | cited, grounded answer; positions recorded | ✅ offline+real verified |
| Deep-Dive | E offline + I real | multi-section, sourced, terminates on progress plateau | ✅ offline+real verified |
| Monitor | I: live RSS → classify → HTML | dedupe works; alerts vs digest split; report written | ✅ |
| Debate / Digest | U + I | judge summary; scheduled briefing dispatched | 🟡 stubs; depth ⬜ |
| Specialty sources | I (respx + live): arXiv, OpenAlex, +PubMed/EDGAR | parse correctly; rate-limited; graded | 🟡 arXiv/OpenAlex ✅; others ⬜ |

## 9. Engineering quality gates (whole repo)

| Gate | How | Standard | Status |
|---|---|---|---|
| Test suite | `uv run pytest` | **100% pass**, 0 unexpected skips | ✅ 814 pass, 3 opt-in skips |
| Coverage | `pytest --cov` | **≥80%** overall; ≥90% on persistence/governor/verification | 🟡 ~83% measured once; not gated |
| Lint | `ruff check` | 0 errors | ✅ ruff clean |
| Types | `mypy src` | 0 errors on public modules | ⬜ not gated |
| CI | GitHub Actions | suite + lint + types green on every push (macOS + Linux) | ⬜ no CI yet |
| Cross-platform | run suite on Linux | green; systemd unit + /var paths work | ⬜ |
| Security review | manual + Sec tests | egress/injection/sandbox boundary reviewed; no high findings | ⬜ |
| Packaging | build + install | `pip install` works; entry points run; launchd/systemd install verified | 🟡 builds; install not verified |

## Top of the queue (highest-leverage gaps)

1. **Golden-set retrieval eval** (precision / MRR / faithfulness numbers) — the core quality claim is currently unmeasured.
2. **Browser render QA + Playwright** for the 7 webapp pages — only static checks done.
3. **CI** (Actions: pytest + ruff + mypy, macOS + Linux) — gates everything else.
4. **Wire egress proxy into the fetch path**; Telegram-confirmed kill switch.
5. **Real reranker + real isolation (bubblewrap / ClamAV)** to satisfy the §3 / §4 standards.
