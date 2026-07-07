"""Offline tests for the structured (per-artifact-type) Logseq export.

Every test drives the real mode engines offline (``gateway=None``) to produce a
``body_json`` exactly as the dispatcher would, then exports it and asserts the
type-specific blocks / tables / page properties appear. A final test asserts
re-export is idempotent (same page path + block uuid, content updated).
"""

from __future__ import annotations

import dataclasses

from lighthouse_ai.targets.logseq import export_draft

# ── page properties (common to every type) ──────────────────────────────────


def test_page_properties_present(tmp_path):
    page = export_draft(
        tmp_path / "g",
        draft_id="d-props",
        title="Props",
        body_html="<p>x</p>",
        source_count=4,
        artifact_type="report",
        body_json={"sections": [{"title": "S", "body": "b", "citations": []}]},
    )
    md = page.path.read_text()
    assert "type:: report" in md
    assert "created:: " in md
    assert "source-count:: 4" in md
    assert "tags:: #lighthouse" in md
    assert f"id:: {page.uuid}" in md


def test_tags_include_lighthouse_and_extras(tmp_path):
    page = export_draft(
        tmp_path / "g",
        draft_id="d-tags",
        title="T",
        body_html="<p>x</p>",
        tags=["physics"],
    )
    md = page.path.read_text()
    assert "#lighthouse" in md and "#physics" in md


# ── matrix (decide) ──────────────────────────────────────────────────────────


def test_matrix_renders_table_winner_crux(tmp_path):
    from lighthouse_ai.modes.decide import run_decide

    report = run_decide(
        "Which database?",
        options=["Postgres", "SQLite"],
        criteria=[{"label": "speed", "weight": 2.0}, {"label": "simplicity", "weight": 1.0}],
    )
    page = export_draft(
        tmp_path / "g",
        draft_id="d-mx",
        title="DB choice",
        body_html="<p>x</p>",
        artifact_type="matrix",
        body_json=dataclasses.asdict(report),
    )
    md = page.path.read_text()
    assert "## Decision matrix" in md
    assert "| Option |" in md
    assert "speed (w=2.0)" in md
    assert "Postgres" in md and "SQLite" in md
    assert "**Winner:** " + report.winner in md
    assert "**Crux:**" in md


# ── timeline (reconstruct) ───────────────────────────────────────────────────


def test_timeline_renders_dated_blocks_with_properties(tmp_path):
    from lighthouse_ai.modes.reconstruct import run_reconstruct

    docs = [
        {
            "doc_id": "a",
            "title": "A",
            "text": "In March 2019 the treaty was signed. In 2020 it expired.",
        },
    ]
    report = run_reconstruct("Treaty timeline", documents=docs)
    assert report.events  # offline extraction found dated events
    page = export_draft(
        tmp_path / "g",
        draft_id="d-tl",
        title="Treaty",
        body_html="<p>x</p>",
        artifact_type="timeline",
        body_json=dataclasses.asdict(report),
    )
    md = page.path.read_text()
    assert "## Timeline" in md
    assert "date:: 2019-03-01" in md
    assert "sources:: a" in md
    assert "certainty:: " in md


# ── verdict (adjudicate) ─────────────────────────────────────────────────────


def test_verdict_renders_perspectives_crux_summary(tmp_path):
    from lighthouse_ai.modes.debate import run_debate

    result = run_debate(claim="X is true", draft="Some draft answer.")
    page = export_draft(
        tmp_path / "g",
        draft_id="d-vd",
        title="Debate",
        body_html="<p>x</p>",
        artifact_type="verdict",
        body_json=dataclasses.asdict(result),
    )
    md = page.path.read_text()
    assert "## Perspectives" in md
    assert "**steelman**" in md
    assert "**Crux of disagreement:**" in md
    assert "**Judge summary:**" in md


# ── table (survey) ───────────────────────────────────────────────────────────


def test_table_renders_evidence_table_and_prisma(tmp_path):
    from lighthouse_ai.modes.survey import run_survey

    docs = [
        {
            "doc_id": "p1",
            "title": "Paper one",
            "text": "The method uses transformers. Accuracy was 0.9.",
        },
        {"doc_id": "p2", "title": "Paper two", "text": "The method uses CNNs. Accuracy was 0.8."},
    ]
    report = run_survey(
        "ML methods",
        documents=docs,
        criteria=[],
        attributes=[
            {"label": "method", "keywords": ["method"]},
            {"label": "accuracy", "keywords": ["accuracy"]},
        ],
    )
    page = export_draft(
        tmp_path / "g",
        draft_id="d-tb",
        title="Survey",
        body_html="<p>x</p>",
        artifact_type="table",
        body_json=dataclasses.asdict(report),
    )
    md = page.path.read_text()
    assert "## Evidence table" in md
    assert "| Document |" in md
    assert "method" in md and "accuracy" in md
    assert "Paper one" in md and "Paper two" in md
    assert "## PRISMA flow" in md
    assert f"Identified: {report.prisma.identified}" in md
    assert f"Included: {report.prisma.included}" in md


# ── transcript (ask) ─────────────────────────────────────────────────────────


def test_transcript_renders_turns_with_citations(tmp_path):
    # Build the transcript body_json shape the dispatcher produces for Ask.
    body_json = {
        "topic": "What is X?",
        "turns": [
            {"role": "user", "text": "What is X?", "citations": []},
            {"role": "assistant", "text": "X is a thing.", "citations": ["c1", "c2"]},
        ],
    }
    page = export_draft(
        tmp_path / "g",
        draft_id="d-tx",
        title="Ask",
        body_html="<p>x</p>",
        artifact_type="transcript",
        body_json=body_json,
    )
    md = page.path.read_text()
    assert "## Transcript" in md
    assert "**User:** What is X?" in md
    assert "**Assistant:** X is a thing." in md
    assert "citations:: c1, c2" in md


# ── report (investigate) ─────────────────────────────────────────────────────


def test_report_renders_sections_with_citations(tmp_path):
    body_json = {
        "question": "How does Y work?",
        "sections": [
            {
                "title": "Background",
                "sub_question": "",
                "body": "Y is old.",
                "citations": ["s1"],
                "is_load_bearing": True,
            },
            {
                "title": "Mechanism",
                "sub_question": "",
                "body": "Y uses Z.",
                "citations": ["s2", "s3"],
                "is_load_bearing": True,
            },
        ],
        "open_questions": ["Is Y scalable?"],
        "ruled_out": [],
    }
    page = export_draft(
        tmp_path / "g",
        draft_id="d-rp",
        title="Report",
        body_html="<p>x</p>",
        artifact_type="report",
        body_json=body_json,
    )
    md = page.path.read_text()
    assert "## Background" in md and "## Mechanism" in md
    assert "Y uses Z." in md
    assert "sources:: s2, s3" in md
    assert "## Open questions" in md
    assert "Is Y scalable?" in md


# ── digest (watch) ───────────────────────────────────────────────────────────


def test_digest_renders_items_with_salience(tmp_path):
    from lighthouse_ai.modes.monitor import MonitorItem, run_monitor

    items = [
        MonitorItem(
            source="s", url="http://a", title="Breaking major news", body="critical urgent " * 50
        ),
        MonitorItem(source="s", url="http://b", title="Minor note", body="short"),
    ]
    report = run_monitor("News", items)
    page = export_draft(
        tmp_path / "g",
        draft_id="d-dg",
        title="Watch",
        body_html="<p>x</p>",
        artifact_type="digest",
        body_json=dataclasses.asdict(report),
    )
    md = page.path.read_text()
    assert "## Digest" in md
    assert "salience" in md
    assert "Minor note" in md


# ── fallback + idempotency ───────────────────────────────────────────────────


def test_falls_back_to_html_when_no_body_json(tmp_path):
    page = export_draft(
        tmp_path / "g",
        draft_id="d-fb",
        title="HTML only",
        body_html="<h2>Heading</h2><p>Para.</p>",
    )
    md = page.path.read_text()
    assert "## Heading" in md
    assert "Para." in md
    assert "type:: lighthouse-draft" in md  # no artifact_type → generic type


def test_unknown_artifact_type_falls_back(tmp_path):
    page = export_draft(
        tmp_path / "g",
        draft_id="d-uk",
        title="Weird",
        body_html="<p>Hello.</p>",
        artifact_type="mystery",
        body_json={"foo": "bar"},
    )
    md = page.path.read_text()
    assert "Hello." in md  # html flatten still happened


def test_structured_reexport_idempotent(tmp_path):
    from lighthouse_ai.modes.decide import run_decide

    r1 = run_decide("Q?", options=["A", "B"], criteria=[{"label": "c", "weight": 1.0}])
    a = export_draft(
        tmp_path / "g",
        draft_id="d-id",
        title="Decision",
        body_html="<p>x</p>",
        artifact_type="matrix",
        body_json=dataclasses.asdict(r1),
    )
    r2 = run_decide("Q?", options=["A", "B", "C"], criteria=[{"label": "c", "weight": 1.0}])
    b = export_draft(
        tmp_path / "g",
        draft_id="d-id",
        title="Decision",
        body_html="<p>y</p>",
        artifact_type="matrix",
        body_json=dataclasses.asdict(r2),
    )
    assert a.uuid == b.uuid  # same draft id → same block uuid
    assert a.path == b.path  # same page path → overwrite, no duplicate
    md = b.path.read_text()
    assert "| C |" in md or "| C " in md  # content updated to the 3-option run
    # Exactly one page file exists for this draft (no duplication).
    assert len(list((tmp_path / "g" / "pages").glob("*.md"))) == 1
