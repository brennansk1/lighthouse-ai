# Research prompt — optimize Lighthouse's web acquisition / scraping stack

> Paste this to a research-capable Claude with **web search + GitHub/PyPI search (tool search)** — or
> the deep-research skill. Attach or point it at [`docs/WEB_SCRAPING.md`](../WEB_SCRAPING.md). Goal: for
> each acquisition stage, find **better strategies, Python libraries, or GitHub repos** to integrate,
> and design the **evaluation** that proves the swap is worth it.

---

You are a research engineer auditing the **web-acquisition / scraping stack** of **Lighthouse**, a
local-first, privacy-preserving research instrument. It deliberately does **not** crawl the open web;
acquisition is a narrow, gated pipeline. Your job: find where an external strategy/library/repo beats
the current approach, **and** specify how to measure the improvement. Every recommendation must be
specific, sourced (URL, ⭐, license, last commit), and fit-checked.

## Use tool search aggressively
For each stage below, actively search **PyPI** and **GitHub** for current libraries, and the web /
arXiv for current best-practice extraction & anti-bot/politeness techniques. Don't rely on memory —
library quality and maintenance change fast; verify last-commit, release cadence, star count, license,
and whether wheels exist for Python ≥3.11 (no surprise system-lib/CUDA requirements).

## Read first
`docs/WEB_SCRAPING.md` documents the pipeline end-to-end with status flags:
(1) **egress guard** (allowlist, decide-before-fetch, `egress.jsonl`) → (2) **source adapters**
(arXiv/OpenAlex/PubMed/Crossref/RSS APIs + SearXNG seam) → (3) **sandbox broker** (hash → scanners →
admit/quarantine/reject) → (4) **extraction** (trafilatura/docling optional, stdlib fallback) →
(5) normalize → (6) chunk → (7) **injection screen** → (8) **CRAG auto-fetch**. It also lists the
**Evaluation strategies (E1–E10)** and the **Known gaps**. Start from the gaps and the 🟡/🔌/❌ flags.

## Hard constraints any recommendation MUST satisfy
1. **Local-first / privacy-preserving.** No mandatory cloud or paid API for the default path; cloud is
   opt-in. Anything that phones home is suspect.
2. **Offline-deterministic + lazy.** The core pipeline must run with none of the optional parsers
   installed (stdlib fallback). New parsers/fetchers must be **lazy-imported, optional**, with graceful
   degradation. Tests stay offline (mock httpx with `respx`); real-network tests gate behind
   `LIGHTHOUSE_REAL_BACKEND=1`.
3. **Security-first.** Every fetched byte still passes the **sandbox broker BEFORE parsing**, and the
   **egress guard decides BEFORE any socket opens**. A library that fetches+parses in one opaque call
   (bypassing the broker) is a poor fit unless it can be split (fetch bytes → broker → parse).
4. **Resource-safe**, **Python ≥3.11**, **MIT/BSD/Apache preferred** (flag GPL/AGPL), actively
   maintained.
5. **Map to a seam:** name the exact swap-in call site (`net.py`, `ingest.py`, `sources/*.py`,
   `sandbox/scanners.py`, `governor/injection_gate.py`, `pipeline.py:_auto_fetch`).

## Research targets (by stage) — answer each with concrete options
- **Extraction (§4, biggest quality lever):** compare **trafilatura vs readability-lxml vs newspaper3k
  vs docling vs resiliparse/selectolax** for HTML main-content + PDF/office. Which gives the best
  main-content precision/recall with the lightest, best-maintained footprint? Recommend a default +
  fallback chain.
- **JS-rendered pages (❌ gap):** is a headless option (Playwright) worth it for a local tool, or does it
  violate resource-safety? If yes, how to gate it (opt-in, bounded, sandboxed)?
- **First-party web search (🔌/❌ gap):** evaluate web-search backends beyond self-hosted SearXNG —
  **Tavily, Exa, Brave Search API, SerpAPI, DuckDuckGo (ddgs)** — on local-first fit (self-hostable /
  free tier / privacy), result quality, and license. Which (if any) belongs as an optional adapter?
- **Politeness/robustness (❌ gap):** `robots.txt` compliance + rate-limiting + retry/backoff —
  candidates like `urllib.robotparser`, `robotexclusionrulesparser`, `courlan`, `tenacity` (already a
  dep), `pyrate-limiter`. Propose a minimal politeness layer for `net.py`.
- **Sandbox hardening (§3):** `yara-python`, ClamAV (`clamd`), `pdfid`/`peepdf` for PDF, bubblewrap/
  sandbox-exec subprocess isolation — which raise catch-rate without heavy ops burden?
- **Injection screen (§5):** ProtectAI `deberta-v3-base-prompt-injection` and alternatives — accuracy
  vs the current regex gate, and whether it can stay lazy/optional.
- **Source adapters (§2):** better academic/source clients (e.g. `pyalex`, `arxiv`, `habanero` for
  Crossref, `biopython` E-utilities) — do they beat the hand-rolled httpx parsers on robustness/
  coverage, and are they worth the dep?

## Deliverable
1. **Recommendation table**, sorted by **(impact × fit) / effort**:

| Stage | Current | Recommended lib/repo (URL, ⭐, license, last commit) | Why better | Swap-in seam | Effort (S/M/L) | Risk / constraint flags |

2. **Default extraction chain** recommendation (primary + fallbacks) with the rationale.
3. **Evaluation plan** mapped to E1–E10 in `WEB_SCRAPING.md`: for each top recommendation, the exact
   metric, dataset to build/borrow, and harness to write so the improvement is *measured*, not assumed.
   (Where a harness exists — the golden-set eval, `eval/research_benchmark.py` — say how to extend it.)
4. **Top 5 "do first"** with one-paragraph rationale each, and an explicit **reject list** (tools that
   look attractive but violate a constraint — e.g. cloud-only scrapers, GPL parsers, anything that
   bypasses the sandbox/egress chokepoints).
5. **Net-new capabilities** worth adding that the stack lacks entirely (e.g. JS rendering, first-party
   web search), flagged separately with the privacy/resource trade-off spelled out.

Be concrete and skeptical. Verify every library claim with a current search; cite the source.
