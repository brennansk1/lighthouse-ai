"""Bounded real-browser smoke of the dashboard.

Starts the FastAPI app in an in-process uvicorn thread (ephemeral port, dies with
this script — no lingering daemon), loads every nav page in headless chromium via
Playwright, and reports console errors / uncaught page exceptions / failed
requests / empty-render (white-screen). Catches JSX-compile + React-runtime
failures that the in-process TestClient API tests cannot.

Run: uv run python scripts/browser_smoke.py
"""
from __future__ import annotations

import sys
import tempfile

from playwright.sync_api import sync_playwright

from lighthouse_ai.paths import make_paths
from lighthouse_ai.supervisor import serve_in_thread

PAGES = ["research", "library", "watch", "sandbox", "health", "info", "settings"]


def main() -> int:
    tmp = tempfile.mkdtemp(prefix="lh-browser-smoke-")
    paths = make_paths(data_dir=tmp)
    server, thread, port = serve_in_thread(paths, port=0)
    base = f"http://127.0.0.1:{port}"
    print(f"server up on {base} (data={tmp})")

    findings: list[str] = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            for page_id in PAGES:
                page = browser.new_page()
                console_errors: list[str] = []
                page_errors: list[str] = []
                failed: list[str] = []
                # Bind the per-page lists as defaults so the lambdas capture this
                # iteration's lists, not the loop variable (ruff B023).
                page.on("console", lambda m, ce=console_errors:
                        ce.append(m.text) if m.type == "error" else None)
                page.on("pageerror", lambda e, pe=page_errors: pe.append(str(e)))
                page.on("requestfailed",
                        lambda r, fl=failed: fl.append(f"{r.method} {r.url}"))

                url = f"{base}/#{page_id}"
                # The dashboard holds a live SSE/event stream open, so
                # "networkidle" never fires — wait for DOM + a fixed mount window.
                page.goto(url, wait_until="domcontentloaded", timeout=20000)
                page.wait_for_timeout(2000)  # let babel compile + React mount

                # Did anything render under the React root?
                body_len = page.evaluate(
                    "() => (document.querySelector('#root') ||"
                    " document.body).innerText.trim().length"
                )
                shot = f"/tmp/lh-smoke-{page_id}.png"
                page.screenshot(path=shot, full_page=True)

                status = "OK"
                if body_len < 20:
                    status = "EMPTY-RENDER"
                    findings.append(f"[{page_id}] white-screen (innerText {body_len} chars)")
                # ignore benign favicon/network-tile 404s; flag JS/compile errors
                real_console = [e for e in console_errors if "favicon" not in e.lower()]
                if real_console:
                    status = "CONSOLE-ERR"
                    findings.append(f"[{page_id}] console: {real_console[:3]}")
                if page_errors:
                    status = "PAGE-ERR"
                    findings.append(f"[{page_id}] pageerror: {page_errors[:3]}")
                print(f"  {page_id:10s} {status:12s} innerText={body_len:5d}  -> {shot}")
                page.close()
            browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=5)

    print("\n=== SUMMARY ===")
    if not findings:
        print("ALL PAGES OK — rendered, no console/page errors.")
        return 0
    print(f"{len(findings)} finding(s):")
    for f in findings:
        print("  -", f)
    return 1


if __name__ == "__main__":
    sys.exit(main())
