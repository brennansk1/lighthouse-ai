"""Web dashboard tests — verify the design bundle is served and APIs respond.

The dashboard is a Claude Design handoff (React via babel-standalone). The
files in ``lighthouse_ai/web/static/`` are the literal bundle; tests confirm
they're reachable AND that the JSON dashboard API returns the right shape
so that swapping React's MOCK for live data is mechanical.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from lighthouse_ai.controlplane import create_app


def test_root_redirects_to_ui(migrated_paths):
    client = TestClient(create_app(migrated_paths))
    r = client.get("/", follow_redirects=False)
    assert r.status_code in (301, 302, 307)
    assert r.headers["location"].rstrip("/") == "/ui"


def test_ui_serves_index_html(migrated_paths):
    client = TestClient(create_app(migrated_paths))
    r = client.get("/ui/")
    assert r.status_code == 200
    assert "Lighthouse" in r.text
    # index.html now loads the real app shell, not the design canvas.
    assert "app.jsx" in r.text


def test_ui_serves_app_files(migrated_paths):
    client = TestClient(create_app(migrated_paths))
    # The production app is split: shared lib + two page bundles + shell.
    for fn in ("app.jsx", "app-lib.jsx", "app-pages-today.jsx",
               "app-pages-rest.jsx", "home-shared.jsx"):
        r = client.get(f"/ui/{fn}")
        assert r.status_code == 200, fn
        assert len(r.text) > 100


def test_ui_index_loads_split_bundles(migrated_paths):
    """index.html must load the 5 production scripts in dependency order."""
    client = TestClient(create_app(migrated_paths))
    html = client.get("/ui/").text
    for fn in ("home-shared.jsx", "app-lib.jsx", "app-pages-today.jsx",
               "app-pages-rest.jsx", "app.jsx"):
        assert fn in html, fn
    assert '<div id="root">' in html


def test_design_canvas_still_available(migrated_paths):
    """The original Claude Design handoff stays reachable at design.html."""
    client = TestClient(create_app(migrated_paths))
    r = client.get("/ui/design.html")
    assert r.status_code == 200
    assert "Home Variations" in r.text


def test_ui_serves_coastal_background():
    from pathlib import Path
    from lighthouse_ai.web.routes import _static_root
    bg = _static_root() / "assets" / "coastal-bg.png"
    assert bg.exists()
    assert bg.stat().st_size > 1000  # non-trivial image


def test_dashboard_api_returns_expected_shape(migrated_paths):
    client = TestClient(create_app(migrated_paths))
    r = client.get("/api/dashboard")
    assert r.status_code == 200
    body = r.json()
    # The shape mirrors the MOCK object in home-shared.jsx.
    for key in ("date", "generated_at", "jobs", "calibration", "budget",
                "alerts", "lead", "digest"):
        assert key in body, key
    assert isinstance(body["jobs"], list)
    assert "brier" in body["calibration"]


def test_dashboard_api_jobs_reflect_state_db(migrated_paths):
    import json
    from lighthouse_ai.persistence import open_db
    conn = open_db(migrated_paths.state_db)
    try:
        conn.execute(
            "INSERT INTO jobs (id, mode, status, metadata_json) "
            "VALUES ('abc', 'Deep-Dive', 'running', ?)",
            (json.dumps({"topic": "EU AI Act", "progress": 0.6,
                         "eta": "~2h", "depth": "Thorough"}),),
        )
    finally:
        conn.close()
    client = TestClient(create_app(migrated_paths))
    body = client.get("/api/dashboard").json()
    assert any(j["id"] == "abc" and j["topic"] == "EU AI Act"
               for j in body["jobs"])


def test_dashboard_api_budget_reflects_governor(migrated_paths):
    from lighthouse_ai.governor import BUDGET_DEFAULTS, Governor
    g = Governor(migrated_paths.state_db, BUDGET_DEFAULTS)
    g.try_spend(usd=1.50, tokens=100_000)
    client = TestClient(create_app(migrated_paths))
    body = client.get("/api/dashboard").json()
    assert abs(body["budget"]["cloud"]["used"] - 1.50) < 1e-6
    assert body["budget"]["tier"] in {"green", "warn", "degrade",
                                       "local_only", "drain", "tripped"}


def test_ui_does_not_shadow_existing_health(migrated_paths):
    """The static mount at /ui/ must not break /health or /governor."""
    client = TestClient(create_app(migrated_paths))
    assert client.get("/health").status_code == 200
    assert client.get("/governor").status_code == 200
    assert client.get("/api/health").status_code == 200


def test_dashboard_lead_picks_review_job(migrated_paths):
    """A job in 'review' status becomes the dashboard's lead story."""
    import json
    from lighthouse_ai.persistence import open_db
    conn = open_db(migrated_paths.state_db)
    try:
        conn.execute(
            "INSERT INTO jobs (id, mode, status, metadata_json) "
            "VALUES ('rev1', 'Deep-Dive', 'review', ?)",
            (json.dumps({"topic": "Resolved holography", "progress": 1.0,
                         "eta": "14d", "depth": "Thorough"}),),
        )
    finally:
        conn.close()
    client = TestClient(create_app(migrated_paths))
    body = client.get("/api/dashboard").json()
    assert body["lead"] is not None
    assert body["lead"]["title"] == "Resolved holography"
    assert "topic" in body["lead"]


def test_dashboard_digest_surfaces_running_jobs(migrated_paths):
    import json
    from lighthouse_ai.persistence import open_db
    conn = open_db(migrated_paths.state_db)
    try:
        conn.execute(
            "INSERT INTO jobs (id, mode, status, metadata_json) "
            "VALUES ('run1', 'Monitor', 'running', ?)",
            (json.dumps({"topic": "Fed discount window", "progress": 0.3}),),
        )
    finally:
        conn.close()
    client = TestClient(create_app(migrated_paths))
    digest = client.get("/api/dashboard").json()["digest"]
    assert digest
    assert any(d["topic"] == "Fed discount window" for d in digest)


def test_dashboard_jsx_exposes_useDashboard_hook():
    """home-shared.jsx must register `useDashboard` on window for variants."""
    from lighthouse_ai.web.routes import _static_root
    src = (_static_root() / "home-shared.jsx").read_text()
    assert "function useDashboard" in src
    assert "useDashboard" in src
    assert "Object.assign(window," in src


def test_home_variants_subscribe_to_live_data():
    """Each Home variant must shadow MOCK with the useDashboard hook."""
    from lighthouse_ai.web.routes import _static_root
    for fn in ("home-a.jsx", "home-b.jsx", "home-c.jsx"):
        src = (_static_root() / fn).read_text()
        assert "window.useDashboard" in src, fn
