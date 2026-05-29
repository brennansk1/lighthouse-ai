"""Tests for Zone A — the mode-aware source recommender.

Builds a temp library of fake skills (mirroring the fixture style in
``tests/test_skills_framework.py``) and asserts the per-mode scoring rules from
MODE_SKILL_INTEGRATION.md §2.2 + §5.2 hold on the deterministic offline path
(token-overlap similarity, no embedder, no gateway).
"""

from __future__ import annotations

import textwrap
from pathlib import Path

from lighthouse_ai.skills.recommender import (
    GENERAL_WEB_ID,
    MODE_WEIGHTS,
    VALID_ROLES,
    Recommendation,
    recommend,
)
from lighthouse_ai.skills.registry import all_skills


def _write_skill(library: Path, skill_id: str, *, manifest_extra: str = "",
                 skill_md: str | None = None) -> Path:
    d = library / skill_id
    d.mkdir(parents=True)
    (d / "manifest.toml").write_text(
        textwrap.dedent(
            f"""
            id = "{skill_id}"
            name = "{skill_id.title()}"
            description = "test skill {skill_id}"
            category = "test"
            tier = "A"
            allowed_domains = ["arxiv.org"]
            {manifest_extra}
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    # A run() entrypoint so the folder is a loadable skill (not strictly needed
    # by the recommender, which reads manifests, but keeps the fixture honest).
    (d / "skill.py").write_text(
        "def run(ctx, q, *, max_results=5):\n    return []\n", encoding="utf-8"
    )
    if skill_md is not None:
        (d / "SKILL.md").write_text(skill_md, encoding="utf-8")
    return d


def _ids(recs: list[Recommendation]) -> list[str]:
    return [r.skill_id for r in recs]


def _rank(recs: list[Recommendation], skill_id: str) -> int:
    return _ids(recs).index(skill_id)


# --------------------------------------------------------------------------- #
# Investigate: grade-A peer-reviewed beats a community lookup skill
# --------------------------------------------------------------------------- #
def test_investigate_ranks_grade_a_above_community_lookup(tmp_path):
    lib = tmp_path / "library"
    _write_skill(
        lib,
        "arxiv",
        manifest_extra=textwrap.dedent(
            """
            signed = true
            default_grade = "A"
            authority = "peer_reviewed"
            perspective_lens = "primary"
            output_shape = "enumerable"
            modes_natural_fit = ["investigate"]
            topics = ["machine learning", "transformers"]
            supported_question_types = ["causal_explanation"]
            """
        ).strip(),
        skill_md="Research arXiv preprints on machine learning and transformers.",
    )
    _write_skill(
        lib,
        "randomwiki",
        manifest_extra=textwrap.dedent(
            """
            default_grade = "C"
            output_shape = "lookup"
            topics = ["general"]
            """
        ).strip(),
        skill_md="A community wiki lookup of general facts.",
    )
    skills = all_skills(lib)
    recs = recommend(
        "why do transformers outperform RNNs in machine learning?",
        mode="investigate",
        depth="standard",
        skills=skills,
        library_dir=lib,
    )
    assert _rank(recs, "arxiv") < _rank(recs, "randomwiki")


def test_investigate_thorough_excludes_community(tmp_path):
    lib = tmp_path / "library"
    _write_skill(lib, "arxiv",
                 manifest_extra='signed = true\ndefault_grade = "A"\noutput_shape = "enumerable"')
    _write_skill(lib, "communityblog", manifest_extra='output_shape = "lookup"')
    skills = all_skills(lib)
    recs = recommend("what is x and why does it matter for evidence",
                     mode="investigate", depth="thorough", skills=skills, library_dir=lib)
    assert "communityblog" not in _ids(recs)
    assert "arxiv" in _ids(recs)


# --------------------------------------------------------------------------- #
# Survey: filters out lookup-shape skills
# --------------------------------------------------------------------------- #
def test_survey_filters_out_lookup_shape(tmp_path):
    lib = tmp_path / "library"
    _write_skill(lib, "openalex",
                 manifest_extra='signed = true\noutput_shape = "enumerable"\ntopics = ["papers"]')
    _write_skill(lib, "factbox",
                 manifest_extra='signed = true\noutput_shape = "lookup"\ntopics = ["papers"]')
    skills = all_skills(lib)
    recs = recommend("survey the landscape of papers", mode="survey",
                     depth="standard", skills=skills, library_dir=lib)
    assert "openalex" in _ids(recs)
    assert "factbox" not in _ids(recs)
    assert MODE_WEIGHTS["survey"]["require_output_shape"] == "enumerable"


# --------------------------------------------------------------------------- #
# Reconstruct: requires temporal_tools
# --------------------------------------------------------------------------- #
def test_reconstruct_requires_temporal_tools(tmp_path):
    lib = tmp_path / "library"
    _write_skill(lib, "newsarchive",
                 manifest_extra='signed = true\ntemporal_tools = true\noutput_shape = "stream"')
    _write_skill(lib, "staticdb",
                 manifest_extra='signed = true\ntemporal_tools = false\noutput_shape = "lookup"')
    skills = all_skills(lib)
    recs = recommend("reconstruct the timeline of events", mode="reconstruct",
                     depth="standard", skills=skills, library_dir=lib)
    assert "newsarchive" in _ids(recs)
    assert "staticdb" not in _ids(recs)


# --------------------------------------------------------------------------- #
# Adjudicate: returns diverse perspective_lens
# --------------------------------------------------------------------------- #
def test_adjudicate_returns_diverse_perspective_lens(tmp_path):
    lib = tmp_path / "library"
    _write_skill(lib, "primarysrc",
                 manifest_extra='signed = true\nperspective_lens = "primary"\ntopics = ["claim"]')
    _write_skill(lib, "regulator",
                 manifest_extra='signed = true\nperspective_lens = "regulatory"\ntopics = ["claim"]')
    _write_skill(lib, "repro",
                 manifest_extra='signed = true\nperspective_lens = "reproducibility"\ntopics = ["claim"]')
    # A second primary-lens skill — must NOT crowd out the distinct lenses.
    _write_skill(lib, "primary2",
                 manifest_extra='signed = true\nperspective_lens = "primary"\ntopics = ["claim"]')
    _write_skill(lib, GENERAL_WEB_ID, manifest_extra='signed = true')
    skills = all_skills(lib)
    recs = recommend("is this disputed claim true?", mode="adjudicate",
                     depth="standard", skills=skills, library_dir=lib)
    # The leading picks (before any duplicate-lens leftovers) span distinct lenses.
    lens_by_id = {m.id: m.perspective_lens for m in skills}
    # general_web role for adjudicate is cross_check (popular lens).
    gw = next(r for r in recs if r.skill_id == GENERAL_WEB_ID)
    assert gw.role == "cross_check"
    leading = [r for r in recs if r.skill_id in lens_by_id][:3]
    lenses = {lens_by_id[r.skill_id] for r in leading}
    assert lenses == {"primary", "regulatory", "reproducibility"}


# --------------------------------------------------------------------------- #
# Decide: per-option scoring merges into one deduped set
# --------------------------------------------------------------------------- #
def test_decide_merges_per_option_sets(tmp_path):
    lib = tmp_path / "library"
    _write_skill(lib, "optionsource", manifest_extra='signed = true\ntopics = ["evidence"]')
    skills = all_skills(lib)

    class _FakeFramed:
        original = "should we choose A or B?"
        question_type = None
        chosen = None
        sub_questions = [
            "What is the strongest case for option A?",
            "What evidence would change the choice?",
        ]
        load_bearing = ["What evidence would change the choice?"]

    recs = recommend(_FakeFramed(), mode="decide", depth="standard",
                     skills=skills, library_dir=lib)
    # No duplicate skill ids after the per-option merge.
    assert len(_ids(recs)) == len(set(_ids(recs)))
    assert "optionsource" in _ids(recs)


# --------------------------------------------------------------------------- #
# Profile overlay: baseline / boosted / excluded
# --------------------------------------------------------------------------- #
def test_profile_overlay_baseline_boost_exclude(tmp_path):
    lib = tmp_path / "library"
    _write_skill(lib, "pubmed", manifest_extra='signed = true\ntopics = ["oncology"]')
    _write_skill(lib, "cochrane", manifest_extra='signed = true\ntopics = ["oncology"]')
    _write_skill(lib, "wikipedia", manifest_extra='topics = ["oncology"]\noutput_shape = "lookup"')
    skills = all_skills(lib)
    profiles = [
        {
            "domain_pattern": "oncology",
            "mode": "investigate",
            "baseline_skills": ["clinicaltrials"],  # not even a candidate
            "boosted_skills": ["cochrane"],
            "excluded_skills": ["wikipedia"],
        }
    ]
    recs = recommend("oncology treatment evidence review", mode="investigate",
                     depth="standard", skills=skills, profiles=profiles, library_dir=lib)
    ids = _ids(recs)
    # excluded filtered out
    assert "wikipedia" not in ids
    # baseline always present even though it wasn't a candidate
    assert "clinicaltrials" in ids
    # boosted outranks the un-boosted peer
    assert _rank(recs, "cochrane") < _rank(recs, "pubmed")


# --------------------------------------------------------------------------- #
# general_web fallback appears when nothing fits
# --------------------------------------------------------------------------- #
def test_general_web_fallback_when_nothing_fits(tmp_path):
    lib = tmp_path / "library"
    # general_web must be discoverable for the fallback to be offered.
    _write_skill(lib, GENERAL_WEB_ID,
                 manifest_extra='signed = true\nbase_url = "https://example.org"')
    # A specialty skill totally irrelevant to the question and lookup-shaped.
    _write_skill(lib, "obscuredb",
                 manifest_extra='signed = true\noutput_shape = "lookup"\ntopics = ["quantum chromodynamics"]',
                 skill_md="quantum chromodynamics lattice computations")
    skills = all_skills(lib)
    recs = recommend("how do I bake sourdough bread at home?", mode="investigate",
                     depth="standard", skills=skills, library_dir=lib)
    gw = next(r for r in recs if r.skill_id == GENERAL_WEB_ID)
    assert gw.role == "primary"
    assert gw.role in VALID_ROLES
    # general_web leads when no specialty clears the threshold.
    assert _ids(recs)[0] == GENERAL_WEB_ID


def test_general_web_breadth_when_specialty_fits(tmp_path):
    lib = tmp_path / "library"
    _write_skill(lib, GENERAL_WEB_ID, manifest_extra='signed = true')
    _write_skill(
        lib, "arxiv",
        manifest_extra=textwrap.dedent(
            """
            signed = true
            default_grade = "A"
            authority = "peer_reviewed"
            perspective_lens = "primary"
            output_shape = "enumerable"
            modes_natural_fit = ["investigate"]
            topics = ["transformers", "machine learning"]
            supported_question_types = ["causal_explanation"]
            """
        ).strip(),
        skill_md="arXiv preprints transformers machine learning attention",
    )
    skills = all_skills(lib)
    recs = recommend("why do transformers outperform RNNs in machine learning?",
                     mode="investigate", depth="standard", skills=skills, library_dir=lib)
    gw = next(r for r in recs if r.skill_id == GENERAL_WEB_ID)
    assert gw.role == "breadth"
    assert _ids(recs)[0] == "arxiv"


# --------------------------------------------------------------------------- #
# Robustness: empty library does not crash
# --------------------------------------------------------------------------- #
def test_empty_library_no_crash(tmp_path):
    lib = tmp_path / "library"
    lib.mkdir()
    recs = recommend("anything at all here", mode="investigate",
                     depth="standard", library_dir=lib)
    # No skills and no general_web on disk → empty, but no exception.
    assert recs == []


def test_accepts_plain_string_offline(tmp_path):
    lib = tmp_path / "library"
    _write_skill(lib, "arxiv", manifest_extra='signed = true\ntopics = ["physics"]')
    skills = all_skills(lib)
    # Plain string + no gateway → deterministic framing, no crash.
    recs = recommend("explain physics of black holes", mode="investigate",
                     skills=skills, library_dir=lib)
    assert "arxiv" in _ids(recs)
