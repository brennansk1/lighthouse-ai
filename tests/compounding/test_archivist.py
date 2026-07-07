"""Tests for the archivist clean→compose→append bridge (OpenHuman §8)."""

from __future__ import annotations

from dataclasses import dataclass, field

from lighthouse_ai.compounding.archivist import (
    archive_conversation,
    archive_report,
    clean_turns,
    compose_md,
    report_to_markdown,
)


@dataclass(frozen=True)
class _Turn:
    role: str
    text: str


@dataclass(frozen=True)
class _Section:
    title: str
    body: str


@dataclass(frozen=True)
class _Report:
    question: str
    sections: list = field(default_factory=list)
    open_questions: list = field(default_factory=list)


# --- clean_turns (pure transform) ------------------------------------------


def test_clean_drops_tool_and_system_turns() -> None:
    turns = [
        _Turn("system", "You are a helpful assistant."),
        _Turn("user", "What is HNSW?"),
        _Turn("tool", '{"tool": "search", "args": {}}'),
        _Turn("assistant", "HNSW is a graph index."),
    ]
    cleaned = clean_turns(turns)
    assert [t.role for t in cleaned] == ["user", "assistant"]


def test_clean_strips_tool_call_json_fence() -> None:
    turns = [
        _Turn("assistant", 'Let me search.\n```json\n{"tool": "search", "q": "x"}\n```\nDone.'),
    ]
    cleaned = clean_turns(turns)
    assert "tool" not in cleaned[0].text.lower() or "search" not in cleaned[0].text
    assert "Let me search." in cleaned[0].text
    assert "Done." in cleaned[0].text


def test_clean_drops_turn_that_becomes_empty() -> None:
    turns = [_Turn("assistant", '```json\n{"tool": "x"}\n```')]
    assert clean_turns(turns) == []


def test_clean_is_pure_does_not_mutate_input() -> None:
    turns = [_Turn("user", "hi")]
    clean_turns(turns)
    assert turns == [_Turn("user", "hi")]


# --- compose_md (deterministic round-trip) ---------------------------------


def test_compose_md_format() -> None:
    turns = [_Turn("user", "Q?"), _Turn("assistant", "A.")]
    md = compose_md(turns)
    assert md == "## user\nQ?\n\n## assistant\nA."


def test_compose_md_is_deterministic() -> None:
    turns = [_Turn("user", "Q?"), _Turn("assistant", "A.")]
    assert compose_md(turns) == compose_md(turns)


# --- report_to_markdown ----------------------------------------------------


def test_report_to_markdown_includes_sections_and_open_questions() -> None:
    report = _Report(
        question="How does X work?",
        sections=[_Section("Mechanism", "It works via Y."), _Section("Caveats", "Except when Z.")],
        open_questions=["What about W?"],
    )
    md = report_to_markdown(report)
    assert md.startswith("# How does X work?")
    assert "## Mechanism" in md and "It works via Y." in md
    assert "## Open questions" in md and "- What about W?" in md


# --- archive_report (idempotent corpus write) ------------------------------


def test_archive_report_writes_corpus_file(tmp_path) -> None:
    report = _Report(question="Q", sections=[_Section("S", "body")])
    corpus = tmp_path / "corpus"
    outcome = archive_report(report, corpus_dir=corpus)
    assert outcome.corpus_path is not None
    assert outcome.corpus_path.exists()
    assert outcome.corpus_path.read_text() == outcome.markdown
    assert outcome.content_id in outcome.corpus_path.name


def test_archive_report_is_idempotent(tmp_path) -> None:
    report = _Report(question="Q", sections=[_Section("S", "body")])
    corpus = tmp_path / "corpus"
    a = archive_report(report, corpus_dir=corpus)
    b = archive_report(report, corpus_dir=corpus)
    # Same content → same path and id; archiving twice is a no-op overwrite.
    assert a.corpus_path == b.corpus_path
    assert a.content_id == b.content_id
    assert len(list((corpus).glob("*.md"))) == 1


def test_archive_report_writes_logseq_when_requested(tmp_path) -> None:
    report = _Report(
        question="Solar power basics", sections=[_Section("PV", "Photovoltaics convert light.")]
    )
    outcome = archive_report(report, corpus_dir=tmp_path / "corpus", logseq_dir=tmp_path / "graph")
    assert outcome.logseq_path is not None
    assert outcome.logseq_path.exists()
    assert "lighthouse-draft" in outcome.logseq_path.read_text()


def test_archive_conversation_round_trip(tmp_path) -> None:
    turns = [_Turn("system", "sys"), _Turn("user", "hi"), _Turn("assistant", "hello")]
    outcome = archive_conversation(turns, corpus_dir=tmp_path / "c", title="My chat")
    assert outcome.corpus_path.exists()
    text = outcome.corpus_path.read_text()
    assert "# My chat" in text
    assert "## user" in text and "## assistant" in text
    assert "## system" not in text  # system turn dropped
