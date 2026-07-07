# Night sprint report — 2026-07-06 → 07

Good morning. Here's what changed while you slept, what you can do now, and the
honest state of things. **Everything is committed on branch
`claude/exciting-lamport-002bc3` (21 commits, not pushed).** Full test suite:
**3222 passing, 0 failing** (was 3160 at the start — +62 new tests); ruff + mypy
clean across 278 files. No real LLM work ran unattended beyond a couple of
bounded, memory-monitored validation runs — your machine was never at risk.

---

## 1. TL;DR — what's new and usable

1. **Artifact Chat (the big one).** Open any finished artifact in the Library and
   **chat with it** — ask questions, probe findings, challenge a claim. Answers
   are grounded in the artifact's own evidence, cite their sources, carry a
   confidence band, and — when the evidence is thin — the chat searches for more.
   Verified working end-to-end against your real Ollama; it gave a genuinely good,
   cited answer. This is the frontier "keep talking to the report" UX, built the
   Lighthouse way (grounded + honest).
2. **A real trust bug fixed.** A research run could silently fall back to the mock
   model while still claiming it ran on Ollama (a "mock masquerade"). That's now
   caught and labelled honestly everywhere — the chat badges it, and research runs
   mark themselves `degraded` with a visible trace step.
3. **~11 bugs fixed** across the first-run, pipeline, and dashboard paths — found by
   parallel review agents, each fix with a regression test. Includes a **blocker**
   (one corrupt DB row could 500 your whole jobs list) and a **disk-safety** bug
   (relevant: your disk is at 94%).
4. **A measurement harness** so "is the output actually good vs. Claude/Gemini?"
   becomes a tracked number, not a vibe.
5. **Privacy hardened** — a DNS-rebinding/SSRF hole in the egress guard is closed.

---

## 2. How to start it (turnkey)

Ollama is already running with the models you need (`qwen3.5:9b`, `bge-m3`), and
the full dependency stack is installed. To use the dashboard:

```bash
cd <this repo>
uv run lighthouse-supervisor      # starts everything; dashboard at http://127.0.0.1:8765
```

Then: **Research** tab to run a new investigation, or **Library** to open a
finished one and use the new **Chat with this artifact** panel at the bottom.

Run a research question from the CLI instead:
```bash
uv run lighthouse research "your question" --arxiv "seed query" --sources 5
```

**One tip that matters (see §5):** on a busy machine with little free RAM, LLM
calls degrade to the fallback model. For reliably-real answers, either close
memory-hungry apps first, or pin the small model:
```bash
LIGHTHOUSE_FORCE_MODEL=qwen3.5:9b uv run lighthouse-supervisor
```

---

## 3. Artifact Chat — how it works

Design doc: [`docs/ARTIFACT_CHAT_DESIGN.md`](docs/ARTIFACT_CHAT_DESIGN.md).
Screenshot of it working: [`visuals/AC_artifact_chat_panel.png`](visuals/AC_artifact_chat_panel.png).

- **Grounded.** When a draft is staged, its evidence chunks are snapshotted, so
  the chat stays grounded in the artifact's own sources even without a running
  vector DB. Each turn retrieves from that evidence and cites it.
- **Escalates.** If your question isn't covered by the artifact's evidence, the
  chat searches for more sources (bounded, egress-guarded), adds them, and answers
  — tagging the turn "🔎 searched and added N sources."
- **Honest.** Every answer states its backend. If a turn ran on the fallback mock
  (e.g. RAM too tight), it's badged "⚠ generated without the local model — treat
  as unreliable." It never fakes a confident answer.
- **Persists + audited.** The conversation reopens where you left off, and every
  turn is on the tamper-evident audit chain.

Suggested starter prompts are auto-derived from the artifact's open questions and
contested claims.

---

## 4. Bugs fixed (all with regression tests)

| # | Severity | Fix |
|---|---|---|
| Jobs-list 500 | **blocker** | One row with corrupt JSON no longer 500s the entire jobs/audit list |
| Disk preflight | major (safety) | The disk-space guard now sizes the *real* model tags it recommends — on a tight disk it correctly refuses an oversized pull (it silently didn't before) |
| Mock masquerade | major (trust) | A mocked synthesis no longer reports `backend=ollama`; runs mark `degraded` visibly |
| Survey false-negative | major | A *missing* attribute rendered as a red "failed fact-check"; now shows neutral "not checked" |
| Deep-dive crash | major | A mid-run retrieval error degrades that section instead of killing the whole job |
| SSE silent death | major | A dashboard tab that fell behind stopped getting live updates forever; now reconnects |
| CLI artifact parity | major | `lighthouse research` drafts now render in the dashboard's typed views (were HTML-only) |
| Empty CSV export | major | A zero-row table now exports its headers instead of a useless one-column CSV |
| Markdown export | major | Matrix/table/timeline artifacts now export full Markdown, not a stub |
| Entailment retry | major (perf) | A failed faithfulness-model load is cached, not re-attempted per claim |
| pynvml warning | minor | Killed the deprecation warning that printed on every command on your Mac |
| init clarity | minor | First-run shows one clear, pullable model tag + size, not a confusing internal name |

---

## 5. What I found (honest findings)

**The output-quality bottleneck — read this.** I ran real research on your Ollama
and measured it. Two real issues surfaced:

1. **Mock masquerade (now fixed for honesty).** On a busy box, the model picker
   chooses a model too big for *live-free* RAM, the admission gate then refuses
   it, and the call silently falls back to the mock. The run still completed and
   (before tonight) looked real. **I made this honest** (labelled everywhere), and
   the chat feature is immune (it badges it). **What I did NOT fully fix:** making
   the picker always choose a model that *fits* so you get a real answer every
   time. Workaround today: `LIGHTHOUSE_FORCE_MODEL=qwen3.5:9b` or free up RAM. This
   is the highest-value next task and I've left it clearly scoped.

2. **Inline citations from the local model.** When the synthesis *did* run real,
   `qwen3.5:9b` didn't always emit inline `[N]` citation markers, so the grounding
   gate scored low coverage even though evidence was retrieved. The chat's
   synthesizer prompt handles this better (its answer cited `[1][2]` correctly),
   but the deep-dive synthesizer prompt could use the same treatment. Scoped as a
   follow-up.

The **frontier-parity grader** ([`eval/frontier_parity.py`](src/lighthouse_ai/eval/frontier_parity.py))
now lets you put a number on both. Run a research question, then grade it — it
scores breadth, grounding, citation-verifiability, contradiction-honesty, and
open-question-honesty, and compares against a Claude/Gemini answer you paste in.

---

## 6. Prime-directive status

- **Trustworthiness** — *stronger.* The mock masquerade (the worst violation) is
  now surfaced, not hidden; the chat and research both refuse to present fake
  answers as real. Grounding + citation discipline apply to chat answers too.
- **Provable privacy** — *stronger.* The DNS-rebinding/SSRF hole is closed; a
  public domain can no longer resolve into your internal network, and the cloud
  metadata endpoint is blocked. `LIGHTHOUSE_AIRGAP=1` still hard-blocks all egress.
- **Auditability** — *maintained + extended.* Chat turns and degraded runs are on
  the HMAC chain.
- **On par with frontier** — *measurable now, not yet proven.* The grader exists;
  the real head-to-head is yours to run (needs pasting in Claude/Gemini outputs).

---

## 7. Remaining gaps (honest)

- **Real-answer reliability on a busy box** (the masquerade root cause) — scoped,
  not fixed. Highest-value next task.
- **Deep-dive inline citations** on the local model — scoped.
- **Two lower-priority bugs I chose not to fix** to stay focused, both noted here:
  a Qdrant dimension-mismatch crash if you switch embedders with Qdrant running
  (you're on the in-memory store by default, so this doesn't bite you today); and
  the acquisition budget counting injection-blocked docs against the source budget.
- **Live-only release gates** (24h soak, code signing, cross-platform, PyPI) —
  unchanged; these don't affect you running it locally.

---

## 8. Housekeeping

- Branch `claude/exciting-lamport-002bc3`, **not pushed** — say the word and I'll
  push to `main`.
- A scratch validation data dir with real research drafts + a demo artifact lives
  under the session scratchpad (not your real `~/.lighthouse`), so nothing polluted
  your setup. The dashboard start command above uses your real data dir.
- `scripts/_serve_dashboard.py` is a dev-only daemon-free dashboard server I used
  for UI verification; harmless to keep or delete.
