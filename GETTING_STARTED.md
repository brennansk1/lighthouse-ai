# Getting Started — your first cited answer in ~10 minutes

This is an honest walkthrough for a non-expert. It gets you from nothing to one
real, citation-backed answer over a folder of your own files. No prior Lighthouse
knowledge assumed.

There is exactly **one irreducible step**: you need a local language model running
(Ollama + one model pull). Everything else is one command each.

---

## Before you start — what you'll need

| Thing | Why | How long |
| --- | --- | --- |
| **Ollama** running locally | Lighthouse never calls a cloud LLM. It talks to a model on *your* machine. | 2 min to install |
| **One model pulled** | The actual brain. This is the step you cannot skip. | 3-5 min (it's a download) |
| **`uv`** | Installs Lighthouse and its Python deps reproducibly. | 1 min |
| A folder of files you care about | Your corpus — PDFs, text, notes. This never leaves your machine. | you already have this |

No Docker. No database server. No cloud account. No API key. The default storage
is in-memory / SQLite files under `~/.lighthouse/` — there is nothing else to stand up.

---

## Step 1 — Install Ollama and pull a model (the one step you can't skip)

Install Ollama from <https://ollama.com>, then pull a small instruct model:

```sh
ollama pull llama3.1:8b      # or any instruct model your RAM can hold
```

On a 16-24 GB machine an 8B model is a comfortable starting point. Bigger isn't
always better here — Lighthouse measures your actual free RAM and recommends models
that fit (see `lighthouse doctor` later). Leave Ollama running.

You can confirm it's alive with:

```sh
ollama list
```

If you see your model listed, you're done with the hard part.

---

## Step 2 — Install Lighthouse

From the project directory:

```sh
uv sync
```

This creates the virtual environment and installs everything Lighthouse needs.
Every command below is run with `uv run` so it uses that environment.

---

## Step 3 — Initialize your data directory

```sh
uv run lighthouse init
```

This creates `~/.lighthouse/` with your config, a hardware profile, and the SQLite
databases Lighthouse uses for state, audit, and citations. It also probes your
machine and prints the model tier it thinks you can run. You only do this once.

> If you'd rather keep everything in a project-local folder, set
> `LIGHTHOUSE_DATA_DIR=/path/to/dir` before running `init` (and every command after).

---

## Step 4 — Ask your first question over your own folder

Point Lighthouse at one or more of your files and ask a real question:

```sh
uv run lighthouse research "What does my Q3 plan say about hiring?" \
    --doc ~/Documents/q3_plan.pdf \
    --doc ~/Documents/notes.md
```

What happens, in plain terms:

1. Your files are ingested into a local corpus (chunked and embedded — on your machine).
2. Lighthouse frames the question, retrieves the relevant chunks, and asks your
   local model to synthesize an answer.
3. A **citation-discipline gate** checks that claims are actually backed by your
   sources. Every claim is recorded as a "calibration position" so you can audit it later.
4. A draft is staged for you to review.

You'll see a line like:

```
staged draft <id> (deep-dive, N section(s), M corpus chunks)
  discipline: passed — 7/8 claims sourced (88% coverage); 8 claim(s) recorded
  review it: dashboard → Drafts, or `lighthouse status`
```

To read what you got:

```sh
uv run lighthouse status
```

---

## Where your output lands

Everything lives under `~/.lighthouse/` (or your `LIGHTHOUSE_DATA_DIR`):

| Path | What's in it |
| --- | --- |
| `~/.lighthouse/staging/` | Staged drafts awaiting your review |
| `~/.lighthouse/corpus/` | Your ingested files, chunked |
| `~/.lighthouse/state.db` | Drafts, runs, pipeline state |
| `~/.lighthouse/audit.db` | The audit trail (what ran, what was fetched) |
| `~/.lighthouse/positions.db` | Each recorded claim + its citation |
| `~/.lighthouse/logs/` | Logs, including `egress.jsonl` (what left the machine, if anything) |

Nothing in this list is on a server. It's all files on your disk.

---

## Going fully offline

If you only want to work over your own documents and guarantee nothing leaves the
machine, set the hard kill switch before any command:

```sh
export LIGHTHOUSE_AIRGAP=1
```

With this set, every outbound request is denied before a socket opens. See
[`docs/SECURITY_POSTURE.md`](docs/SECURITY_POSTURE.md) for exactly what does and
doesn't egress.

---

## ⚠️ Not yet safe to rely on for...

Be honest with yourself about what this is today. Lighthouse is a **research
instrument under active validation**, not a finished product. Specifically:

- **Live-data work where being current matters.** Full live-data validation is
  still pending. Treat answers that depend on freshly fetched web/API data as
  *drafts to verify*, not ground truth.
- **High-stakes or regulated decisions** (legal, medical, financial, safety).
  The citation gate tells you whether a claim is *sourced*, not whether the source
  is *right*. A human still has to check.
- **Anything you'd act on without reading the cited source.** The whole point of
  the citations is that you open them. If you wouldn't check the citation, don't
  rely on the claim.

When in doubt: read the citation, and keep `LIGHTHOUSE_AIRGAP=1` on if you want a
guarantee that your corpus stays on your machine.

---

## If something goes wrong

- **No answer / model errors** — confirm Ollama is running (`ollama list`) and the
  model you pulled is actually loaded.
- **"Run lighthouse init first"** — you skipped Step 3, or your `LIGHTHOUSE_DATA_DIR`
  doesn't match between commands.
- **Wrong model recommended for your RAM** — run `uv run lighthouse doctor` to see
  the measured RAM and the budget-aware model picks.
