# verification/

Verification, calibration, and compounding knowledge (design §22, §23):
deterministic claim-quality gates, WEP-band confidence accounting,
Brier-scored position tracking, auto-resolution of past-deadline positions,
and an HMAC-chained audit log that makes every tool-policy refusal
tamper-evident.

## Public surface

- `discipline.py` — `check`, `extract_claims`, `check_source_diversity`,
  `downgrade_wep`, `Claim`, `DisciplineReport`. Source-diversity +
  entailment gate (§12): regex claim extraction, citation-coverage floor,
  optional two-source rule for high-stakes claims, MiniCheck/HHEM
  entailment scoring when available. `downgrade_wep` scales stated
  probability by citation coverage before WEP mapping — honest-over-impressive.
- `resolver.py` — `run_resolver_pass`, `attempt_auto_resolve`,
  `classify_resolution_kind`, `ResolutionResult`. Retrieval-augmented
  auto-resolver (Halawi et al., NeurIPS 2024): re-researches positions
  at their `resolve_by` deadline; skips human-only claims; commits Brier
  score on resolution. Respects a `GenerationGuard` to prevent
  double-writes when a newer pass overtakes a slow one.
- `positions.py` — `record_position`, `resolve_position`, `score_all`,
  `Position`. WAL SQLite position registry: every high-confidence emitted
  claim gets a row (WEP band + probability + 90-day default deadline);
  `score_all` returns aggregate calibration metrics.
- `wep.py` — `WEP_BANDS`, `WEPBand`, `band_for_probability`, `parse_band`.
  Five ICD-203/Kent WEP bands (remote → almost_certain); every claim
  carries one.
- `brier.py` — `brier_score`, `mean_brier`. Squared-error calibration
  score; lower is better; range [0, 1].
- `entailment.py` — `score_claim`, `score_claims`, `available`,
  `MINICHECK_THRESHOLD`. Lazy-loaded entailment scorer: prefers
  MiniCheck-Flan-T5-Large (MIT, 770 M params); falls back to
  HHEM-2.1-Open (cosine proxy); returns 1.0 (no penalty) when neither
  is installed so `discipline.check` degrades to regex-only coverage.
- `audit_chain.py` — `append_event`, `seal_event_chain`,
  `verify_audit_chain`, `AuditEvent`, `resolve_secret`. HMAC-chained
  audit log: each row seals over `(prev_hmac ‖ seq ‖ ts ‖ actor ‖
  event_type ‖ payload)`. Chain key lives in the OS keychain in
  production; explicit `secret` accepted for tests.
- `hypotheses.py` — `add_hypothesis`, `update_hypothesis`,
  `list_hypotheses`, `Hypothesis`. Minimal CRUD on the hypotheses table
  (statuses: open / supported / refuted / retired).
- `skills.py` — `add_skill`, `list_skills`, `increment_use`, `Skill`.
  Reusable research procedures (§23.2); stored in `state.db`; full
  execution runtime arrives in a later sprint.

## Calls into

- `..rag.hybrid` — evidence retrieval used by the resolver to re-research
  a position at its deadline (production path; gateway is the current seam).
- `..subconscious.overlap.GenerationGuard` — resolver pass claims a
  generation and aborts writes if overtaken.
- `..governor.scheduler_gate` — LLM-bound resolution calls run under a
  host-courtesy `permit()` (wired by the caller; not imported directly).
- `..persistence.open_db` — PRAGMA-disciplined SQLite for positions,
  hypotheses, skills, and audit_events tables.

## Called by

- `..pipeline` — `discipline.check` gates synthesis blocks before they
  reach the user; `record_position` logs high-confidence claims.
- `..modes.deepdive` — `discipline.check` used as an entailment gate
  seam; `run_resolver_pass` kept as a background operation.
- `..governor.tool_policy` — tool-policy refusals logged via
  `audit_chain.append_event`.

## Invariants

- `discipline.check` is deterministic and side-effect-free; it never
  writes to any store.
- `downgrade_wep` always returns a WEPBand; it never raises on valid
  probability input.
- `run_resolver_pass` with `dry_run=True` never writes to the database.
- `entailment.score_claim` returns 1.0 (neutral / no penalty) when no
  scorer is available — discipline degrades gracefully, never hardens.
- `audit_chain.verify_audit_chain` returns an empty list iff the chain
  is intact; any tampered seq appears in the returned list.
