# Lighthouse

> Local-first, hardware-adaptive 24/7 multi-agent research system. Runs on
> your machine, on your files, with reproducible auditable outputs.

Lighthouse is the tool you reach for instead of Gemini Deep Research,
OpenAI Deep Research, Claude Research, Perplexity Pro, Elicit, or
Consensus — while keeping every byte on your hardware.

The full design specification is in `lighthouse_design.md`. The
surface design is in `webapp_tui_design.md`. A frank, line-by-line view of
what's done vs. pending is in **[`PRODUCTION_CHECKLIST.md`](./PRODUCTION_CHECKLIST.md)**.

**Status:** ~12,400 source lines, 86 modules, **622 passing tests**. A full
research slice runs end-to-end, locally, today.

## What works today

- **Real local research, end-to-end:** ingest docs → frame the question →
  retrieve with real **`bge-m3`** embeddings → synthesize with a real local
  LLM via **Ollama** → enforce a **citation-discipline gate** → record
  **calibration positions** → stage a draft → approve it → export to Logseq.
- **Honest by construction:** every claim carries a WEP confidence band,
  unsourced claims are downgraded, predictions are tracked and Brier-scored,
  and an HMAC-chained audit log makes the whole run tamper-evident.
- **Hardware-adaptive:** probes RAM/GPU → tier; budget-aware model selection
  with **MoE SSD-paging awareness** and a **runtime RAM guard** so it never
  swaps your machine to death; disk-safe model pulls.
- **Two surfaces:** a React **web dashboard** (7 pages, Cmd-K palette, live
  SSE, light/dark) and a **Textual TUI** (7 screens) — same JSON API.
- **Durable & governed:** SQLite-WAL spine, outbox+saga consistency, a
  Governor with token-budget circuit-breakers, sandboxed ingestion.
- **Real sources:** RSS, arXiv, OpenAlex adapters.

See `PRODUCTION_CHECKLIST.md` for what's stubbed (real reranker, LangGraph,
Qdrant/Litestream runtime, cloud escalation, Zotero/Telegram, …).

## Quick start

```bash
# install uv: https://docs.astral.sh/uv/
uv sync
uv run lighthouse init --no-install-service   # set up ~/.lighthouse
uv run lighthouse doctor                      # readiness check

# run research offline (stub backends, no model load — instant):
uv run lighthouse research "What mitigates decoherence?" --doc notes.txt --offline

# or for real (needs Ollama + a pulled model; loads into RAM):
uv run lighthouse models bind                 # map roles → installed Ollama tags
uv run lighthouse research "..." --arxiv "quantum error correction"
```

Launch the dashboard / TUI:

```bash
uv run lighthouse-supervisor      # then open http://127.0.0.1:8765/
uv run lighthouse tui             # terminal dashboard
```

Other commands: `lighthouse status`, `cost report`, `positions-due`,
`models {list,pull,info}`, `quarantine list`, `audit verify`,
`sandbox redteam`, `export <draft> --logseq <dir>`, `pause`/`resume`.

## Running the test suite

```bash
uv run pytest -q          # 622 pass; 3 skip (opt-in real-backend / litestream binary)
```

Real-backend integration tests are opt-in (they load a model into RAM):

```bash
LIGHTHOUSE_REAL_BACKEND=1 uv run pytest tests/test_backends_ollama.py
```

## Architecture

```
src/lighthouse_ai/
├── cli.py                 typer CLI (init, doctor, status, pause/resume, cost, budget)
├── supervisor.py          launchd/systemd-managed long-lived process
├── controlplane.py        FastAPI app on 127.0.0.1:8765
├── persistence.py         §26.1 PRAGMA discipline + sqlite helpers
├── schema.py              per-DB migrations
├── paths.py               filesystem layout (~/.lighthouse/*)
├── hardware.py            §5.1 probe + tier classification
├── litestream.py          replica config + lag reporting
├── gateway.py             §6 model gateway + fingerprinting
├── intents.py             §25 outbox API
├── effector.py            durable intent drainer
├── sagas.py               §25.4 compensator registry
├── governor/              §24 token buckets + degradation
├── rag/                   §14 chunker / embedder / store / BM25 / fusion / hybrid
├── sandbox/               §15 scanners + quarantine + broker
├── modes/                 monitor, deepdive, quc, digest, debate
├── framing/               §10 framing pipeline + §14.5 adaptive router
├── verification/          §22-23 WEP, Brier, positions, hypotheses, skills, audit chain
├── output/                §20 Tufte-CSS HTML renderer
├── web/                   static design bundle + /api/dashboard
├── catalog/               5-tier model catalog
└── templates/             config.toml / launchd plist / systemd unit / litestream.yml
```

## Production swap-in points

The Sprint 5 implementations are runnable end-to-end but use stub
backends so the system has no external dependencies. Production swaps:

| Interface (Protocol)              | Stub                  | Production                  |
| --------------------------------- | --------------------- | --------------------------- |
| `rag.embedder.Embedder`           | `HashEmbedder`        | BGE-M3 via FlagEmbedding    |
| `rag.store.VectorStore`           | `InMemoryStore`       | Qdrant (HNSW + int8)        |
| `rag.rerank.Reranker`             | `ScoreReranker`       | Qwen3-Reranker-0.6B         |
| `gateway` model dispatch          | `MockProvider`        | Ollama / MLX / vLLM         |
| `sandbox.scanners`                | Pure-Python           | qpdf, oletools, ClamAV, YARA |
| `governor.langfuse_stub`          | No-op                 | Self-hosted Langfuse         |

## License

MIT. See [LICENSE](./LICENSE).
