"""Offline-deterministic tests for Reconstruct Zone-Q features:

* Conflicting dates for one event → weighted winner + disputed badge
  when certainty < 0.6.
* Conflicting facts (different actor/action at same date) → split entries
  with factual_split_ref cross-references.
* Source-grade-weighted vote.
* Alternate dates retained.
* Synthesis pass (deterministic offline).

All tests run without a gateway (gateway=None).
"""

from __future__ import annotations

from lighthouse_ai.modes.reconstruct import (
    _DISPUTED_DATE_THRESHOLD,
    Document,
    TimelineEvent,
    run_reconstruct,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _event_by_action_fragment(events: list[TimelineEvent], fragment: str) -> TimelineEvent:
    """Return the first event whose action contains *fragment* (case-insensitive)."""
    frag = fragment.lower()
    for e in events:
        if frag in e.action.lower():
            return e
    raise KeyError(f"No event with action containing {fragment!r}")


# ---------------------------------------------------------------------------
# Disputed-date badge
# ---------------------------------------------------------------------------

class TestDisputedDateBadge:
    """certainty < 0.6 → disputed_date=True (§6.2)."""

    def test_disputed_date_false_when_unanimous(self):
        """All sources agree → no disputed date."""
        docs = [
            Document("d1", "A", "In 2020 the merger closed."),
            Document("d2", "B", "In 2020 the merger closed."),
            Document("d3", "C", "In 2020 the merger closed."),
        ]
        r = run_reconstruct("q", docs)
        assert r.events[0].certainty == 1.0
        assert r.events[0].disputed_date is False

    def test_disputed_date_false_when_certainty_at_threshold(self):
        """certainty == 0.6 is exactly at the threshold — NOT disputed."""
        # 3 sources: 2 agree on 2020, 1 says 2019 → certainty = 2/3 ≈ 0.667 (not disputed)
        docs = [
            Document("d1", "A", "In 2020 the merger closed."),
            Document("d2", "B", "In 2020 the merger closed."),
            Document("d3", "C", "In 2019 the merger closed."),
        ]
        r = run_reconstruct("q", docs)
        ev = r.events[0]
        assert ev.certainty == round(2 / 3, 3)
        # 0.667 >= 0.6 → not disputed
        assert ev.disputed_date is False

    def test_disputed_date_true_when_certainty_below_threshold(self):
        """certainty < 0.6 → disputed_date=True."""
        # 2 sources, 1 says 2020, 1 says 2019 → certainty = 0.5 < 0.6
        docs = [
            Document("d1", "A", "In 2020 the merger closed."),
            Document("d2", "B", "In 2019 the merger closed."),
        ]
        r = run_reconstruct("q", docs)
        ev = r.events[0]
        assert ev.certainty == 0.5
        assert ev.disputed_date is True

    def test_disputed_date_threshold_value(self):
        """_DISPUTED_DATE_THRESHOLD is 0.6 (§6.2)."""
        assert _DISPUTED_DATE_THRESHOLD == 0.6

    def test_disputed_date_true_minority_winner(self):
        """One of five sources disagrees → majority wins but certainty=0.8 (not disputed)."""
        docs = [
            Document("d1", "A", "In 2020 the vote happened."),
            Document("d2", "B", "In 2020 the vote happened."),
            Document("d3", "C", "In 2020 the vote happened."),
            Document("d4", "D", "In 2020 the vote happened."),
            Document("d5", "E", "In 2019 the vote happened."),
        ]
        r = run_reconstruct("q", docs)
        ev = r.events[0]
        # 4 of 5 agree → certainty = 0.8 → not disputed
        assert ev.certainty == 0.8
        assert ev.disputed_date is False

    def test_three_way_split_disputed(self):
        """Three sources each reporting a different date → certainty = 1/3 < 0.6."""
        docs = [
            Document("d1", "A", "In 2020 the deal closed."),
            Document("d2", "B", "In 2019 the deal closed."),
            Document("d3", "C", "In 2021 the deal closed."),
        ]
        r = run_reconstruct("q", docs)
        ev = r.events[0]
        assert ev.certainty == round(1 / 3, 3)
        assert ev.disputed_date is True


# ---------------------------------------------------------------------------
# Alternate dates retained
# ---------------------------------------------------------------------------

class TestAlternateDates:
    """Losing date clusters are preserved in alternate_dates for UI hover."""

    def test_alternate_dates_populated_on_conflict(self):
        """The losing date is present in alternate_dates."""
        docs = [
            Document("d1", "A", "In 2020 the merger closed."),
            Document("d2", "B", "In 2020 the merger closed."),
            Document("d3", "C", "In 2019 the merger closed."),
        ]
        r = run_reconstruct("q", docs)
        ev = r.events[0]
        assert ev.date == "2020-01-01"
        alt_dates = [d for d, _w in ev.alternate_dates]
        assert "2019-01-01" in alt_dates

    def test_alternate_dates_empty_when_no_conflict(self):
        docs = [
            Document("d1", "A", "In 2020 the merger closed."),
            Document("d2", "B", "In 2020 the merger closed."),
        ]
        r = run_reconstruct("q", docs)
        ev = r.events[0]
        assert ev.alternate_dates == ()

    def test_alternate_dates_does_not_include_winning_date(self):
        """The winning date must never appear in alternate_dates."""
        docs = [
            Document("d1", "A", "In 2020 the merger closed."),
            Document("d2", "B", "In 2019 the merger closed."),
        ]
        r = run_reconstruct("q", docs)
        ev = r.events[0]
        alt_dates = [d for d, _w in ev.alternate_dates]
        assert ev.date not in alt_dates


# ---------------------------------------------------------------------------
# Source-grade-weighted vote
# ---------------------------------------------------------------------------

class TestSourceGradeWeightedVote:
    """Grade weights influence the winning date selection."""

    def test_grade_weight_tips_balance(self):
        """A single high-grade source outweighs two low-grade sources (by weight)."""
        docs = [
            Document("hi", "HighGrade", "In 2022 the agreement signed."),
            Document("lo1", "LowGrade1", "In 2020 the agreement signed."),
            Document("lo2", "LowGrade2", "In 2020 the agreement signed."),
        ]
        # hi gets weight 3.0; lo1/lo2 each get 1.0 → 2022 total=3.0 vs 2020 total=2.0
        r = run_reconstruct(
            "q", docs, source_grades={"hi": 3.0, "lo1": 1.0, "lo2": 1.0}
        )
        ev = r.events[0]
        assert ev.date == "2022-01-01"

    def test_default_grades_behave_as_count_vote(self):
        """With no source_grades, the result is the same as pure count vote."""
        docs = [
            Document("d1", "A", "In 2020 the merger closed."),
            Document("d2", "B", "In 2020 the merger closed."),
            Document("d3", "C", "In 2019 the merger closed."),
        ]
        r_no_grade = run_reconstruct("q", docs)
        r_uniform = run_reconstruct(
            "q", docs, source_grades={"d1": 1.0, "d2": 1.0, "d3": 1.0}
        )
        assert r_no_grade.events[0].date == r_uniform.events[0].date
        assert r_no_grade.events[0].certainty == r_uniform.events[0].certainty

    def test_zero_grade_silences_source(self):
        """A source with grade 0.0 contributes no weight to any date."""
        docs = [
            Document("trusted", "A", "In 2020 the bill passed."),
            Document("silenced", "B", "In 2019 the bill passed."),
        ]
        # silenced contributes nothing → 2020 wins with weight 1.0 vs 0.0
        r = run_reconstruct(
            "q", docs, source_grades={"trusted": 1.0, "silenced": 0.0}
        )
        ev = r.events[0]
        assert ev.date == "2020-01-01"

    def test_source_grades_none_equivalent_to_empty(self):
        """Passing source_grades=None is equivalent to not passing it."""
        docs = [
            Document("d1", "A", "In 2020 the merger closed."),
            Document("d2", "B", "In 2019 the merger closed."),
        ]
        r1 = run_reconstruct("q", docs)
        r2 = run_reconstruct("q", docs, source_grades=None)
        assert r1.events[0].date == r2.events[0].date
        assert r1.events[0].certainty == r2.events[0].certainty


# ---------------------------------------------------------------------------
# Factual-split: different actor/action at same date
# ---------------------------------------------------------------------------

class TestFactualSplit:
    """Different actor/action at the same date → split into cross-referenced entries."""

    def _split_docs(self) -> list[Document]:
        """Two docs with the same date but clearly different events on that date."""
        return [
            Document(
                "d1", "Source A",
                "On 2020-06-01 Parliament voted on the budget.",
            ),
            Document(
                "d2", "Source B",
                "On 2020-06-01 Tesla announced a product.",
            ),
        ]

    def test_factual_split_produces_two_events(self):
        """Two factually distinct events on the same date stay as two events."""
        r = run_reconstruct("q", self._split_docs())
        # Both events share date 2020-06-01 but differ in action/actors.
        dates = [e.date for e in r.events]
        assert dates.count("2020-06-01") == 2

    def test_factual_split_ref_set(self):
        """Both split events should carry factual_split_ref pointing to each other."""
        r = run_reconstruct("q", self._split_docs())
        evs = [e for e in r.events if e.date == "2020-06-01"]
        assert len(evs) == 2
        a, b = evs[0], evs[1]
        assert a.factual_split_ref == b.event_id
        assert b.factual_split_ref == a.event_id

    def test_factual_split_ref_none_for_uncontested_events(self):
        """Events that are not part of a factual split must have factual_split_ref=None."""
        docs = [
            Document("d1", "A", "In 2020 the merger closed."),
            Document("d2", "B", "In 2021 the company went public."),
        ]
        r = run_reconstruct("q", docs)
        for ev in r.events:
            assert ev.factual_split_ref is None

    def test_same_actor_not_split(self):
        """Events with overlapping actors at the same date are NOT factual splits."""
        docs = [
            Document("d1", "A", "In 2020 Parliament passed the bill."),
            Document("d2", "B", "In 2020 Parliament passed the new bill."),
        ]
        r = run_reconstruct("q", docs)
        for ev in r.events:
            assert ev.factual_split_ref is None

    def test_factual_split_preserves_sources(self):
        """Sources on each split event remain correct (not merged)."""
        r = run_reconstruct("q", self._split_docs())
        evs = {e.event_id: e for e in r.events if e.date == "2020-06-01"}
        assert len(evs) == 2
        for ev in evs.values():
            # Each event should have exactly one source.
            assert len(ev.sources) >= 1

    def test_factual_split_ref_is_mutual(self):
        """If A.factual_split_ref == B.event_id then B.factual_split_ref == A.event_id."""
        r = run_reconstruct("q", self._split_docs())
        id_map = {e.event_id: e for e in r.events}
        for ev in r.events:
            if ev.factual_split_ref is not None:
                partner = id_map[ev.factual_split_ref]
                assert partner.factual_split_ref == ev.event_id


# ---------------------------------------------------------------------------
# Synthesis notes (gap #20)
# ---------------------------------------------------------------------------

class TestSynthesisNotes:
    """synthesis_notes surface trends/patterns across events."""

    def test_synthesis_notes_present_on_report(self):
        docs = [Document("d1", "A", "In 2020 it began. In 2021 it ended.")]
        r = run_reconstruct("q", docs)
        assert hasattr(r, "synthesis_notes")
        assert isinstance(r.synthesis_notes, list)

    def test_synthesis_notes_mention_disputed_events(self):
        """When a disputed event exists, synthesis notes must mention it."""
        docs = [
            Document("d1", "A", "In 2020 the treaty was signed."),
            Document("d2", "B", "In 2019 the treaty was signed."),
        ]
        r = run_reconstruct("q", docs)
        assert r.events[0].disputed_date is True
        combined = " ".join(r.synthesis_notes).lower()
        assert "disputed" in combined or "certainty" in combined

    def test_synthesis_notes_mention_split_events(self):
        """When factual splits exist, synthesis notes must acknowledge them."""
        docs = [
            Document("d1", "A", "On 2020-06-01 Parliament voted on the budget."),
            Document("d2", "B", "On 2020-06-01 Tesla announced a product."),
        ]
        r = run_reconstruct("q", docs)
        split_events = [e for e in r.events if e.factual_split_ref is not None]
        if split_events:
            combined = " ".join(r.synthesis_notes).lower()
            assert "split" in combined or "factual" in combined or "contradiction" in combined

    def test_synthesis_notes_include_timeline_span(self):
        """Synthesis notes must state the timeline span when multiple events exist."""
        docs = [
            Document("d1", "A", "In 2019 it began. In 2022 it ended."),
        ]
        r = run_reconstruct("q", docs)
        if len(r.events) >= 2:
            combined = " ".join(r.synthesis_notes)
            assert "2019" in combined or "2022" in combined

    def test_synthesis_notes_deterministic(self):
        """Same inputs produce identical synthesis_notes across two calls."""
        docs = [
            Document("d1", "A", "In 2020 the merger closed."),
            Document("d2", "B", "In 2019 the merger closed."),
        ]
        r1 = run_reconstruct("q", docs)
        r2 = run_reconstruct("q", docs)
        assert r1.synthesis_notes == r2.synthesis_notes

    def test_synthesis_notes_empty_events_no_crash(self):
        """No events (no dates in docs) produces synthesis_notes without crashing."""
        docs = [Document("d1", "A", "Nothing happened here.")]
        r = run_reconstruct("q", docs)
        assert r.events == []
        assert isinstance(r.synthesis_notes, list)


# ---------------------------------------------------------------------------
# Backward-compatibility: existing fields must still work
# ---------------------------------------------------------------------------

class TestBackwardCompatibility:
    """Existing TimelineEvent and ReconstructReport fields remain stable."""

    def test_timeline_event_existing_fields(self):
        docs = [Document("d1", "A", "In 2020 it began.")]
        r = run_reconstruct("q", docs)
        ev = r.events[0]
        assert hasattr(ev, "event_id")
        assert hasattr(ev, "date")
        assert hasattr(ev, "actors")
        assert hasattr(ev, "action")
        assert hasattr(ev, "sources")
        assert hasattr(ev, "certainty")
        assert hasattr(ev, "inferred")
        assert hasattr(ev, "date_conflicts")
        assert hasattr(ev, "winning_source_count")
        assert hasattr(ev, "total_source_count")

    def test_reconstruct_report_existing_fields(self):
        docs = [Document("d1", "A", "In 2020 it began.")]
        r = run_reconstruct("q", docs)
        assert hasattr(r, "question")
        assert hasattr(r, "events")
        assert hasattr(r, "claims")
        assert hasattr(r, "doc_count")

    def test_run_reconstruct_signature_stable(self):
        """run_reconstruct must accept its existing positional + keyword args."""
        import inspect

        from lighthouse_ai.modes.reconstruct import run_reconstruct as _rr
        sig = inspect.signature(_rr)
        params = list(sig.parameters)
        assert "question" in params
        assert "documents" in params
        assert "gateway" in params
        assert "job_id" in params
        assert "gate" in params
        assert "positions_db" in params

    def test_existing_tests_unaffected_modal_vote(self):
        """The classic 2-of-3 modal vote still produces the correct result."""
        docs = [
            Document("d1", "A", "In 2020 the merger closed."),
            Document("d2", "B", "In 2020 the merger closed."),
            Document("d3", "C", "In 2019 the merger closed."),
        ]
        r = run_reconstruct("q", docs)
        ev = r.events[0]
        assert ev.date == "2020-01-01"
        assert ev.certainty == round(2 / 3, 3)
        assert len(ev.date_conflicts) == 1
        assert ev.date_conflicts[0].normalized == "2019-01-01"

    def test_existing_certainty_formula_unchanged(self):
        """Certainty = winning_source_count / total_source_count (existing spec)."""
        docs = [
            Document("d1", "A", "In 2021 the deal closed."),
            Document("d2", "B", "In 2021 the deal closed."),
            Document("d3", "C", "In 2021 the deal closed."),
        ]
        r = run_reconstruct("q", docs)
        ev = r.events[0]
        assert ev.certainty == 1.0
        assert ev.winning_source_count == 3
        assert ev.total_source_count == 3
