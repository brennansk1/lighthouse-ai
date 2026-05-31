# Release runbook — the live-only gates (R5–R8)

Everything offline-buildable is done and green (see `DEFINITION_OF_DONE.md` R1–R4,
R9–R10). These four gates can only be *executed* on real hardware / other platforms
/ with signing certs — they are not runnable in the offline dev loop. This file
makes each one turnkey: the exact command, the pass bar, and where it's wired.

> Prereqs for the real-backend gates: `LIGHTHOUSE_REAL_BACKEND=1`, Ollama running
> with `bge-m3` + a small chat model, and the optional extras installed
> (`uv sync --all-extras`). Cold-start details: `docs/dev/LIVE_TESTING_HANDOFF.md`.

## R5 — 24 h soak + disaster-recovery drill

**Soak (slow-leak detection).** A turnkey harness ships:

```bash
uv run python scripts/soak.py --hours 24 --load        # the gate
uv run python scripts/soak.py --seconds 60             # CI-safe smoke (verified green)
```

It boots the web server + all 5 daemon loops, drives a trivial job each minute, and
samples RSS / open-fds / thread-count throughout. **Pass:** no loop death, clean
shutdown, and **no monotonic upward trend** in RSS/fds/threads (the leak signature).
For a production-faithful run, instead start the real `lighthouse-supervisor` (see
`deploy/`) and point a monitor at its PID for 24 h.

**DR drill.** Kill the supervisor mid-write, restore, confirm no corruption:

```bash
lighthouse backup                       # snapshot
kill -9 $(cat ~/.lighthouse/supervisor.pid)   # crash mid-flight
lighthouse-supervisor &                 # restart → orphaned intents requeued
lighthouse integrity                    # schema intact, audit chain verifies
```

**Pass:** in-flight jobs marked `interrupted`, audit chain verifies, no corrupt DB.

## R6 — cross-platform (Linux + macOS service)

Install the supervisor as a user service and confirm it boots, serves, and survives
logout — see [`deploy/README.md`](../deploy/README.md) (systemd unit + launchd plist
provided). Then run the suite on Linux:

```bash
uv run pytest -q          # must be green on Linux as on macOS
uv run ruff check src tests && uv run mypy src/lighthouse_ai
```

**Pass:** suite green on both OSes; the service starts, `/api/health` → 200, and it
restarts after a kill.

## R7 — security review (status)

✅ Done for the egress / injection / sandbox boundary (Areas 1/2/4 well-defended;
fixed a scan-time zip-bomb DoS; 2 low-priority residuals in `FUTURE_FEATURES.md`
§10). Re-run the redteam corpus before each release:

```bash
uv run python -m pytest tests/ -q -k "redteam or sandbox or injection or egress"
```

**Pass:** 100% of known-hostile artifacts blocked, 0 false positives.

## R8 — package + sign + publish

```bash
uv build                                        # wheel + sdist (clean-room verified)
# clean-room check: install the wheel into a fresh venv with base deps only and
# confirm the 3 console scripts run + bundled dashboard/skills/catalog load.
python -m twine check dist/*
# macOS signing (needs a Developer ID cert):
#   codesign --deep --sign "Developer ID Application: <you>" <app-bundle>
#   xcrun notarytool submit … && xcrun stapler staple …
python -m twine upload dist/*                    # PyPI (needs a token)
```

**Pass:** `pip install lighthouse-ai` on a clean machine → `lighthouse init` →
`lighthouse-supervisor` → a real research run reaches the Definition of done.

---

When all four are green, every box in `DEFINITION_OF_DONE.md` §2 is checked and the
product is shippable. Record results in `docs/PRODUCTION_CHECKLIST.md`.
