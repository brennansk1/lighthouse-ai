"""Supervisor soak test — detect slow leaks over a long run (R5).

Boots the web server + all 5 daemon loops on a temp data dir and samples RSS,
open file descriptors, and thread count at a fixed cadence, optionally driving
sustained load (a trivial offline job enqueued each minute). At the end it reports
min/max/growth per metric and a leak verdict: a *monotonic* upward trend in RSS or
fds across the whole run is the slow-leak signature the 24 h soak must rule out.

Usage:
    uv run python scripts/soak.py                  # 60 s smoke (CI-safe)
    uv run python scripts/soak.py --hours 24 --load # the real overnight soak
    uv run python scripts/soak.py --seconds 600 --sample-every 30 --load

Daemon threads die with the script. No real backend (stub models via the forced-
offline dispatch loop, no model load) and no egress (LIGHTHOUSE_AIRGAP is set
unless the caller already chose a value): the soak measures *our* leaks, not
network noise, and a 24 h `--load` run must not hammer live feeds once a minute.
For a production-faithful soak run the actual `lighthouse-supervisor` and point a
process monitor at its PID; this harness is the turnkey, dependency-light version.
"""
from __future__ import annotations

import argparse
import itertools
import json
import os
import sys
import tempfile
import time

import psutil

from lighthouse_ai import supervisor as S
from lighthouse_ai.paths import make_paths
from lighthouse_ai.persistence import open_db
from lighthouse_ai.supervisor import serve_in_thread


def _enqueue_trivial_job(state_db, n: int) -> None:
    """Insert a tiny offline 'decide' job so the dispatch path stays exercised."""
    meta = {"topic": f"soak option pick {n}", "options": ["A", "B"],
            "criteria": [{"label": "cost", "weight": 1.0}]}
    conn = open_db(state_db)
    try:
        conn.execute(
            "INSERT INTO jobs (id, mode, status, metadata_json) VALUES (?, ?, 'queued', ?)",
            (f"soak-{n}", "decide", json.dumps(meta)))
    finally:
        conn.close()


def _is_monotonic_growth(series: list[float], *, min_frac: float,
                         min_abs: float = 0.0, warmup_frac: float = 0.2) -> bool:
    """True if the series rises by > min_frac end-over-start AND mostly monotonically.

    A genuine leak grows steadily; transient bumps (GC, caches warming) are not
    monotonic. We require both a net rise and that ≥80% of steps are non-decreasing.

    The first ``warmup_frac`` of samples is excluded: connection pools, kqueue
    fds and caches settle during the first minutes of a run, and measured from
    sample 0 that warmup reads as monotonic growth (observed live: fds 7→10,
    plateau). ``min_abs`` additionally requires the post-warmup rise to be big
    enough to matter — e.g. a 4-fd drift is noise, a 20-fd rise is a leak.
    """
    s = series[int(len(series) * warmup_frac):]
    if len(s) < 4 or s[0] <= 0:
        return False
    net = s[-1] - s[0]
    ups = sum(1 for a, b in itertools.pairwise(s) if b >= a)
    return net > min_frac * s[0] and net >= min_abs and ups >= 0.8 * (len(s) - 1)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=int, default=60)
    ap.add_argument("--hours", type=float, default=None)
    ap.add_argument("--sample-every", type=int, default=10)
    ap.add_argument("--load", action="store_true", help="enqueue a job each minute")
    args = ap.parse_args()
    duration = int(args.hours * 3600) if args.hours else args.seconds
    os.environ.setdefault("LIGHTHOUSE_AIRGAP", "1")

    tmp = tempfile.mkdtemp(prefix="lh-soak-")
    paths = make_paths(data_dir=tmp)
    server, web_thread, port = serve_in_thread(paths, port=0)
    loops = [
        S._start_subconscious_loop(paths, interval_s=10.0),
        S._start_monitor_loop(paths, interval_s=10.0),
        S._start_dispatch_loop(paths, interval_s=5.0, offline=True),
        S._start_resolver_loop(paths, interval_s=30.0),
        S._start_backup_loop(paths),
    ]
    proc = psutil.Process()
    print(f"soak: {duration}s, sampling every {args.sample_every}s, "
          f"{len(loops)} loops, load={args.load} (data={tmp})")

    rss: list[float] = []
    fds: list[float] = []
    threads: list[float] = []
    findings: list[str] = []
    t0 = time.monotonic()
    jobs = 0
    next_job = 60.0
    while time.monotonic() - t0 < duration:
        elapsed = time.monotonic() - t0
        if args.load and elapsed >= next_job:
            jobs += 1
            try:
                _enqueue_trivial_job(paths.state_db, jobs)
            except Exception as exc:
                findings.append(f"enqueue failed: {exc!r}")
            next_job += 60.0
        rss.append(proc.memory_info().rss / 1e6)
        try:
            fds.append(float(proc.num_fds()))
        except Exception:
            fds.append(0.0)
        threads.append(float(proc.num_threads()))
        alive = sum(1 for t in loops if t.is_alive())
        if alive < len(loops):
            findings.append(f"loop(s) died at t={elapsed:.0f}s: "
                            f"{[t.name for t in loops if not t.is_alive()]}")
        if len(rss) % 6 == 1:
            print(f"  t={elapsed:6.0f}s  rss={rss[-1]:6.0f}MB  fds={fds[-1]:.0f}  "
                  f"threads={threads[-1]:.0f}  loops={alive}/5  jobs={jobs}")
        time.sleep(args.sample_every)

    server.should_exit = True
    web_thread.join(timeout=10)
    if web_thread.is_alive():
        findings.append("web server did not shut down within 10s")

    def _report(name: str, s: list[float], unit: str) -> None:
        if s:
            print(f"  {name:8} min={min(s):.0f}{unit} max={max(s):.0f}{unit} "
                  f"start={s[0]:.0f} end={s[-1]:.0f}")

    print("\n=== SOAK SUMMARY ===")
    _report("rss", rss, "MB")
    _report("fds", fds, "")
    _report("threads", threads, "")
    if _is_monotonic_growth(rss, min_frac=0.5, min_abs=50.0):
        findings.append(f"possible MEMORY leak: RSS rose {rss[0]:.0f}→{rss[-1]:.0f}MB monotonically")
    if _is_monotonic_growth(fds, min_frac=0.5, min_abs=20.0):
        findings.append(f"possible FD leak: fds rose {fds[0]:.0f}→{fds[-1]:.0f} monotonically")
    if _is_monotonic_growth(threads, min_frac=0.5, min_abs=4.0):
        findings.append(f"possible THREAD leak: {threads[0]:.0f}→{threads[-1]:.0f} monotonically")
    if findings:
        for f in findings:
            print("  -", f)
        print("RESULT: FAIL")
        return 1
    print("RESULT: PASS — no loop death, no monotonic RSS/fd/thread growth, clean shutdown.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
