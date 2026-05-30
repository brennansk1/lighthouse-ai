"""Real-browser interaction flow: create a research job + toggle global Pause.

Validates the actual user journey end-to-end through the live UI -> API -> DB,
which the render-only smoke and the in-process API tests don't cover together.
Bounded (in-thread uvicorn, ephemeral port, dies with the script).

Run: uv run python scripts/browser_flow.py
"""
from __future__ import annotations

import sys
import tempfile

import httpx
from playwright.sync_api import sync_playwright

from lighthouse_ai.paths import make_paths
from lighthouse_ai.supervisor import serve_in_thread

TOPIC = "What is retrieval-augmented generation?"


def main() -> int:
    tmp = tempfile.mkdtemp(prefix="lh-browser-flow-")
    paths = make_paths(data_dir=tmp)
    server, thread, port = serve_in_thread(paths, port=0)
    base = f"http://127.0.0.1:{port}"
    findings: list[str] = []
    print(f"server up on {base}")

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            errors: list[str] = []
            posts: list[str] = []
            page.on("pageerror", lambda e: errors.append(str(e)))

            def _on_response(r):
                if "/api/jobs" in r.url and r.request.method == "POST":
                    body = ""
                    try:
                        body = r.text()[:200]
                    except Exception:
                        pass
                    posts.append(f"POST /api/jobs -> {r.status}: {body}")

            page.on("response", _on_response)

            # ---- Flow 1: create a research job through the 3-step wizard ----
            page.goto(f"{base}/#research", wait_until="domcontentloaded")
            try:
                # Step 1 — pick a mode (cards load from GET /api/modes).
                card = page.get_by_role("button", name="Investigate", exact=False).first
                card.wait_for(state="visible", timeout=15000)
                card.click()
                # Step 2 — wait for the frame step, then fill the question.
                page.get_by_text("Frame your", exact=False).first.wait_for(
                    state="visible", timeout=10000)
                box = page.get_by_placeholder("e.g. What is driving", exact=False)
                box.wait_for(state="visible", timeout=8000)
                box.fill(TOPIC)
                page.get_by_role("button", name="Next: review",
                                 exact=False).first.click()
                # Step 3 — launch (target the BUTTON, not descriptive prose that
                # also contains the word "launch").
                launch = page.get_by_role("button", name="Launch",
                                          exact=False).first
                launch.wait_for(state="visible", timeout=10000)
                launch.click()
                page.wait_for_timeout(2500)
            except Exception as exc:
                page.screenshot(path="/tmp/lh-flow-fail.png", full_page=True)
                findings.append(f"wizard interaction error: {exc!r} "
                                "(screenshot /tmp/lh-flow-fail.png)")

            for pr in posts:
                print(f"  net: {pr}")
            jobs = httpx.get(f"{base}/api/jobs", timeout=10).json()
            job_list = jobs.get("jobs", jobs) if isinstance(jobs, dict) else jobs
            created = [j for j in job_list
                       if TOPIC[:20] in str(j.get("metadata_json", j))
                       or TOPIC[:20] in str(j)]
            if created:
                print(f"  job-create  OK    {len(job_list)} job(s); ours present "
                      f"(mode={created[0].get('mode')}, status={created[0].get('status')})")
            else:
                findings.append(f"wizard launch did not create a job (jobs={job_list})")
                print(f"  job-create  FAIL  jobs={job_list}")

            # ---- Flow 2: global Pause toggle ----
            page.get_by_text("Pause all", exact=False).first.click()
            page.wait_for_timeout(800)
            ctrl = httpx.get(f"{base}/api/control", timeout=10).json()
            paused_after = "paus" in str(ctrl).lower()
            resume_visible = page.get_by_text("Resume work", exact=False).count() > 0
            if paused_after and resume_visible:
                print(f"  pause-btn   OK    control={ctrl}")
            else:
                findings.append(f"Pause did not flip state (control={ctrl}, "
                                f"resume_visible={resume_visible})")
                print(f"  pause-btn   FAIL  control={ctrl} resume_visible={resume_visible}")
            # Resume so we leave clean state.
            if resume_visible:
                page.get_by_text("Resume work", exact=False).first.click()
                page.wait_for_timeout(600)

            # ---- Flow 3: sandbox upload — benign accepted, hostile rejected ----
            import os
            page.goto(f"{base}/#sandbox", wait_until="domcontentloaded")
            page.wait_for_timeout(1200)
            benign = os.path.join(tmp, "benign.txt")
            with open(benign, "w") as fh:
                fh.write("hello lighthouse — benign analysis data for the sandbox.\n")
            page.locator("input[type='file']").set_input_files(benign)
            page.wait_for_timeout(1800)
            eicar = os.path.join(tmp, "evil.com")
            with open(eicar, "w") as fh:
                fh.write(r"X5O!P%@AP[4\PZX54(P^)7CC)7}$EICAR-STANDARD-"
                         r"ANTIVIRUS-TEST-FILE!$H+H*")
            page.locator("input[type='file']").set_input_files(eicar)
            page.wait_for_timeout(1800)

            sb = httpx.get(f"{base}/api/sandbox", timeout=10).json()
            items = sb.get("items", sb) if isinstance(sb, dict) else sb
            benign_stored = any("benign" in str(i.get("filename", "")) for i in items)
            eicar_clean = any("evil" in str(i.get("filename", "")) and
                              i.get("scan_verdict") == "clean" for i in items)
            if benign_stored and not eicar_clean:
                print(f"  sandbox     OK    benign stored; EICAR not stored-as-clean "
                      f"({len(items)} item(s))")
            else:
                findings.append(f"sandbox security: benign_stored={benign_stored}, "
                                f"eicar_clean={eicar_clean}, items={items}")
                print(f"  sandbox     FAIL  benign_stored={benign_stored} "
                      f"eicar_clean={eicar_clean}")

            if errors:
                findings.append(f"page errors: {errors[:3]}")
            browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=5)

    print("\n=== SUMMARY ===")
    if not findings:
        print("INTERACTION FLOWS OK — wizard creates a job; global Pause toggles "
              "state; sandbox stores benign + blocks EICAR.")
        return 0
    for f in findings:
        print("  -", f)
    return 1


if __name__ == "__main__":
    sys.exit(main())
