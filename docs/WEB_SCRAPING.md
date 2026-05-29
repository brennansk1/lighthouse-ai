# Lighthouse — Web Acquisition & Scraping Capabilities + Evaluation Strategies

> **Read-this-first.** This document is the companion to [`MODE_PROCESSES.md`](./MODE_PROCESSES.md).
> It describes **how content enters Lighthouse from the outside world** — every fetch path, the
> security chokepoints they pass through, and **how to evaluate** whether each is good enough. It is
> written to be reasoned about without the source tree; `module.py:symbol` paths are locators only. A
> companion research prompt ([`research_prompts/analyze_webscraping.md`](./research_prompts/analyze_webscraping.md))
> uses this doc to hunt for better libraries/strategies.

Lighthouse is **local-first and privacy-preserving**: it does **not** crawl the open web by default.
Acquisition is deliberately narrow and gated — a small set of vetted **source adapters**, an
**egress allowlist**, and a **sandbox broker** that every byte passes through before it is parsed.
"Scraping" here means *structured acquisition from known sources*, not general crawling.

**Status legend:** ✅ real/production-shaped · 🟡 heuristic/partial (works, better approach intended) ·
🔌 contract exists, not wired into the live path · ❌ not present (gap).

---

## 0. The acquisition pipeline (end to end)

```
 query / URL / feed
      │
      ▼
 (1) EGRESS GUARD — net.py + governor/egress_proxy.py        ✅  decide-before-fetch, allowlist, audit
      │  allow?                                  deny → EgressBlocked (no packet leaves)
      ▼
 (2) SOURCE ADAPTER — sources/{arxiv,openalex,pubmed,crossref,rss,searxng}.py   ✅ (APIs) / 🔌 (searxng)
      │  raw bytes / structured records
      ▼
 (3) SANDBOX BROKER — sandbox/broker.py + scanners.py        ✅  hash → scan → admit/quarantine/reject
      │  admitted bytes
      ▼
 (4) EXTRACT — ingest.py                                     🟡  trafilatura/docling (optional) → stdlib fallback
      │  clean text → Document
      ▼
 (5) NORMALIZE — NFC unicode, strip control/zero-width       ✅
      │
      ▼
 (6) CHUNK — rag/chunker.py                                  ✅  800-tok / 100 overlap
      │
      ▼
 (7) INJECTION SCREEN — governor/injection_gate.py           🟡  weighted-regex; flagged chunks dropped
      │  survivors
      ▼
   HybridSearch corpus (retrievable)
```

Auto-fetch (8) is a CRAG-style pre-loop that runs (1)→(7) automatically when a research job starts
with an empty corpus (see §8).

---

## 1. Egress guard — `net.py` + `governor/egress_proxy.py` ✅

The single security invariant: **decide before you fetch, never after** — a non-allowlisted host or a
`PRIVATE`-tier request is refused *before a packet leaves the machine* (a post-hoc check is worthless
once bytes are on the wire).

- **`EgressProxy`** is a *pure policy oracle*: allow/deny + audit, never opens a socket (testable).
- **`net.py`** is the only code that turns a verdict into a real `httpx` request; on deny it raises
  `EgressBlocked` before constructing the request; on allow it fetches and reports the real
  byte/status back to `egress.jsonl` (tamper-evident audit trail).
- **Default allowlist** (`DEFAULT_ALLOWED_DOMAINS`): `arxiv.org`, `openalex.org`, `api.crossref.org`,
  `pubmed.ncbi.nlm.nih.gov`, … Subdomain matching is label-boundary safe (`export.arxiv.org` ✅,
  `evilarxiv.org` ✗).
- **Privacy tiers** classify a request; `PRIVATE` is refused outright.

> 🟡 The allowlist is static and code-defined. **Eval/owner questions:** is the allowlist the right
> default set? Should adding a domain require an explicit user action with an audit entry? Is there a
> per-domain rate budget (today pacing is caller-side)?

## 2. Source adapters — `sources/*.py`

All return `rag.chunker.Document(id, text, metadata)` objects ready to ingest. **Each is API-based, not
HTML-scraping** — they parse structured responses (Atom/JSON), which is robust and ToS-friendly.

| Adapter | Endpoint | Auth | Returns | Status |
|---------|----------|------|---------|--------|
| `arxiv.py` | `export.arxiv.org/api/query` (Atom) | none | title + abstract, `grade=A`, `source=arxiv` | ✅ |
| `openalex.py` | OpenAlex REST | none | title + inverted-abstract reconstruction, `cited_by_count` | ✅ |
| `pubmed.py` | NCBI E-utilities | none (key optional) | title + abstract | ✅ |
| `crossref.py` | `api.crossref.org` | none | bibliographic metadata | ✅ |
| `rss.py` | arbitrary feed URL (via sandbox) | none | feed items (title + body) | ✅ |
| `searxng.py` | self-hosted SearXNG (`localhost:8888`) | none | federated web results, domain-filtered | 🔌 |

- **Quality signal:** adapters set `metadata["grade"]` / `source` / `published_date` so retrieval can
  filter by quality class (academic A-grade vs web).
- **Rate limiting** is **caller-paced** (e.g. arXiv's 3 s/request) — one request per `search()` call;
  there is no centralized limiter or backoff pool (tenacity retry exists in the effector, not here).

> 🟡/🔌 **SearXNG is the only general-web path** and requires the user to self-host a meta-search
> engine (Docker stack), then it federates Google/Bing/DuckDuckGo/Semantic Scholar and filters to
> quality domains. It is a seam (CRAG mid-loop fetch), not wired into the live research loop yet.
> **Eval question:** without SearXNG, coverage is limited to academic APIs + RSS — is that the right
> default surface for the target user, or is a first-party web-search adapter needed?

## 3. Sandbox broker — `sandbox/broker.py` + `scanners.py` ✅

**The single chokepoint** (§15.4): *every* externally-fetched byte is brokered **before parsing**,
because parsing untrusted HTML/PDF is itself an attack surface.

Pipeline: hash the payload → run every applicable `Scanner` → aggregate (**any reject wins; else any
quarantine wins; else admit**) → record in `quarantine.db`.

| Scanner | Catches |
|---------|---------|
| `PDFJavaScriptScanner` | `/JS`, `/JavaScript`, `/OpenAction` etc. in PDFs |
| `HTMLScriptScanner` | `<script>` / event-handler payloads in HTML |
| `ArchiveBombScanner` | zip-bomb (compression-ratio / nesting) heuristics |
| `EICARScanner` | the EICAR antivirus test signature (proves wiring) |

> 🟡 Scanners are **signature/heuristic**, in-process. The design notes future hardening:
> bubblewrap/sandbox-exec subprocess download, a **YARA** ruleset, **ClamAV** daemon socket, and a WORM
> mirror. **Eval question:** what is the broker's catch-rate vs false-quarantine-rate on a labeled
> corpus of benign + hostile PDFs/HTML/archives?

## 4. Extraction — `ingest.py` 🟡

After the broker admits bytes, `ingest.py` extracts readable text. **Tiered, graceful degradation:**
the production stack uses **`trafilatura`** (HTML→main-content) and **`docling`** (PDF/office), but both
are **optional, lazy-imported** — absent, it falls back to **stdlib-only** extraction so the core
pipeline never blocks on a heavy parser. Text is then normalized (Unicode NFC, strip zero-width /
control chars) so chunking + hashing are stable.

> 🟡 **This is the biggest *quality* lever in acquisition.** Stdlib fallback extraction is crude
> (tag-stripping); trafilatura/readability-grade extraction dramatically changes what reaches the
> corpus. Neither trafilatura nor docling is a *declared* dependency — a clean install gets the crude
> path. **Eval question:** extraction fidelity (main-content precision/recall, boilerplate removal) of
> stdlib vs trafilatura vs readability-lxml vs newspaper3k vs docling, measured against a hand-labeled
> set of real pages/PDFs. ❌ **No JS-rendered-page support** (no Playwright/Selenium) — SPA content is
> invisible.

## 5. Injection screening — `governor/injection_gate.py` 🟡

Every extracted chunk is **hostile-until-proven-otherwise**. The `InjectionGate` scores each chunk with
a weighted-regex classifier (instruction-override, system-prompt-probe, role-assertion, exfiltration
lure, delimiter-breakout, …); **chunks scoring ≥0.5 are dropped from the retrievable corpus** and
counted. Companion **Spotlighting** (delimiting / datamarking / encoding; *Hines et al.*) can wrap
untrusted content so the model is told never to obey it; `normalize_unicode` (NFKC) defeats homoglyph
evasion before scoring. (Full signature table in `MODE_PROCESSES.md` §0.3.)

> 🟡 Heuristic by design (offline, zero-download). Intended on-top layer: the **ProtectAI deBERTa**
> prompt-injection classifier — not wired; the call site is isolated for a swap. **Eval question:**
> precision/recall of the gate on an indirect-prompt-injection benchmark (e.g. a labeled set of
> poisoned web pages).

## 6. Chunking + corpus

`rag/chunker.py` → 800-token chunks, 100-token overlap, sentence/paragraph boundaries, protected code
fences, content-addressed ids; metadata (source, grade, published_date) travels with each chunk so
retrieval can filter. Survivors enter `HybridSearch` (BM25 + dense ANN + RRF + reranker — see
`MODE_PROCESSES.md` §0.4). (✅, boundaries are regex/whitespace 🟡.)

## 7. Where each research mode gets its corpus

- **Watch** pulls via `rss.py` through the broker on a schedule (the only *continuous* acquisition).
- **Investigate / Ask / Survey / Reconstruct** read the **ingested corpus**; if empty at job start,
  **Investigate/Ask auto-fetch** (§8). Survey/Reconstruct currently expect documents to be attached.
- **Decide / Adjudicate** are corpus-optional (reasoning over provided options/claims).

## 8. Auto-fetch (CRAG pre-loop) — `pipeline.py:_auto_fetch` ✅ (academic only)

When `auto_fetch_sources=True` and the corpus is empty at research start, the pipeline fetches the top
`auto_fetch_max_results` (default 5) from **arXiv + OpenAlex**, ingests them through (1)→(7), then
proceeds. (Corrective-RAG style: don't reason on an empty corpus.)

> ❌ **Auto-fetch is NOT wired into the dispatcher path** (the job runner) yet — only the
> `ResearchPipeline` direct path. This is the #1 functional gap for a new user (see
> `MODE_PROCESSES.md` cross-cutting #4). Mid-loop CRAG re-fetch (fetch more when a sub-question is
> unanswered) is a SearXNG seam, not wired.

---

## Evaluation strategies (how to know each stage is good enough)

Acquisition quality compounds downstream — a bad extraction or a missed hostile payload poisons every
artifact. Evaluate per stage; most have an existing or easily-built harness.

| # | Stage | What to measure | Method / harness |
|---|-------|-----------------|------------------|
| E1 | **Extraction fidelity** (§4) | main-content precision/recall, boilerplate removal, table/figure retention | Hand-label N real pages/PDFs; diff each extractor's output vs gold; score ROUGE/F1 on main text. Compare stdlib vs trafilatura vs readability-lxml vs newspaper3k vs docling. |
| E2 | **Source coverage / recall** (§2) | for a set of questions with known key papers, fraction surfaced by auto-fetch | Curate question→known-sources pairs; run auto-fetch; measure recall@k per source adapter. |
| E3 | **Retrieval quality** (§6) | precision@5 / recall@5 / MRR over a golden set | **Exists:** `eval/` golden-set harness (currently P@5≈0.17, R@5≈0.83, MRR≈0.83 — recall strong, precision is the reranker's job). |
| E4 | **Injection catch-rate** (§5) | precision/recall on indirect-prompt-injection | Labeled corpus of poisoned vs benign chunks; ROC of `InjectionGate.score`; compare vs ProtectAI deBERTa. |
| E5 | **Sandbox catch-rate** (§3) | hostile-payload detection vs false-quarantine | Labeled benign+hostile PDFs/HTML/zips; confusion matrix per scanner. |
| E6 | **Egress correctness** (§1) | zero packets to non-allowlisted hosts; every fetch audited | Property test: assert no socket opens on deny; reconcile `egress.jsonl` against allowlist. |
| E7 | **Dedup effectiveness** (Watch) | duplicate-suppression precision/recall | Feed known dup/near-dup feed items; measure suppressed vs leaked at the 0.97 cosine threshold. |
| E8 | **Source-quality grading** | does `grade`/quality-class correlate with downstream citation usefulness? | Track which graded sources end up cited in accepted artifacts. |
| E9 | **Politeness / robustness** | rate-limit compliance, retry/backoff, robots.txt | ❌ none today — needs a limiter + `robots.txt` check before this is even measurable. |
| E10 | **End-to-end groundedness** | do auto-fetched corpora produce higher citation/entailment coverage? | Run the research benchmark (`eval/research_benchmark.py`) with vs without auto-fetch. |

**Recommended baseline order:** E3 (golden-set retrieval — exists) → E1 (extraction — biggest quality
lever) → E10 (does better acquisition move artifact quality?) → E4/E5 (security catch-rates) → E2/E7.

---

## Known gaps (acquisition)

- ❌ **No general web crawler / no `robots.txt` compliance / no rate-limiter pool** — by design
  (local-first, narrow surface), but it caps coverage.
- ❌ **No JS-rendered page support** (no headless browser) — SPA/dynamic content is invisible.
- 🟡 **trafilatura/docling are optional, not default deps** — a clean install gets crude extraction.
- 🔌 **SearXNG (general web) is a seam**, requires self-hosting, not wired into the loop.
- ❌ **Auto-fetch not wired into the dispatcher** (only the direct pipeline path).
- 🟡 **No first-party web-search adapter** (Brave/Tavily/Exa/SerpAPI-style) — academic APIs + RSS only.

---

## Appendix: dependencies & provenance

**In-tree, no external dep:** `net.py` (egress wrapper over httpx), `governor/egress_proxy.py` (policy
oracle + `egress.jsonl`), `sandbox/{broker,scanners,quarantine}.py`, `governor/injection_gate.py`,
`sources/*.py` (httpx + stdlib XML/JSON parsing), `ingest.py` (stdlib fallback).

**Declared runtime deps used here:** `httpx` (all fetching), `pyyaml` (config), stdlib
`xml.etree.ElementTree` (Atom/RSS), `unicodedata` (normalization).

**Optional / not-declared (lazy-imported, graceful fallback):** `trafilatura` (HTML main-content),
`docling` (PDF/office) — extraction tier; install to upgrade §4.

**External processes (opt-in):** **SearXNG** (self-hosted meta-search, Docker stack); **Ollama**/
**Qdrant** are downstream of acquisition (embedding/retrieval), not fetchers.

**Algorithms / sources cited:** Corrective-RAG (CRAG) — the empty-corpus auto-fetch and mid-loop
re-fetch seam; **Spotlighting** (Hines et al.) — untrusted-content wrapping; **EICAR** — AV test
signature; allowlist + decide-before-fetch — Lighthouse's own egress design (§15).

**Candidate libraries to evaluate (not yet integrated) — see the research prompt:** `trafilatura`,
`readability-lxml`, `newspaper3k`, `docling`, `playwright` (JS rendering), `tavily-python` / `exa-py` /
Brave Search API (first-party web search), `courlan` + `robotexclusionrulesparser` (politeness),
`yara-python` / ClamAV (sandbox hardening), ProtectAI `deberta-v3-base-prompt-injection` (injection).
