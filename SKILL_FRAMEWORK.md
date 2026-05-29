# Lighthouse — Research-Skills Framework

> **Purpose.** Define what a *skill* is, the contract every skill obeys, the capability surface it may
> touch, and the security model that lets the library grow with community contributions without
> widening the platform's attack surface. Companion to `MODE_SKILL_INTEGRATION.md` (how the seven
> modes consume skills).

## 1. What a skill is

A skill is a self-contained folder that teaches Lighthouse to research **one source** well. It welds
**knowledge** (a guide the planner reads) to **capability** (a small entrypoint that composes the
platform's vetted primitives into a source-specific toolkit). The platform stays small and trusted;
the library scales. Adding a source is a new folder under `src/lighthouse_ai/skills/library/<id>/` —
**no core code change, no central list to edit** (discovery is a directory scan).

```
skills/library/wikipedia/
  SKILL.md         # LLM-readable guide: when to use, query translation, tool playbook, biases, citation
  manifest.toml    # machine-readable config (see §3)
  skill.py         # entrypoint(s): run(...) and, if watchable, run_watchable(...)
  tools/           # optional: typed, named tools the run() composes
  parsers/         # optional: source-specific extractors (e.g. infobox walker)
  policies/        # optional: rate budgets, cached robots snapshot, known-issues
  examples/        # 3–5 worked examples (question → tool sequence → expected shape)
  tests/           # offline-deterministic by default; live tests gated by LIGHTHOUSE_REAL_BACKEND=1
```

Folder names must be valid Python identifiers — the loader imports them as
`lighthouse_ai.skills.library.<id>`.

## 2. The entrypoint contract

A skill's `skill.py` exposes:

```python
def run(ctx: SkillContext, question: str, *, max_results: int = 5) -> list[Document]:
    ...
# only if manifest declares watchable = true:
def run_watchable(ctx: SkillContext, query: str, *, since, max_results: int = 5) -> list[Document]:
    ...
```

`run` returns broker-admitted `Document`s; the runner attributes each with `skill_id`/`skill_version`
(and `community`/`grade`/`fetch_backend` tags) automatically. The mode engine consumes the documents
unchanged. A skill **never** interprets modes — it only produces a corpus. The entrypoint path is set
by `manifest.entrypoint` (default `"skill:run"`, i.e. `skill.py::run`).

## 3. The manifest (`manifest.toml`)

Declarative configuration — the recommender's scoring surface, the egress-narrowing input, and the
provenance source of truth. Implemented by `lighthouse_ai.skills.schema.SkillManifest`.

| Field | Meaning |
|---|---|
| `id` | must equal the folder name |
| `name`, `description`, `category`, `version` | identity / catalog display |
| `tier` | `A` (first-party API / clean fetch) · `B` (in-process JS render, no evasion) · `C` (fingerprint tools; requires `tierc_escalation`+`tierc_reason`) |
| `base_url`, `allowed_domains` | fetch policy; domains are **narrowed to the platform allowlist** by the runner (a skill can never widen reach) |
| `rate_limit_per_sec`, `robots_policy` | politeness |
| `default_grade`, `license`, `signed`, `audit_tags` | provenance; **unsigned ⇒ `community` tag + WEP downgrade** |
| `supported_question_types` (alias `question_types`), `topics` | recommender rule scoring |
| `modes_natural_fit`, `modes_weak_fit` | per-mode affinity |
| `output_shape` | `lookup` \| `enumerable` \| `graph` \| `stream` (Survey requires `enumerable`) |
| `temporal_tools` | exposes time-ordered queries (Reconstruct) |
| `perspective_lens`, `authority` | Adjudicate diversity + source independence |
| `watchable`, `watchable_tools` | Pattern-2 eligibility; a `@watchable` tool accepts `since=` and returns time-ordered results |
| `tierc_escalation`, `tierc_reason` | **declarative only** — a skill never ships evasion code |
| `entrypoint` | `"module:func"` relative to the skill package (default `skill:run`) |

## 4. The capability surface (`SkillContext`)

A skill reaches the world **only** through the `SkillContext` passed to its entrypoint:

- `ctx.fetch(url, *, privacy=PUBLIC_OK) -> httpx.Response` — egress-guarded GET, restricted to the
  skill's *effective* domains (declared ∩ platform allowlist).
- `ctx.fetch_and_document(url, ...) -> Document | None` — fetch → **broker admit** → ingest parse →
  tagged Document. The broker is non-bypassable; `None` means the broker REJECTed the payload.
- `ctx.document_from_bytes(payload, ...)` — broker + parse bytes the skill already fetched.
- `ctx.make_document(doc_id=, text=, metadata=)` — wrap trusted **first-party API** text (e.g. an
  arXiv abstract from a vetted `sources/` adapter). Use only for content not fetched as a web page.

Every primitive emits an audit line stamped with `skill_id`+`skill_version`.

## 5. Security model

The library is expandable, so a malicious or careless skill is a real threat. Four layered defenses:

1. **Capability restriction (load-time import guard).** The registry statically scans every `.py` in a
   skill for forbidden imports (`httpx`, `requests`, `urllib`, `socket`, `subprocess`, `ctypes`, …). A
   skill that tries to bypass `SkillContext` **fails to load** (`SkillLoadError`). This is a denylist
   guard for V1; a stricter import-hook sandbox is the documented V2.
2. **Untrusted-content treatment.** `SKILL.md` is Spotlighted (`governor.injection_gate.spotlight`)
   before the planner reads it, so a skill can't prompt-inject the planner.
3. **Signing + downgrade.** Officially curated skills set `signed = true`. Unsigned skills load with a
   `community` audit tag and a WEP downgrade on any claim depending solely on them
   (`verification.discipline.downgrade_wep`) — the same mechanism Tier-C uses.
4. **Tier-C is declarative, gated, audited.** A skill never ships evasion. It *declares* Tier-C need in
   the manifest; the user's per-domain `lighthouse trust add` gates whether it happens; every Tier-C
   chunk is `#anti-bot-bypass`-tagged and WEP-downgraded.

## 6. What the platform guarantees vs what a skill provides

**Platform owns:** the fetch path (`net.py` + politeness + `governor/egress_proxy.py` allowlist), the
broker (`sandbox/broker.py` + scanners — every byte passes through), the capability-restricted runner,
the audit chain, the discipline/WEP gate. **A skill provides:** knowledge (when/how), source-specific
tools, source-specific parsers, source-specific policies, examples, tests.

## 7. Registry / runner API (Python)

```python
from lighthouse_ai.skills import (
    discover_skills, all_skills, load_skill,        # registry
    SkillManifest, load_manifest,                   # schema
    SkillContext, build_context,                    # capabilities
    run_skill, run_watchable, SkillRun,             # runner
)

manifests = discover_skills()                       # {id: SkillManifest} — directory scan
skill = load_skill("wikipedia")                     # validate + import-guard + import entrypoints
run = run_skill(skill, question, broker=broker, platform_allowlist=allowlist, gateway=gw)
run.documents     # list[Document], each tagged with provenance
run.ok, run.thin  # diagnostics; run.thin is the dispatcher's cue to fall back to general_web
```

`run_skill`/`run_watchable` never raise from a skill fault — a raising skill yields
`SkillRun(error=...)` so a job/tick degrades gracefully.

## 8. Adding a skill (checklist)

1. `mkdir src/lighthouse_ai/skills/library/<id>/`, add `__init__.py`.
2. Author `manifest.toml` (`id` == folder; declare tier, domains, scoring fields).
3. Add the skill's domains to `governor/egress_proxy.py` (or the user's trust allowlist) — the
   platform ceiling must permit them.
4. Write `skill.py` with `run` (and `run_watchable` if `watchable`), composing only `SkillContext`.
5. Write `SKILL.md` (the planner's guide + tool playbook + biases).
6. Add `examples/` and `tests/` (offline-deterministic).
7. `discover_skills()` and `/api/sources` pick it up automatically.
