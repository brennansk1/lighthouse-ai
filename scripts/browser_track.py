"""Bounded Track-tab browser QA: seed positions, load /#track, capture errors.

In-thread uvicorn (dies with the script — no daemon, per the resource-safety
invariant). Seeds resolved positions + a human-queue item so the calibration
ReliabilityBands + HumanQueue components actually render, then checks for
JSX-compile / React-runtime errors and screenshots to /tmp/lh-track.png.

Run: uv run python scripts/browser_track.py
"""

from __future__ import annotations

import sys
import tempfile

from playwright.sync_api import sync_playwright

from lighthouse_ai.paths import make_paths
from lighthouse_ai.supervisor import serve_in_thread
from lighthouse_ai.verification.positions import (
    enqueue_human_resolution,
    record_position,
    resolve_position,
)


def main() -> int:
    tmp = tempfile.mkdtemp(prefix="lh-track-verify-")
    paths = make_paths(data_dir=tmp)
    server, thread, port = serve_in_thread(paths, port=0)  # migrates the DBs
    # Seed: two resolved in the "likely" band (one hit, one miss) + one human-queue.
    p1 = record_position(
        paths.positions_db, claim="GDP growth will exceed 2% in 2026.", probability=0.8
    )
    p2 = record_position(
        paths.positions_db, claim="The bill will pass committee by Q3.", probability=0.8
    )
    p3 = record_position(
        paths.positions_db, claim="Should the agency prioritize solar over wind?", probability=0.5
    )
    resolve_position(paths.positions_db, p1.id, outcome=True)
    resolve_position(paths.positions_db, p2.id, outcome=False)
    enqueue_human_resolution(
        paths.positions_db, p3.id, "subjective or long-horizon claim — needs a human"
    )

    base = f"http://127.0.0.1:{port}"
    print(f"server up on {base}")
    rc = 0
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page()
            console_errors: list[str] = []
            page_errors: list[str] = []
            page.on(
                "console", lambda m: console_errors.append(m.text) if m.type == "error" else None
            )
            page.on("pageerror", lambda e: page_errors.append(str(e)))
            page.goto(f"{base}/#track", wait_until="domcontentloaded", timeout=20000)
            page.wait_for_timeout(2500)
            text = page.evaluate("() => (document.querySelector('#root')||document.body).innerText")
            page.screenshot(path="/tmp/lh-track.png", full_page=True)
            checks = {
                "Needs your call": "Needs your call" in text,
                "human-queue claim": "prioritize solar" in text,
                "reliability heading": "how often is it right" in text,
                "came-true label": "Came true" in text,
            }
            for k, ok in checks.items():
                print(f"  [{'OK' if ok else 'MISS'}] {k}")
            if console_errors:
                print("CONSOLE ERRORS:", console_errors[:5])
                rc = 1
            if page_errors:
                print("PAGE ERRORS:", page_errors[:5])
                rc = 1
            if not all(checks.values()):
                print("CONTENT MISSING")
                rc = 1
            browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=5)
    print("screenshot: /tmp/lh-track.png")
    print("RESULT:", "PASS" if rc == 0 else "FAIL")
    return rc


if __name__ == "__main__":
    sys.exit(main())
