"""Tests for Mode A (Monitor) + HTML rendering."""

from __future__ import annotations

from lighthouse_ai.modes.monitor import (
    ClassifiedItem,
    MonitorItem,
    MonitorState,
    default_salience,
    run_monitor,
)
from lighthouse_ai.output.html import (
    Citation,
    Claim,
    render_claims,
    render_html_document,
    render_monitor_html,
)
from lighthouse_ai.rag.embedder import HashEmbedder


def _items() -> list[MonitorItem]:
    return [
        MonitorItem(source="src1", url="https://a/1",
                    title="Breaking news on AI policy",
                    body="A major breaking development. " * 30,
                    published_at="2026-05-27T10:00:00Z"),
        MonitorItem(source="src1", url="https://a/2",
                    title="Quiet update on tax code",
                    body="Minor update; nothing urgent.",
                    published_at="2026-05-27T10:01:00Z"),
        MonitorItem(source="src2", url="https://a/3",
                    title="Rumor about quantum chip",
                    body="Alleged speculation about quantum.",
                    published_at="2026-05-27T10:02:00Z"),
    ]


def test_monitor_splits_alerts_and_digest():
    report = run_monitor("AI policy", _items())
    assert report.total_seen == 3
    assert report.alerts
    assert all(a.is_alert for a in report.alerts)
    assert all(not d.is_alert for d in report.digest)
    assert len(report.alerts) + len(report.digest) == 3


def test_monitor_dedups_repeated_urls_across_runs():
    items = _items()
    state = MonitorState()
    run_monitor("t", items, state=state)
    r2 = run_monitor("t", items, state=state)
    assert r2.suppressed_duplicates == 3
    assert not r2.alerts and not r2.digest


def test_default_salience_boosts_for_breaking_words():
    item = MonitorItem(source="s", url="u", title="x",
                       body="breaking " + "word " * 10)
    s, cat = default_salience(item)
    assert cat in {"alert", "informational"}


def test_default_salience_penalizes_speculation():
    item = MonitorItem(source="s", url="u", title="x",
                       body="rumor about speculation alleged")
    s, cat = default_salience(item)
    assert cat == "noise"


def test_monitor_semantic_dedup_via_embedder():
    e = HashEmbedder(dim=128)
    items = [
        MonitorItem(source="s1", url="https://x/1",
                    title="Quantum breakthrough at MIT lab",
                    body="Long body. " * 30),
        # Different URL, almost-identical title — should be suppressed by semantic dedup.
        MonitorItem(source="s2", url="https://x/2",
                    title="Quantum breakthrough at MIT lab",
                    body="Long body. " * 30),
    ]
    report = run_monitor("quantum", items,
                         embed_titles=lambda ts: e.embed(ts))
    assert report.suppressed_duplicates >= 1


# --- HTML output -------------------------------------------------

def test_render_monitor_html_contains_topic_and_items():
    report = run_monitor("Test Topic", _items())
    out = render_monitor_html(report)
    assert "Test Topic" in out
    assert "Alerts" in out
    assert "Digest" in out
    assert out.startswith("<!doctype html>")


def test_render_html_document_escapes_input():
    html = render_html_document(title="<script>", subtitle="ok", body_html="<p>x</p>")
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_render_claims_with_wep_and_citations():
    c1 = Claim("The sky is blue.", wep="almost_certain",
               citations=[Citation("NOAA", "https://noaa.gov", grade="A",
                                   published="2024-01-01")])
    html = render_claims([c1])
    assert "almost certain" in html
    assert "NOAA" in html
    assert "wep-almost-certain" in html


def test_render_monitor_html_handles_empty_report():
    from lighthouse_ai.modes.monitor import MonitorReport
    report = MonitorReport(topic="empty", generated_at="t", alerts=[],
                           digest=[], suppressed_duplicates=0, total_seen=0)
    html = render_monitor_html(report)
    assert "(none)" in html
