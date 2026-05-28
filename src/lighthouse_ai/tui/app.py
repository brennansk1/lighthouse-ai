"""Lighthouse TUI root app — sidebar + content switcher + status bar.

Seven pages, a flat keymap (digits 1-7 switch pages), the built-in command
palette (Ctrl-P), and a ``?`` help overlay. Polls the control plane every
few seconds and degrades to a clear offline hint when the supervisor is
down — never crashes.

Entrypoint contract: ``lighthouse tui`` constructs ``LighthouseTUI(client=...)``.
Pass a :class:`~lighthouse_ai.tui.client.LighthouseClient` (default) or a
``FakeClient`` (tests). Both satisfy the ``Client`` protocol.
"""

from __future__ import annotations

from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.theme import Theme
from textual.widgets import ContentSwitcher, Footer

from .client import Client, LighthouseClient
from .screens import (
    DraftsPage,
    HealthPage,
    HelpModal,
    HomePage,
    IntelligencePage,
    JobsPage,
    PositionsPage,
    SettingsPage,
    TopicsPage,
)
from .widgets import Sidebar, StatusBar

# (page_id, sidebar label, page class). Order drives digits 1-8.
PAGES = [
    ("home", "Home", HomePage),
    ("jobs", "Jobs", JobsPage),
    ("drafts", "Drafts", DraftsPage),
    ("topics", "Topics", TopicsPage),
    ("positions", "Positions", PositionsPage),
    ("health", "Health", HealthPage),
    ("settings", "Settings", SettingsPage),
    ("intelligence", "Intelligence", IntelligencePage),
]

# Coastal palette (mirrors web/static/tokens.css), expressed as Textual
# themes so the whole TUI can flip light/dark from one place.
COASTAL_LIGHT = Theme(
    name="coastal-light",
    primary="#0e3a5f",      # navy
    secondary="#2d7a9e",    # mid-sea teal
    accent="#c9a050",       # beam / sand-gold
    foreground="#0b2335",   # deep navy ink
    background="#f4f1ea",   # warm cream paper
    surface="#ede7d8",      # sand tint
    panel="#fbfaf7",        # near-white card
    success="#4a8a6e",      # algae
    warning="#d97742",      # very-likely orange
    error="#c44536",        # beacon red
    dark=False,
)

COASTAL_DARK = Theme(
    name="coastal-dark",
    primary="#7ab5c9",      # sky
    secondary="#2d7a9e",    # mid-sea teal
    accent="#f0c75e",       # warm beam
    foreground="#e7eef3",
    background="#081a28",    # deep ocean night
    surface="#0e2a3d",
    panel="#11334a",
    success="#4a8a6e",
    warning="#d97742",
    error="#c44536",
    dark=True,
)


class LighthouseTUI(App):
    CSS_PATH = Path(__file__).parent / "styles.tcss"

    BINDINGS = [
        Binding("1", "goto('home')", "Home", show=False),
        Binding("2", "goto('jobs')", "Jobs", show=False),
        Binding("3", "goto('drafts')", "Drafts", show=False),
        Binding("4", "goto('topics')", "Topics", show=False),
        Binding("5", "goto('positions')", "Positions", show=False),
        Binding("6", "goto('health')", "Health", show=False),
        Binding("7", "goto('settings')", "Settings", show=False),
        Binding("8", "goto('intelligence')", "Intelligence", show=False),
        Binding("question_mark", "help", "Help"),
        Binding("ctrl+t", "toggle_theme", "Theme", show=False),
        Binding("q", "quit", "Quit"),
        # Action keys route to the active page so they work regardless of
        # which inner widget currently holds focus (nav list, table, …).
        Binding("n", "page_do('new')", "New", show=False),
        Binding("enter", "page_do('detail')", "Open", show=False),
        Binding("a", "page_do('approve')", "Approve", show=False),
        Binding("r", "page_do('reject')", "Reject", show=False),
        Binding("p", "page_do('pause')", "Pause", show=False),
        Binding("y", "page_do('yes')", "Confirm", show=False),
        Binding("d", "page_do('defer')", "Defer", show=False),
    ]

    def __init__(self, client: Client | None = None) -> None:
        super().__init__()
        self.client: Client = client or LighthouseClient()

    def compose(self) -> ComposeResult:
        yield Sidebar([(pid, label) for pid, label, _ in PAGES], id="sidebar")
        with ContentSwitcher(initial="home", id="main"):
            for pid, _label, cls in PAGES:
                yield cls(id=pid)
        yield StatusBar("tier — · $— of $— · — · ? help", id="status")
        yield Footer()

    def on_mount(self) -> None:
        self.register_theme(COASTAL_LIGHT)
        self.register_theme(COASTAL_DARK)
        self.theme = "coastal-dark"
        self.query_one(Sidebar).select("home")
        self.set_interval(5.0, self.refresh_status)
        self.refresh_status()

    # ─────────────────────────── navigation ───────────────────────────
    def action_goto(self, page: str) -> None:
        self.query_one("#main", ContentSwitcher).current = page
        self.query_one(Sidebar).select(page)

    def on_sidebar_nav_selected(self, event: Sidebar.NavSelected) -> None:
        self.action_goto(event.page_id)

    def _active_page(self):
        cur = self.query_one("#main", ContentSwitcher).current
        return self.query_one(f"#{cur}")

    def action_page_do(self, what: str) -> None:
        """Route a flat-keymap action to the active page if it handles it."""
        page = self._active_page()
        methods = {
            "new": ("action_new_job", "action_new_topic"),
            "detail": ("action_open_detail",),
            "approve": ("action_approve", "action_acknowledge"),
            "reject": ("action_reject", "action_resolve"),
            "pause": ("action_pause",),
            "yes": ("action_resolve_yes",),
            "defer": ("action_resolve_defer",),
        }.get(what, ())
        for name in methods:
            fn = getattr(page, name, None)
            if fn is not None:
                fn()
                return
        # `n` on Positions means "refuted"; route there if nothing else took it.
        if what == "new" and hasattr(page, "action_resolve_no"):
            page.action_resolve_no()

    def action_help(self) -> None:
        self.push_screen(HelpModal())

    def action_toggle_theme(self) -> None:
        self.theme = ("coastal-light" if self.theme == "coastal-dark"
                      else "coastal-dark")

    # ─────────────────────────── status bar ───────────────────────────
    def refresh_status(self) -> None:
        bar = self.query_one("#status", StatusBar)
        sidebar = self.query_one(Sidebar)
        try:
            health = self.client.get("/api/health")
            jobs = self.client.get("/api/jobs").get("jobs", [])
        except Exception:
            bar.set_offline()
            return
        bar.set_health(health, jobs)
        # Sidebar work-counters: only where the user must act.
        running = sum(1 for j in jobs if j.get("status") == "running")
        review = sum(1 for j in jobs if j.get("status") == "review")
        sidebar.set_counter("jobs", running)
        sidebar.set_counter("drafts", review)
        try:
            overdue = self.client.get("/api/positions", overdue="true")
            sidebar.set_counter("positions", len(overdue.get("positions", [])))
        except Exception:
            pass
        try:
            escs = self.client.get("/api/escalations", status="open")
            sidebar.set_counter(
                "intelligence", len(escs.get("escalations", [])))
        except Exception:
            pass


def main() -> None:  # pragma: no cover - entrypoint
    LighthouseTUI().run()


if __name__ == "__main__":  # pragma: no cover
    main()
