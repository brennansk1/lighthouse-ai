# modes/

The five research modes (design §9): pure orchestrators that compose the
RAG, gateway, governor, compounding, and verification subsystems into
complete research workflows. No direct I/O — all external access is
threaded through `gateway` and `embed_titles` parameters.

## Public surface

- `monitor.py` — Mode A. `run_monitor`, `MonitorItem`, `MonitorReport`,
  `ClassifiedItem`, `MonitorState`, `default_salience`,
  `make_hotness_salience` (hotness-backed salience scorer). Continuous
  polling cycle: SHA-256 URL dedup → optional semantic near-duplicate
  filter (cosine ≥ 0.97) → salience classify → split alerts (≥ 0.7)
  vs digest. Idempotent over (source, item_id).
- `deepdive.py` — Mode B. `run_deepdive`, `DraftReport`, `Section`,
  `compact`, `CompactedContext`. TTD-DR backbone (Google §9.2): skeleton
  → researcher fan-out per section → denoiser/synthesizer merge → up to
  N rounds until discovery-progress curve flattens
  (`_discovery_progress < progress_threshold`). ReSum-style context
  compaction (`compact`) carries established facts and open questions
  between rounds (§14.11). Auto-wires Mode E on load-bearing sections
  that surface `[CONTRADICTION]` markers.
- `quc.py` — Mode C. `ask`, `QUCSession`, `Turn`. Multi-turn chat:
  appends user turn, fans out to RAG when the query exceeds
  `retrieve_threshold` words, drafts a cited answer. `render_history`
  truncates oldest turns to a char budget (production: ReSum compaction).
- `digest.py` — Mode D. `aggregate_digest`, `Digest`, `DigestSection`.
  Pure aggregator: bucketes `MonitorReport` objects by topic, takes all
  alerts + top-5 digest items per topic, sorts topics by alert count.
  No LLM call; the caller handles write-to-file and notification.
- `debate.py` — Mode E. `run_debate`, `DebateResult`, `Perspective`,
  `PerspectiveResponse`, `PERSPECTIVES`. Four canonical perspectives
  (steelman, devils_advocate, base_rate, fragility) each critique a
  claim+draft; a judge tallies agreements and unresolved disputes. Used
  directly by the CLI and auto-wired from `deepdive._extract_debate_subquestions`.

## Calls into

- `..rag.hybrid.HybridSearch` — evidence retrieval in Mode B and C.
- `..gateway.Gateway` — researcher/synthesizer/aux_context LLM roles
  (Modes B, C, E); absent gateway degrades each mode to a deterministic
  stub.
- `..governor.scheduler_gate.SchedulerGate` — `permit()` wraps every
  LLM call in Modes A (embed) and B; passed as optional `gate` parameter.
- `..compounding.hotness` — `hotness_at`, `TOPIC_CREATION_THRESHOLD`
  used by `make_hotness_salience` in Mode A.
- `..framing.run_framing` — question decomposition into sub-questions
  and load-bearing set at the start of Mode B.
- `.debate.run_debate` — Mode B imports Mode E for contradiction
  resolution within the research loop.

## Called by

- `..pipeline` — orchestrates modes as pipeline stages.
- `..cli` — dispatches user commands to the appropriate mode.

## Invariants

- Every mode function is pure over its I/O seams: no direct file, network,
  or DB access. Statefulness (dedup ledger, session history) is explicit in
  parameters.
- A mode that receives `gateway=None` must complete without error, returning
  a deterministic stub result.
- Mode B terminates in at most `max_rounds` rounds regardless of discovery
  progress or gateway behavior.
- Mode A salience threshold for alerts is fixed at 0.7 (`ClassifiedItem.is_alert`).
