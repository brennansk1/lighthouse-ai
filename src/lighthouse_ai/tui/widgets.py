"""Reusable Lighthouse TUI widgets.

These are deliberately small, data-driven, and side-effect free so they
can be unit-tested in isolation with Textual's headless pilot. Each reads
its state from plain Python and renders via Rich markup, so tests can read
text with ``str(widget.render())``.
"""

from __future__ import annotations

from collections.abc import Iterable

from textual.app import ComposeResult
from textual.containers import Container
from textual.message import Message
from textual.widgets import Label, ListItem, ListView, Static

# Unicode block ramp used for sparklines and bars (low → high).
_SPARK_BARS = "▁▂▃▄▅▆▇█"

# Coastal palette echo of web/static/tokens.css WEP bands. Maps a band /
# phrase to a Rich color so badges read the same as the webapp.
_WEP_COLORS: dict[str, str] = {
    "almost no chance": "#1b3a52",
    "very unlikely": "#2f6b88",
    "unlikely": "#5a9aa8",
    "roughly even": "#a6a297",
    "even": "#a6a297",
    "likely": "#c9a050",
    "very likely": "#d97742",
    "almost certain": "#a8412c",
    "certain": "#a8412c",
}


def sparkline(values: Iterable[float], width: int = 0) -> str:
    """Render an iterable of numbers as a unicode sparkline string.

    Empty input → empty string. A flat series renders as the lowest bar.
    ``width`` (optional) truncates to the most recent ``width`` points.
    """
    vals = [float(v) for v in values]
    if not vals:
        return ""
    if width and len(vals) > width:
        vals = vals[-width:]
    lo, hi = min(vals), max(vals)
    span = hi - lo
    if span == 0:
        return _SPARK_BARS[0] * len(vals)
    out = []
    last = len(_SPARK_BARS) - 1
    for v in vals:
        idx = int((v - lo) / span * last)
        out.append(_SPARK_BARS[max(0, min(last, idx))])
    return "".join(out)


class Sparkline(Static):
    """A single-line unicode sparkline. Set data via :meth:`set_values`."""

    def __init__(self, values: Iterable[float] | None = None, **kw) -> None:
        super().__init__("", **kw)
        self.add_class("spark")
        self._values: list[float] = [float(v) for v in (values or [])]
        self._refresh()

    def set_values(self, values: Iterable[float]) -> None:
        self._values = [float(v) for v in values]
        self._refresh()

    def _refresh(self) -> None:
        self.update(sparkline(self._values) or "—")


class WepBadge(Static):
    """A colored confidence (Words-of-Estimative-Probability) badge."""

    def __init__(self, phrase: str | None = None, band: str | None = None,
                 **kw) -> None:
        super().__init__("", **kw)
        self.set_wep(phrase, band)

    def set_wep(self, phrase: str | None, band: str | None = None) -> None:
        self._phrase = (phrase or "unrated").strip()
        self._band = band
        color = _WEP_COLORS.get(self._phrase.lower(), "#6c7c8b")
        label = self._phrase
        if band:
            label = f"{label} ({band})"
        self.update(f"[white on {color}] {label} [/]")


class StatusBar(Static):
    """Bottom status line: tier · $used/$cap · jobs · ``? help``.

    Plain-English only, mirroring the webapp status bar. Call
    :meth:`set_health` with the ``/api/health`` payload + jobs list, or
    :meth:`set_offline` when the supervisor can't be reached.
    """

    def set_offline(self) -> None:
        self.add_class("-offline")
        self.update("supervisor offline — run `lighthouse start`   ·   ? help")

    def set_health(self, health: dict, jobs: list[dict]) -> None:
        """Update the status bar from a health or dashboard payload.

        Accepts both the ``/api/health`` shape (no ``budget`` key) and the
        ``/api/dashboard`` shape (has ``budget.cloud``).  When budget data is
        absent the budget chip is hidden rather than showing ``$— of $—``.
        """
        self.remove_class("-offline")
        h = health or {}
        hw = h.get("hardware") or {}
        running = sum(1 for j in jobs if j.get("status") == "running")
        review = sum(1 for j in jobs if j.get("status") == "review")
        job_bits = f"{running} running"
        if review:
            job_bits += f", {review} need{'s' if review == 1 else ''} review"
        tier = hw.get("tier") or "—"

        # Budget is present only in the /api/dashboard shape.  /api/health
        # does not emit it, so guard every level with .get() and tolerate None.
        budget_chip = ""
        budget = h.get("budget")
        if isinstance(budget, dict):
            cloud = budget.get("cloud")
            if isinstance(cloud, dict):
                used = cloud.get("used")
                cap = cloud.get("cap")
                if used is not None and cap is not None:
                    budget_chip = f"  ·  ${used} of ${cap}"

        self.update(
            f"tier {tier}{budget_chip}  ·  {job_bits}  ·  ? help"
        )


class Sidebar(Container):
    """Left navigation list with per-item work counters.

    ``pages`` is a list of ``(page_id, label)`` tuples. Counters are set
    later via :meth:`set_counter` (only Jobs/Drafts/Positions carry one —
    reference pages do not). Emits :class:`Sidebar.NavSelected` on click /
    enter so the app can route to the page without touching internals.
    """

    class NavSelected(Message):
        def __init__(self, page_id: str) -> None:
            self.page_id = page_id
            super().__init__()

    def __init__(self, pages: list[tuple[str, str]], **kw) -> None:
        super().__init__(**kw)
        self._pages = pages
        self._counters: dict[str, int] = {}

    def compose(self) -> ComposeResult:
        yield Static("Lighthouse", classes="brand")
        yield ListView(id="nav")

    def on_mount(self) -> None:
        nav = self.query_one("#nav", ListView)
        for pid, label in self._pages:
            nav.append(ListItem(Label(label), id=f"nav-{pid}"))

    def set_counter(self, page_id: str, count: int) -> None:
        """Update the trailing work-counter for a nav item (0 hides it)."""
        self._counters[page_id] = count
        try:
            item = self.query_one(f"#nav-{page_id}", ListItem)
        except Exception:
            return
        label = next((lbl for pid, lbl in self._pages if pid == page_id), page_id)
        text = label
        if count:
            text = f"{label}  [b]{count}[/]"
        item.query_one(Label).update(text)

    def select(self, page_id: str) -> None:
        """Programmatically highlight a nav item (keeps sidebar in sync)."""
        nav = self.query_one("#nav", ListView)
        for i, (pid, _label) in enumerate(self._pages):
            if pid == page_id:
                nav.index = i
                return

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.item.id and event.item.id.startswith("nav-"):
            event.stop()
            self.post_message(self.NavSelected(event.item.id[4:]))
