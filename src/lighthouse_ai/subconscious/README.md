# subconscious/

Background-tick intelligence: the passive/actionable split (reflections vs
escalations) and the overlap guard that keeps scheduled passes from
double-committing. (OpenHuman §3 + §4.)

## Public surface

- `overlap.py` — `GenerationGuard` (monotonic generation counter), `TickResult`.
- `types.py` — `Reflection`, `Escalation`, `ReflectionKind`, `EscalationStatus`,
  `EscalationPriority`, `ChunkSnapshot`.
- `reflection.py` — `MAX_REFLECTIONS_PER_TICK` (= 5), `apply_cap`.
- `store.py` — `ReflectionStore` (WAL SQLite; reflections + escalations tables).
- `engine.py` — `SubconsciousEngine.tick()`, `stale_position_escalations`,
  `act_on_reflection` (spawns a *fresh* job, never mutates a session).

## Calls into

- `..governor.scheduler_gate` — each tick's LLM-bound producers run under a
  host-courtesy `permit()`.
- `..persistence.open_db` — PRAGMA-disciplined SQLite connections.
- `..verification.positions` / `..verification.resolver` — the stale-position
  (resolve-by-due) escalation producer; the resolver also uses the overlap guard.

## Called by

- `..verification.resolver.run_resolver_pass` (overlap guard).
- (planned) the supervisor's scheduled background loop; the dashboard
  **Intelligence** page + a `reflections_act` endpoint (UI not yet built).

## Invariants

- A `Reflection` never carries a side effect; an `Escalation` always carries
  status + priority.
- A tick emits ≤ `MAX_REFLECTIONS_PER_TICK` reflections.
- A tick overtaken by a newer generation discards its writes (no double-commit).
