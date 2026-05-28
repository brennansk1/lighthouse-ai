"""The seven TUI page panes plus their detail/modal screens.

Each page is a Container swapped into the main area by the app's
ContentSwitcher. Pages load data from ``self.app.client`` on mount and on
a poll timer (5–10 s). They degrade gracefully when the supervisor is
offline — every screen shows a hint instead of crashing.

Action keys are exposed as ``action_*`` methods and the app routes the
flat keymap to whichever page is active (see ``app.action_page_do``), so
they fire regardless of which inner widget holds focus.
"""

from __future__ import annotations

import json as _json
import re
from typing import Any

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import (
    Button, DataTable, Input, Label, ListItem, ListView, Markdown, Static,
    TabbedContent, TabPane,
)

from .client import SupervisorOffline
from .widgets import Sparkline, WepBadge, sparkline


# ════════════════════════════ base page ════════════════════════════
class _Page(Container):
    """Base page: client helpers + poll cadence + graceful-offline flag."""

    POLL_SECONDS = 8.0

    def client_get(self, path: str, **params: Any) -> dict[str, Any] | None:
        try:
            return self.app.client.get(path, **params)
        except SupervisorOffline:
            return None
        except Exception:  # noqa: BLE001 - never let a page crash the app
            return None

    def client_post(self, path: str, json: dict | None = None) -> dict[str, Any] | None:
        try:
            return self.app.client.post(path, json=json)
        except SupervisorOffline:
            self.app.notify("Supervisor offline", severity="error")
            return None
        except Exception as exc:  # noqa: BLE001
            self.app.notify(f"Request failed: {exc}", severity="error")
            return None

    def start_polling(self) -> None:
        self.refresh_data()
        self.set_interval(self.POLL_SECONDS, self.refresh_data)

    def refresh_data(self) -> None:  # pragma: no cover - overridden
        ...


# ════════════════════════════ HOME ════════════════════════════
class HomePage(_Page):
    def compose(self) -> ComposeResult:
        yield VerticalScroll(Static(id="home-body"))

    def on_mount(self) -> None:
        self.start_polling()

    def refresh_data(self) -> None:
        d = self.client_get("/api/dashboard")
        body = self.query_one("#home-body", Static)
        if d is None:
            body.update(
                "[yellow]Supervisor offline.[/] Could not reach the control "
                "plane.\n\nStart it with  [b]lighthouse start[/]  then press "
                "[b]1[/] to retry.")
            return
        cal = d.get("calibration") or {}
        jobs = d.get("jobs") or []
        running = [j for j in jobs if j.get("status") == "running"]
        review = [j for j in jobs if j.get("status") == "review"]
        lines = [
            f"[b]{d.get('greeting', 'Good morning')}[/]   {d.get('date', '')}",
            "",
            f"  Running now        [b]{len(running)}[/]",
            f"  Awaiting approval  [b]{len(review)}[/]",
            f"  Calibration Brier  [b]{cal.get('brier', cal.get('mean_brier', '—'))}[/]"
            "  (lower is better)",
            "",
        ]
        lead = d.get("lead")
        if lead:
            wep = lead.get("wep") or {}
            lines += [
                "[b]Lead finding[/]",
                f"  {lead.get('title', '')}",
                f"  confidence: {wep.get('phrase', 'unrated')}",
                "  [dim][r] read · [a] approve · [x] reject[/]",
                "",
            ]
        alerts = d.get("alerts") or []
        lines.append(f"[b]Alerts ({len(alerts)})[/]")
        if not alerts:
            lines.append("  Nothing needs attention.")
        for a in alerts:
            lines.append(
                f"  • [#c44536]{(a.get('kind', '') or '').upper()}[/] "
                f"{a.get('text', '')}")
        lines.append("")
        digest = d.get("digest") or []
        lines.append("[b]Topic activity — last 24h[/]")
        if not digest:
            lines.append("  No activity yet. Add a topic (press [b]4[/]).")
        for item in digest:
            lines.append(
                f"  [#2d7a9e]{(item.get('topic') or '').upper()}[/] "
                f"{item.get('delta', '')}")
        # Calibration sparkline (history if present, else single point).
        hist = cal.get("history") or cal.get("brier_history") or []
        if hist:
            lines += ["", f"[b]Brier 30d[/]  {sparkline(hist)}"]
        body.update("\n".join(lines))


# ════════════════════════════ JOBS ════════════════════════════
class JobsPage(_Page):
    def compose(self) -> ComposeResult:
        yield DataTable(id="jobs-table", cursor_type="row")
        yield Static("[dim]↑/↓ move · enter detail · n new · p pause/resume[/]",
                     classes="page-foot")

    def on_mount(self) -> None:
        t = self.query_one("#jobs-table", DataTable)
        t.add_columns("ID", "Mode", "Topic", "Status", "Progress")
        self._rows: list[dict] = []
        self.start_polling()

    def refresh_data(self) -> None:
        d = self.client_get("/api/jobs")
        t = self.query_one("#jobs-table", DataTable)
        prev = t.cursor_row
        t.clear()
        self._rows = (d or {}).get("jobs", [])
        if not self._rows:
            t.add_row("—", "—", "no jobs yet", "—", "—")
            return
        for j in self._rows:
            md = j.get("metadata") or {}
            prog = int((md.get("progress") or 0) * 100)
            bar = "█" * (prog // 20) + "░" * (5 - prog // 20)
            t.add_row(j["id"], j.get("mode", ""), md.get("topic", "—"),
                      j.get("status", ""), f"{bar} {prog}%", key=j["id"])
        if 0 <= prev < t.row_count:
            t.move_cursor(row=prev)

    def _selected_job(self) -> dict | None:
        t = self.query_one("#jobs-table", DataTable)
        if t.row_count == 0 or not self._rows:
            return None
        try:
            row_key = t.coordinate_to_cell_key(t.cursor_coordinate).row_key
        except Exception:  # noqa: BLE001
            return None
        return next((j for j in self._rows if j["id"] == row_key.value), None)

    def action_pause(self) -> None:
        job = self._selected_job()
        if not job:
            return
        verb = "resume" if job.get("status") == "paused" else "pause"
        self.client_post(f"/api/jobs/{job['id']}/{verb}")
        self.refresh_data()

    def action_new_job(self) -> None:
        self.app.push_screen(NewJobModal())

    def action_open_detail(self) -> None:
        job = self._selected_job()
        if job:
            self.app.push_screen(JobDetailScreen(job["id"]))

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.row_key and event.row_key.value:
            self.app.push_screen(JobDetailScreen(event.row_key.value))


# ════════════════════════════ JOB DETAIL ════════════════════════════
class JobDetailScreen(ModalScreen):
    """Pushed screen with tabs: Trace / Evidence / Model calls / Intents."""

    BINDINGS = [Binding("escape", "dismiss", "Back")]

    def __init__(self, job_id: str) -> None:
        super().__init__()
        self.job_id = job_id

    def compose(self) -> ComposeResult:
        with Container(id="job-detail-box"):
            yield Label(f"Job {self.job_id}   [dim](Esc back)[/]")
            with TabbedContent(initial="jd-trace"):
                with TabPane("Trace", id="jd-trace"):
                    yield VerticalScroll(Static(id="jd-trace-body"))
                with TabPane("Evidence", id="jd-evidence"):
                    yield VerticalScroll(Static(id="jd-evidence-body"))
                with TabPane("Model calls", id="jd-calls"):
                    yield DataTable(id="jd-calls-table", cursor_type="row")
                with TabPane("Intents", id="jd-intents"):
                    yield VerticalScroll(Static(id="jd-intents-body"))

    def on_mount(self) -> None:
        self.query_one("#jd-calls-table", DataTable).add_columns(
            "Seq", "Time", "Model", "Tokens")
        try:
            d = self.app.client.get(f"/api/jobs/{self.job_id}")
        except Exception:  # noqa: BLE001
            d = None
        if not d:
            self.query_one("#jd-trace-body", Static).update(
                "[yellow]Could not load job detail (supervisor offline).[/]")
            return
        md = d.get("metadata") or {}
        stages = md.get("trace") or [
            "framing", "planner", "researchers", "denoiser"]
        self.query_one("#jd-trace-body", Static).update(
            f"[b]{md.get('topic', self.job_id)}[/]\n\n"
            f"Mode: {d.get('mode', '—')}   Status: {d.get('status', '—')}\n\n"
            "[b]Pipeline[/]\n" + "\n".join(f"  → {s}" for s in stages))
        ev = md.get("evidence") or []
        self.query_one("#jd-evidence-body", Static).update(
            "\n".join(f"  • {e}" for e in ev) if ev
            else "No evidence chunks recorded for this job.")
        t = self.query_one("#jd-calls-table", DataTable)
        for c in d.get("model_calls") or []:
            t.add_row(str(c.get("seq", "")), c.get("ts", ""),
                      c.get("model", ""), str(c.get("tokens", 0)))
        if t.row_count == 0:
            t.add_row("—", "—", "no model calls yet", "—")
        intents = md.get("intents") or []
        self.query_one("#jd-intents-body", Static).update(
            "\n".join(f"  {i.get('target', '?')}: {i.get('status', '?')}"
                      for i in intents) if intents
            else "No outbox intents for this job.")


# ════════════════════════════ DRAFTS ════════════════════════════
class DraftsPage(_Page):
    def compose(self) -> ComposeResult:
        with Horizontal():
            yield ListView(id="drafts-list")
            with VerticalScroll(id="draft-detail"):
                yield Static(id="draft-head")
                yield WepBadge(id="draft-wep")
                yield Markdown("", id="draft-body")
        yield Static("[dim]↑/↓ move · enter open · a approve · r reject[/]",
                     classes="page-foot")

    def on_mount(self) -> None:
        self._drafts: list[dict] = []
        self._selected: str | None = None
        self._sig: list | None = None
        self.start_polling()

    def refresh_data(self) -> None:
        d = self.client_get("/api/drafts")
        new_drafts = (d or {}).get("drafts", [])
        offline = d is None
        # Skip a full rebuild when nothing changed — avoids ID collisions
        # from clear()/append() racing across poll ticks.
        signature = [offline, [(x.get("id"), x.get("status")) for x in new_drafts]]
        if getattr(self, "_sig", None) == signature:
            self._drafts = new_drafts
            return
        self._sig = signature
        self._drafts = new_drafts
        lv = self.query_one("#drafts-list", ListView)
        lv.clear()
        if offline:
            lv.append(ListItem(Label("Supervisor offline")))
            return
        if not self._drafts:
            lv.append(ListItem(Label("No drafts staged")))
            return
        for i, dr in enumerate(self._drafts):
            status = (dr.get("status") or "?")[:3]
            lv.append(ListItem(Label(f"[dim]{status}[/]  {dr.get('title', '')}"),
                               id=f"draft-row-{i}"))

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if not event.item.id or not event.item.id.startswith("draft-row-"):
            return
        idx = int(event.item.id.rsplit("-", 1)[1])
        if 0 <= idx < len(self._drafts):
            self._show_detail(self._drafts[idx]["id"])

    def _show_detail(self, did: str) -> None:
        self._selected = did
        detail = self.client_get(f"/api/drafts/{did}")
        if not detail:
            return
        self.query_one("#draft-head", Static).update(
            f"[b]{detail.get('title', '')}[/]\n"
            f"Sources: {detail.get('source_count', 0)}   "
            f"Status: {detail.get('status', '—')}")
        self.query_one("#draft-wep", WepBadge).set_wep(
            detail.get("wep_phrase"), detail.get("wep_band"))
        self.query_one("#draft-body", Markdown).update(
            _html_to_md(detail.get("body_html", "") or detail.get("body_md", "")))

    def action_approve(self) -> None:
        if not self._selected:
            return
        if self.client_post(f"/api/drafts/{self._selected}/approve") is not None:
            self.app.notify("Approved & published")
            self.refresh_data()

    def action_reject(self) -> None:
        if not self._selected:
            return
        self.app.push_screen(RejectModal(self._selected))


# ════════════════════════════ TOPICS ════════════════════════════
class TopicsPage(_Page):
    def compose(self) -> ComposeResult:
        with Horizontal():
            yield DataTable(id="topics-table", cursor_type="row")
            with VerticalScroll(id="topic-detail"):
                with TabbedContent(initial="tp-overview"):
                    with TabPane("Overview", id="tp-overview"):
                        yield Static(id="topic-overview")
                    with TabPane("Sources", id="tp-sources"):
                        yield Static(id="topic-sources")
                    with TabPane("Recent items", id="tp-items"):
                        yield Static(id="topic-items")
        yield Static("[dim]↑/↓ move · enter detail · n new[/]",
                     classes="page-foot")

    def on_mount(self) -> None:
        t = self.query_one("#topics-table", DataTable)
        t.add_columns("Name", "Mode", "Sources")
        self._topics: list[dict] = []
        self.start_polling()

    def refresh_data(self) -> None:
        d = self.client_get("/api/topics")
        t = self.query_one("#topics-table", DataTable)
        t.clear()
        self._topics = (d or {}).get("topics", [])
        if not self._topics:
            t.add_row("no topics yet", "—", "—")
            return
        for tp in self._topics:
            t.add_row(tp["name"], tp.get("mode", ""),
                      str(tp.get("source_count", 0)), key=tp["id"])

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        tid = event.row_key.value if event.row_key else None
        if not tid:
            return
        detail = self.client_get(f"/api/topics/{tid}")
        if not detail:
            return
        self.query_one("#topic-overview", Static).update(
            f"[b]{detail.get('name', '')}[/]\n\n"
            f"Mode: {detail.get('mode', '—')}\n"
            f"Cadence: {detail.get('cadence', '—')}\n"
            f"Status: {detail.get('status', '—')}")
        srcs = detail.get("sources", [])
        self.query_one("#topic-sources", Static).update(
            "\n".join(f"  [{s.get('grade', '?')}] {s.get('url', '')}"
                      for s in srcs) if srcs else "  No sources yet.")
        items = detail.get("recent_items", [])
        self.query_one("#topic-items", Static).update(
            "\n".join(f"  • {i}" for i in items) if items
            else "  No recent items.")

    def action_new_topic(self) -> None:
        self.app.push_screen(NewTopicModal())


# ════════════════════════════ POSITIONS ════════════════════════════
class PositionsPage(_Page):
    def compose(self) -> ComposeResult:
        with TabbedContent(initial="tab-overdue"):
            with TabPane("Overdue", id="tab-overdue"):
                yield VerticalScroll(Static(id="pos-overdue"))
            with TabPane("All", id="tab-all"):
                yield VerticalScroll(Static(id="pos-all"))
            with TabPane("Calibration", id="tab-cal"):
                yield VerticalScroll(Static(id="pos-cal"))
            with TabPane("Hypotheses", id="tab-hyp"):
                yield VerticalScroll(Static(id="pos-hyp"))

    def on_mount(self) -> None:
        self._overdue: list[dict] = []
        self.start_polling()

    def refresh_data(self) -> None:
        overdue = self.client_get("/api/positions", overdue="true") or {}
        self._overdue = overdue.get("positions", [])
        self.query_one("#pos-overdue", Static).update(
            _format_positions(self._overdue, "Nothing overdue. Good."))
        all_pos = self.client_get("/api/positions") or {}
        self.query_one("#pos-all", Static).update(
            _format_positions(all_pos.get("positions", []), "No positions yet."))
        self.query_one("#pos-cal", Static).update(
            _format_calibration(self.client_get("/api/calibration") or {}))
        hyp = self.client_get("/api/hypotheses") or {}
        self.query_one("#pos-hyp", Static).update(
            _format_hypotheses(hyp.get("hypotheses", [])))

    def _first_overdue_id(self) -> int | None:
        return self._overdue[0]["id"] if self._overdue else None

    def action_resolve_yes(self) -> None:
        self._resolve("confirmed")

    def action_resolve_no(self) -> None:
        self._resolve("refuted")

    def action_resolve_defer(self) -> None:
        self._resolve("defer")

    def _resolve(self, outcome: str) -> None:
        pid = self._first_overdue_id()
        if pid is None:
            return
        if self.client_post(f"/api/positions/{pid}/resolve",
                            json={"outcome": outcome}) is not None:
            self.app.notify(f"Position {pid}: {outcome}")
            self.refresh_data()


# ════════════════════════════ HEALTH ════════════════════════════
class HealthPage(_Page):
    def compose(self) -> ComposeResult:
        with TabbedContent(initial="h-overview"):
            with TabPane("Overview", id="h-overview"):
                yield VerticalScroll(Static(id="health-overview"))
            with TabPane("Budget", id="h-budget"):
                yield Static(id="health-budget")
            with TabPane("Storage", id="h-storage"):
                yield VerticalScroll(Static(id="health-storage"))
            with TabPane("Audit", id="h-audit"):
                yield DataTable(id="audit-table", cursor_type="row")

    def on_mount(self) -> None:
        self.query_one("#audit-table", DataTable).add_columns(
            "Seq", "Time", "Actor", "Event")
        self.start_polling()

    def refresh_data(self) -> None:
        h = self.client_get("/api/health")
        if not h:
            self.query_one("#health-overview", Static).update(
                "[yellow]Supervisor offline.[/] Run `lighthouse start`.")
            return
        self.query_one("#health-overview", Static).update(
            _format_health_overview(h))
        self.query_one("#health-budget", Static).update(
            _format_budget(h.get("budget") or {}))
        self.query_one("#health-storage", Static).update(
            _format_storage(h.get("storage") or {}))
        audit = self.client_get("/api/audit", limit=50) or {}
        t = self.query_one("#audit-table", DataTable)
        t.clear()
        for e in audit.get("events", []):
            t.add_row(str(e.get("seq", "")), e.get("ts", ""),
                      e.get("actor", ""), e.get("event_type", ""))
        if t.row_count == 0:
            t.add_row("—", "—", "no events", "—")


# ════════════════════════════ SETTINGS ════════════════════════════
class SettingsPage(_Page):
    def compose(self) -> ComposeResult:
        with TabbedContent(initial="s-general"):
            with TabPane("General", id="s-general"):
                yield Static(id="set-general")
            with TabPane("Models", id="s-models"):
                yield Static(id="set-models")
            with TabPane("Secrets", id="s-secrets"):
                yield Static(id="set-secrets")
            with TabPane("Skills", id="s-skills"):
                yield VerticalScroll(Static(id="set-skills"))
            with TabPane("Perspectives", id="s-persp"):
                yield VerticalScroll(Static(id="set-persp"))
            with TabPane("Advanced", id="s-adv"):
                yield VerticalScroll(Static(id="set-adv"))

    def on_mount(self) -> None:
        # Settings rarely change; poll slowly.
        self.refresh_data()
        self.set_interval(30.0, self.refresh_data)

    def refresh_data(self) -> None:
        cfg = (self.client_get("/api/settings") or {}).get("config", {})
        lh = cfg.get("lighthouse", {})
        hw = cfg.get("hardware", {})
        self.query_one("#set-general", Static).update(
            f"Version: {lh.get('version', '—')}\n"
            f"Data dir: {lh.get('data_dir', '~/.lighthouse')}\n"
            f"Detected tier: {hw.get('detected_tier', '—')}\n"
            f"Logseq: {'enabled' if cfg.get('logseq', {}).get('enabled') else 'disabled'}\n"
            f"Telegram: {'enabled' if cfg.get('telegram', {}).get('enabled') else 'disabled'}")
        h = self.client_get("/api/health") or {}
        ext = h.get("external", {})
        self.query_one("#set-models", Static).update(
            f"Ollama: {'reachable' if ext.get('ollama') else 'offline (run: ollama serve)'}\n"
            f"Qdrant: {'reachable' if ext.get('qdrant') else 'offline (optional)'}\n\n"
            "Pull a model:  lighthouse models pull qwen3:8b")
        sec = (self.client_get("/api/secrets") or {}).get("secrets", {})
        self.query_one("#set-secrets", Static).update(
            "\n".join(f"{k}: {v}" for k, v in sec.items())
            or "No secrets in the file store.")
        skills = (self.client_get("/api/skills") or {}).get("skills", [])
        self.query_one("#set-skills", Static).update(
            "\n".join(f"• {s.get('name', '?')} (used {s.get('use_count', 0)}×)"
                      for s in skills) or "No skills curated yet.")
        persp = (self.client_get("/api/perspectives") or {}).get("perspectives", [])
        self.query_one("#set-persp", Static).update(
            "\n".join(f"• {p.get('name', '?')} — {p.get('stance', '')}"
                      for p in persp) or "No perspectives defined.")
        self.query_one("#set-adv", Static).update(
            _json.dumps(cfg, indent=2) if cfg else "{}")


# ════════════════════════════ modals ════════════════════════════
class NewJobModal(ModalScreen):
    BINDINGS = [Binding("escape", "dismiss", "Cancel")]

    def compose(self) -> ComposeResult:
        yield Container(
            Label("New job"),
            Input(placeholder="Topic", id="job-topic"),
            Input(placeholder="Mode (Deep-Dive)", id="job-mode", value="Deep-Dive"),
            Horizontal(Button("Cancel", id="cancel"),
                       Button("Create", variant="primary", id="ok")),
            id="modal-box",
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "ok":
            topic = self.query_one("#job-topic", Input).value.strip()
            mode = self.query_one("#job-mode", Input).value.strip() or "Deep-Dive"
            if topic:
                self.app.client.post("/api/jobs", json={"mode": mode, "topic": topic})
                self.app.notify("Job queued")
        self.dismiss()


class NewTopicModal(ModalScreen):
    BINDINGS = [Binding("escape", "dismiss", "Cancel")]

    def compose(self) -> ComposeResult:
        yield Container(
            Label("New topic"),
            Input(placeholder="Name", id="topic-name"),
            Input(placeholder="Mode (Monitor)", id="topic-mode", value="Monitor"),
            Input(placeholder="Source URL (optional)", id="topic-src"),
            Horizontal(Button("Cancel", id="cancel"),
                       Button("Create", variant="primary", id="ok")),
            id="modal-box",
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "ok":
            name = self.query_one("#topic-name", Input).value.strip()
            mode = self.query_one("#topic-mode", Input).value.strip() or "Monitor"
            src = self.query_one("#topic-src", Input).value.strip()
            if name:
                self.app.client.post("/api/topics", json={
                    "name": name, "mode": mode,
                    "sources": [src] if src else []})
                self.app.notify("Topic created")
        self.dismiss()


class RejectModal(ModalScreen):
    BINDINGS = [Binding("escape", "dismiss", "Cancel")]

    def __init__(self, draft_id: str) -> None:
        super().__init__()
        self.draft_id = draft_id

    def compose(self) -> ComposeResult:
        yield Container(
            Label("Reject draft — reason?"),
            Input(placeholder="One-line reason", id="reason"),
            Horizontal(Button("Cancel", id="cancel"),
                       Button("Reject", variant="error", id="ok")),
            id="modal-box",
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "ok":
            reason = self.query_one("#reason", Input).value.strip()
            if reason:
                self.app.client.post(f"/api/drafts/{self.draft_id}/reject",
                                     json={"reason": reason})
                self.app.notify("Rejected")
        self.dismiss()


class HelpModal(ModalScreen):
    """A ``?`` help overlay listing the flat keymap."""

    BINDINGS = [Binding("escape", "dismiss", "Close"),
                Binding("question_mark", "dismiss", "Close")]

    HELP = (
        "1–7        switch pages (Home … Settings)\n"
        "↑ / ↓      move row focus in a list\n"
        "Enter      open detail\n"
        "n          new item (job / topic)\n"
        "a / r      approve / reject (Drafts)\n"
        "y / n / d  resolve overdue position\n"
        "Ctrl-P     command palette\n"
        "Esc        back / close\n"
        "?          this help\n"
        "q          quit"
    )

    def compose(self) -> ComposeResult:
        yield Container(
            Static("Keyboard shortcuts", classes="help-title"),
            Static(self.HELP),
            id="help-box",
        )


# ════════════════════════════ formatters ════════════════════════════
def _html_to_md(s: str) -> str:
    """Strip tags down to plain text for the Markdown widget. Cheap and safe."""
    if not s:
        return "_No body._"
    if "<" not in s:
        return s
    text = re.sub(r"<br\s*/?>", "\n", s)
    text = re.sub(r"</p>", "\n\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    return text.strip() or "_No body._"


def _format_positions(positions: list[dict], empty: str) -> str:
    if not positions:
        return empty
    out = []
    for p in positions:
        band = p.get("wep_band") or p.get("wep_phrase") or "unrated"
        conf = p.get("confidence")
        conf_s = f" ({int(conf * 100)}%)" if isinstance(conf, (int, float)) else ""
        if p.get("outcome") is None:
            verdict = "[dim]unresolved — [y] confirmed  [n] refuted  [d] defer[/]"
        else:
            verdict = ("[#4a8a6e]confirmed[/]" if p["outcome"]
                       else "[#c44536]refuted[/]")
            verdict += f" · Brier {float(p.get('brier') or 0):.3f}"
        out.append(f"• {p.get('claim', '')}\n    {band}{conf_s} · {verdict}")
    return "\n\n".join(out)


def _format_calibration(cal: dict) -> str:
    if not cal.get("n"):
        return "No resolved positions yet."
    lines = [
        f"Mean Brier: [b]{cal.get('mean_brier', 0):.3f}[/]  (lower is better)",
        f"Resolved:   {cal.get('n')}",
        f"Avg confidence: {cal.get('mean_probability', 0):.2f}",
        f"Hit rate:       {cal.get('mean_outcome_rate', 0):.2f}",
        f"Calibration error: {cal.get('calibration_error', 0):.3f}",
        "",
    ]
    hist = cal.get("brier_history") or cal.get("history")
    if hist:
        lines += [f"Brier trend  {sparkline(hist)}", ""]
    lines += _reliability_diagram(cal.get("bins") or cal.get("reliability") or [])
    by_domain = cal.get("by_domain") or []
    if by_domain:
        lines += ["", "By domain", "  DOMAIN        N    BRIER"]
        for d in by_domain:
            lines.append(
                f"  {str(d.get('domain', '?'))[:12]:12}  {d.get('n', 0):<4} "
                f"{d.get('brier', 0):.3f}")
    return "\n".join(lines)


def _reliability_diagram(bins: list[dict]) -> list[str]:
    """ASCII reliability diagram. Each bin has predicted + observed in 0..1."""
    if not bins:
        return ["Reliability diagram: not enough resolved positions."]
    rows = 6
    grid = [[" " for _ in range(len(bins))] for _ in range(rows)]
    for col, b in enumerate(bins):
        obs = max(0.0, min(1.0, float(b.get("observed", b.get("outcome_rate", 0)))))
        r = rows - 1 - int(obs * (rows - 1))
        grid[r][col] = "●"
    out = ["Reliability (● = observed; closer to diagonal = better)"]
    for i, line in enumerate(grid):
        axis = "1.0" if i == 0 else ("0.0" if i == rows - 1 else "   ")
        out.append(f"  {axis}│ " + "".join(line))
    out.append("      └" + "─" * (len(bins) + 1))
    return out


def _format_hypotheses(hyps: list[dict]) -> str:
    if not hyps:
        return "No hypotheses yet."
    cols: dict[str, list[str]] = {
        "open": [], "supported": [], "refuted": [], "retired": []}
    for h in hyps:
        cols.setdefault(h.get("status", "open"), []).append(
            h.get("statement", ""))
    out = []
    for status, items in cols.items():
        out.append(f"[b]{status.upper()} ({len(items)})[/]")
        out += [f"  • {s}" for s in items] or ["  —"]
        out.append("")
    return "\n".join(out)


def _format_health_overview(h: dict) -> str:
    def mark(ok: bool) -> str:
        return "[#4a8a6e]✓[/]" if ok else "[dim]–[/]"
    dbs = h.get("databases", {})
    db_ok = bool(dbs) and all(v == "ok" for v in dbs.values())
    hw = h.get("hardware", {})
    st = h.get("storage", {})
    ext = h.get("external", {})
    b = h.get("budget", {})
    usd = b.get("usd", {})
    lines = [
        f"Health · [b]{h.get('overall', '?')}[/]   (checked {h.get('checked_at', '')})",
        "",
        f"{mark(True)} Hardware    {hw.get('platform', '')} {hw.get('arch', '')} · "
        f"{hw.get('total_ram_gb', '?')} GB · tier {hw.get('tier', '?')}",
        f"{mark(True)} Storage     {st.get('disk_free_gb', '?')} GB free",
        f"{mark(db_ok)} Databases   "
        f"{sum(1 for v in dbs.values() if v == 'ok')} of {len(dbs)} healthy",
        f"{mark(h.get('audit_chain_ok') is not False)} Audit chain "
        f"{'intact' if h.get('audit_chain_ok') is not False else 'BROKEN'}",
        f"{mark(bool(ext.get('ollama')))} External    ollama "
        f"{'✓' if ext.get('ollama') else 'offline'} · qdrant "
        f"{'✓' if ext.get('qdrant') else 'offline (optional)'}",
        f"{mark(b.get('tier') == 'green')} Budget      "
        f"${usd.get('used', '?')} of ${usd.get('cap', '?')} (tier {b.get('tier', '?')})",
        "",
        "No action needed." if h.get("overall") == "green"
        else "Review the rows above.",
    ]
    return "\n".join(lines)


def _format_budget(b: dict) -> str:
    if not b:
        return "No budget data."

    def bar(used: float, cap: float) -> str:
        pct = min((used / cap) if cap else 0, 1.0)
        filled = int(pct * 12)
        return "█" * filled + "░" * (12 - filled)

    usd = b.get("usd", {})
    tok = b.get("tokens", {})
    tc = b.get("tool_calls", {})
    return (
        f"USD (monthly)   {bar(usd.get('used', 0), usd.get('cap', 1))}  "
        f"${usd.get('used', 0)} of ${usd.get('cap', 0)}\n"
        f"Tokens (daily)  {bar(tok.get('used', 0), tok.get('cap', 1))}  "
        f"{tok.get('used', 0) / 1e6:.1f}M of {tok.get('cap', 0) / 1e6:.0f}M\n"
        f"Tool calls      {bar(tc.get('used', 0), tc.get('cap', 1))}  "
        f"{tc.get('used', 0)} of {tc.get('cap', 0)}\n\n"
        f"Tier: [b]{b.get('tier', '?')}[/]\n\n"
        "[dim][b] reset budget · [K] kill all jobs (both ask to confirm)[/]"
    )


def _format_storage(s: dict) -> str:
    if not s:
        return "No storage data."
    lines = [
        f"Disk: {s.get('disk_free_gb', '?')} GB free of "
        f"{s.get('disk_total_gb', '?')} GB", ""]
    for name, b in (s.get("subdirs_bytes") or {}).items():
        lines.append(f"  {name + '/':14} {b / 1e6:.1f} MB")
    lines += ["", "Litestream replicas:"]
    reps = s.get("replicas") or []
    if not reps:
        lines.append("  none yet")
    for r in reps:
        lag = r.get("lag_seconds")
        lines.append(
            f"  {r.get('name', '?')}: "
            f"{'no snapshot' if lag is None else f'lag {lag}s'}")
    return "\n".join(lines)
