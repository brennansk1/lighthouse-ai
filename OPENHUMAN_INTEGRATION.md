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
| 4 | **Tick overlap guard** — generation-counter cancellation | `subconscious/overlap.py` + `verification/resolver.py` | P1 | ✅ |
| 3 | **Reflection / Escalation split** — passive vs actionable findings | `subconscious/` + dashboard Intelligence page | P1 | ✅ |
| 5 | **TokenJuice-style payload compaction** — deterministic pre-context compaction | `rag/compaction.py` | P2 | ✅ |
| 6 | **Tool-Policy risk tiers** — risk-tiered prompt-visibility + runtime enforcement | `governor/tool_policy.py` | P2 | ✅ (substrate; no tool-runtime to wire yet) |
| 8 | **Archivist clean→compose→append** — finished job → durable corpus | `compounding/archivist.py` | P3 | ✅ |
| 7 | **Per-module README + Calls-into/Called-by convention** | repo-wide docs | P3 | ✅ all six major modules covered |

Build order: **1 → 2 → 4 → 3 → 5 → 6 → 8 → 7** — all items complete.

## Outstanding follow-ups

- **§2 dossier page** — `EntityHotnessStore.should_materialise` fires once an entity crosses
  `TOPIC_CREATION_THRESHOLD`; the dossier page that renders when the gate fires is not yet
  built (needs a Topics sub-view or dedicated page; browser QA required).
- **§5/§6 wiring** — compaction on the Deep-Dive evidence-prompt path; tool-policy
  enforcement at a real executor call site once tool-calling lands.
- **§3 browser QA** — Intelligence page built; browser render testing requires local
  Ollama + arXiv (unavailable in cloud sandbox).

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

## Implemented this pass (§4 → §3 → §5 → §6 → §8 → §7)

- **§4 Tick Overlap Guard** — `subconscious/overlap.py` `GenerationGuard`; wired into
  `verification/resolver.run_resolver_pass` (claims a generation, refuses commits once a
  newer pass starts). *Exit met:* overlapping passes never double-commit.
- **§3 Reflection / Escalation split** — `subconscious/` types + `apply_cap`
  (`MAX_REFLECTIONS_PER_TICK=5`) + WAL store + tick engine (scheduler-gated, overlap-guarded)
  + stale-position (resolve-by-due) escalation producer + `act_on_reflection` (spawns a fresh
  job). Dashboard **Intelligence** page (8th) + `reflections_act` endpoint still to build.
- **§5 TokenJuice Compaction** — `rag/compaction.py`: three-layer overlay, grapheme-safe
  transforms, `CompactionStats`; wired into `pipeline.ingest_text` for HTML payloads. Our own
  rules (tokenjuice JSON not copied — license uncleared).
- **§6 Tool-Policy Risk Tiers** — `governor/tool_policy.py`: `ToolCapability`/`TaskProfile`,
  `visible_tools` (prompt-visibility, ≤ceiling) + `enforce` (runtime refusal, audit-logged);
  `from_content` clamped to read-only. Substrate only — no tool-calling runtime to wire yet.
- **§8 Archivist** — `compounding/archivist.py`: `clean_turns` → `compose_md` →
  `archive_report`/`archive_conversation` (content-addressed, idempotent; optional Logseq).
- **§7 Conventions** — READMEs added for `governor/`, `subconscious/`, `compounding/` with
  Calls-into / Called-by maps; older modules pending.

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
