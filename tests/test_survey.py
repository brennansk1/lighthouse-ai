"""Offline-deterministic tests for the Survey engine.

All tests run without a gateway (no LLM calls).  Any real-backend behaviour
is covered by integration tests gated behind LIGHTHOUSE_REAL_BACKEND=1.
"""

from __future__ import annotations

import pytest

from lighthouse_ai.modes.survey import (
    AttributeSpec,
    Document,
    EvidenceRow,
    ScreeningCriterion,
    run_survey,
)

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

DOCS = [
    Document("d1", "RCT of drug A",
             "This randomized controlled trial enrolled 200 patients. "
             "The sample size was 200. Outcome was positive."),
    Document("d2", "Opinion piece",
             "This editorial argues a point. No trial was run here."),
    Document("d3", "Cohort study",
             "A randomized study of 50 patients. The sample size was 50."),
]

CRITERIA = [
    ScreeningCriterion("is a trial", keywords=("randomized", "trial")),
    ScreeningCriterion("not an editorial", keywords=("editorial",), exclude=True),
]

ATTRS = [AttributeSpec("sample size", keywords=("sample size", "patients"))]


# ---------------------------------------------------------------------------
# Guard-rail validation
# ---------------------------------------------------------------------------

def test_requires_documents():
    with pytest.raises(ValueError, match="document"):
        run_survey("q", documents=[], criteria=CRITERIA, attributes=ATTRS)


def test_requires_attributes():
    with pytest.raises(ValueError, match="attribute"):
        run_survey("q", documents=DOCS, criteria=CRITERIA, attributes=[])


def test_requires_nonempty_question():
    with pytest.raises(ValueError, match="question"):
        run_survey("", documents=DOCS, criteria=CRITERIA, attributes=ATTRS)


def test_requires_nonempty_question_whitespace():
    """A question that is only whitespace must be rejected."""
    with pytest.raises(ValueError, match="question"):
        run_survey("   ", documents=DOCS, criteria=CRITERIA, attributes=ATTRS)


# ---------------------------------------------------------------------------
# Core screening logic
# ---------------------------------------------------------------------------

def test_screening_includes_and_excludes():
    r = run_survey("Which trials?", DOCS, CRITERIA, ATTRS)
    decided = {d.doc_id: d.included for d in r.decisions}
    assert decided["d1"] is True
    assert decided["d2"] is False   # editorial excluded
    assert decided["d3"] is True


def test_all_excluded():
    """When every document is excluded the report has no rows but is still valid."""
    docs = [
        Document("e1", "editorial one", "This editorial is useless."),
        Document("e2", "editorial two", "Another editorial here."),
    ]
    crits = [ScreeningCriterion("not editorial", keywords=("editorial",), exclude=True)]
    attrs = [AttributeSpec("n", keywords=("n",))]
    r = run_survey("q", docs, crits, attrs)
    assert r.prisma.included == 0
    assert r.prisma.excluded == 2
    assert r.rows == []
    # All decisions should show included=False.
    assert all(not d.included for d in r.decisions)


def test_no_criteria_includes_all():
    """With an empty criteria list every document is included."""
    r = run_survey("q", DOCS, criteria=[], attributes=ATTRS)
    assert r.prisma.included == len(DOCS)
    assert {row.doc_id for row in r.rows} == {"d1", "d2", "d3"}


def test_exclusion_criterion_with_empty_keywords_is_vacuous():
    """An exclusion criterion with no keywords never matches anything."""
    crits = [ScreeningCriterion("vacuous exclude", keywords=(), exclude=True)]
    r = run_survey("q", DOCS, crits, ATTRS)
    assert r.prisma.included == len(DOCS)


def test_inclusion_criterion_with_empty_keywords_is_vacuous():
    """An inclusion criterion with no keywords is always satisfied."""
    crits = [ScreeningCriterion("vacuous include", keywords=(), exclude=False)]
    r = run_survey("q", DOCS, crits, ATTRS)
    assert r.prisma.included == len(DOCS)


def test_screening_case_insensitive():
    """Keyword matching must be case-insensitive."""
    docs = [Document("x", "Study", "RANDOMIZED trial of something.")]
    crits = [ScreeningCriterion("trial", keywords=("randomized",))]
    r = run_survey("q", docs, crits, ATTRS)
    assert r.decisions[0].included is True


def test_screening_whitespace_normalised():
    """Extra whitespace in the document must not break keyword matching."""
    docs = [Document("x", "Study", "This is a  randomized\n\ttrial.")]
    crits = [ScreeningCriterion("trial", keywords=("randomized trial",))]
    r = run_survey("q", docs, crits, ATTRS)
    # The normalised haystack collapses whitespace so "randomized trial" matches.
    assert r.decisions[0].included is True


def test_screening_reason_recorded():
    """Excluded documents must carry an informative reason string."""
    r = run_survey("Which trials?", DOCS, CRITERIA, ATTRS)
    d2 = next(d for d in r.decisions if d.doc_id == "d2")
    assert "editorial" in d2.reason.lower()


# ---------------------------------------------------------------------------
# PRISMA accounting
# ---------------------------------------------------------------------------

def test_prisma_counts_consistent():
    r = run_survey("Which trials?", DOCS, CRITERIA, ATTRS)
    assert r.prisma.identified == 3
    assert r.prisma.included + r.prisma.excluded == r.prisma.identified
    assert r.prisma.included == 2


def test_prisma_screened_equals_identified():
    """Offline path screens every document, so screened == identified."""
    r = run_survey("Which trials?", DOCS, CRITERIA, ATTRS)
    assert r.prisma.screened == r.prisma.identified


def test_prisma_excluded_reasons_populated():
    """excluded_reasons additive field maps excluded doc_ids to reason strings."""
    r = run_survey("Which trials?", DOCS, CRITERIA, ATTRS)
    assert "d2" in r.prisma.excluded_reasons
    assert isinstance(r.prisma.excluded_reasons["d2"], str)
    assert r.prisma.excluded_reasons["d2"]  # non-empty


def test_prisma_no_false_exclusions_in_reasons():
    """Included documents must NOT appear in excluded_reasons."""
    r = run_survey("Which trials?", DOCS, CRITERIA, ATTRS)
    for doc_id in {"d1", "d3"}:
        assert doc_id not in r.prisma.excluded_reasons


# ---------------------------------------------------------------------------
# Evidence rows and cells
# ---------------------------------------------------------------------------

def test_rows_only_for_included_docs():
    r = run_survey("Which trials?", DOCS, CRITERIA, ATTRS)
    assert {row.doc_id for row in r.rows} == {"d1", "d3"}


def test_evidence_cells_extract_and_gate():
    r = run_survey("Which trials?", DOCS, CRITERIA, ATTRS)
    rows = {row.doc_id: row for row in r.rows}
    cell = rows["d1"].cells[0]
    assert cell.attribute == "sample size"
    assert cell.value  # found a sentence mentioning sample size
    assert cell.citation_chunk_ids == ("d1",)
    # Offline (no real scorer) → unchecked: score is None and the cell is NOT
    # marked entailed (an unchecked cell must never fabricate a pass).
    assert cell.entailment_score is None
    assert cell.entailed is False


def test_empty_text_produces_empty_cell():
    """A document with no text yields empty-value cells without crashing."""
    docs = [Document("empty", "Empty doc", "")]
    r = run_survey("q", docs, criteria=[], attributes=ATTRS)
    row = r.rows[0]
    assert row.cells[0].value == ""
    assert row.cells[0].entailed is False
    # A missing/never-extracted attribute is UNCHECKED, not a failed fact-check:
    # score is None (neutral badge), not 0.0 (which renders as "✗ uncertain").
    assert row.cells[0].entailment_score is None


def test_missing_attrs_field_populated():
    """EvidenceRow.missing_attrs lists labels whose extracted value is empty."""
    docs = [Document("m", "Missing", "This doc says nothing relevant.")]
    attrs = [
        AttributeSpec("sample size", keywords=("sample size",)),
        AttributeSpec("outcome", keywords=("outcome",)),
    ]
    r = run_survey("q", docs, criteria=[], attributes=attrs)
    row = r.rows[0]
    # Both attributes are absent from the text — both should be listed as missing.
    assert "sample size" in row.missing_attrs
    assert "outcome" in row.missing_attrs


def test_missing_attrs_empty_when_all_found():
    """EvidenceRow.missing_attrs is empty when every attribute is extracted."""
    r = run_survey("Which trials?", DOCS, CRITERIA, ATTRS)
    rows = {row.doc_id: row for row in r.rows}
    # d1 has "sample size" in its text — no missing attrs expected.
    assert rows["d1"].missing_attrs == []


def test_empty_attribute_keywords_uses_label_fallback():
    """AttributeSpec with no keywords should still extract via label match."""
    docs = [Document("l", "Lab", "The outcome was positive and significant.")]
    attrs = [AttributeSpec("outcome")]  # no keywords — label fallback
    r = run_survey("q", docs, criteria=[], attributes=attrs)
    row = r.rows[0]
    assert row.cells[0].value  # label 'outcome' found in text
    assert "outcome" not in row.missing_attrs


def test_cells_count_equals_attrs_count():
    """Every evidence row must have exactly one cell per attribute spec."""
    attrs = [
        AttributeSpec("sample size", keywords=("sample size",)),
        AttributeSpec("outcome", keywords=("outcome",)),
    ]
    r = run_survey("Which trials?", DOCS, CRITERIA, attrs)
    for row in r.rows:
        assert len(row.cells) == len(attrs)


# ---------------------------------------------------------------------------
# Duplicate document handling
# ---------------------------------------------------------------------------

def test_duplicate_doc_ids_deduplicated():
    """Duplicate doc_ids are silently deduplicated; only the first is kept."""
    docs = [
        Document("dup", "First", "randomized trial data."),
        Document("dup", "Second", "randomized trial more data."),  # duplicate id
        Document("unique", "Unique", "randomized trial unique."),
    ]
    crits = [ScreeningCriterion("trial", keywords=("randomized",))]
    r = run_survey("q", docs, crits, ATTRS)
    # Only 2 unique ids → 2 identified.
    assert r.prisma.identified == 2
    assert r.prisma.included == 2
    doc_ids = [row.doc_id for row in r.rows]
    assert doc_ids.count("dup") == 1


def test_duplicate_docs_same_as_single():
    """Deduplication makes a corpus of one repeated doc equivalent to one doc."""
    single = [Document("d", "Title", "randomized trial here.")]
    duped = single * 5
    crits = [ScreeningCriterion("t", keywords=("randomized",))]
    r_single = run_survey("q", single, crits, ATTRS)
    r_duped = run_survey("q", duped, crits, ATTRS)
    assert r_single.prisma.identified == r_duped.prisma.identified == 1


# ---------------------------------------------------------------------------
# Dict input coercion
# ---------------------------------------------------------------------------

def test_dict_inputs_coerced():
    r = run_survey(
        "q",
        documents=[{"id": "x", "title": "T", "text": "randomized trial of 10."}],
        criteria=[{"label": "trial", "keywords": ["randomized"]}],
        attributes=[{"label": "n", "keywords": ["10"]}],
    )
    assert r.rows[0].doc_id == "x"


def test_dict_doc_prefers_doc_id_over_id():
    """When both 'doc_id' and 'id' are present, 'doc_id' wins."""
    r = run_survey(
        "q",
        documents=[{"doc_id": "preferred", "id": "fallback",
                    "title": "T", "text": "randomized trial."}],
        criteria=[],
        attributes=[{"label": "x", "keywords": ["trial"]}],
    )
    assert r.rows[0].doc_id == "preferred"


def test_dict_doc_falls_back_to_index_id():
    """When neither 'doc_id' nor 'id' is present, a positional id is used."""
    r = run_survey(
        "q",
        documents=[{"title": "T", "text": "randomized trial."}],
        criteria=[],
        attributes=[{"label": "x", "keywords": ["trial"]}],
    )
    assert r.decisions[0].doc_id == "doc0"


def test_dict_exclude_criterion_coerced():
    """Exclusion criteria expressed as dicts are correctly coerced."""
    docs = [Document("e", "Ed", "This is an editorial piece.")]
    r = run_survey(
        "q",
        docs,
        criteria=[{"label": "no editorial", "keywords": ["editorial"], "exclude": True}],
        attributes=[{"label": "x", "keywords": ["editorial"]}],
    )
    assert r.decisions[0].included is False
    assert r.prisma.excluded == 1


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------

def test_deterministic():
    r1 = run_survey("Which trials?", DOCS, CRITERIA, ATTRS)
    r2 = run_survey("Which trials?", DOCS, CRITERIA, ATTRS)
    assert [d.included for d in r1.decisions] == [d.included for d in r2.decisions]
    assert [c.value for row in r1.rows for c in row.cells] == \
           [c.value for row in r2.rows for c in row.cells]


def test_deterministic_with_dict_inputs():
    """Dict inputs must also produce a deterministic result across two calls."""
    kwargs = dict(
        question="trial?",
        documents=[{"id": "a", "title": "A", "text": "randomized trial of 100 patients."}],
        criteria=[{"label": "rct", "keywords": ["randomized"]}],
        attributes=[{"label": "n", "keywords": ["patients"]}],
    )
    r1 = run_survey(**kwargs)
    r2 = run_survey(**kwargs)
    assert r1.rows[0].cells[0].value == r2.rows[0].cells[0].value


# ---------------------------------------------------------------------------
# Report-level invariants
# ---------------------------------------------------------------------------

def test_claims_non_empty():
    r = run_survey("Which trials?", DOCS, CRITERIA, ATTRS)
    assert r.claims
    assert isinstance(r.claims[0], str)


def test_claims_contain_question():
    r = run_survey("Which trials?", DOCS, CRITERIA, ATTRS)
    assert "Which trials?" in r.claims[0]


def test_report_preserves_question():
    r = run_survey("My special question", DOCS, CRITERIA, ATTRS)
    assert r.question == "My special question"


def test_decisions_length_equals_doc_count():
    """One decision per (deduplicated) document."""
    r = run_survey("Which trials?", DOCS, CRITERIA, ATTRS)
    assert len(r.decisions) == len(DOCS)


def test_evidence_row_is_dataclass_instance():
    """Rows are EvidenceRow instances (not plain dicts)."""
    r = run_survey("Which trials?", DOCS, CRITERIA, ATTRS)
    for row in r.rows:
        assert isinstance(row, EvidenceRow)
