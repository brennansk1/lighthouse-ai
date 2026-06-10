# Lighthouse — Future Features Roadmap

> Candidate features beyond the v1.0 bundle (skill framework + 36-source library + mode↔skill
> integration + frontier-gap core). Companion to `SKILL_LIBRARY_V1.md` §5/§6 (deferred skills +
> composing pattern) and `MODE_SKILL_INTEGRATION.md` §9 (open work). Nothing here is committed scope;
> each item is gated by the same bar as v1: a real user need, a lawful/free access path, and no
> duplication of shipped capability.

---

## 1. Watch v2 — user-defined website monitors with scrapability verification

**The ask.** Let a user point Watch at an arbitrary website (not just a v1 skill or an RSS feed),
have Lighthouse *verify it can actually be scraped lawfully and reliably*, and then set explicit
**trigger criteria** that decide when a change becomes an alert.

**Flow:**
1. **Add source.** User pastes a URL in Watch → "Monitor a website". Plain-language: "Paste a page or
   site you want to keep an eye on."
2. **Scrapability pre-flight (the new capability).** Before accepting the monitor, run a one-time
   check and show the user a clear verdict:
   - robots.txt allows fetching this path (reuse `net_politeness.RobotsPolicy`); show the declared
     crawl-delay.
   - The page is reachable through the egress guard (host allowlisted, or offer a one-click
     `trust add <domain>` with the reason recorded).
   - **Extractability tier:** does the static fetch + trafilatura yield real content (≥N tokens)? If
     not, flag that it needs Tier-B JS rendering (see §3) and whether that's enabled.
   - **Change-detectability:** does the page expose a feed (RSS/Atom/sitemap `lastmod`), an
     `ETag`/`Last-Modified` header, or must we diff rendered content? Pick the cheapest reliable
     signal.
   - Verdict surfaced as: ✓ "Good to monitor (feed available)", ◐ "Monitorable, but needs JS
     rendering / content-diff (heavier)", ✗ "Can't monitor — robots disallows / paywall / not
     reachable" with the reason. Visibility-with-reason, never silent failure.
3. **Set trigger criteria.** The user chooses what counts as an alert, in plain language:
   - **Any change** to the page/section (content hash diff).
   - **New items** match keywords / a topic (interest-relative salience, reuse Watch's gateway
     salience from `modes/monitor.py`).
   - **A specific element changed** (CSS/XPath selector the user picks, or "the price", "the version
     number", "the headline list") — a guided selector, not raw XPath for non-technical users.
   - **Threshold** triggers ("number above/below X", "date passed", "status changed to Y").
   - **Cadence** (how often to check) + quiet-hours, reusing `SchedulerGate`.
4. **Run + escalate.** Each tick: politeness → broker → extract → diff against the stored snapshot →
   evaluate trigger → reflection (passive) vs escalation (actionable), reusing the existing
   dedup/hotness/escalation pipeline and `monitor_session` persistence.

**Where it plugs in (mostly reuse):** a new `skills/library/web_monitor/` watchable skill +
`run_watchable(ctx, query, *, since)`; a `verify_scrapable(ctx, url) -> Verdict` tool composing
`net_politeness` (robots/crawl-delay), the egress guard, the extractor chain, and a header/feed
probe; per-monitor snapshot state in `state.db`; trigger evaluation as a small rule engine. The
content-diff + selector + threshold logic and the scrapability pre-flight are the genuinely new
parts; everything else is existing Watch machinery.

**Guardrails:** robots-respecting by default; Tier-C never auto-engaged (only via explicit
`trust add`); every monitored fetch audit-logged; per-domain rate budget enforced; a monitor that
starts failing (robots changed, paywall added, layout broke the selector) self-reports an unreachable
state instead of silently going quiet.

---

## 2. Smarter recommender + framing (learned, not just heuristic)

- **Telemetry-learned recommender (V2).** Learn per-user/per-domain skill weights from accept/dismiss
  signals on the source picker; warm-start a Question Library of past framings.
- **Skill profiles persistence backend.** v1 persists picker choices to localStorage only — add a
  real settings store + `PATCH /api/sources` so per-domain profiles (baseline/boosted/excluded
  skills) and per-source trust survive restarts and sync across the CLI/TUI/web.
- **Trained framing/route classifiers.** Replace the LLM-few-shot + keyword fallback with a small
  fine-tuned DistilBERT-class classifier for question typing and Adaptive-RAG routing (the documented
  upgrade path in `framing/`), for speed + determinism without a gateway.

---

## 3. Acquisition tiers — actually build Tier-B and gate Tier-C

- **Tier-B in-process JS rendering.** Wire Crawl4AI / Playwright behind `general_web.fetch_url_js`
  (currently a documented stub): real-browser, no fingerprint evasion, scheduler-gated, browser-pool
  RAM cap, chunks tagged `fetch_backend="js"` with the existing extra WEP downgrade. Unlocks SPA-only
  pages and the Watch-v2 content-diff path for JS sites.
- **Tier-C fingerprint browsers.** Patchright / Camoufox / nodriver, only behind
  `lighthouse trust add <domain> --reason`, `#anti-bot-bypass`-tagged + WEP-downgraded — for the rare
  case a user lawfully needs a site that blocks plain automation. Half-life measured in weeks; ship as
  opt-in with a clear staleness warning.
- **Per-source health endpoint.** `/api/sources/health` (last successful fetch, error rate,
  rate-limit budget remaining, robots freshness) to make the Health dashboard live and power
  `lighthouse doctor sources`.

---

## 4. v1.1 skills (gap-report-driven, per SKILL_LIBRARY_V1 §5)

- **Community sources:** Reddit, Hacker News, Stack Exchange — with `community` tags + WEP downgrade.
- **Bluesky** (open API; the most credible social v1.1 candidate).
- **Patents:** USPTO / EPO / Google Patents (narrow audience, high value when needed).
- **State/local government** data (per-state legislatures, agencies).
- **Podcast platforms** via the shared audio-transcript pipeline (Spotify/Apple), where lawful.
- **NYT / Fox** as optional metadata-tier adapters (already shown ◐ in the trust matrix).

## 5. Composing capabilities (SKILL_LIBRARY_V1 §6)

- **ID resolver** (DOI ↔ PMID ↔ arXiv-id ↔ OpenAlex ↔ Semantic-Scholar) — consolidate per-skill
  resolvers into one composing utility.
- **AllSides / Ad Fontes bias overlay** promoted out of the News Orchestrator into a composing
  capability usable by RSS + user-added outlets.
- **ORCID resolver** (author identity, called by OpenAlex/Crossref/arXiv).
- **OpenCorporates resolver** (company identity, called by SEC EDGAR/News/ProPublica).

---

## 6. Depth, calibration, and long-horizon work

- **Deep-tier checkpoint/resume wiring.** `modes/exhaustive.py` already exposes serializable tree
  state (`to_state`/`from_state`); wire dispatcher-level checkpoints to `state.db` so a multi-hour
  Deep run survives a crash/close and resumes from the last node.
- **Calibration auto-resolver — full loop in the UI.** The resolver + Brier loop ship; surface
  per-skill and per-mode calibration trends in Track over time, and let users review/override
  machine resolutions.
- **VOI tuning from outcomes.** Learn the value-of-information weights in the Deep tree from which
  branches actually changed final answers.
- **Interactive Ask chat in the dashboard.** The Ask engine is conversational
  (sessions, directives `/sources` `@skill` `/adjudicate`, per-turn skill audit)
  but the dashboard treats every Ask as a one-shot job that lands as a static
  transcript. A real chat surface needs a synchronous turn endpoint that runs
  `quc.ask` with the live gateway inside the web process (today only the
  dispatcher holds a gateway), plus a continuation UI. The transcript *viewer*
  ships (Library renders turns as chat bubbles); the interactive loop is this
  deliberate, separately-designed feature.
- **Auto-Adjudicate sub-job spawn.** The dispatcher's §6.4 hook
  (`dispatcher._maybe_flag_auto_adjudicate`) detects contradictions and records the decision on the
  artifact/job meta, but deliberately does not enqueue the Adjudicate sub-job itself: a job that
  spawns jobs needs loop-guard and budget treatment first (a contradiction loop must trip
  `LoopTripped`, and the child must draw down the parent's budget, not a fresh one). Wire the spawn
  through the governor once those two guarantees are specified.

---

## 7. Reach and collaboration

- **Multi-modal ingestion.** Images (chart/figure OCR + caption), audio/video beyond transcripts
  (the shared `sources/transcript.py` is the seam), spreadsheets/datasets as first-class evidence.
- **Export + sharing.** One-click export of an artifact (report/table/timeline/matrix) to
  PDF/DOCX/Markdown with the full provenance manifest; shareable read-only artifact links.
- **Remote / mobile access** to running jobs and digests (the supervisor already serves an API).
- **Collaborative research** — multiple users on a shared corpus with per-claim attribution.

---

## 8. Usability — the "5/5 for both audiences" push

External critique pass on getting to a flawless rating for general-public AND researcher usability.
Each item is weighed (pro / con) and only the on-mission ones are adopted.

### Public — lower the barrier from infrastructure to one click
- **One-click desktop app (ADOPT).** A Tauri/Electron wrapper that silently bundles + supervises a
  *local* Ollama + Qdrant, so there's no Docker/terminal. *Pro:* eliminates the biggest non-technical
  barrier; stays fully local-first. *Con:* packaging/signing/auto-update work per-OS (already a Phase-4
  item) + bundle size. **On-mission — this is the right public on-ramp.**
- **Onboarding API-key wizard (ADOPT).** A Settings flow to paste/toggle the free source keys
  (FRED/BEA/BLS/Census/Guardian/Congress/GitHub) into the existing keyring/secrets store, with
  "skip / add later" and per-source enable. *Pro:* removes config.toml hand-editing; pairs with the
  trust matrix; secrets infra already exists. *Con:* minor. **Adopt — UI over existing keyring.**
- **Intent templates / "recipes" (ADOPT, reframed).** Plain-intent starting points
  ("Draft a literature review", "Fact-check this claim", "Build a timeline") that pre-fill
  mode + depth + recommended sources behind the scenes via the existing framing classifier. *Pro:*
  big cognitive-load win for newcomers. *Con:* the critique's premise ("choosing raw scripts like
  `ask_store.py`") is a misread — users already pick plain-language modes; the real value is the
  preset bundles. **Adopt as recipe presets, not a re-architecture.**
- **Cloud-hosted SaaS (DECLINE).** *Con:* directly violates the local-first / regulated-industry moat
  (HIPAA/ABA/ITAR — the corpus never leaves the user's hardware). A hosted multitenant version would
  forfeit the entire wedge. **Declined on principle** — the desktop app above is the abstraction layer
  instead.

### Researcher — deeper extensibility, transparency, reproducibility
- **Skill scaffolding generator + author guide (ADOPT).** `lighthouse skill new <id>` boilerplate
  generator + a documented base contract + loading skills from a user/out-of-tree directory (not just
  the in-tree library). *Pro:* the framework already supports drop-in folders + the import guard +
  community tag — this is the natural last mile for niche/proprietary sources. *Con:* none material.
  **Strong adopt — highest-leverage researcher win, small build on existing machinery.**
- **Granular steerability for reproducibility (ADOPT).** Expose per-role seed / temperature / top-p in
  config + UI and let a run "lock" them; record them in the provenance manifest so an experiment is
  byte-reproducible. *Pro:* directly serves the determinism/reproducibility pillar that is already a
  core differentiator; the gateway already runs temp-0 + fingerprinting, so this surfaces existing
  knobs. *Con:* minor. **Strong adopt.**
- **Graph-RAG + entity/relation extraction (ADOPT, scoped).** A *local* knowledge graph built over the
  corpus (entity + relation extraction → graph store; the Adaptive-RAG router already has a GRAPH
  route, and the Wikidata skill yields structured entities) so a researcher can see how variables/
  entities interact, not just where a fact came from. *Pro:* a real research frontier; composes with
  existing pieces. *Con:* full *causal inference* is research-grade and easy to overclaim, and a
  citation-graph that needs an external API/OpenAlex dump risks local-first — so **scope to local
  corpus Graph-RAG + relation extraction; treat causal inference as a clearly-labeled stretch**, not a
  promised feature.
- **MkDocs/Sphinx docs site + advanced tutorials (ADOPT, lower priority).** A built docs site with
  end-to-end tutorials (e.g. precision-oncology pipeline, policy-shift timeline, custom-skill authoring,
  reproducible-experiment setup). *Pro:* adoption + credibility; the `docs/` content is already rich.
  *Con:* mostly content work, not differentiating engineering. **Adopt as a documentation track.**

*This is a menu, not a commitment. Pull an item into a sprint when a real user keeps hitting its
absence.*

## 9. Minor polish (from live testing, 2026-05-29)
- **Pre-flight API-key check for key-gated skills.** FRED/Congress/GovInfo/regulations.gov/CourtListener
  currently fire the live request even when no key is configured and rely on the server to reject it
  (400/401/403), then degrade gracefully with a `lighthouse trust add <domain>` note. This is correct and
  safe, just slightly wasteful — a pre-flight "this source needs a free key (set it in Settings)"
  short-circuit would skip the wasted round-trip and give the user a clearer up-front message. Low
  priority; touches each key-gated adapter's key-resolution + their tests.

## 10. Security-review residuals (boundary review, 2026-05-29)
A focused review of the egress/skill-runner/sandbox/injection boundary found Areas 1 (egress/SSRF),
2 (skill import-guard/capabilities), and 4 (injection gate) well-defended. One real finding was **fixed**
(scan-time zip-decompression bomb — `ArchiveBombScanner` now caps nested-member reads). Two residuals,
both low-priority, are noted here rather than fixed under time pressure:
- **DNS-rebinding / private-IP egress** (`net.py`/`egress_proxy.py`): the allowlist is hostname-only and
  never resolves/pins IPs, so an allowlisted domain whose DNS points at a loopback/link-local address
  (169.254.169.254, 127.0.0.1) would be fetched. Requires the attacker to control DNS for an allowlisted
  domain (compromised CDN) — outside the realistic local-first threat model. *Fix when convenient:*
  resolve the host in `net.get` and reject private/loopback/link-local IPs before opening the socket.
- **Scanner content-type confusion** (`scanners.py` HTML/PDF `supports()`): a script-bearing HTML/SVG (or
  JS-PDF) uploaded under a spoofed `text/plain` content type with no extension skips the active-content
  scanner, though `ingest` still parses it by magic-byte sniff. **Low impact in this system**: the tool
  extracts *text* and never renders/executes fetched markup, so the active content never runs; EICAR and
  other malware scanners still fire. A clean fix needs broker-level content-sniffing (so `supports()` can
  see bytes) — a regex sniff-gate in `scan()` was tried and reverted because `<script>` appears in both
  the danger and sniff patterns, causing false positives on benign prose (violates the sandbox's no-FP
  bar). Defer until the broker passes a content sniff to `supports()`.
