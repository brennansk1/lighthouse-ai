# Lighthouse, Product & Codebase Review Panel

## 0. Assumptions & clarifying questions

**Assumptions (from CONTEXT):**
- Solo, part-time, unfunded founder; scarce hours are the binding constraint on everything below. [ASSUMPTION]
- "Winning" = a credible credential artifact + *some* real adoption; paid usage is a bonus, not the goal. [ASSUMPTION]
- Primary buyer is a law-firm Knowledge-Management / practice-support lead bound by ABA Model Rule 1.6; HIPAA compliance analyst is the close second. [ASSUMPTION]
- Local-first / air-gap capability is non-negotiable and will not be traded away. [README/memory]
- Stage is pre-alpha, "feature-complete" only against mocked backends; one live pass on one Mac mini (2026-05-30). [README]

**Clarifying questions (answers most change the recommendations):**
1. Is your true objective the credential or the adoption? If credential, a measured scorecard ships first; if adoption, the demo + 5 buyers ships first. This forks Crux #2.
2. Will you accept that the first real user runs Lighthouse on a *personal/lab machine*, not a managed firm laptop? If no, the locked-down-endpoint wall makes legal unwinnable and you must re-pick the buyer.
3. Have you ever spoken to a real law-firm KM lead who said "yes, I'd run this"? If not, that one conversation outranks every item here.
4. Are you willing to feature-flag (not delete) 3 verticals and 6 modes out of v1.0? Every recommendation assumes yes.
5. Is the entailment/egress gap a known shortcut or a surprise? Determines whether the README is a fixable honesty bug or a deeper QA-process problem.

## 1. Executive verdict

Not yet on a path to a product people want — but the *raw material* for one is here. The biggest strength is genuine, differentiated engineering: a local-first, air-gap-capable research instrument with provenance and audit machinery that frontier tools structurally cannot offer and open-source RAG cannot match on the audit dimension. The biggest threat is that the entire capability surface was built test-first against mocks and is largely unvalidated on live data, while the two load-bearing trust claims are *false in the shipped default*: the egress guard is not on the fetch path (so "data never leaves your hardware" is unenforced), and the entailment gate returns "fully entailed" for every claim when no scorer is installed (the default), with a cosine-similarity fallback that can pass flatly-contradicted claims. The product is also scoped ~3–4x too large for a solo part-timer and written in ~30 proprietary nouns its named buyer cannot parse. **The one move:** collapse to a single legal-confidentiality wedge — Investigate at Standard/Thorough — wire the egress guard, fix the entailment gate to fail honestly, and drive that one spine to *one real measured number* on a real legal corpus.

## 2. Expert memos

### 2.1 Principal Product Manager (JTBD / ICP / scope)

| Claim | Tag | Severity | Who |
|---|---|---|---|
| No defined ICP; README says "regulated-industry," design doc says "researchers across domains" — root cause of over-scope | README | Blocker | Founder; every buyer |
| v1.0 is 3–4 products bolted together (legal/clinical/federal/finance), each a different buyer | README | Blocker | Founder; buyers |
| "Feature-complete" counts capabilities, not validated jobs; core claim is mock-validated | README | Blocker | Founder; buyer |
| 7 modes × 4 depths = 28 combos; 1–2 carry the wedge value, 26 are validation/maintenance debt | INFERENCE | Major | Founder; user |
| README jargon (WEP/ICD-203/RRF/PROV-O) won't parse for the named buyer | README | Major | Buyer |
| No positive wedge use case; only the negative "can't use the cloud tool" | INFERENCE | Major | Founder; buyer |
| Breadth dilutes the credential ("275 modules, 0 users" vs "the tool N firms use") | ASSUMPTION | Opportunity | Founder |
| Whether a regulated buyer will adopt an air-gapped local tool is unverified — highest-risk assumption | NEEDS-USER-TEST | Blocker | Founder; buyer |

**Top 3:** (1) No ICP/wedge — name ONE buyer + ONE job. (2) v1.0 scoped 3–4x too large; cut to one mode/two depths/6–8 sources. (3) Zero real users on real data, yet the artifact reads as done.
**Top opportunity:** Collapse to the legal practice-support wedge ("air-gapped, citation-audited memo on a confidential corpus"), ship only Investigate at Standard/Thorough, rewrite the first screen in buyer language, put it in front of 5 real law-firm researchers on their own files — cuts validation surface ~10x and produces a stronger credential.

### 2.2 Staff Software Architect

| Claim | Tag | Severity | Who |
|---|---|---|---|
| "Measured quality" rests on a 6-query/8-doc disjoint-topic golden set; recall@5=MRR=1.0 is trivial and proves nothing | README | Blocker | Solo builder; KM lead |
| Faithfulness gate is a no-op in the shipped default; HHEM fallback is cosine similarity, not entailment | README | Blocker | HIPAA/legal buyer acting on "verified" claims |
| Contradiction detector is a ~15-pair antonym/negation regex — near-zero recall on real conflicts | README | Major | Any due-diligence buyer |
| Bus-factor: ~49k LOC / 275 modules / 37 APIs / one part-timer = funded-team surface; complexity not paying rent | INFERENCE | Major | Builder; future buyer |
| Mock-first testing hides the LLM-agent failure modes that matter; 2950 green tests = mock self-consistency | README | Major | Builder; first user |
| Deep tier is single-threaded RAM-gated on a 24GB box that has crashed; checkpoint not wired to dispatcher resume | README | Major | Deep-tier buyer; builder |
| Triangulation depends on metadata hygiene the live pipeline isn't audited for | INFERENCE | Minor | Compliance analyst |

**Top 3:** (1) Quality loop is self-certifying — replace the toy golden set with a 100+ query topically-dense labeled set. (2) Faithfulness gate is OFF by default and miscategorized — ship the model or stop calling it an entailment gate. (3) Bus-factor vs surface area; the differentiated Deep tier is unvalidated and not crash-resumable.
**Top opportunity:** Stop building and instrument — collapse to one spine (Investigate/Standard, real Ollama, real bge-m3), drive it to a *measured live* faithfulness/retrieval number with a planted-hallucination adversarial test that actually uses the entailment model. Feature-flag everything that has never run live.

### 2.3 Senior UX Researcher

| Claim | Tag | Severity | Who |
|---|---|---|---|
| ~30 proprietary nouns before the first use case; the learning cliff is presented as the value prop | README | Blocker | Non-builder buyer |
| The good plain-language copy is locked inside the in-app Guide; the README (the selling artifact) is the jargon one | README | Major | Buyers in consideration phase |
| 7 modes × 4 depths = 28 start states named in Lighthouse's verbs, not the user's tasks; Intent Recipes hidden | README | Major | First-time users |
| "Depth scales coverage, never trust" is a counter-intuitive claim that produces the wrong mental model → over-select Deep | INFERENCE | Major | Any depth-selecting user |
| 9 tabs with colliding names (Track/Watch/Activity; Sandbox×2); differentiator buried inside Track | README | Major | New users |
| First-10-min path assumes a dev toolchain; Guide says "about a minute" — contradiction | README | Blocker | Non-technical buyer |
| README leads with mechanism, not outcome; the best plain-language asset is buried in a tab | INFERENCE | Opportunity | Every buyer |

**Top 3:** (1) README is ~30 proprietary nouns; the good copy is locked behind install — selling and onboarding artifacts swapped voices. (2) First-run assumes brew/ollama/docker while the Guide promises a minute; the two surfaces contradict. (3) 28-combo taxonomy in Lighthouse's verbs + a counter-intuitive depth/trust invariant that drives over-selection of Deep.
**Top opportunity:** Promote the in-app "trust wedge" voice to the top of the README/landing page; lead with one outcome sentence + three trust properties in plain words, then a "who it's for," then the pipeline. Add one "I'm not sure — start here" button defaulting mode and depth to auto.

### 2.4 Regulatory & Security Counsel

| Claim | Tag | Severity | Who |
|---|---|---|---|
| README sells live egress enforcement; PRODUCTION_CHECKLIST says the proxy is NOT on the fetch path — direct contradiction | README | Blocker | Every regulated buyer; founder's legal exposure |
| "Single chokepoint" is false: ~24 source adapters fetch via raw httpx with zero egress guard | README | Blocker | Anyone relying on the audit log |
| Telegram channel POSTs research summaries to api.telegram.org outside the guard, not on the allowlist | README | Major | Rule 1.6 / HIPAA buyer |
| Allowlist matches hostname strings, not resolved IPs; subdomain wildcard + no DNS pinning = SSRF/rebinding surface | INFERENCE | Major | Infosec reviewer; ITAR buyers |
| "Tamper-evident" overstated for the insider/local-admin threat; keychain falls back to a 0600 file | INFERENCE | Major | E-discovery / litigation buyers |
| HIPAA/GDPR/ITAR used as labels with no control mapping/DPIA/data-flow; checklist internally inconsistent on the review | INFERENCE | Major | Procurement/InfoSec reviewers |
| "Air-gap capable" is an untested posture, not a verifiable mode; no single egress-kill flag | INFERENCE | Major | ITAR / true air-gap buyers |

**Top 3:** (1) The two authoritative docs contradict on the load-bearing claim; until the guard is wired AND the README reconciled, every compliance claim is unsupported and repeating it is legal exposure. (2) No single egress chokepoint in fact (~24 adapters + Telegram bypass it), so the audit log can't answer "what left my machine?" (3) Compliance terms used as labels without the artifacts a real infosec review demands.
**Top opportunity:** Make air-gap a first-class, verifiable, default-defensible MODE: route the raw-httpx adapters + Telegram through EgressGuardedClient; add `LIGHTHOUSE_AIRGAP=1` that hard-disables all egress with a network-removed test; reconcile the README to claim only what the code enforces + a one-page honest Security Posture doc.

### 2.5 GTM & Positioning Strategist (in-character: law-firm KM lead)

| Claim | Tag | Severity | Who |
|---|---|---|---|
| Two conflicting positioning statements; README narrows to compliance, design doc stays broad | README | Blocker | Founder; named buyer |
| Value prop not legible in one sentence; 90-bullet jargon wall confirms the founder's own fear | README | Blocker | Buyer; conversion rate |
| Differentiation rests on local-first (commoditizable) while "deeper than frontier" is unproven (no Bench run) | README | Major | Founder; buyer |
| No path to money or credential; SaaS already declined, no monetization named; effort leaking to revenue-shaped features | README | Major | Founder's career ROI |
| Headline compliance claims ("no BAA required") outrun validation — ends the conversation with a trained buyer | INFERENCE | Major | Named legal + HIPAA buyer |
| Surface area (subconscious, 24/7, Telegram, Hotness, 9 tabs) reads as attack surface to a conservative buyer | INFERENCE | Major | Named buyer; build hours |
| No competitive teardown vs the real incumbents (Lexis+ AI, CoCounsel, Harvey) | INFERENCE | Major | Named buyer |

**Top 3:** (1) Positioning is split-brained — commit to the narrow law-firm-confidentiality wedge. (2) Value prop is illegible — README is an engineering changelog, not a buyer message. (3) Differentiation and trust both overclaimed relative to evidence.
**Top opportunity:** Collapse to one legible, demonstrable promise: "Run deep, citation-checked research on confidential client documents that never leave your laptop — with a tamper-evident audit trail a partner can defend." Rewrite the README top third, demote 80% of bullets to CAPABILITIES.md, replace "no BAA required" with "verify it yourself with `lighthouse audit-egress`," and record one 3-minute confidential-matter screen capture as the pitch + credential.

### 2.6 Deep-Research / IR Domain Expert

| Claim | Tag | Severity | Who |
|---|---|---|---|
| Entailment/faithfulness gate is a no-op by default (score_claim returns 1.0 when no scorer importable) | README | Blocker | Every default-install user |
| HHEM fallback computes cosine similarity, not entailment — can silently certify contradicted claims | INFERENCE | Blocker | Users with sentence-transformers but not MiniCheck |
| "Proof" that grounding catches hallucinations is one hardcoded 3-sentence corpus testing id-range validation | README | Major | Domain reviewer; founder |
| Contradiction detection is shallow lexical matching despite "3-layer" framing | INFERENCE | Major | Compliance / litigation analyst |
| Evidence→probability mapping is a hand-tuned uncalibrated prior, not a calibrated estimate | README | Major | Anyone trusting the WEP band |
| Resolver auto-resolves from up to 3 general-web docs with no independence requirement | INFERENCE | Minor | Auto-calibration users |
| Hybrid retrieval is competently built but its quality knobs are untuned defaults presented as SOTA | README | Minor | IR reviewers |
| Adversarial refutation collapses to "has a citation → stands" offline | INFERENCE | Minor | Buyers comparing the "survives refutation" claim |

**Top 3:** (1) The headline trust gate is dark on the default install. (2) The cosine fallback is methodologically wrong and certifies hallucinations green. (3) The "measured, not claimed" numbers are not measured against any real benchmark.
**Top opportunity:** Run the minimum credible live-validation pass that produces ONE checkable number: a 25–50 question legal/compliance gold set with annotated supporting/contradicting passages; run the full live pipeline with MiniCheck installed; report precision@5/recall@5, human-adjudicated faithfulness on a 10-claim contradiction subset (prove MiniCheck catches them and cosine does NOT), and Brier. Make MiniCheck a hard dependency for high-stakes runs and disable the cosine fallback.

### 2.7 Skeptical Target Buyer (KM Lead, 35-attorney firm, Rule 1.6)

| Claim | Tag | Severity | Who |
|---|---|---|---|
| Quick-start drops me off before value: 5 tools (brew, Ollama, pip, Docker, daemon) + 10GB pull before one result | README | Blocker | Me; any non-developer I'd roll this out to |
| "pip install lighthouse-ai" doesn't work — nothing on PyPI, only a local 0.1.0 wheel | README | Blocker | Any external user following the quick-start |
| Compliance pitch ("no BAA required," "FedRAMP-adjacent") would get me fired if I repeated it; tool egresses by default | README | Blocker | Me, InfoSec, the firm's E&O posture |
| Core product claim is admittedly unvalidated (built against mocks; one Mac-mini pass) | README | Major | Me; the attorneys relying on citations |
| Drowning in jargon I can't translate to my boss or 35 busy users | INFERENCE | Major | Me selling internally; adopters |
| Hardware bar understated — firm laptops are 16GB Windows; no Windows support | INFERENCE | Major | Procurement/IT; non-Mac users |
| No release date, no support commitment, no second human | ASSUMPTION | Major | Me justifying a multi-seat commitment |
| Whether output is good enough on a real legal corpus is unknowable from the repo | NEEDS-USER-TEST | Opportunity | Me, before any pilot |

**Top 3:** (1) Install is a non-starter for my world and the headline command doesn't even work. (2) The compliance language is overstated and would get me in trouble. (3) The core trust claim is admittedly unvalidated, so I can't promise a partner the citations are real.
**Top opportunity:** Build one honest, narrow, signed on-ramp — a signed .app or a single `lighthouse onboard` that auto-pulls a RAM-appropriate model, skips Docker, defaults egress OFF, and gets me from download to one cited answer on my own folder in under 15 minutes, plus a one-page jargon-free "where your data goes" sheet for InfoSec. This is mostly subtraction.

### 2.8 Technical Writer / DevRel

| Claim | Tag | Severity | Who |
|---|---|---|---|
| README is written for the founder; ~90 dense bullets / ~2,500 words read as a build-log, not a pitch | README | Major | Prospective buyer |
| Advertised install path is broken for a stranger (pip install of an unpublished package) | README | Blocker | Anyone installing from the README as written |
| No buyer-facing onboarding doc exists anywhere across 210 markdown files | README | Major | Buyer; first-time user |
| Docs set is unnavigable: 210 files, 5 un-indexed root docs, dev working-notes leaking into the public surface | README | Major | Contributor; buyer judging maturity |
| README's own honesty undercuts the sale: sells compliance up top, discloses caveats 50 lines later | README | Major | Regulated buyer; founder's credibility |
| Status section is a metrics wall that signals to engineers, not buyers | INFERENCE | Minor | Non-technical buyer |
| No screenshot/GIF/sample output for a tool whose pitch is a dashboard | INFERENCE | Opportunity | Prospective buyer |
| Whether jargon smothers the buyer needs one real non-author reader to attempt the quick-start | NEEDS-USER-TEST | Major | Founder's go/no-go on README |

**Top 3:** (1) Broken primary install path — make "uv sync from source" the primary, footnote the PyPI line. (2) No buyer-facing entry doc exists. (3) README is a build-log trying to be both sales page and status tracker.
**Top opportunity:** Split the README into a short buyer-facing pitch (one problem sentence, three plain outcomes, ONE annotated screenshot, a working 10-minute first-run) + a separate ARCHITECTURE/STATUS doc, and write the missing GETTING_STARTED.md with an honest "not yet safe to trust for X" box.

## 3. Cruxes

**Crux 1 — Under-built vs over-exposed trust machinery** *(Architect, IR Expert vs UX, Buyer)* — RESOLVED.
Architect/IR want MORE verification (MiniCheck hard-dep, kill cosine fallback, real gold set); UX/Buyer say the product already drowns the buyer in trust jargon. **Resolution (false conflict — different layers):** make verification HONEST without making it louder. Ship MiniCheck as a hard dependency for high-stakes runs, DELETE the cosine HHEM fallback, and report `entailment_checked=False` instead of silently returning 1.0. Simultaneously HIDE the nouns — the buyer reads "every sentence is checked against your sources; uncheckable claims are flagged, not hidden," never "WEP band." Engine fix and surface fix are not in tension.

**Crux 2 — Measurement artifact vs demo artifact** *(Architect vs PM/GTM)* — **🔶 OPEN TRADE-OFF.**
Both want to narrow to one wedge, but disagree on the single next deliverable: Architect wants a defensible measured scorecard; GTM/PM want a buyer-legible demo + 5 real buyers. The two share ~70% of the work (both need the live spine on a real legal corpus); the fork is the last mile. **Strong default:** measure-small first (25–50 query gold set + 10-claim adversarial subset, days not weeks), because without one real number the README's trust claims stay INFERENCE and the demo is unsellable to a Rule-1.6 buyer trained to distrust unqualified claims — then package that same run as the demo. Invert only if you value adoption signal over credential. Founder must decide.

**Crux 3 — Zero-config first result vs local-first reality** *(Buyer, UX vs Architecture)* — **🔶 OPEN TRADE-OFF (partially fixable; residual hard floor).**
Buyer would never complete the install; UX wants one-button start; but local-first hard-requires pulling and running a multi-GB local model. **Resolution:** (1) fix the lie — demote `pip install` to a footnote, make `uv sync` primary today; (2) kill Docker/daemon from first-run, default to the in-memory/SQLite spine, auto-select a RAM-appropriate model; (3) the IRREDUCIBLE floor — the buyer must still install Ollama + pull a multi-GB model, which no packaging fixes on a no-admin firm laptop. Honest read: target the KM lead's personal/lab machine for the first real user, not the managed endpoint.

**Crux 4 — Can you lead with the air-gap wedge?** *(Security Counsel, Buyer vs GTM)* — RESOLVED.
GTM is right that local-first + provenance is the only durable wedge; Counsel/Buyer are right the current claim is a misrepresentation (egress guard not on the fetch path, ~24 adapters + Telegram bypass it, "no BAA required" is legal exposure). **Resolution (not a trade-off — wedge correct, claim unshippable, fix solo-sized):** mandatory sequence before ANY compliance language ships — wire the raw-httpx adapters + Telegram through EgressGuardedClient; add `LIGHTHOUSE_AIRGAP=1` with a network-removed test; reconcile the README to claim only what the code enforces + a one-page Security Posture doc. The hard parts already exist; this is wiring + truthful scoping.

**Crux 5 — Commit to legal, or stay cross-domain?** *(PM/GTM vs Architect, with design doc dissent)* — RESOLVED.
**Resolution:** commit to the legal practice-support wedge for v1.0; demote the other three verticals and six modes to a clearly-labeled roadmap behind a "future" flag — do NOT delete the code. Tie-breakers: the Architect is vertical-agnostic so legal satisfies the measurement spine too; breadth already built is a maintenance liability for a solo builder, not an asset; a finished narrow tool is a stronger credential than "275 modules, 0 users." Honor the one dissent: reconcile the *design doc to the README's narrowing*, not the reverse.

**Crux 6 — Expose Deep tier in v1.0?** *(UX, Architect vs the differentiation story)* — RESOLVED.
**Resolution:** do NOT expose Deep tier in the v1.0 wedge; ship Investigate at Standard + Thorough only and present Deep as "coming soon." The UX over-selection risk (the risk-averse buyer wrongly prefers Deep) and the Architect fragility risk (single-threaded, hours, crashes the dev box) COMPOUND. The "frontier can't reach this depth" moat is unproven anyway. Defer until crash-resumable AND measured. (Note: dispatcher.py L584–596 does appear to wire checkpoint/resume — fix that README inconsistency, but still defer.)

**Crux 7 — Do honesty caveats go up with the pitch or down with the architecture?** *(Tech Writer, Counsel vs GTM simplification)* — RESOLVED.
**Resolution:** caveats go UP, with the pitch. The Tech Writer's split is right, but the top section carries a prominent "What this does NOT yet claim" box (not-validated-on-your-corpus, egress-guard-being-wired, no-independent-security-review). The named buyer is trained to distrust unqualified claims; leading with honest limits DISARMS the risk reflex. Demote the engineering volume (test counts, RRF k=60, module counts), not the honesty.

## 4. Customer-confusion register

| # | Issue | Severity | Who it hurts | Fix |
|---|---|---|---|---|
| 1 | No ICP/wedge; design doc ("researchers across domains") and README ("regulated knowledge workers") name different buyers — root cause of over-scope | Blocker | Founder; every buyer | Amend design doc to "v1.0 = legal KM-lead; cross-domain = roadmap"; reconcile README to the same buyer + one job |
| 2 | Headline install path `pip install lighthouse-ai` fails at step 2 — nothing on PyPI, only a local 0.1.0 wheel | Blocker | Every top-down evaluator | Make `uv sync from source` the labeled primary path today; footnote the PyPI line |
| 3 | Load-bearing compliance claim contradicted by the project's own checklist and unenforced in code (egress proxy not on fetch path; 25 adapters + Telegram bypass it) | Blocker | Every regulated buyer + GC; founder's legal exposure | Wire adapters + Telegram through EgressGuardedClient; add `LIGHTHOUSE_AIRGAP=1` + network-removed test; replace "no BAA required" with "verify with `lighthouse audit-egress`" |
| 4 | Entailment/faithfulness gate is a no-op on the default install (score_claim returns 1.0 when no scorer importable) | Blocker | Every default-install user; KM/HIPAA analyst | MiniCheck hard-dep for high-stakes; report `entailment_checked=False` instead of 1.0; stop calling it a gate unless wired |
| 5 | HHEM fallback is cosine similarity, not entailment — silently certifies contradicted claims with a green number | Blocker | Users with sentence-transformers but not MiniCheck | Delete the cosine fallback (entailment.py L96–101); report unchecked, never a fabricated pass |
| 6 | First-run assumes a dev toolchain (brew + 10GB pull + Docker + daemon) while the in-app Guide promises "about a minute" | Blocker | Non-technical buyer; managed endpoints | Kill Docker/daemon from first-run; default in-memory/SQLite; auto-select model; fix the Guide copy; document the irreducible Ollama floor |
| 7 | README is a ~90-bullet build-log forcing ~30 proprietary nouns before any use case; good copy locked in the in-app Guide | Major | Named KM lead; every non-engineer evaluator | Split README: short buyer pitch (problem + 3 plain outcomes + 1 screenshot + 10-min run) up top; bullets/metrics to a separate doc |
| 8 | v1.0 scoped ~3–4x too large (7 modes × 4 depths × 37 multi-vertical sources) | Major | Founder (maintenance); buyers (no deep vertical) | Ship only Investigate at Standard+Thorough over 6–8 legal/federal sources; feature-flag the rest |
| 9 | Quality loop is self-certifying — 6-query/8-doc disjoint golden set; recall@5=MRR=1.0 proves nothing; toy benchmark | Major | Builder; domain reviewer; buyer | Build a 25–50 query legal gold set (multi-relevant + 10-claim adversarial subset); run live; gate trust language on one real number |
| 10 | Compliance terms used as labels with no control mapping/DPIA/data-flow; checklist internally inconsistent on the security review | Major | Procurement/InfoSec/legal reviewers | Drop the logos; ship a one-page honest Security Posture doc; reconcile the checklist |
| 11 | Deep tier is the headline differentiator but least-validated, hardware-fragile, and most likely to be wrongly selected | Major | Risk-averse buyer; founder's dev box | Don't expose Deep in v1.0 ("coming soon"); ship Standard+Thorough; SHOW the coverage-vs-trust invariant instead of asserting it |
| 12 | Bus-factor vs surface area: ~49k LOC / 275 modules / 37 APIs / one part-timer; complexity not paying rent | Major | Builder; future buyer (abandonment) | Freeze the spine; pin deps; live contract-tests for 6–8 wedge sources only; everything else behind the future flag |
| 13 | Mock-first testing hides LLM-agent failure modes; 2950 green tests = mock self-consistency | Major | Builder; first external user | Run the wedge job end-to-end on real Ollama; fix what breaks; add real-backend integration tests for the spine before more features |
| 14 | Contradiction detector is a ~15-pair antonym/negation regex with near-zero recall, sold as a trust guarantee | Major | HIPAA/litigation analyst | Stop selling "3-layer detection" until it has measured recall; route through the LLM denoiser and measure, or scope the claim down |
| 15 | 9 dashboard tabs with colliding names (Track/Watch/Activity; Sandbox×2); differentiator buried in Track | Minor | New users; differentiator hunters | Rename to disambiguate (Track→Forecasts, Activity→Runs); rename the scanner; promote or cut Intelligence |
| 16 | README leads with mechanism not outcome; no screenshot/GIF/sample output anywhere | Minor | Every first-impression buyer | Lead with one outcome sentence + 3 trust properties + 1 annotated screenshot; caveats up in the same eyeful |

## 5. Feature & capability register

| # | Item | Action | Impact | Effort | When | Rationale |
|---|---|---|---|---|---|---|
| 1 | Name ONE buyer + ONE wedge job (amend design doc + README to law-firm KM lead / air-gapped citation-audited memo) | Add | High | Low | Now | Root cause of over-scope; no copy/demo/scope-cut possible until fixed. Pure decision + edit. [README] |
| 2 | Cut v1.0 to Investigate × {Standard, Thorough} over 6–8 legal/federal sources; feature-flag the rest | Cut | High | Med | Now | 3–4x over-scoped for solo; breadth is debt, not asset. Keep the code, stop selling it as v1.0. [README/INFERENCE] |
| 3 | Replace "HIPAA/ABA 1.6/GDPR/ITAR compliant" + "no BAA required" with falsifiable "verify with `lighthouse audit-egress`" | Cut | High | Low | Now | Egress proxy not on the fetch path; repeating the claim is legal exposure. [README] |
| 4 | Route 23 raw-httpx adapters + Telegram through EgressGuardedClient | Add | High | Med | Now | Audit log can't answer "what left my machine?" until wired — the entire wedge. Hard parts exist. [README] |
| 5 | Add `LIGHTHOUSE_AIRGAP=1` hard-kill flag + network-removed test | Add | High | Med | Now | Air-gap is currently posture with no enforcing switch; web-retrieval egresses by default. [README] |
| 6 | Delete cosine HHEM fallback; report `entailment_checked=False` instead of returning 1.0 | Cut | High | Low | Now | Green-but-false faithfulness number is worse than none for a regulated buyer. [README] |
| 7 | Make MiniCheck a hard dependency for high-stakes runs | Add | High | Low | Next | Headline gate is dark on the default install. Cost is ~770M install weight. [README] |
| 8 | Build a 25–50 query legal gold set + adversarial subset; run live; report one real precision@5/faithfulness/Brier | Add | High | Med | Now | golden.py (6/8 disjoint) measures nothing; until one real number exists, trust claims are INFERENCE. Days not weeks. [README] |
| 9 | Make `uv sync from source` the primary install path; footnote `pip`/`uvx` | Cut | High | Low | Now | Nothing on PyPI; stranger fails at step 2. Zero-cost honesty fix. [README] |
| 10 | Kill Docker/daemon from first-run; default in-memory/SQLite; auto-select model | Cut | High | Low | Next | Removes 2 of 5 tools; catalog already budget-aware. [INFERENCE] |
| 11 | Do NOT expose Deep tier in v1.0 ("coming soon") | Defer | Med | Low | Next | Over-selection + crash/non-resume risks compound; moat unproven. Fix the README/resume doc inconsistency. [README/INFERENCE] |
| 12 | Rewrite README top third: problem + 3 plain outcomes + 1 screenshot + prominent "does NOT yet claim" box | Add | High | Low | Now | First screen forces ~30 nouns then discloses caveats 50 lines later. Plain copy already exists in-app. [README] |
| 13 | Move 90 capability bullets + test-count Status wall into a separate ARCHITECTURE/CAPABILITIES doc | Merge | Med | Low | Now | Test count is volume, not buyer evidence. Same edit pass as the rewrite. [README] |
| 14 | Write the missing GETTING_STARTED.md (10-min first run + honest "not safe to trust for X" box) | Add | Med | Low | Next | No first-win doc across 210 markdown files. A day of writing. [README] |
| 15 | One-page honest Security & Compliance Posture doc (data-flow, what egresses when) | Add | Med | Low | Next | Honesty-plus-proof outconverts any logo; solo-sized once the guard is wired. [INFERENCE] |
| 16 | Record a 3-minute confidential-matter screen capture as pitch + credential | Add | Med | Low | Next | No screenshot/output exists; reuses the same live spine run. Package once, use twice. [INFERENCE] |
| 17 | Show the depth coverage-vs-trust invariant in the UI instead of asserting it | Add | Low | Low | Later | Counter-intuitive caption produces wrong model; cheap label fix once Deep is hidden. [INFERENCE] |
| 18 | Put the wedge in front of ~5 real law-firm researchers on their own machine/files | Add | High | Med | Next | Entire thesis rests on this; zero evidence any buyer said yes. One real user > 1000 tests. [NEEDS-USER-TEST] |
| 19 | Replace the toy research_benchmark with a real-data harness driven by the gold set | Merge | Med | Low | Next | Only proves id-range validation; folds into the gold-set build. [README] |
| 20 | Strengthen contradiction detection beyond 15 antonym pairs | Defer | Med | High | Later | Near-zero recall undercuts the claim, but robust semantic detection is hard. Scope the claim down for now. [INFERENCE] |
| 21 | Audit ingestion metadata hygiene (skill_id/source) so triangulation can't be inflated | Defer | Low | Med | Later | Second-order behind egress/entailment/ICP fires. [INFERENCE] |
| 22 | Decide + state explicitly: credential artifact, not a business; stop building revenue-shaped features | Cut | Med | Low | Next | SaaS already declined; effort leaking to governor cost reports / tool-policy tiers with no thesis. [README] |
| 23 | Competitive teardown vs real incumbents (Lexis+ AI, CoCounsel, Harvey) | Defer | Med | Low | Later | Buyer's first question has no answer, but premature while the buyer can't install it. [INFERENCE] |
| 24 | Trim public docs surface (210 files, un-indexed root docs, dev notes); add role-based entry map | Cut | Low | Low | Later | Tidiness signals maturity; low-stakes cleanup behind the fires. [README] |
| 25 | Pin deps + live API-contract tests for the 5 wedge sources | Add | Med | Med | Later | Drift vectors for a solo maintainer; scope to wedge sources only. [INFERENCE] |
| 26 | Build SaaS / hosted control plane | Cut | Low | High | Never | Declined on principle; forfeits the local-first moat. [README] |
| 27 | Cross-platform Windows support | Defer | Med | High | Later | Gates managed-endpoint adoption — the lowest-probability path. Validate the Mac/personal wedge first. [README] |

## 6. Prioritized roadmap

Calibrated to a solo part-time builder. If you do nothing else, do these in this order — each later bet depends on the earlier ones being true.

**Bet 1 — Stop the lies (1–2 evenings).** Demote `pip install` to a footnote, make `uv sync` primary; replace "HIPAA/no BAA required" with the falsifiable egress claim; reconcile the design doc + README to ONE buyer (legal KM lead) + ONE job. *Effort: hours. Leading indicator:* a stranger can follow the README without failing at step 2, and you can state the buyer/job in one sentence without hedging.

**Bet 2 — Make the wedge claim TRUE in code (1–2 weekends).** Wire the ~23 raw-httpx adapters + Telegram through EgressGuardedClient; add `LIGHTHOUSE_AIRGAP=1` + a network-removed test; delete the cosine HHEM fallback; make `score_claim` report `entailment_checked=False` instead of 1.0. *Effort: days. Leading indicator:* `lighthouse audit-egress` truthfully logs every outbound call, and the research slice runs green with the network physically removed.

**Bet 3 — Cut to one spine (1 weekend).** Feature-flag the other 3 verticals, 6 modes, and Deep tier behind a "future" flag (don't delete). Ship Investigate × {Standard, Thorough} over 6–8 legal/federal sources. *Effort: days. Leading indicator:* the v1.0 surface you must validate/document/maintain dropped ~10x; nothing outside the spine is sold or documented as ready.

**Bet 4 — Produce ONE real number (a few days, MiniCheck installed).** Build a 25–50 query legal gold set with annotated supporting/contradicting passages + a 10-claim adversarial subset; run the full live pipeline; report precision@5, human-adjudicated faithfulness, Brier; prove MiniCheck catches contradictions the cosine path passed. *Effort: days. Leading indicator:* one defensible measured number you'd let a skeptical domain expert audit; every README trust claim now gated on it.

**Bet 5 — Package the same run + rewrite the front door (1 weekend).** Rewrite the README top third (problem + 3 plain outcomes + 1 screenshot + "does NOT yet claim" box); move bullets/metrics to a CAPABILITIES doc; write GETTING_STARTED.md + the Security Posture doc; record the 3-minute confidential-matter capture. *Effort: ~2 days writing. Leading indicator:* a non-author KM-lead reader reaches a cited answer (or DMs you) without bouncing on jargon.

**Bet 6 — Put it in front of 5 real buyers (ongoing).** Target personal/lab machines, not managed endpoints. Ask: would you run this, and does your hardware survive it. *Effort: outreach. Leading indicator:* at least one real law-firm researcher runs it on their own files — the single signal that converts "275 modules, 0 users" into a credential.

## 7. The one thing

**Collapse to the legal-confidentiality wedge and make its one promise simultaneously TRUE and MEASURED: wire the egress guard, fix the entailment gate to fail honestly, ship only Investigate at Standard/Thorough, and drive that one spine to a single real faithfulness/retrieval number on a real legal corpus.**

This is one move because the pieces are inseparable: the wedge ("your confidential corpus never leaves your machine, every claim is checked against your sources, here's the audit trail") is only sellable if the egress guard actually enforces it AND the entailment gate actually checks — and it's only believable to a Rule-1.6 buyer if there's one number behind it. It directly attacks both of the founder's stated fears (mock-validation and jargon overload) and serves the credential goal better than any breadth.

**Strongest objection:** "Narrowing throws away the breadth I already built, and measurement is slow — I should keep momentum shipping features." **Rebuttal:** the breadth is already a maintenance liability accruing validation debt for a solo maintainer, not an asset; feature-flagging preserves the code at zero cost while stopping the bleed. And measurement isn't slow here — it's days, sharing ~70% of its work with the demo, and without one real number every trust claim in your README is INFERENCE that a trained buyer will reject on sight, making the next 1,000 mock tests worthless.

**What would change my mind:** (1) A real law-firm KM lead tells you in a conversation that they'd adopt the *broad* cross-domain tool and don't care about a measured faithfulness number — then adoption, not measurement, leads. (2) The named buyer's hardware reality (no-admin firm laptops, no personal/lab machine) makes legal structurally unreachable — then re-pick the buyer before narrowing onto legal. (3) Your true goal is purely the credential with zero adoption ambition — then a pure measured scorecard, not the wedge+demo, is the cheaper artifact.