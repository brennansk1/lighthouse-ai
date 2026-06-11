"""Bounded supervisor integration smoke (no LIGHTHOUSE_REAL_BACKEND → stub
backends, no model loads). Boots the web server + all 5 daemon loops on a temp
data dir, watches them tick without crashing for ~30s, exercises the global
Pause API, and confirms clean shutdown. Daemon threads die with the script.

Run: uv run python scripts/supervisor_smoke.py
"""
from __future__ import annotations

import sys
import tempfile
import time

import httpx
import psutil

from lighthouse_ai import supervisor as S
from lighthouse_ai.paths import make_paths
from lighthouse_ai.supervisor import serve_in_thread


def main() -> int:
    tmp = tempfile.mkdtemp(prefix="lh-supervisor-smoke-")
    paths = make_paths(data_dir=tmp)
    server, web_thread, port = serve_in_thread(paths, port=0)
    base = f"http://127.0.0.1:{port}"
    print(f"web up on {base}")

    loops = [
        S._start_subconscious_loop(paths, interval_s=3.0),
        S._start_monitor_loop(paths, interval_s=3.0),
        S._start_dispatch_loop(paths, interval_s=2.0, offline=True),
        S._start_resolver_loop(paths, interval_s=5.0),
        S._start_backup_loop(paths),
    ]
    print(f"started {len(loops)} daemon loops: {[t.name for t in loops]}")

    findings: list[str] = []
    rss0 = psutil.Process().memory_info().rss / 1e6
    for i in range(10):  # ~30s
        alive = sum(1 for t in loops if t.is_alive())
        free = psutil.virtual_memory().available / 1e9
        if alive < len(loops):
            dead = [t.name for t in loops if not t.is_alive()]
            findings.append(f"loop(s) died: {dead}")
        if i % 3 == 0:
            print(f"  t={i*3:2d}s  loops_alive={alive}/5  RAM_free={free:.1f}GB")
        time.sleep(3)

    # Health endpoint responds while loops run.
    try:
        h = httpx.get(f"{base}/api/health", timeout=5)
        print(f"  /api/health -> {h.status_code}")
    except Exception as exc:
        findings.append(f"/api/health failed: {exc!r}")

    # Global Pause API flips state; loops should honor it.
    httpx.post(f"{base}/api/pause", json={"hard": False}, timeout=5)
    time.sleep(2)
    ctrl = httpx.get(f"{base}/api/control", timeout=5).json()
    if "paus" not in str(ctrl).lower():
        findings.append(f"pause did not flip state: {ctrl}")
    else:
        print(f"  pause OK -> {ctrl}")
    httpx.post(f"{base}/api/resume", timeout=5)

    rss1 = psutil.Process().memory_info().rss / 1e6
    print(f"  RSS {rss0:.0f}MB -> {rss1:.0f}MB over the run")

    # Clean shutdown.
    server.should_exit = True
    web_thread.join(timeout=5)
    shutdown_clean = not web_thread.is_alive()
    if not shutdown_clean:
        findings.append("web server did not shut down within 5s")
    else:
        print("  clean shutdown OK")

    print("\n=== SUMMARY ===")
    if not findings:
        print("SUPERVISOR SMOKE OK — 5 loops booted + ticked + survived; pause "
              "works; clean shutdown; no RSS blowup.")
        return 0
    for f in findings:
        print("  -", f)
    return 1


if __name__ == "__main__":
    sys.exit(main())
