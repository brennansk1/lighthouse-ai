# governor/

The single cross-cutting runtime guardrail (design §24): resource accounting,
host courtesy, loop/injection/egress guards, and tool-exposure policy.

## Public surface

- `buckets.py` — `Governor`, hierarchical token buckets, `degradation_tier`,
  `BudgetTripped`.
- `scheduler_gate.py` — `SchedulerGate` (host-courtesy `permit()`),
  `current_policy`, `sample_signals`, `Policy`/`PauseReason`/`Signals`. (§1)
- `tool_policy.py` — `ToolCapability`, `TaskProfile`, `decide`, `visible_tools`,
  `enforce`, `ToolPolicyViolation`. Two-point enforcement (prompt-visibility +
  runtime refusal). (§6)
- `loop_detector.py` — `LoopDetector` (runaway-loop trip).
- `injection_gate.py` — `InjectionGate`, `spotlight`.
- `egress_proxy.py` — `EgressProxy`, `PrivacyTier`.

## Calls into

- `..verification.audit_chain.append_event` — tool-policy refusals logged to the
  HMAC chain.
- `psutil` (lazy) — power/CPU signals for the scheduler gate.

## Called by

- `..modes.deepdive` / `..pipeline` — scheduler gate wraps LLM calls; loop +
  injection guards screen the research loop and ingest path.
- `..subconscious.engine` — ticks run LLM-bound producers under the scheduler gate.
- `..cli.doctor` — reports the current scheduler-gate policy.

## Invariants

- Every LLM-bound call goes through **both** the scheduler gate (host courtesy)
  and the budget/RAM accounting (resource accounting).
- `current_policy` is total (never raises) for any `Signals`.
- Content-derived (`from_content`) steps may only ever invoke `read_only` tools.
