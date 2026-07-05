# Lighthouse — Goal Statement

**What it is, for whom.** Lighthouse is a local-first, air-gapped deep-research
instrument. A user with a confidential corpus (legal matter, patient set, deal
room) points it at documents that cannot leave their machine and gets back
deep, citation-audited research: seven research modes (Watch, Ask, Investigate,
Survey, Reconstruct, Decide, Adjudicate), each producing a typed artifact, at
four depth tiers (Quick → Deep), run entirely on local hardware and local
models (Ollama), reviewed in a web dashboard or TUI.

**The competitive bar.** Lighthouse aims to be a deep-research tool **on par
with or better than Claude and Gemini deep research** — while running entirely
on local LLMs mapped to the user's hardware tier. The wedge is structural, not
raw model power: cloud deep research time-boxes to ~10–20 min (≈ Standard
tier); Lighthouse's Thorough and Deep tiers buy the same acquire-as-you-learn
loop more time, more sources, adversarial refutation, and a coverage critic —
depth a time-boxed service can't reach — plus enforced citation honesty
(entailment-gated, zero fabricated citations) that cloud services don't
enforce. Hardware-mapped model selection (tier-curated picks, admission gate,
no swap) is what makes that depth feasible on modest local machines. Every
design decision should be weighable against this bar: does it close the gap
with cloud deep research, or widen Lighthouse's structural advantages
(unbounded depth, verifiable grounding, provable privacy)?

**What "quality" means in this domain, ranked:**
1. **Trustworthiness over speed.** Zero fabricated citations is a hard
   invariant at every depth tier — a claim is entailed by a real cited source
   chunk or it is dropped/flagged, never asserted.
2. **Privacy is falsifiable, not asserted.** The corpus stays on the machine;
   `lighthouse audit-egress` and `LIGHTHOUSE_AIRGAP=1` let the user *prove* it.
   No feature may add an egress path outside the guard.
3. **Auditability.** Every run is HMAC-chain logged (model, sources, content
   hash), tamper-evident, replayable.
4. **Honesty about status.** The project deliberately does not overclaim
   (pre-alpha, validation phase, "what this does NOT yet claim" in README).
   Changes must preserve that honesty — no aspirational claims in docs or UI.
5. **Hardware adaptivity.** Runs on modest hardware (dev box: Apple M4 24 GB,
   T2 tier); an admission gate prevents swap; model picks are tier-curated.

**Implicit domain invariants:**
- Regulated-setting posture (legal/clinical/financial): data integrity and
  provenance beat features.
- Tests never require a real LLM backend by default (`LIGHTHOUSE_REAL_BACKEND=1`
  opt-in); tests never start background processes (dev-box stability).
- MIT-licensed project: no copyleft (AGPL/GPL) dependency may become a default
  path (see the existing `pdf-fast` extra precedent).
- Local-first: no cloud service dependency may enter the default path.

**Current phase (2026-07):** feature-complete for v1.0 scope; live validation
on real hardware done (17 bugs fixed); remaining release work is live-only
gates: soak, signing, cross-platform, PyPI. The next increment of value is
release-readiness and polish, not new research surface.
