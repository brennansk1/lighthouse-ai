"""Bounded UX sweep of every dashboard tab against DEFINITION_OF_DONE §3.

In-thread uvicorn (no daemon). Seeds a little data so empty/non-empty states are
both exercisable, loads each tab in headless chromium, captures console/page
errors + body length (white-screen check), and screenshots to /tmp/lh-ux-<tab>.png.

Run: uv run python scripts/browser_ux_sweep.py
"""

from __future__ import annotations

import sys
import tempfile

from playwright.sync_api import sync_playwright

from lighthouse_ai.paths import make_paths
from lighthouse_ai.supervisor import serve_in_thread

TABS = [
    "research",
    "library",
    "watch",
    "track",
    "activity",
    "sandbox",
    "health",
    "info",
    "settings",
]


def main() -> int:
    tmp = tempfile.mkdtemp(prefix="lh-ux-sweep-")
    paths = make_paths(data_dir=tmp)
    server, thread, port = serve_in_thread(paths, port=0)
    base = f"http://127.0.0.1:{port}"
    print(f"server up on {base}")
    rc = 0
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            for tab in TABS:
                page = browser.new_page()
                cerr: list[str] = []
                perr: list[str] = []
                page.on(
                    "console", lambda m, c=cerr: c.append(m.text) if m.type == "error" else None  # type: ignore
                )
                page.on("pageerror", lambda e, p=perr: p.append(str(e)))  # type: ignore
                page.goto(f"{base}/#{tab}", wait_until="domcontentloaded", timeout=20000)
                page.wait_for_timeout(2000)
                body_len = page.evaluate(
                    "() => (document.querySelector('#root')||document.body).innerText.trim().length"
                )
                page.screenshot(path=f"/tmp/lh-ux-{tab}.png", full_page=True)
                status = "ok"
                if cerr or perr:
                    status = f"ERRORS console={cerr[:3]} page={perr[:3]}"
                    rc = 1
                elif body_len < 40:
                    status = f"WHITE-SCREEN (body_len={body_len})"
                    rc = 1
                print(f"  [{tab:9}] body_len={body_len:5} {status}")
                page.close()
            browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=5)
    print("RESULT:", "PASS" if rc == 0 else "FAIL")
    return rc


if __name__ == "__main__":
    sys.exit(main())
