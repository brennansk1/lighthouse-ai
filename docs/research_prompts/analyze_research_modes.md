# Research prompt — optimize Lighthouse's 7 research modes

> Paste this to a research-capable Claude (web search + GitHub/PyPI/arXiv access, or the deep-research
> skill). Attach or point it at [`docs/MODE_PROCESSES.md`](../MODE_PROCESSES.md). Goal: for each of the
> 7 modes (and the shared spine), find **better strategies, Python libraries, or GitHub repos** worth
> integrating — with concrete, fit-checked recommendations.

---

You are a research engineer auditing **Lighthouse**, a local-first research instrument, to decide where
adopting an external strategy / library / repo would beat its current home-grown approach. Your output
will drive integration decisions, so every recommendation must be **specific, sourced, and fit-checked**
— not a generic "you could use X."

## Read first
`docs/MODE_PROCESSES.md` is the source of truth. It documents, with embedded algorithms, the **shared
spine** (backend selection, chunking, injection gate, hybrid retrieval, discipline gate, calibration,
depth tiers §0.7, adversarial §0.8, coverage critic §0.9, provenance §0.10, benchmark §0.11) and the
**7 modes**: Watch (digest), Ask (transcript), Investigate (report, TTD-DR), Survey (PRISMA table),
Reconstruct (timeline), Decide (matrix), Adjudicate (verdict) — plus the Deep-tier recursive engine.
Each mode and spine component ends with a **❓ "Is this optimal?"** block — those are your starting
research questions. Treat them as the prioritized backlog.

## Hard constraints any recommendation MUST satisfy (a recommendation that violates these is invalid)
1. **Local-first.** Runs on a laptop (Apple M4 / 24 GB), LLM via **Ollama**, vectors via Qdrant or
   in-memory. No mandatory cloud service or paid API. Cloud is opt-in only.
2. **Offline-deterministic.** Every engine must still run with `gateway=None` producing a deterministic
   stub; the default test suite is offline + LLM-free. Real/model/network paths gate behind
   `LIGHTHOUSE_REAL_BACKEND=1`. A library that *requires* a network call or model download to function
   at all is a poor fit unless it's lazy-imported and degrades.
3. **Resource-safe.** No background process that could exhaust RAM; one Ollama model at a time
   (the `ollama_slot` admission seam). Heavy deps (torch-pulling) must be **lazy-imported, optional**,
   with graceful fallback.
4. **Licensing:** prefer MIT/BSD/Apache-2.0. Flag GPL/AGPL/non-commercial explicitly.
5. **Maintenance:** prefer actively-maintained (commits in last ~12 mo, releases, real adoption).
   Flag abandoned/single-maintainer/<500-star niche repos as higher risk.
6. **Python ≥3.11.** Pure-Python or easy-wheel deps preferred; flag anything needing system libs/CUDA.
7. **Map to a seam.** Lighthouse exposes clean injectable call sites (`gateway`, `gate`, `fetch_fn`,
   `reranker`, `salience_fn`, the discipline gate, the framing planner). A recommendation must name the
   **exact swap-in call site** (`module.py:symbol`) — these are swaps, not rewrites.

## What to do, per mode + per spine component
For each ❓ block in `MODE_PROCESSES.md`, and for the shared spine, research:
- **State of the art:** what is the current best-practice strategy/algorithm for this task? Cite the
  paper(s) and any reference implementation. (e.g. for Investigate: is TTD-DR still the best deep-
  research loop vs plan-execute / graph approaches? For Decide: weighted-sum vs AHP/TOPSIS/ELECTRE /
  Monte-Carlo sensitivity? For Reconstruct: regex dates vs HeidelTime/SUTime temporal taggers? For the
  injection gate: regex vs ProtectAI deBERTa? For framing: keyword rules vs a planner LLM / classifier?)
- **Concrete library or repo:** name specific PyPI packages and GitHub repos (with URLs, star count,
  last-commit, license) that implement it and could drop into the named seam.
- **Fit check:** does it satisfy all 7 constraints above? If not, say which it violates and whether
  there's a lighter alternative.
- **Expected gain:** what metric would improve, and is there a way to measure it (tie to the benchmark
  in §0.11 or the golden-set eval where possible)?

## Deliverable — a prioritized recommendation table
Produce one row per actionable recommendation, sorted by **(impact × fit) / effort**:

| Mode / component | Current approach | Recommended strategy/lib/repo (URL, ⭐, license, last commit) | Why it's better | Swap-in seam (`module.py:symbol`) | Effort (S/M/L) | Risk / constraint flags | How to measure the gain |

Then:
- **Top 5 "do these first"** — highest leverage, lowest risk, with a one-paragraph rationale each.
- **Explicitly reject** any obvious-but-bad fit (e.g. LangChain/LangGraph if it conflicts with the
  intentional plain-Python design; cloud-only tools) and say why.
- **Net-new capabilities** Lighthouse lacks entirely that a library would unlock (flag separately).
- Keep the competitive thesis in mind: Lighthouse wins on **trustworthiness** (grounding, calibration,
  reproducibility) and **unbounded local depth**, NOT on raw model power. Favor recommendations that
  deepen that moat (better grounding/verification/decomposition) over ones that just chase frontier
  fluency.

Be skeptical and concrete. "Could help" is not useful; "swap `ScoreReranker` for `FlagReranker`
(`BAAI/bge-reranker-v2-m3`, Apache-2.0, lazy-imports torch) at `pipeline.py` — golden-set says precision
is the metric it moves" is useful.
