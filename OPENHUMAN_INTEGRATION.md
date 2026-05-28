# Lighthouse ← OpenHuman: Integration Status & Plan

This tracks the adoption of selected subsystems from OpenHuman
(`tinyhumansai/openhuman`) into Lighthouse. It is the canonical build tracker for the
integration; each item maps to a concrete Lighthouse file path with tests and exit
criteria. Scope discipline: we take only the engineering substrate that strengthens the
local-first, no-egress, auditable-research mission — everything cloud/consumer-surface is
rejected (see §9).

Legend: ✅ done & tested · 🟡 partial · ⬜ not started.

## Status table

| # | Feature (OpenHuman origin) | Lighthouse target | Priority | Status |
|---|----------------------------|-------------------|----------|--------|
| 1 | **Scheduler Gate** — host-condition throttle for background AI | `governor/scheduler_gate.py`, wired into Governor + Deep-Dive + pipeline | **P0** | ✅ |
| 2 | **Hotness Score** — deterministic entity-importance formula | `compounding/hotness.py` + Monitor salience | **P0** | ✅ |
| 4 | **Tick overlap guard** — generation-counter cancellation | `subconscious/` + `verification/resolver.py` | P1 | ⬜ |
| 3 | **Reflection / Escalation split** — passive vs actionable findings | `subconscious/` + dashboard Intelligence page | P1 | ⬜ |
| 5 | **TokenJuice-style payload compaction** — deterministic pre-context compaction | `rag/compaction.py` | P2 | ⬜ |
| 6 | **Tool-Policy risk tiers** — risk-tiered prompt-visibility + runtime enforcement | extend tool-exposure logic | P2 | ⬜ |
| 8 | **Archivist clean→compose→append** — finished job → durable corpus | `compounding/archivist.py` | P3 | ⬜ |
| 7 | **Per-module README + Calls-into/Called-by convention** | repo-wide docs | P3 | ⬜ |

Build order: **1 → 2 → 4 → 3 → 5 → 6 → 8 → 7**. (1 and 2 complete.)

---

## 1. Scheduler Gate — ✅ DONE

`governor/scheduler_gate.py`. The Governor meters budget (token buckets) and RAM (won't
OOM); the gate adds the third axis — **host pressure**: is now a polite time to run?

- `PauseReason`, `Policy` enums; `Signals`, `SchedulerGateConfig` dataclasses.
- `current_policy(cfg, sig)` — total function. Order: user-off → server/aggressive →
  battery → cpu → normal. Battery floor 80% (`<` throttles), CPU ceiling 70% (`>` throttles).
- `sample_signals(cfg)` — psutil probe with env overrides winning (explicit truthy/falsy,
  garbage → real probe): `LIGHTHOUSE_ON_AC_POWER`, `_BATTERY_CHARGE` (0..1), `_CPU_USAGE`,
  `_SERVER_MODE`.
- **Synchronous translation** of OpenHuman's async gate: `SchedulerGate.permit()` is a
  context manager backed by a `threading.Semaphore` global slot. NORMAL/AGGRESSIVE acquire
  immediately; THROTTLED sleeps `throttled_backoff_ms`; PAUSED re-polls every
  `paused_poll_ms` and resumes on flip.
- **Wired**: `modes/deepdive.py` `_research_section` + `_denoise` wrap `gateway.complete`
  via an injected `gate`; `pipeline.py` constructs a gate for real (non-offline) runs;
  `governor/__init__.py` exports the public surface; `[governor.scheduler_gate]` added to
  `templates/config.toml`; `lighthouse doctor` prints policy + reason + signals.
- **Tests**: `tests/governor/test_scheduler_gate.py` — env parsing, policy truth table,
  totality (hypothesis), throttle/pause sleep behaviour, and `max_concurrent_llm`
  serialisation.

Exit criteria met: a Deep-Dive on battery <80% serialises section research to ≤1 concurrent
LLM call; `mode="off"` pauses new work and resumes on flip; `doctor` reports the policy.

**Follow-ups (deferred):** gate Monitor sync loop and `verification/resolver.py` ticks (§1.5
"future"); gate the `pipeline._auto_fetch` embedding pass.

## 2. Hotness Score — ✅ DONE

`compounding/hotness.py`. One deterministic, LLM-free formula:

```
hotness = ln(mentions + 1) + 0.5·distinct_sources + recency_decay(last_seen)
        + graph_centrality + 2·query_hits        # TOPIC_CREATION_THRESHOLD = 10.0
```

- `EntityStats`, `recency_decay` (piecewise: ≤1d→1.0; 1–7d→1.0→0.5; 7–30d→0.5→0.0; >30d→0),
  `hotness_at`/`hotness`, and `HotnessBreakdown` (decomposes a score into the five named
  terms for the UI "why salient" tooltip).
- `distinct_sources` uses **independent-source** semantics (distinct domains, per
  `verification/discipline.check_source_diversity`) — never raw citation count, so citation
  cartels / syndication can't inflate hotness.
- **Wired**: `modes/monitor.make_hotness_salience(tracked, …)` returns a `SalienceFn` that
  scores an item by the max hotness of tracked entities it mentions (opt-in; the
  length+keyword `default_salience` remains the fallback).
- **Tests**: `tests/compounding/test_hotness.py` — OpenHuman's three locked cases, decay
  boundaries (1d/7d/30d), breakdown sums to total, and monotonicity properties (hypothesis).

Exit criteria met: salience ordering is reproducible and every score decomposes into the
five named terms.

**Follow-ups (deferred):** the `entity_hotness` persistence table (§2.4) and the
dossier-materialisation gate (`compounding/`), which land with the dossier work; feeding
`query_hits_30d` back from retrieval (§2.5, optional/later).

---

## Remaining (not yet started) — design carried from the spec

- **§4 Tick Overlap Guard (P1):** monotonic generation counter in `subconscious/engine.py`
  and `verification/resolver.py`; a tick checks its generation before committing and
  discards superseded results; pair with a per-task `in_progress`→`cancelled` DB status so
  startup recovery cleans crashes. *Exit:* no scheduled pass double-commits when a tick runs
  longer than its interval.
- **§3 Reflection / Escalation split (P1):** new `subconscious/` module (types, reflection
  with `MAX_REFLECTIONS_PER_TICK=5`, store, engine). Reflection = passive observation with
  provenance, never auto-posts; "Investigate" spawns a *fresh* job. Escalation = actionable
  (retraction → re-verify; resolve-by-due). New dashboard **Intelligence** page (8th).
- **§5 TokenJuice Compaction (P2):** `rag/compaction.py` — three-layer rule overlay
  (builtin < user < project), grapheme-safe, deterministic pre-context compaction of fetched
  sources before ReSum's semantic pass; stats logged to `lighthouse cost report`. *Verify
  `vincentkoc/tokenjuice` license before lifting any builtin rule JSON.*
- **§6 Tool-Policy Risk Tiers (P2):** `TaskRiskLevel` + `ToolCapability`; enforce at both
  prompt-visibility and runtime; `from_content` steps may call only `read_only` tools.
- **§8 Archivist (P3):** `compounding/archivist.py` — `clean_turns` → `compose_md` →
  `archive_report` (corpus + Logseq via the outbox; idempotent, audited).
- **§7 Conventions (P3):** per-module READMEs with Calls-into / Called-by maps, backfilled
  as each module above is touched.

## Cross-cutting requirements (apply to every item)

- Every LLM-bound call goes through **both** the Scheduler Gate (§1) and the Governor
  budget/RAM guard.
- `distinct_sources` everywhere means **independent** sources (discipline-layer semantics).
- New persistent state uses SQLite WAL + HMAC audit; external-store writes go through the
  outbox/effector.
- **No new network egress** — the offline/airplane-mode proof must still pass with all
  features enabled.

## Explicitly NOT integrating

Desktop mascot · Google Meet participant · ElevenLabs voice/STT-TTS · 118 Composio OAuth
integrations · managed model-routing backend · screen-intelligence/screenshot watching ·
20-minute auto-fetch-everything loop (Lighthouse's auto-fetch is query-scoped + corpus-gated
by design) · `agentmemory` external backend proxy. Reasons: all depend on cloud egress or a
consumer surface that breaks the local-first, no-egress, auditable-research positioning.
