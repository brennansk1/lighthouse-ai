# Artifact Chat — design

Open any staged artifact (report, matrix, timeline, evidence table, verdict,
transcript, digest) and **chat with it**: ask questions, probe the findings,
challenge a claim — and when the artifact's own evidence can't answer, the chat
**runs additional grounded research** and continues. This is the roadmap's R-D
("report-grounded interactive follow-up") built for real.

## 1. Why it fits Lighthouse

Frontier deep-research tools (Claude, Gemini) let you keep talking to a finished
report — it's their best UX. Lighthouse should match it *and* keep its wedge:
every chat answer is **grounded in real cited evidence, honesty-gated, and
auditable**, and it runs on the local model. The chat is not a general
assistant; it is a lens onto *this artifact and its corpus*. That framing is
also what makes it work on a 9-14B local model: the model's job stays narrow
(synthesize from retrieved evidence), never "answer from memory".

## 2. What the user sees

In the Library / Review view of any artifact, a **"Chat" tab** (beside the typed
view) opens a conversation panel that blends with the existing chat-bubble
transcript styling:

- The panel opens seeded with a one-line orientation ("Ask about this
  investigation — its findings, sources, open questions, or anything it didn't
  cover") and 2-3 **suggested prompts** derived from the artifact (its open
  questions and contested claims make excellent starter chips).
- User types → the answer **streams token-by-token** (reusing the SSE feed).
- Each answer shows **inline citations** that resolve to the artifact's own
  sources (click → the source snippet), a **confidence band** (WEP, same as the
  rest of the app), and — when it happened — a subtle **"researched N new
  sources"** note.
- A per-answer **backend badge** states honestly what produced it: real local
  model, or a degraded fallback ("⚠ generated without the local model —
  treat as unreliable"). This is non-negotiable (see §9).
- The conversation persists with the artifact and reopens where it left off.

## 3. Grounding model (the heart of it)

Every turn is retrieval-grounded; the model never free-associates. Grounding has
three layers, tried in order:

1. **Artifact evidence snapshot.** When a draft is staged we persist the exact
   evidence chunks it was built on (id, text, source metadata) to a new
   `artifact_evidence` table keyed by `draft_id`. At chat time we build a small
   in-memory `HybridSearch` over that snapshot. This makes a chat **grounded in
   the artifact's own sources even when Qdrant isn't running** (the default is
   the in-memory store, which is gone after the run) — critical for the local,
   air-gapped use case.
2. **Persistent corpus.** If a Qdrant corpus is reachable, its retriever is
   layered in too, so the chat can reach beyond the artifact's cited slice into
   the whole local corpus.
3. **Fresh research** (§4) when 1+2 are thin.

The turn engine is the existing `quc.ask()` — it already retrieves (top-k),
builds an evidence block, renders history, prompts the gateway, and returns a
`Turn` with citations. We reuse it verbatim and feed it the artifact-grounded
retriever + an **artifact-anchored session**: the session is seeded with a
system-style preamble carrying the artifact's question, its load-bearing
findings, its open questions and any contested claims, so follow-ups build on
the work instead of restarting cold.

## 4. Research escalation ("do more if needed")

The decision to research must not depend on the weak model introspecting its own
knowledge (local models are unreliable at "do I know this?"). It is
**retrieval-signal-driven and conservative**:

- After grounding-layer retrieval, compute a cheap **sufficiency score**: number
  of hits above a relevance floor and their top score. If the question retrieves
  little from the artifact + corpus (e.g. < 2 hits over the floor), the turn
  **escalates**.
- Escalation runs the existing acquire-as-you-learn `Acquirer` for *this
  question* (politeness + egress rails, budget-capped), ingests what it finds
  into the chat's in-memory retriever, and re-retrieves. The answer is then
  drafted over the enlarged evidence, and the turn is tagged `researched: true`
  with a note ("searched the web and added N sources").
- Hard limits: a per-turn acquisition budget, the Governor loop-guard, and the
  scheduler gate — a chat turn can never runaway-spend. If escalation still
  finds nothing, the answer says so honestly ("I searched and couldn't find
  evidence on this; the artifact doesn't cover it") rather than inventing.
- Heavy asks ("do a full deep-dive on X") are offered as a **spawned follow-up
  job** through the normal dispatcher (a chip: "Run this as a new
  investigation"), not attempted synchronously — that keeps the turn responsive
  and reuses the audited job path.

## 5. Architecture

```
Browser (Chat tab)
   │  POST /api/artifacts/{draft_id}/chat  {message}
   ▼
Web process (FastAPI)
   ├─ ChatService (new: modes/artifact_chat.py)
   │    1. load/create session (ask_store, keyed by draft_id)
   │    2. build artifact-grounded retriever (evidence snapshot [+ Qdrant])
   │    3. sufficiency check → maybe Acquirer escalation (budget-capped)
   │    4. quc.ask(session, msg, hybrid=grounded, gateway=live)  ← reused
   │    5. discipline gate on the answer (citation coverage, WEP downgrade)
   │    6. record backend honesty (real / mock / stalled) for the turn
   │    7. persist session; audit chat.turn
   │    └─ streams chat.token over the SSE bus
   └─ live Gateway  ← build_runtime_gateway(paths), built once & cached
                       (closes the "web process has no gateway" gap)
```

The live gateway is built lazily on first chat use and cached on the app state
(probing shells out to Ollama; do it once, never per turn). It inherits the
same RAM-admission seam as the dispatcher, so a chat turn is subject to the same
swap-safety guarantees.

## 6. API contract

- `POST /api/artifacts/{draft_id}/chat` — body `{ "message": str }`.
  Returns `{ "session_id": str, "turn": Turn }` where
  `Turn = { role, text, citations: [{id, source, snippet}], wep_band,
  backend: "ollama"|"mock"|"mock-lowmem"|"stalled", researched: bool,
  research_note: str|null }`. During generation it emits `chat.token`
  SSE events `{draft_id, token}` for live streaming, and a terminal
  `chat.turn` event.
- `GET  /api/artifacts/{draft_id}/chat` — the session so far:
  `{ session_id, turns: [Turn], suggestions: [str] }` (suggestions derived from
  the artifact's open questions / contested claims).
- Errors degrade, never 500: no gateway → an honest offline turn; a stalled
  backend → a `stalled` turn surfaced as such.

## 7. Persistence

- `artifact_evidence(draft_id, chunk_id, text, source, metadata_json)` — new
  table; the artifact's cited chunks, written when the draft is staged.
- `ask_sessions` — reused; the chat session is keyed to the artifact via a
  deterministic session id (`chat-<draft_id>`) and `job_id`.
- Every turn appends a `chat.turn` audit event (question hash, citation count,
  backend, researched flag) to the HMAC chain — the chat is as auditable as a
  research run.

## 8. Techniques for the local-model constraint

- **Retrieval-first, memory-never.** Each turn injects retrieved evidence; the
  prompt instructs "answer only from the evidence and the artifact; if it's not
  there, say so." This is how a 9B model gives frontier-grade *trust* without
  frontier-grade parametric knowledge.
- **Context compaction.** Long chats are compacted (`CompactedContext` /
  `compact_evidence`) so the effective context stays inside the local model's
  reliable window — long raw histories degrade small models fast.
- **Grounded escalation, not self-assessment** (§4) — the retrieval signal, not
  the model, decides when to research.
- **Answer-side discipline gate.** The drafted answer runs the same citation /
  entailment discipline as a research draft; unsupported claims are downgraded
  or dropped, so the chat cannot fabricate a confident wrong answer.
- **Anchored, bounded turns.** The artifact preamble keeps the model on-topic;
  per-turn budgets keep it cheap and responsive.

## 9. Honesty & safety

- **No silent mock.** Tonight's validation caught a *mock masquerade* — a
  synthesis that fell back to the MockProvider while provenance still read
  `backend=ollama`. A chat is the worst place for that: the user would trust a
  fake answer. So each turn records the **synthesizer's actual backend** (not
  "did any Ollama call happen") and the UI badges a degraded turn loudly. This
  also motivates a broader fix (surfacing per-call backend truth) tracked in the
  sprint report.
- **Egress stays guarded.** Escalation fetches go through the same egress guard /
  `LIGHTHOUSE_AIRGAP` kill switch as everything else — a chat can't leak the
  corpus.
- **Auditable.** Every turn is on the tamper-evident chain.

## 10. Build plan (leaves)

- **AC1** `artifact_evidence` table + snapshot on draft stage (dispatcher +
  pipeline persist paths).
- **AC2** `modes/artifact_chat.py` — `ChatService`: grounded retriever build,
  sufficiency check + Acquirer escalation, reuse `quc.ask`, discipline gate,
  backend-honesty capture, session persistence, audit.
- **AC3** web: `GET/POST /api/artifacts/{id}/chat` + cached
  `build_runtime_gateway` in the web process + `chat.token`/`chat.turn` SSE.
- **AC4** frontend: Chat tab in the artifact view — streaming bubbles, citation
  chips, WEP band, backend badge, suggested prompts, "researched" note.
- **AC5** tests: offline turn (gateway=None), snapshot-grounded retrieval,
  escalation trigger on thin retrieval, backend-honesty labeling, endpoint
  shapes, persistence/audit. Vision-check the panel.
```
```
