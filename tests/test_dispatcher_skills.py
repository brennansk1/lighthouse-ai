"""Zone J — dispatcher + pipeline skill execution (offline-deterministic).

These tests exercise the dispatcher's skill-execution path:

* a job carrying ``selected_skills`` runs each skill through the broker and feeds
  its Documents into the mode engine's hybrid corpus (``meta["documents"]``);
* an empty ``selected_skills`` leaves dispatch behaviour UNCHANGED (back-compat);
* a thin specialty result triggers the ``general_web`` CRAG gap-filler;
* the auto-Adjudicate flag is set only when all five §6.4 conditions hold (a
  cross-skill, balanced, high-severity, load-bearing clash at Thorough/Deep).

A temp skill library with fake skills is built (mirroring
``tests/test_skills_framework.py``) and ``load_skill`` is monkeypatched so the
dispatcher resolves them without touching the in-tree library.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

import lighthouse_ai.dispatcher as dispatcher
from lighthouse_ai.skills import load_skill as real_load_skill


def _write_skill(
    library: Path, skill_id: str, *, manifest_extra: str = "", skill_py: str | None = None
) -> Path:
    d = library / skill_id
    d.mkdir(parents=True)
    (d / "manifest.toml").write_text(
        textwrap.dedent(
            f"""
            id = "{skill_id}"
            name = "{skill_id.title()}"
            description = "test skill"
            category = "test"
            tier = "A"
            signed = true
            allowed_domains = ["arxiv.org"]
            {manifest_extra}
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    body = skill_py or textwrap.dedent(
        """
        def run(ctx, question, *, max_results=5):
            doc = ctx.make_document(
                doc_id="t1", text="answer: " + question, metadata={"source": "x"})
            return [doc]
        """
    )
    (d / "skill.py").write_text(body, encoding="utf-8")
    return d


@pytest.fixture
def skill_lib(tmp_path) -> Path:
    """A temp library whose skills the dispatcher loads via a patched load_skill."""
    return tmp_path / "skill_library"


@pytest.fixture
def patched_load(skill_lib, monkeypatch):
    """Patch the dispatcher's lazily-imported ``load_skill`` onto ``skill_lib``."""

    def _load(skill_id, library_dir=None):
        return real_load_skill(skill_id, library_dir=skill_lib)

    monkeypatch.setattr("lighthouse_ai.skills.load_skill", _load)
    return _load


# --- 1. selected_skills documents flow into the hybrid corpus --------------- #


def test_selected_skills_feed_documents_into_meta(skill_lib, patched_load):
    _write_skill(skill_lib, "alpha")
    meta = {
        "topic": "what is quantum",
        "mode": "investigate",
        "selected_skills": ["alpha"],
        dispatcher._BROKER_META_KEY: object(),
    }  # placeholder; real broker below

    # Use a real broker so run_skill admits the document.
    from lighthouse_ai.sandbox.broker import build_default_broker

    meta[dispatcher._BROKER_META_KEY] = build_default_broker(skill_lib)

    docs = dispatcher._inject_skill_documents(meta, gateway=None)
    assert docs, "skill should have produced documents"
    # meta["documents"] now carries the skill output in the hybrid-corpus shape.
    md = meta["documents"]
    assert md and any("answer: what is quantum" in d["text"] for d in md)
    assert md[0]["skill_id"] == "alpha"
    # And the hybrid builder accepts those documents (non-None corpus).
    hybrid = dispatcher._build_hybrid(meta, gateway=None)
    assert hybrid is not None


def test_investigate_job_runs_skills_end_to_end(migrated_paths, skill_lib, patched_load):
    _write_skill(skill_lib, "alpha")
    job = dispatcher.ClaimedJob(
        id="j-skills",
        mode="investigate",
        meta={"topic": "graph neural networks", "selected_skills": ["alpha"]},
    )
    draft_id = dispatcher.run_job(migrated_paths, job, gateway=None)
    assert draft_id is not None
    # The private handoff keys must not leak into the persisted meta.
    from lighthouse_ai.persistence import open_db

    conn = open_db(migrated_paths.state_db)
    try:
        import json

        meta_json = conn.execute(
            "SELECT metadata_json FROM jobs WHERE id=?", ("j-skills",)
        ).fetchone()
        # job row may not exist (dispatcher.run_job doesn't insert), so just
        # confirm the draft was written.
        row = conn.execute("SELECT body_json FROM drafts WHERE id=?", (draft_id,)).fetchone()
        assert row is not None
        if meta_json and meta_json[0]:
            persisted = json.loads(meta_json[0])
            assert dispatcher._BROKER_META_KEY not in persisted
            assert dispatcher._SKILL_DOCS_META_KEY not in persisted
    finally:
        conn.close()


# --- 2. empty selected_skills → behaviour unchanged ------------------------- #


def test_empty_selected_skills_leaves_meta_unchanged(skill_lib, patched_load):
    meta = {"topic": "anything", "mode": "investigate", dispatcher._BROKER_META_KEY: None}
    docs = dispatcher._inject_skill_documents(meta, gateway=None)
    assert docs == []
    assert "documents" not in meta  # untouched


def test_empty_selected_skills_does_not_run_skills(skill_lib, patched_load, monkeypatch):
    called = {"n": 0}

    def _boom(*a, **k):
        called["n"] += 1
        raise AssertionError("run_skill must not be called with no skills")

    monkeypatch.setattr("lighthouse_ai.skills.run_skill", _boom)
    meta = {"topic": "t", "mode": "investigate", dispatcher._BROKER_META_KEY: None}
    dispatcher._inject_skill_documents(meta, gateway=None)
    assert called["n"] == 0


# --- 3. thin specialty result triggers general_web gap-filler --------------- #


def test_thin_specialty_triggers_general_web_gap_filler(skill_lib, patched_load):
    # Specialty skill returns nothing (thin) → general_web fallback runs.
    _write_skill(
        skill_lib, "emptyspec", skill_py="def run(ctx, q, *, max_results=5):\n    return []\n"
    )
    _write_skill(
        skill_lib,
        "general_web",
        skill_py=textwrap.dedent(
            """
            def run(ctx, question, *, max_results=5):
                return [ctx.make_document(
                    doc_id="gw", text="web fallback: " + question,
                    metadata={"source": "web"})]
            """
        ),
    )
    from lighthouse_ai.sandbox.broker import build_default_broker

    broker = build_default_broker(skill_lib)
    meta = {
        "topic": "obscure topic",
        "mode": "investigate",
        "selected_skills": ["emptyspec"],
        dispatcher._BROKER_META_KEY: broker,
    }
    docs = dispatcher._inject_skill_documents(meta, gateway=None)
    assert docs, "gap-filler should have produced documents"
    assert any("web fallback" in d.text for d in docs)
    assert any(d.metadata.get("skill_id") == "general_web" for d in docs)


def test_no_gap_filler_when_specialty_has_results(skill_lib, patched_load):
    _write_skill(skill_lib, "alpha")  # returns a doc → not thin
    _write_skill(
        skill_lib,
        "general_web",
        skill_py=textwrap.dedent(
            """
            def run(ctx, question, *, max_results=5):
                return [ctx.make_document(doc_id="gw", text="SHOULD_NOT_APPEAR",
                                          metadata={})]
            """
        ),
    )
    from lighthouse_ai.sandbox.broker import build_default_broker

    broker = build_default_broker(skill_lib)
    docs = dispatcher._run_selected_skills(
        {"topic": "q", "selected_skills": ["alpha"]}, gateway=None, broker=broker
    )
    assert docs
    assert not any("SHOULD_NOT_APPEAR" in d.text for d in docs)


def test_gap_filler_absent_general_web_no_crash(skill_lib, patched_load):
    _write_skill(
        skill_lib, "emptyspec", skill_py="def run(ctx, q, *, max_results=5):\n    return []\n"
    )
    from lighthouse_ai.sandbox.broker import build_default_broker

    broker = build_default_broker(skill_lib)
    # No general_web in the library → must degrade silently to [].
    docs = dispatcher._run_selected_skills(
        {"topic": "q", "selected_skills": ["emptyspec"]}, gateway=None, broker=broker
    )
    assert docs == []


# --- 4. auto-Adjudicate flag only under the five §6.4 conditions ------------ #


def _cross_skill_balanced_docs():
    """A load-bearing cross-skill clash: one supporting + one opposing chunk from
    two different skills (balanced) → high severity → auto-Adjudicate eligible."""
    from lighthouse_ai.rag.chunker import Document

    support = Document(
        id="c-sup",
        text="The treatment is effective and safe.",
        metadata={"skill_id": "skillA", "entailment_score": 0.9},
    )
    oppose = Document(
        id="c-opp",
        text="The treatment is ineffective and unsafe.",
        metadata={"skill_id": "skillB", "entailment_score": 0.1},
    )
    return [support, oppose]


def test_auto_adjudicate_flag_set_under_five_conditions():
    meta = {"depth": "thorough", "job_id": "j-auto"}
    summary = {"body_json": {"finding": "The treatment is effective and safe."}}
    dispatcher._maybe_flag_auto_adjudicate(meta, summary, _cross_skill_balanced_docs())
    assert "auto_adjudicate" in meta
    assert meta["auto_adjudicate"].startswith("contradiction-")
    assert summary["body_json"]["auto_adjudicate"] == meta["auto_adjudicate"]


def test_auto_adjudicate_not_set_at_quick_depth():
    # Condition 4 (Thorough/Deep) fails at quick depth.
    meta = {"depth": "quick", "job_id": "j-auto"}
    summary = {"body_json": {"finding": "The treatment is effective and safe."}}
    dispatcher._maybe_flag_auto_adjudicate(meta, summary, _cross_skill_balanced_docs())
    assert "auto_adjudicate" not in meta


def test_auto_adjudicate_not_set_when_single_skill():
    # Condition 1 (cross_skill) fails when both chunks share one skill_id.
    from lighthouse_ai.rag.chunker import Document

    docs = [
        Document(
            id="c1",
            text="The treatment is effective.",
            metadata={"skill_id": "skillA", "entailment_score": 0.9},
        ),
        Document(
            id="c2",
            text="The treatment is ineffective.",
            metadata={"skill_id": "skillA", "entailment_score": 0.1},
        ),
    ]
    meta = {"depth": "thorough", "job_id": "j-auto"}
    summary = {"body_json": {"finding": "The treatment is effective."}}
    dispatcher._maybe_flag_auto_adjudicate(meta, summary, docs)
    assert "auto_adjudicate" not in meta


def test_auto_adjudicate_no_docs_is_noop():
    meta = {"depth": "deep", "job_id": "j"}
    summary = {"body_json": {"finding": "x is effective."}}
    dispatcher._maybe_flag_auto_adjudicate(meta, summary, [])
    assert "auto_adjudicate" not in meta
