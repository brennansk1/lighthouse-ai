"""TUI tests using Textual's headless pilot. No live supervisor — a
FakeClient feeds canned API responses, so these run fast and never load a
model or open a socket.

Read rendered text via ``str(widget.render())`` (Textual 8.x: Static has
no ``.renderable``; use ``.render()``)."""

from __future__ import annotations

import pytest

from lighthouse_ai.tui.app import PAGES, LighthouseTUI
from lighthouse_ai.tui.client import FakeClient, SupervisorOffline
from lighthouse_ai.tui.widgets import Sparkline, StatusBar, WepBadge, sparkline

pytestmark = pytest.mark.asyncio


# ──────────────────────────── fixtures ────────────────────────────
def _fake() -> FakeClient:
    return FakeClient({
        "/api/dashboard": {
            "greeting": "Good morning", "date": "Wed 27 May",
            "calibration": {"brier": 0.183, "history": [0.2, 0.19, 0.18, 0.183]},
            "jobs": [{"id": "7f2a", "status": "running", "mode": "Deep-Dive",
                      "metadata": {"topic": "EU AI Act", "progress": 0.6}},
                     {"id": "a91d", "status": "review", "mode": "QUC",
                      "metadata": {"topic": "ARM errata", "progress": 1.0}}],
            "alerts": [{"kind": "budget", "text": "Cloud at 71%"}],
            "digest": [{"topic": "EU AI Act", "delta": "New text published"}],
            "lead": {"title": "A lead finding", "wep": {"phrase": "likely"}},
        },
        "/api/jobs": {"jobs": [
            {"id": "7f2a", "status": "running", "mode": "Deep-Dive",
             "metadata": {"topic": "EU AI Act", "progress": 0.6}},
            {"id": "a91d", "status": "review", "mode": "QUC",
             "metadata": {"topic": "ARM errata", "progress": 1.0}}]},
        "/api/jobs/7f2a": {
            "id": "7f2a", "status": "running", "mode": "Deep-Dive",
            "metadata": {"topic": "EU AI Act", "progress": 0.6,
                         "trace": ["framing", "planner"],
                         "evidence": ["chunk-1", "chunk-2"],
                         "intents": [{"target": "logseq", "status": "queued"}]},
            "model_calls": [{"seq": 4, "ts": "now", "model": "qwen3:8b",
                             "tokens": 1200}]},
        "/api/drafts": {"drafts": [
            {"id": "d1", "title": "Holography draft", "status": "staged"}]},
        "/api/drafts/d1": {"id": "d1", "title": "Holography draft",
                           "status": "staged", "wep_phrase": "very likely",
                           "wep_band": "0.85-0.95", "source_count": 23,
                           "body_html": "<p>body text</p>"},
        "/api/topics": {"topics": [
            {"id": "t1", "name": "Quantum", "mode": "Monitor",
             "source_count": 2, "status": "active"}]},
        "/api/topics/t1": {"id": "t1", "name": "Quantum", "mode": "Monitor",
                           "cadence": "continuous", "status": "active",
                           "sources": [{"id": 1, "grade": "A",
                                        "url": "https://x/feed"}]},
        "/api/positions": {"positions": [
            {"id": 1, "claim": "X happens", "wep_band": "likely",
             "confidence": 0.8, "outcome": None}]},
        "/api/positions?overdue=true": {"positions": [
            {"id": 1, "claim": "X happens", "wep_band": "likely",
             "confidence": 0.8, "outcome": None}]},
        "/api/calibration": {"n": 1, "mean_brier": 0.04,
                             "mean_probability": 0.8, "mean_outcome_rate": 1.0,
                             "calibration_error": 0.2,
                             "bins": [{"observed": 0.1}, {"observed": 0.9}]},
        "/api/hypotheses": {"hypotheses": [
            {"id": 1, "statement": "Quantum supremacy holds", "status": "open"}]},
        "/api/health": {
            "overall": "green", "checked_at": "now",
            "hardware": {"platform": "macos", "arch": "arm64",
                         "total_ram_gb": 64, "tier": "T3"},
            "databases": {"state": "ok", "audit": "ok"},
            "external": {"ollama": True, "qdrant": False},
            "budget": {"tier": "green", "usd": {"used": 32, "cap": 50},
                       "tokens": {"used": 800000, "cap": 8000000},
                       "tool_calls": {"used": 1500, "cap": 5000}},
            "storage": {"disk_total_gb": 500, "disk_free_gb": 312,
                        "subdirs_bytes": {"corpus": 2.1e9}, "replicas": []},
            "outbox_depth": 0, "audit_chain_ok": True,
        },
        "/api/audit": {"events": [
            {"seq": 1, "ts": "now", "actor": "gateway",
             "event_type": "model_call"}]},
        "/api/settings": {"config": {"lighthouse": {"version": "0.2.0"},
                                     "hardware": {"detected_tier": "T3"}}},
        "/api/skills": {"skills": [{"name": "extract_table", "use_count": 3}]},
        "/api/perspectives": {"perspectives": [
            {"name": "steelman", "stance": "best case"}]},
        "/api/secrets": {"secrets": {"audit.chain": "***"}},
    })


class _Offline:
    def get(self, path, **kw):
        raise SupervisorOffline("down")

    def post(self, path, json=None):
        raise SupervisorOffline("down")

    def available(self):
        return False

    def close(self):
        pass


# ────────────────────────── widget unit tests ──────────────────────────
async def test_sparkline_empty_and_flat():
    assert sparkline([]) == ""
    assert sparkline([5, 5, 5]) == "▁▁▁"


async def test_sparkline_monotonic_uses_full_ramp():
    out = sparkline([0, 1, 2, 3, 4, 5, 6, 7])
    assert out[0] == "▁" and out[-1] == "█"


async def test_sparkline_widget_renders():
    app = LighthouseTUI(client=_fake())
    async with app.run_test():
        sp = Sparkline([1, 2, 3])
        await app.mount(sp)
        assert "▁" in str(sp.render())


async def test_wep_badge_colors_phrase():
    app = LighthouseTUI(client=_fake())
    async with app.run_test():
        badge = WepBadge("very likely", "0.85-0.95")
        await app.mount(badge)
        text = str(badge.render())
        assert "very likely" in text and "0.85-0.95" in text


async def test_status_bar_widget_offline_class():
    app = LighthouseTUI(client=_fake())
    async with app.run_test():
        bar = StatusBar()
        await app.mount(bar)
        bar.set_offline()
        assert bar.has_class("-offline")
        assert "offline" in str(bar.render()).lower()


# ──────────────────────────── app boot ────────────────────────────
async def test_app_boots_and_shows_home():
    app = LighthouseTUI(client=_fake())
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.query_one("#main").current == "home"
        assert "Good morning" in str(app.query_one("#home-body").render())


async def test_home_shows_alert_and_digest():
    app = LighthouseTUI(client=_fake())
    async with app.run_test() as pilot:
        await pilot.pause()
        body = str(app.query_one("#home-body").render())
        assert "BUDGET" in body
        assert "EU AI ACT" in body


async def test_digit_keys_switch_all_seven_pages():
    app = LighthouseTUI(client=_fake())
    async with app.run_test() as pilot:
        for key, page in [("2", "jobs"), ("3", "drafts"), ("4", "topics"),
                          ("5", "positions"), ("6", "health"),
                          ("7", "settings"), ("1", "home")]:
            await pilot.press(key)
            await pilot.pause()
            assert app.query_one("#main").current == page


async def test_all_seven_pages_exist():
    app = LighthouseTUI(client=_fake())
    async with app.run_test() as pilot:
        await pilot.pause()
        for pid, _label, _cls in PAGES:
            assert app.query_one(f"#{pid}") is not None


async def test_sidebar_nav_click_switches_page():
    app = LighthouseTUI(client=_fake())
    async with app.run_test() as pilot:
        from lighthouse_ai.tui.widgets import Sidebar
        app.query_one(Sidebar).post_message(Sidebar.NavSelected("health"))
        await pilot.pause()
        assert app.query_one("#main").current == "health"


# ──────────────────────────── per-screen data ────────────────────────────
async def test_jobs_table_populated():
    app = LighthouseTUI(client=_fake())
    async with app.run_test() as pilot:
        await pilot.press("2")
        await pilot.pause()
        from textual.widgets import DataTable
        assert app.query_one("#jobs-table", DataTable).row_count == 2


async def test_drafts_list_populated():
    app = LighthouseTUI(client=_fake())
    async with app.run_test() as pilot:
        await pilot.press("3")
        await pilot.pause()
        from textual.widgets import ListView
        assert len(app.query_one("#drafts-list", ListView).children) == 1


async def test_topics_table_populated():
    app = LighthouseTUI(client=_fake())
    async with app.run_test() as pilot:
        await pilot.press("4")
        await pilot.pause()
        from textual.widgets import DataTable
        t = app.query_one("#topics-table", DataTable)
        assert t.row_count == 1


async def test_positions_tabs_render():
    app = LighthouseTUI(client=_fake())
    async with app.run_test() as pilot:
        await pilot.press("5")
        await pilot.pause()
        assert "X happens" in str(app.query_one("#pos-overdue").render())
        assert "Brier" in str(app.query_one("#pos-cal").render())


async def test_positions_hypotheses_kanban():
    app = LighthouseTUI(client=_fake())
    async with app.run_test() as pilot:
        await pilot.press("5")
        await pilot.pause()
        hyp = str(app.query_one("#pos-hyp").render())
        assert "OPEN" in hyp and "Quantum supremacy" in hyp


async def test_positions_calibration_has_reliability():
    app = LighthouseTUI(client=_fake())
    async with app.run_test() as pilot:
        await pilot.press("5")
        await pilot.pause()
        assert "Reliability" in str(app.query_one("#pos-cal").render())


async def test_health_overview_renders():
    app = LighthouseTUI(client=_fake())
    async with app.run_test() as pilot:
        await pilot.press("6")
        await pilot.pause()
        ov = str(app.query_one("#health-overview").render())
        assert "Hardware" in ov and "green" in ov


async def test_health_budget_bars():
    app = LighthouseTUI(client=_fake())
    async with app.run_test() as pilot:
        await pilot.press("6")
        await pilot.pause()
        assert "USD" in str(app.query_one("#health-budget").render())


async def test_health_audit_table():
    app = LighthouseTUI(client=_fake())
    async with app.run_test() as pilot:
        await pilot.press("6")
        await pilot.pause()
        from textual.widgets import DataTable
        assert app.query_one("#audit-table", DataTable).row_count == 1


async def test_settings_general_renders():
    app = LighthouseTUI(client=_fake())
    async with app.run_test() as pilot:
        await pilot.press("7")
        await pilot.pause()
        assert "0.2.0" in str(app.query_one("#set-general").render())


async def test_settings_skills_and_perspectives():
    app = LighthouseTUI(client=_fake())
    async with app.run_test() as pilot:
        await pilot.press("7")
        await pilot.pause()
        assert "extract_table" in str(app.query_one("#set-skills").render())
        assert "steelman" in str(app.query_one("#set-persp").render())


# ──────────────────────────── status bar ────────────────────────────
async def test_status_bar_shows_tier():
    app = LighthouseTUI(client=_fake())
    async with app.run_test() as pilot:
        await pilot.pause()
        assert "T3" in str(app.query_one("#status").render())


async def test_status_bar_shows_running_and_review():
    app = LighthouseTUI(client=_fake())
    async with app.run_test() as pilot:
        await pilot.pause()
        bar = str(app.query_one("#status").render())
        assert "1 running" in bar and "review" in bar


async def test_sidebar_counters_set():
    app = LighthouseTUI(client=_fake())
    async with app.run_test() as pilot:
        await pilot.pause()
        from lighthouse_ai.tui.widgets import Sidebar
        # jobs running=1, drafts(review)=1, positions overdue=1
        assert app.query_one(Sidebar)._counters["jobs"] == 1
        assert app.query_one(Sidebar)._counters["positions"] == 1


# ──────────────────────────── modals ────────────────────────────
async def test_new_job_modal_posts():
    fake = _fake()
    app = LighthouseTUI(client=fake)
    async with app.run_test() as pilot:
        await pilot.press("2")
        await pilot.pause()
        await pilot.press("n")
        await pilot.pause()
        app.screen.query_one("#job-topic").value = "New research topic"
        await pilot.click("#ok")
        await pilot.pause()
        assert any(p[0] == "/api/jobs" for p in fake.posts)


async def test_new_topic_modal_posts():
    fake = _fake()
    app = LighthouseTUI(client=fake)
    async with app.run_test() as pilot:
        await pilot.press("4")
        await pilot.pause()
        await pilot.press("n")
        await pilot.pause()
        app.screen.query_one("#topic-name").value = "Photonics"
        await pilot.click("#ok")
        await pilot.pause()
        assert any(p[0] == "/api/topics" for p in fake.posts)


async def test_reject_modal_posts_reason():
    fake = _fake()
    app = LighthouseTUI(client=fake)
    async with app.run_test() as pilot:
        await pilot.press("3")
        await pilot.pause()
        from lighthouse_ai.tui.screens import DraftsPage
        # select the draft then open reject modal
        app.query_one("#drafts", DraftsPage)._selected = "d1"
        await pilot.press("r")
        await pilot.pause()
        app.screen.query_one("#reason").value = "weak sourcing"
        await pilot.click("#ok")
        await pilot.pause()
        assert any(p[0] == "/api/drafts/d1/reject" for p in fake.posts)


async def test_drafts_approve_posts():
    fake = _fake()
    app = LighthouseTUI(client=fake)
    async with app.run_test() as pilot:
        await pilot.press("3")
        await pilot.pause()
        from lighthouse_ai.tui.screens import DraftsPage
        app.query_one("#drafts", DraftsPage)._selected = "d1"
        await pilot.press("a")
        await pilot.pause()
        assert any(p[0] == "/api/drafts/d1/approve" for p in fake.posts)


async def test_help_overlay_opens():
    app = LighthouseTUI(client=_fake())
    async with app.run_test() as pilot:
        await pilot.press("question_mark")
        await pilot.pause()
        from lighthouse_ai.tui.screens import HelpModal
        assert isinstance(app.screen, HelpModal)


async def test_job_detail_screen_tabs():
    app = LighthouseTUI(client=_fake())
    async with app.run_test() as pilot:
        await pilot.press("2")
        await pilot.pause()
        from lighthouse_ai.tui.screens import JobsPage, JobDetailScreen
        app.query_one("#jobs", JobsPage).action_open_detail()
        await pilot.pause()
        assert isinstance(app.screen, JobDetailScreen)
        assert "framing" in str(app.screen.query_one("#jd-trace-body").render())


# ──────────────────────────── offline ────────────────────────────
async def test_offline_home_degrades_gracefully():
    app = LighthouseTUI(client=_Offline())
    async with app.run_test() as pilot:
        await pilot.pause()
        assert "offline" in str(app.query_one("#home-body").render()).lower()


async def test_offline_status_bar():
    app = LighthouseTUI(client=_Offline())
    async with app.run_test() as pilot:
        await pilot.pause()
        bar = app.query_one("#status")
        assert "offline" in str(bar.render()).lower()
        assert bar.has_class("-offline")


async def test_offline_all_pages_no_crash():
    app = LighthouseTUI(client=_Offline())
    async with app.run_test() as pilot:
        for key in "234567":
            await pilot.press(key)
            await pilot.pause()
        # If we got here without an exception, the app stayed alive.
        assert app.query_one("#main") is not None


# ──────────────────────────── theme ────────────────────────────
async def test_theme_toggle():
    app = LighthouseTUI(client=_fake())
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.theme == "coastal-dark"
        await pilot.press("ctrl+t")
        await pilot.pause()
        assert app.theme == "coastal-light"
