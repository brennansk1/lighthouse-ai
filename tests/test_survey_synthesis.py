"""Offline-deterministic tests for Survey Zone-Q features:

* Contested cell detection when included docs disagree on an attribute.
* PRISMA discordant_findings annotation.
* Multi-doc synthesis pass (deterministic offline path).

All tests run without a gateway (gateway=None).
"""

from __future__ import annotations

from lighthouse_ai.modes.survey import (
    AttributeSpec,
    Document,
    EvidenceCell,
    ScreeningCriterion,
    run_survey,
)

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

INCLUDE_CRIT = [ScreeningCriterion("trial", keywords=("trial",))]
SAMPLE_ATTR = AttributeSpec("sample size", keywords=("sample size", "patients"))
OUTCOME_ATTR = AttributeSpec("outcome", keywords=("outcome",))


def _make_docs(*texts: str, prefix: str = "d") -> list[Document]:
    return [
        Document(f"{prefix}{i}", f"Title {i}", text)
        for i, text in enumerate(texts, start=1)
    ]


# ---------------------------------------------------------------------------
# Contested cell detection
# ---------------------------------------------------------------------------

class TestContestedCells:
    """Two included documents disagree on the same attribute → contested flag."""

    def test_contested_flag_set_when_values_differ(self):
        """When two docs extract different values for an attribute, both cells
        are marked contested=True."""
        docs = [
            Document("a", "Trial A", "This trial enrolled 200 patients sample size was 200."),
            Document("b", "Trial B", "This trial enrolled 50 patients sample size was 50."),
        ]
        r = run_survey("q", docs, criteria=[], attributes=[SAMPLE_ATTR])
        cells_by_doc = {row.doc_id: row.cells[0] for row in r.rows}
        # Both documents return different sentences mentioning "sample size" /
        # "patients" — the extracted values will differ, so both cells should be
        # marked contested.
        assert cells_by_doc["a"].contested is True
        assert cells_by_doc["b"].contested is True

    def test_contested_by_points_to_other_doc(self):
        """contested_by must name the other disagreeing document, not self."""
        docs = [
            Document("a", "Trial A", "This trial enrolled 200 patients sample size was 200."),
            Document("b", "Trial B", "This trial enrolled 50 patients sample size was 50."),
        ]
        r = run_survey("q", docs, criteria=[], attributes=[SAMPLE_ATTR])
        cells_by_doc = {row.doc_id: row.cells[0] for row in r.rows}
        assert "b" in cells_by_doc["a"].contested_by
        assert "a" in cells_by_doc["b"].contested_by
        # Self must not appear in its own contested_by list.
        assert "a" not in cells_by_doc["a"].contested_by
        assert "b" not in cells_by_doc["b"].contested_by

    def test_no_contested_when_all_agree(self):
        """When both documents extract the same value, no cell is contested."""
        docs = [
            Document("a", "Trial A", "The sample size was 200 patients."),
            Document("b", "Trial B", "The sample size was 200 patients."),
        ]
        r = run_survey("q", docs, criteria=[], attributes=[SAMPLE_ATTR])
        for row in r.rows:
            for cell in row.cells:
                assert cell.contested is False
                assert cell.contested_by == ()

    def test_empty_value_not_contested(self):
        """An empty extracted value should never be counted as a disagreement."""
        docs = [
            Document("a", "Trial A", "This trial has sample size of 100 patients."),
            Document("b", "Trial B", "This trial mentions no numeric measures."),
        ]
        r = run_survey("q", docs, criteria=[], attributes=[SAMPLE_ATTR])
        cells_by_doc = {row.doc_id: row.cells[0] for row in r.rows}
        # b has empty value → not contested on either side
        assert cells_by_doc["b"].value == ""
        assert cells_by_doc["b"].contested is False
        assert cells_by_doc["a"].contested is False

    def test_contested_cell_is_frozen_dataclass(self):
        """EvidenceCell is a frozen dataclass — contested fields are present."""
        docs = [
            Document("a", "A", "This trial enrolled 200 patients sample size was 200."),
            Document("b", "B", "This trial enrolled 50 patients sample size was 50."),
        ]
        r = run_survey("q", docs, criteria=[], attributes=[SAMPLE_ATTR])
        for row in r.rows:
            cell = row.cells[0]
            assert isinstance(cell, EvidenceCell)
            assert hasattr(cell, "contested")
            assert hasattr(cell, "contested_by")

    def test_contested_only_for_differing_attribute(self):
        """Only the attribute that actually differs should be marked contested."""
        docs = [
            Document(
                "a", "A",
                "This trial enrolled 200 patients sample size was 200. The outcome was positive.",
            ),
            Document(
                "b", "B",
                "This trial enrolled 50 patients sample size was 50. The outcome was positive.",
            ),
        ]
        attrs = [SAMPLE_ATTR, OUTCOME_ATTR]
        r = run_survey("q", docs, criteria=[], attributes=attrs)
        cells_by_doc_attr = {
            (row.doc_id, cell.attribute): cell
            for row in r.rows
            for cell in row.cells
        }
        # sample size differs → contested
        assert cells_by_doc_attr[("a", "sample size")].contested is True
        assert cells_by_doc_attr[("b", "sample size")].contested is True
        # outcome is the same → NOT contested
        assert cells_by_doc_attr[("a", "outcome")].contested is False
        assert cells_by_doc_attr[("b", "outcome")].contested is False

    def test_three_docs_two_agree_one_differs(self):
        """When 2 of 3 docs agree and 1 differs, the outlier cell is contested."""
        docs = [
            Document("a", "A", "This trial enrolled 200 patients sample size was 200."),
            Document("b", "B", "This trial enrolled 200 patients sample size was 200."),
            Document("c", "C", "This trial enrolled 50 patients sample size was 50."),
        ]
        r = run_survey("q", docs, criteria=[], attributes=[SAMPLE_ATTR])
        cells_by_doc = {row.doc_id: row.cells[0] for row in r.rows}
        # All three have non-empty values that differ between {a,b} and {c}.
        assert cells_by_doc["c"].contested is True
        # a and b have the same value as each other but differ from c → contested
        assert cells_by_doc["a"].contested is True
        assert cells_by_doc["b"].contested is True

    def test_single_doc_never_contested(self):
        """A single included document cannot contest itself."""
        docs = [Document("a", "A", "This trial enrolled 100 patients sample size was 100.")]
        r = run_survey("q", docs, criteria=[], attributes=[SAMPLE_ATTR])
        assert r.rows[0].cells[0].contested is False
        assert r.rows[0].cells[0].contested_by == ()


# ---------------------------------------------------------------------------
# PRISMA discordant_findings annotation
# ---------------------------------------------------------------------------

class TestPrismaDiscordantFindings:
    """PRISMA.discordant_findings is populated when docs disagree (§6.2)."""

    def test_discordant_findings_populated(self):
        """discordant_findings maps attribute labels to the contested doc_ids."""
        docs = [
            Document("a", "A", "This trial enrolled 200 patients sample size was 200."),
            Document("b", "B", "This trial enrolled 50 patients sample size was 50."),
        ]
        r = run_survey("q", docs, criteria=[], attributes=[SAMPLE_ATTR])
        assert "sample size" in r.prisma.discordant_findings
        contested_ids = r.prisma.discordant_findings["sample size"]
        assert "a" in contested_ids
        assert "b" in contested_ids

    def test_discordant_findings_empty_when_all_agree(self):
        """discordant_findings is empty when no attribute has a conflict."""
        docs = [
            Document("a", "A", "The sample size was 200 patients."),
            Document("b", "B", "The sample size was 200 patients."),
        ]
        r = run_survey("q", docs, criteria=[], attributes=[SAMPLE_ATTR])
        assert r.prisma.discordant_findings == {}

    def test_discordant_count_reflects_contested_cells(self):
        """discordant_count equals the number of contested cells across all rows."""
        docs = [
            Document("a", "A", "This trial enrolled 200 patients sample size was 200."),
            Document("b", "B", "This trial enrolled 50 patients sample size was 50."),
        ]
        r = run_survey("q", docs, criteria=[], attributes=[SAMPLE_ATTR])
        expected = sum(1 for row in r.rows for cell in row.cells if cell.contested)
        assert r.prisma.discordant_count == expected
        assert r.prisma.discordant_count >= 2  # at least a and b are contested

    def test_discordant_count_zero_when_no_conflicts(self):
        docs = [
            Document("a", "A", "The sample size was 200 patients."),
            Document("b", "B", "The sample size was 200 patients."),
        ]
        r = run_survey("q", docs, criteria=[], attributes=[SAMPLE_ATTR])
        assert r.prisma.discordant_count == 0

    def test_discordant_findings_doc_ids_sorted(self):
        """doc_id lists inside discordant_findings are deterministically sorted."""
        docs = [
            Document("z", "Z", "This trial enrolled 200 patients sample size was 200."),
            Document("a", "A", "This trial enrolled 50 patients sample size was 50."),
        ]
        r = run_survey("q", docs, criteria=[], attributes=[SAMPLE_ATTR])
        if "sample size" in r.prisma.discordant_findings:
            ids = r.prisma.discordant_findings["sample size"]
            assert ids == sorted(ids)

    def test_discordant_annotation_only_for_included_docs(self):
        """Excluded documents must not contribute to discordant_findings."""
        docs = [
            Document("inc1", "Trial A", "This trial enrolled 200 patients sample size was 200."),
            Document("inc2", "Trial B", "This trial enrolled 50 patients sample size was 50."),
            Document("exc1", "Editorial", "This editorial argues sample size was 999 patients."),
        ]
        crits = [ScreeningCriterion("no editorial", keywords=("editorial",), exclude=True)]
        r = run_survey("q", docs, crits, [SAMPLE_ATTR])
        # exc1 is excluded — it must not appear in discordant_findings.
        for doc_list in r.prisma.discordant_findings.values():
            assert "exc1" not in doc_list


# ---------------------------------------------------------------------------
# Synthesis notes (deterministic offline pass, gap #20)
# ---------------------------------------------------------------------------

class TestSynthesisNotes:
    """synthesis_notes are populated offline and surface cross-doc patterns."""

    def test_synthesis_notes_present_on_report(self):
        """SurveyReport always has a synthesis_notes field."""
        docs = [Document("a", "A", "The trial enrolled 100 patients.")]
        r = run_survey("q", docs, criteria=[], attributes=[SAMPLE_ATTR])
        assert hasattr(r, "synthesis_notes")
        assert isinstance(r.synthesis_notes, list)

    def test_synthesis_notes_mention_discordant_attrs(self):
        """When docs disagree, synthesis notes must mention the contested attribute."""
        docs = [
            Document("a", "A", "This trial enrolled 200 patients sample size was 200."),
            Document("b", "B", "This trial enrolled 50 patients sample size was 50."),
        ]
        r = run_survey("q", docs, criteria=[], attributes=[SAMPLE_ATTR])
        combined = " ".join(r.synthesis_notes).lower()
        assert "sample size" in combined

    def test_synthesis_notes_mention_discordant_count(self):
        """Synthesis notes must mention how many attributes are contested."""
        docs = [
            Document("a", "A", "This trial enrolled 200 patients sample size was 200."),
            Document("b", "B", "This trial enrolled 50 patients sample size was 50."),
        ]
        r = run_survey("q", docs, criteria=[], attributes=[SAMPLE_ATTR])
        combined = " ".join(r.synthesis_notes)
        assert "1" in combined  # one contested attribute

    def test_synthesis_notes_no_conflict(self):
        """When there are no conflicts, notes should reflect agreement."""
        docs = [
            Document("a", "A", "The sample size was 200 patients."),
            Document("b", "B", "The sample size was 200 patients."),
        ]
        r = run_survey("q", docs, criteria=[], attributes=[SAMPLE_ATTR])
        combined = " ".join(r.synthesis_notes).lower()
        assert "agree" in combined or "consistent" in combined

    def test_synthesis_notes_survey_surfaces_not_arbitrates(self):
        """Synthesis notes must say survey surfaces, not arbitrate contradictions."""
        docs = [
            Document("a", "A", "This trial enrolled 200 patients sample size was 200."),
            Document("b", "B", "This trial enrolled 50 patients sample size was 50."),
        ]
        r = run_survey("q", docs, criteria=[], attributes=[SAMPLE_ATTR])
        combined = " ".join(r.synthesis_notes).lower()
        # The note should explicitly say "surfaces" or "does not arbitrate".
        assert "surface" in combined or "arbitrat" in combined

    def test_synthesis_notes_deterministic(self):
        """Calling run_survey twice with the same inputs produces identical notes."""
        docs = [
            Document("a", "A", "This trial enrolled 200 patients sample size was 200."),
            Document("b", "B", "This trial enrolled 50 patients sample size was 50."),
        ]
        r1 = run_survey("q", docs, criteria=[], attributes=[SAMPLE_ATTR])
        r2 = run_survey("q", docs, criteria=[], attributes=[SAMPLE_ATTR])
        assert r1.synthesis_notes == r2.synthesis_notes

    def test_synthesis_notes_empty_rows_no_crash(self):
        """No rows (all excluded) produces synthesis notes without crashing."""
        docs = [Document("x", "Editorial", "This editorial argues something.")]
        crits = [ScreeningCriterion("no editorial", keywords=("editorial",), exclude=True)]
        r = run_survey("q", docs, crits, [SAMPLE_ATTR])
        assert r.rows == []
        assert isinstance(r.synthesis_notes, list)


# ---------------------------------------------------------------------------
# Backward-compatibility: existing fields still work
# ---------------------------------------------------------------------------

class TestBackwardCompatibility:
    """Existing SurveyReport, EvidenceCell, PrismaFlow fields must still work."""

    def test_evidence_cell_existing_fields_unchanged(self):
        docs = [Document("a", "A", "The trial enrolled 100 patients.")]
        r = run_survey("q", docs, criteria=[], attributes=[SAMPLE_ATTR])
        cell = r.rows[0].cells[0]
        assert hasattr(cell, "attribute")
        assert hasattr(cell, "value")
        assert hasattr(cell, "citation_chunk_ids")
        assert hasattr(cell, "entailment_score")
        assert hasattr(cell, "entailed")

    def test_prisma_existing_fields_unchanged(self):
        docs = [Document("a", "A", "The trial enrolled 100 patients.")]
        r = run_survey("q", docs, criteria=[], attributes=[SAMPLE_ATTR])
        p = r.prisma
        assert hasattr(p, "identified")
        assert hasattr(p, "screened")
        assert hasattr(p, "included")
        assert hasattr(p, "excluded")
        assert hasattr(p, "excluded_reasons")

    def test_run_survey_signature_stable(self):
        """run_survey must accept its existing positional + keyword args."""
        import inspect

        from lighthouse_ai.modes.survey import run_survey as _rs
        sig = inspect.signature(_rs)
        params = list(sig.parameters)
        assert "question" in params
        assert "documents" in params
        assert "criteria" in params
        assert "attributes" in params
        assert "gateway" in params
        assert "job_id" in params
        assert "gate" in params
        assert "positions_db" in params
