# Lighthouse — Skill Library v1.0 Specification (Per-Source)

> **Purpose.** Define the complete set of research skills shipping in Lighthouse v1.0, one per
> source, covering every domain a serious researcher or general user might bring to the tool.
> Companion to `SKILL_FRAMEWORK.md` (what a skill is) and `MODE_SKILL_INTEGRATION.md` (how modes
> consume skills).
>
> **The governing rule.** *One skill per source. A domain is a tag, not a folder.* Economics is
> not a skill — it's a label that FRED, BEA, BLS, World Bank, OECD, OpenAlex (econ papers), SEC
> EDGAR, and others all carry on their manifest. The recommender uses domain tags as one ranking
> signal; the user-facing source picker shows skills filtered by relevance to the question, not by
> a "domain selector" the user has to navigate first.
>
> **What earns v1 inclusion.** A skill ships in v1 if a user from at least one of the target
> domains would reach for it as a *primary* tool (not occasional), AND a free or lawfully-fetchable
> access path exists, AND it doesn't duplicate another v1 skill's coverage. Below that bar, it's
> v1.1 — and v1.1 selection is driven by real-user gap reports, not speculative completeness.

---

## 0. Design rules

Before the list, the rules that produced it. If we drift from these the library becomes incoherent.

### 0.1 One skill per source
A *source* is a discrete, fetchable place: an API endpoint set, a feed protocol, a site with a
coherent extraction strategy. arXiv is one source. PubMed is one source. Reuters is one source.
Federal Register and regulations.gov are *two* sources even though they're often used together —
they have different APIs, different content types, different audit semantics.

The pull toward bundling ("they're both government regulatory stuff, make one skill") should be
resisted. Bundled skills produce worse SKILL.md guides (which tool playbook? which API's
limitations?), confused tool naming, and tangled audit provenance. Splitting them produces clean,
testable, individually-improvable skills with crisp domain tags.

### 0.2 A domain is a manifest tag
Every skill's `manifest.toml` declares which domains it serves:
```toml
domains = ["economics", "policy", "finance"]
primary_for = ["economics"]
secondary_for = ["policy", "finance"]
```
The recommender uses these tags as one feature in its scoring function. A user asking about
unemployment trends gets BLS recommended first (primary for economics), FRED second (also primary,
slightly less specific), Federal Register relevant rules third (secondary for economics through
the regulatory channel). The user never picks "economics" as a category — they ask their question,
the recommender ranks skills, the user sees a list filtered by relevance.

### 0.3 News is per-outlet plus a meta-skill
Each news outlet gets its own skill folder (with its own free-API quirks, its own AllSides bias
overlay, its own beat-coverage notes, its own watchable feeds). The meta-skill that orchestrates
cross-outlet `compare_coverage` and the trust-selection UI is a *separate* skill that depends on
the per-outlet skills. This is the cleanest architecture and lets each outlet's particularities
live where they belong.

### 0.4 Build cost scales sub-linearly within families
Splitting Federal Register from regulations.gov from GovInfo from Congress.gov doesn't quadruple
the work. The first skill in a family ("U.S. federal government APIs") establishes the patterns —
auth, politeness, broker integration, common parsers — and subsequent skills in the family are
days, not weeks. Same logic for economic-data sources (FRED first, then BEA / BLS / World Bank /
OECD reuse most of the structure) and news outlets (Reuters first as the prototype, then the rest
in parallel). The honest estimate is in §9 below.

---

## 1. The full v1.0 skill library

Thirty-five source skills plus one meta-skill, organized by source family.

### Web infrastructure (3)
1. **General Web** — SearXNG meta-search + Tier-A/B/C fetch + extract chain
2. **RSS / Atom feeds** — user-added feed monitoring (channel)
3. **Internet Archive Wayback Machine** — historical web + link-rot mitigation

### Academic literature (5)
4. **arXiv** — preprint server (CS, ML, physics, math, quant-bio, quant-fin)
5. **OpenAlex** — open academic graph (250M+ works, citations, affiliations)
6. **PubMed** — biomedical literature with MeSH support
7. **Crossref** — DOI registry + Retraction Watch overlay + scholarly metadata
8. **Semantic Scholar** — citation-intent classification + influential-citation signal OpenAlex lacks

### Clinical / biomedical (1)
9. **ClinicalTrials.gov** — trial registry, endpoints, amendments

### Legal (1)
10. **CourtListener / RECAP** — federal case law + docket tracking (Free Law Project)

### U.S. federal government (4)
11. **Federal Register** — rule notices, executive orders
12. **regulations.gov** — public comment dockets
13. **GovInfo** — CFR, U.S. Code, Congressional Record, GAO reports
14. **Congress.gov** — bills, votes, committee activity, member records

### Corporate / financial filings (1)
15. **SEC EDGAR** — 10-K / 10-Q / 8-K / proxy / insider transactions

### Economic data (5)
16. **FRED (St. Louis Fed)** — U.S. macro time series
17. **BEA** — GDP, trade, national accounts
18. **BLS** — employment, CPI, productivity, occupational data
19. **World Bank Open Data** — international development indicators
20. **OECD Data** — comparative cross-country economic + social indicators

### Engineering / software (2)
21. **GitHub** — repos, releases, issues, security advisories
22. **PyPI / npm / crates.io** — package registries, version + dependency tracking

### Reference / orientation (2)
23. **Wikipedia** — universal disambiguator + entity context (downgraded for load-bearing claims)
24. **Wikidata** — structured knowledge graph (entities, properties, identifiers)

### Media — video / audio (2)
25. **YouTube** — Data API + legitimate transcript extraction
26. **Internet Archive (audio / video collections)** — public-domain + CC + archived radio/TV

### News (per-outlet, 6 in v1 seed list)
27. **Reuters** — wire service, global
28. **Associated Press** — wire service, U.S.-centric
29. **BBC News** — international, public-funded
30. **NPR** — U.S. public radio
31. **The Guardian** — UK + international, Open Platform API
32. **ProPublica** — investigative, U.S., free + their open data archive

### News meta-skill (1)
33. **News Orchestrator** — cross-outlet `compare_coverage`, trust-selection UI, AllSides bias overlay, user-added RSS-feed-outlet registration

### Specialty (2)
34. **WHO (World Health Organization)** — international health data, ICD codes, disease outbreaks
35. **U.S. Census Bureau** — demographic data, ACS, decennial census

### Composing utility (1, not a destination)
36. **Retraction Watch lookup** — utility composed into arXiv, OpenAlex, PubMed, Crossref

**Total: 35 destination skills + 1 composing utility = 36 modules.**

Each one passes the inclusion bar (primary tool for at least one domain, free/lawful access, no v1
duplication). The honest build cost — §9 — is real but tractable because most are in families that
share patterns.

---

## 2. Per-skill specifications

Each entry: one-paragraph purpose, tools, parsers, manifest highlights, notes. Skills already
specified in earlier docs are summarized here with their key facts; the new and split-out ones get
full treatment.

### 1. General Web
Anchor and universal fallback. SearXNG meta-search by default; Tier-A static fetch via httpx +
trafilatura; Tier-B in-process JS via Crawl4AI (scheduler-gated, audit-tagged); Tier-C
fingerprint-tool fallback only behind explicit per-domain trust. Six roles tracked by the
recommender. Domain tags: **all twelve**. Full spec in `MODE_SKILL_INTEGRATION.md` §5.

### 2. RSS / Atom feeds
User-extensibility channel. Promotes existing `sources/rss.py` to a full skill with watchable
tools. Point Lighthouse at any RSS / Atom URL. Per-feed grade and bias-rating set at registration.
Domain tags: **all**.

### 3. Internet Archive Wayback Machine
Historical web + link-rot mitigation via the Wayback CDX HTTP API (avoiding the AGPL
`internetarchive` Python package). Critical for Reconstruct, journalism dead-link recovery, legal
"what did the page say on the audit date." Tools: `lookup_url_at_date`, `list_snapshots`,
`fetch_snapshot`, `submit_for_archiving`. Domain tags: **journalism, legal, policy, IC, history**.

### 4. arXiv
CS/ML/physics/math/quant-bio/quant-fin preprint server. Wraps the existing adapter; tools beyond
the adapter (`list_recent_in_category` watchable, `get_replaced_versions`, `expand_to_categories`).
Politeness: 3s/request hard cap. Domain tags: **academic_cs_ml, engineering, quant_finance, physics, math**.

### 5. OpenAlex
Open academic graph. Wraps `pyalex` (MIT). Citation-graph tools (`get_citations_in/out`),
institutional affiliation resolver (critical for source-independence — same lab → not independent),
`list_recent_in_concept` watchable, Retraction Watch overlay applied automatically. Domain tags:
**academic_cs_ml, clinical, policy, economics, every academic-touching domain**.

### 6. PubMed
Biomedical literature with MeSH support. Wraps Biopython `Bio.Entrez`. `expand_to_mesh` tool;
publication-type classifier (RCT / observational / review / meta-analysis — crucial for
Survey/PRISMA); `list_recent_by_mesh` watchable. **The clinical wedge depends on this being built
well.** Domain tags: **clinical, public_health, academic_biomedical**.

### 7. Crossref
DOI registry + metadata + Retraction Watch overlay (Crossref Labs, DOI `10.13003/c23rw1d9`).
Tools: `lookup_doi`, `get_works_by_funder`, `search_works`, `get_retraction_status`. Wraps
`habanero` (MIT). Domain tags: **academic_cs_ml, clinical, every academic-touching domain**.

### 8. Semantic Scholar
Citation-intent classification (supporting / contrasting / extending / background) + influential-
citation flag — signal OpenAlex lacks. Free API with key, 1 req/s. Recommender promotes it over
OpenAlex when the question is about *how* a paper is cited. Domain tags: **academic_cs_ml, clinical**.

### 9. ClinicalTrials.gov
Trial registry. Tools: `search_trials`, `fetch_trial`, `get_endpoints` (pre-registered vs reported
→ outcome-switching detection), `get_amendments` (modification chronology for Reconstruct),
`list_trials_by_condition` watchable. Domain tags: **clinical, regulatory, drug_development**.

### 10. CourtListener / RECAP
Free Law Project federal case-law + PACER dockets. Tools: `search_cases`, `fetch_opinion`,
`list_dockets_for_party`, `get_oral_argument_audio` (→ shared audio-transcript pipeline),
`track_docket` watchable, `get_citation_treatment` (rough Shepardizing). SKILL.md explicit on
federal-strong / state-varies coverage. Domain tags: **legal, journalism, policy, IC**.

### 11. Federal Register
Rule notices, executive orders, proclamations. Tools: `search_rules`, `fetch_rule`,
`list_recent_in_agency` watchable, `get_executive_orders`, `track_rulemaking` (NPRM → final).
Domain tags: **policy, legal, regulatory**.

### 12. regulations.gov
Public-comment dockets. Sister to Federal Register, different source. Tools: `search_dockets`,
`fetch_docket`, `list_comments`, `fetch_comment`, `track_docket_activity` watchable. Domain tags:
**policy, legal, regulatory**.

### 13. GovInfo
GPO archive — CFR, U.S. Code, Congressional Record, public laws, GAO reports. Tools:
`search_collection`, `fetch_document`, `get_cfr_section`, `get_uscode_section`,
`list_recent_in_collection` watchable. Domain tags: **policy, legal, regulatory, journalism**.

### 14. Congress.gov
Bills, votes, committee activity, member records — *current* legislative activity. Tools:
`search_bills`, `fetch_bill`, `get_vote_record`, `list_member_actions`, `track_committee`
watchable. Domain tags: **policy, politics, legal**.

### 15. SEC EDGAR
U.S. corporate filings. Risk-factor (Item 1A) and MD&A (Item 7) parsers are the high-value
specialty tools. Tools: `search_filings`, `fetch_filing`, `parse_10k_item_1a`, `parse_10k_item_7`,
`parse_10q_changes`, `list_recent_for_cik` watchable, `get_insider_transactions`,
`get_proxy_executives`. Politeness: SEC requires identifying User-Agent. Domain tags: **finance,
M&A, corporate_intelligence, regulatory**.

### 16. FRED (St. Louis Fed)
U.S. macro time series. Tools: `search_series`, `fetch_series`, `list_releases` watchable,
`get_release_calendar`, `compare_series`, `get_revisions` (point-in-time data). API key (free).
Domain tags: **economics, finance, policy**.

### 17. BEA
GDP, personal income, international transactions, regional + industry accounts. Tools:
`search_dataset`, `fetch_table`, `list_nipa_tables`, `list_regional_tables`, `get_industry_account`.
API key (free). Domain tags: **economics, policy, regional_economics**.

### 18. BLS
Employment, unemployment, CPI, PPI, productivity, occupational, time-use. Tools: `search_series`,
`fetch_series` (date range + seasonal-adjustment toggle), `list_releases` watchable,
`get_release_calendar`, `compare_geographies`, `get_occupation_data`. API key (free). Domain tags:
**economics, policy, labor_research, journalism**.

### 19. World Bank Open Data
International development indicators, 200+ economies. Tools: `search_indicator`, `fetch_indicator`,
`list_indicators_by_topic`, `compare_countries`, `get_country_metadata`. No auth. Domain tags:
**economics, international_development, policy, global_health**.

### 20. OECD Data
Comparative cross-country indicators (productivity, well-being, education, taxation). Tools:
`search_dataset`, `fetch_dataset`, `compare_countries`, `list_recent_releases`. Domain tags:
**economics, policy, comparative_research**.

### 21. GitHub
Repos, releases, issues, security advisories. Tools: `search_repos`, `fetch_readme`,
`list_releases` watchable, `list_recent_issues` watchable, `get_dependency_graph`, `get_license`,
`get_security_advisories` (GHSA), `fetch_file` (broker-mediated), `get_commit_history` watchable.
Auth via `lighthouse config set github.token`. Domain tags: **engineering, academic_cs_ml,
software_research, security**.

### 22. PyPI / npm / crates.io
Three sub-adapters under one skill (unified use cases). Tools per registry: `search_package`,
`fetch_package_metadata`, `get_versions`, `get_dependencies`, `get_dependents`,
`list_recent_releases_for_package` watchable. Domain tags: **engineering, security (supply-chain)**.

### 23. Wikipedia
Universal disambiguator; SKILL.md says explicitly *not a primary citation source*. Tools: `search`,
`fetch_page`, `extract_infobox`, `walk_category`, `recent_revisions` (edit-war detection),
`talk_page`, `citations`. Domain tags: **all (orientation)**.

### 24. Wikidata
Structured knowledge graph — entities, properties, cross-source IDs. Value is identifier
resolution (person → ORCID + VIAF + IMDb + ISNI in one query). Tools: `search_entity`,
`fetch_entity`, `get_properties`, `resolve_identifier`. Domain tags: **all (identifier resolution)**.

### 25. YouTube
Legitimate path: Data API v3 metadata + `yt-dlp` / `youtube-transcript-api` transcripts via
official caption endpoints. Tools: `get_metadata`, `get_transcript`, `get_channel_info`,
`list_channel_uploads` watchable, `search_videos`. Auto-caption detector → `transcript_quality=low`
+ downgrade. Per-channel trust promotion. Domain tags: **media, journalism, pop_culture, education,
politics**.

### 26. Internet Archive — audio/video collections
Separate research surface from Wayback. Public-domain films, CC recordings, archived radio, the
Television News Archive (captioned/searchable). Tools: `search_av`, `fetch_metadata`,
`fetch_transcript`, `get_collection_listing`. Domain tags: **media, journalism, pop_culture, history**.

### 27–32. News (per-outlet)
**Reuters** (Open Platform API, Center), **Associated Press** (RSS+web, Center), **BBC News**
(RSS, Lean Left), **NPR** (RSS+web + `fetch_audio_transcript`, Lean Left), **The Guardian** (Open
Platform API + granular `get_tags`, Left), **ProPublica** (RSS+web + `search_data_repo` open data,
Lean Left). Each: `search_articles`, `fetch_article`, `list_recent_in_topic` watchable. Domain
tags: **journalism + outlet-specific**.

### 33. News Orchestrator (meta-skill)
Cross-outlet coordinator. Trust-selection UI; `compare_coverage` (same query across N trusted
outlets, side-by-side with bias overlay); user-added RSS-outlet registration; AllSides/Ad Fontes
overlay config; the `lighthouse doctor news` boot re-check. Tools: `search_news`, `compare_coverage`,
`register_custom_outlet`, `validate_outlet_access`, `get_bias_overlay`. Depends on the six per-
outlet skills. Domain tags: **journalism, politics, IC, finance**.

### 34. WHO
International health data, ICD codes, outbreak surveillance, vaccine schedules. Tools: `search_data`,
`fetch_indicator`, `list_outbreaks` watchable, `get_icd_code`, `compare_countries`. Domain tags:
**clinical, public_health, international, global_health**.

### 35. U.S. Census Bureau
Demographics, ACS, decennial census, business surveys. Tools: `search_dataset`, `fetch_acs_table`,
`fetch_decennial`, `query_geographic` (FIPS/tract/block group), `compare_periods`. API key (free).
Domain tags: **policy, demographics, sociology, journalism, economics**.

### 36. Retraction Watch lookup (composing utility)
Not a destination. A capability called by arXiv/OpenAlex/PubMed/Crossref when fetching a paper.
Internal tools: `lookup_doi`, `lookup_pmid`, `lookup_arxiv_id`, `list_recent_retractions` watchable,
`propagate_retraction` (demotes Positions citing retracted sources, escalates in Track). Crossref
Labs (DOI `10.13003/c23rw1d9`). Manifest declares `composing_skill=true`. Domain tags: **all
academic-touching**.

---

## 3. Cross-domain coverage check
Every domain (academic, clinical, legal, policy, journalism, IC/OSINT, finance, engineering, media,
pop-culture, politics, economics, public health, international, demographics) has ≥6 primary-fit or
strong-secondary skills. Every mode has substantially more candidate skills than needed for
non-trivial recommendation: **30+ watchable** (Watch), **23 enumerable** (Survey), **16 with
temporal tools** (Reconstruct), per-option (Decide), perspective-lens diversity (Adjudicate), all
skills (Ask/Investigate).

---

## 4. The trust + fetch matrix users see (News)
Settings → News shows each outlet's fetch status / method / AllSides rating / trust toggle. Seed
six are `✓` and pre-selected (Reuters, AP, BBC, NPR, Guardian, ProPublica). NYT is `◐` (metadata+
abstract only), WSJ/Bloomberg/FT are `✗` (paywall/ToS — not fetchable), Fox is `◐` (RSS only),
user-added RSS outlets are `✓`. **Visibility-with-reason beats silent omission.** The user cannot
override the fetch-status column — paywall/ToS constraints are platform invariants.

---

## 5. Deliberately NOT in v1.0 (v1.1 candidates, gap-report-driven)
Reddit/HN/Stack Exchange (community-graded, v1.1 w/ downgrades); Google Scholar (no API, Tier-C,
permanently rejected); paywalled news bodies; Bluesky/Twitter/Mastodon (volatile APIs, Bluesky the
top v1.1 candidate); paywalled academic DBs (OpenAlex covers public content); CDC/FDA/EMA (overlap
PubMed+ClinicalTrials+FedReg+WHO); state-level gov; patents (USPTO/EPO); podcast platforms; arXiv-
Sanity overlays. v1.1 bar: (a) real-user gap report, (b) free/lawful access, (c) no v1 duplication.

---

## 6. The composing-capability pattern
Retraction Watch is the v1 proof of a *composing* skill (called by others, not user-picked,
`composing_skill=true`). v1.1 candidates following the pattern: an ID resolver
(DOI↔PMID↔arXiv↔OpenAlex↔S2), the AllSides bias overlay promoted out of News Orchestrator, an ORCID
resolver, an OpenCorporates company-identity resolver.

---

## 7. First-launch defaults
General Web selected; all Tier-A skills with valid credentials available (auth-required ones
prompt once); News Orchestrator initialized with the six seed outlets; AllSides overlay on
(toggleable); YouTube available (Data API auth-gated, transcripts work without auth); Wikipedia,
Wikidata, Wayback, arXiv, OpenAlex, PubMed, Crossref, Semantic Scholar, Retraction Watch all
available without auth (rate-limited). The recommender then ranks available skills against the
question.

---

## 8. Eight architectural invariants
1. **One skill per source.** Domain is a manifest tag, not a folder.
2. **Skills are content + capability welded.** SKILL.md (guide) + tools/ (toolkit).
3. **Skills compose platform primitives.** No raw `httpx.get()`; every fetch → `net.fetch` →
   politeness → broker.
4. **Skill identity flows through metadata.** Document → chunk → claim; discipline gate uses it for
   source-independence.
5. **One recommender, mode-parameterized.** N skills ≠ N codepaths.
6. **Trust is user-configurable.** News outlets, RSS grades, YouTube channels, community skills,
   Tier-C allowlists — all in Settings, per-user.
7. **What we can't fetch is visible.** `✗` with reason, not silent absence.
8. **The general fallback is itself a skill.** No separate fallback codepath.

---

## 9. Build order (dependency- and risk-ordered; family batching bounds cost)
**Foundation:** General Web (anchor).
**Academic literature family:** arXiv (validates adapter→skill upgrade) → OpenAlex → Crossref +
Retraction Watch composing utility → PubMed → Semantic Scholar.
**Reference family:** Wikipedia → Wikidata.
**Clinical:** ClinicalTrials.gov → WHO.
**Channels:** RSS (wraps existing adapter) → Internet Archive Wayback.
**U.S. federal family:** Federal Register → regulations.gov → GovInfo → Congress.gov.
**Legal:** CourtListener (shares audio-transcript infra with YouTube).
**Corporate/financial:** SEC EDGAR.
**Economic-data family:** FRED (prototype) → BEA → BLS → World Bank → OECD → U.S. Census.
**Engineering family:** GitHub → PyPI/npm/crates.io.
**Media:** YouTube (depends on audio-transcript infra from CourtListener) → Internet Archive AV.
**News family:** Reuters (prototype) → AP → BBC → NPR → The Guardian → ProPublica.
**News orchestration:** News Orchestrator (depends on all six per-outlet skills).

Honest estimate: **18 weeks serial; ~11–13 weeks with sensible parallelization within families.**
The regulated-industry wedge (PubMed → ClinicalTrials → CourtListener → SEC EDGAR → Federal
Register + GovInfo + Congress.gov) completes by week 11.

---

## 10. What ships at v1.0
Every skill above (35 destinations + 1 composing utility) **plus**: the skill framework (registry,
loader, capability runner, manifest schema, audit-chain skill_id propagation, signing + community +
WEP downgrade); the mode-parameterized recommender (domain-tag matching, SKILL.md embedding
similarity, profile overlay, user override); the source picker UI (Research/Watch/Ask integration,
editable plan); the trust matrix UI (News, community skills, Tier-C); the contradiction artifact +
per-mode handling + auto-Adjudicate trigger; the eval harness (per-skill recall@k + calibration);
and `lighthouse doctor news`. Substantial but bounded — every component is specified here or in a
companion document; none is speculative.

*End of v1.0 skill library specification.*
