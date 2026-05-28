"""HTML rendering — Tufte-CSS aesthetic, sidenote citations, WEP color bands.

Produces a single self-contained ``.html`` file with an inline minimal
stylesheet inspired by Tufte CSS (margin notes, generous whitespace).
Production wires the full Tufte CSS file from ``/opt/lighthouse/templates/``
and runs Pandoc/Quarto for richer exports.
"""

from __future__ import annotations

import html as _html
from dataclasses import dataclass, field
from typing import Iterable


_TUFTE_LITE_CSS = """
<style>
  :root { --bg:#fffff8; --fg:#111; --accent:#a00; --muted:#666; }
  body { background: var(--bg); color: var(--fg);
         font-family: et-book, Palatino, Georgia, serif;
         max-width: 1400px; margin: 2rem auto; padding: 0 2rem; line-height: 1.6; }
  h1, h2, h3 { font-weight: 400; line-height: 1.2; }
  h1 { font-size: 2.2rem; margin-bottom: 0.2rem; }
  h2 { font-size: 1.6rem; margin-top: 2.4rem; }
  .meta { color: var(--muted); font-size: 0.9rem; }
  .wep { display: inline-block; padding: 0 0.4rem; border-radius: 0.2rem;
         font-size: 0.8rem; font-weight: 600; margin-left: 0.5rem;
         vertical-align: middle; }
  .wep-almost-certain { background: #064; color: #fff; }
  .wep-likely         { background: #07a; color: #fff; }
  .wep-even           { background: #888; color: #fff; }
  .wep-unlikely       { background: #b50; color: #fff; }
  .wep-remote         { background: #911; color: #fff; }
  .alert  { border-left: 4px solid var(--accent); padding: 0.5rem 1rem;
            background: #fff; margin: 1rem 0; }
  .digest-item { padding: 0.5rem 0; border-bottom: 1px dotted var(--muted); }
  .sidenote { color: var(--muted); font-size: 0.85rem; float: right;
              clear: right; width: 30%; margin-right: -35%; }
  sup.cite { color: var(--accent); cursor: help; }
  table { border-collapse: collapse; margin: 1rem 0; }
  th, td { padding: 0.3rem 0.7rem; border-bottom: 1px solid #ddd; text-align: left; }
  pre { background: #f4f4ec; padding: 0.6rem; overflow-x: auto; }
</style>
"""


@dataclass(frozen=True)
class Citation:
    label: str
    url: str | None = None
    grade: str | None = None
    published: str | None = None


WEP_BANDS = {
    "almost_certain": "almost certain",
    "likely": "likely",
    "even": "even chance",
    "unlikely": "unlikely",
    "remote": "remote",
}


@dataclass(frozen=True)
class Claim:
    text: str
    wep: str | None = None
    citations: list[Citation] = field(default_factory=list)


def _escape(s: str | None) -> str:
    return _html.escape(s or "")


def _wep_chip(wep: str | None) -> str:
    if not wep:
        return ""
    label = WEP_BANDS.get(wep, wep)
    return f'<span class="wep wep-{_escape(wep.replace("_", "-"))}">{_escape(label)}</span>'


def _citations_block(cites: Iterable[Citation]) -> str:
    cites_list = list(cites)
    if not cites_list:
        return ""
    parts = []
    for i, c in enumerate(cites_list, 1):
        tooltip = " — ".join(filter(None, [c.label, c.grade, c.published]))
        a = f'<a href="{_escape(c.url)}">{_escape(c.label)}</a>' if c.url else _escape(c.label)
        parts.append(f'<sup class="cite" title="{_escape(tooltip)}">[{i}]</sup>{a}')
    return " ".join(parts)


def render_html_document(*, title: str, subtitle: str = "", body_html: str = "") -> str:
    """Wrap arbitrary body HTML in the Lighthouse Tufte-lite template."""
    return (
        f"<!doctype html><html><head><meta charset='utf-8'>"
        f"<title>{_escape(title)}</title>{_TUFTE_LITE_CSS}</head><body>"
        f"<h1>{_escape(title)}</h1>"
        f"<p class='meta'>{_escape(subtitle)}</p>"
        f"{body_html}"
        f"</body></html>"
    )


def render_claims(claims: Iterable[Claim]) -> str:
    parts = ["<section class='claims'>"]
    for c in claims:
        cite_html = _citations_block(c.citations)
        parts.append(f"<p>{_escape(c.text)}{_wep_chip(c.wep)} {cite_html}</p>")
    parts.append("</section>")
    return "".join(parts)


def render_monitor_html(report) -> str:  # type: ignore[no-untyped-def]
    """Render a :class:`modes.monitor.MonitorReport` as a standalone HTML file."""
    body = [f"<h2>{_escape(report.topic)}</h2>",
            f"<p class='meta'>Generated {_escape(report.generated_at)} — "
            f"{report.total_seen} items, {report.suppressed_duplicates} duplicates suppressed.</p>"]

    body.append("<h2>Alerts</h2>")
    if not report.alerts:
        body.append("<p>(none)</p>")
    for a in report.alerts:
        body.append(
            f"<div class='alert'>"
            f"<strong>{_escape(a.item.title)}</strong>"
            f"<span class='wep wep-likely'>salience {a.salience:.2f}</span>"
            f"<br><span class='meta'>{_escape(a.item.source)} — "
            f"{_escape(a.item.published_at or '')}</span>"
            f"<p>{_escape(a.item.body[:400])}</p>"
            f"<a href='{_escape(a.item.url)}'>{_escape(a.item.url)}</a>"
            f"</div>"
        )

    body.append("<h2>Digest</h2>")
    if not report.digest:
        body.append("<p>(none)</p>")
    for d in report.digest:
        body.append(
            f"<div class='digest-item'>"
            f"<a href='{_escape(d.item.url)}'>{_escape(d.item.title)}</a>"
            f"<span class='meta'> — {_escape(d.item.source)} — "
            f"salience {d.salience:.2f}</span>"
            f"</div>"
        )

    return render_html_document(
        title=f"Lighthouse Monitor — {report.topic}",
        subtitle=f"as of {report.generated_at}",
        body_html="".join(body),
    )
