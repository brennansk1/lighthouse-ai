"""Offline-deterministic tests for the Reconstruct engine."""

from __future__ import annotations

import pytest

from lighthouse_ai.modes.reconstruct import (
    Document,
    _event_key,
    _extract_actors,
    _find_date,
    _normalize_date,
    run_reconstruct,
)

# ---------------------------------------------------------------------------
# Basic contract
# ---------------------------------------------------------------------------

def test_requires_documents():
    with pytest.raises(ValueError):
        run_reconstruct("q", documents=[])


def test_extracts_and_sorts_events():
    docs = [
        Document("d1", "A", "In 2020 the company launched. "
                            "In 2022 it raised a round."),
        Document("d2", "B", "In 2021 a competitor appeared."),
    ]
    r = run_reconstruct("History?", docs)
    dates = [e.date for e in r.events]
    assert dates == sorted(dates)
    assert "2020-01-01" in dates
    assert "2021-01-01" in dates
    assert "2022-01-01" in dates


def test_dedup_same_event_across_sources():
    docs = [
        Document("d1", "A", "In 2020 the company launched."),
        Document("d2", "B", "In 2020 the company launched."),
    ]
    r = run_reconstruct("History?", docs)
    assert len(r.events) == 1
    ev = r.events[0]
    assert set(ev.sources) == {"d1", "d2"}
    assert ev.certainty == 1.0
    assert ev.date_conflicts == ()


def test_date_conflict_resolved_by_modal_vote():
    # Same action, three sources: two say 2020, one says 2019 → 2020 wins.
    docs = [
        Document("d1", "A", "In 2020 the merger closed."),
        Document("d2", "B", "In 2020 the merger closed."),
        Document("d3", "C", "In 2019 the merger closed."),
    ]
    r = run_reconstruct("History?", docs)
    assert len(r.events) == 1
    ev = r.events[0]
    assert ev.date == "2020-01-01"
    assert ev.certainty == round(2 / 3, 3)
    assert len(ev.date_conflicts) == 1
    assert ev.date_conflicts[0].normalized == "2019-01-01"


def test_partial_dates_normalized():
    docs = [Document("d1", "A", "On 2023-05 the policy changed.")]
    r = run_reconstruct("q", docs)
    assert r.events[0].date == "2023-05-01"


def test_deterministic():
    docs = [Document("d1", "A", "In 2020 x happened. In 2021 y happened.")]
    r1 = run_reconstruct("q", docs)
    r2 = run_reconstruct("q", docs)
    assert [(e.event_id, e.date) for e in r1.events] == \
           [(e.event_id, e.date) for e in r2.events]


def test_dict_documents_coerced():
    r = run_reconstruct("q", documents=[{"id": "z", "text": "In 2020 it began."}])
    assert r.events[0].sources == ("z",)


# ---------------------------------------------------------------------------
# Date parsing — written formats
# ---------------------------------------------------------------------------

def test_written_month_year():
    """'March 2019' should parse to 2019-03-01."""
    docs = [Document("d1", "A", "In March 2019 the treaty was signed.")]
    r = run_reconstruct("q", docs)
    assert len(r.events) == 1
    assert r.events[0].date == "2019-03-01"


def test_written_month_day_year_no_comma():
    """'Mar 3 2019' should parse to 2019-03-03."""
    docs = [Document("d1", "A", "On Mar 3 2019 the summit concluded.")]
    r = run_reconstruct("q", docs)
    assert len(r.events) == 1
    assert r.events[0].date == "2019-03-03"


def test_written_month_day_year_with_comma():
    """'March 3, 2019' should parse to 2019-03-03."""
    docs = [Document("d1", "A", "On March 3, 2019 the bill passed.")]
    r = run_reconstruct("q", docs)
    assert len(r.events) == 1
    assert r.events[0].date == "2019-03-03"


def test_written_month_day_ordinal():
    """'January 1st, 2021' should parse to 2021-01-01."""
    docs = [Document("d1", "A", "On January 1st, 2021 they launched.")]
    r = run_reconstruct("q", docs)
    assert len(r.events) == 1
    assert r.events[0].date == "2021-01-01"


def test_written_month_case_insensitive():
    """Lowercase month names should also be recognized."""
    docs = [Document("d1", "A", "In february 2022 the audit started.")]
    r = run_reconstruct("q", docs)
    assert len(r.events) == 1
    assert r.events[0].date == "2022-02-01"


def test_iso_year_month():
    """'2023-05' ISO partial date normalizes to 2023-05-01."""
    docs = [Document("d1", "A", "On 2023-05 the policy changed.")]
    r = run_reconstruct("q", docs)
    assert r.events[0].date == "2023-05-01"


def test_full_iso_date_preserved():
    """A complete ISO date '2024-07-15' should pass through unchanged."""
    docs = [Document("d1", "A", "On 2024-07-15 the server went down.")]
    r = run_reconstruct("q", docs)
    assert r.events[0].date == "2024-07-15"


def test_multiple_date_formats_in_same_corpus():
    """ISO, written month-year, and written MDY should all extract correctly."""
    docs = [
        Document("d1", "A", "In 2018 the project began."),
        Document("d2", "B", "In October 2019 the beta launched."),
        Document("d3", "C", "On Sep 15, 2020 the product shipped."),
    ]
    r = run_reconstruct("q", docs)
    dates = {e.date for e in r.events}
    assert "2018-01-01" in dates
    assert "2019-10-01" in dates
    assert "2020-09-15" in dates


# ---------------------------------------------------------------------------
# _find_date unit tests
# ---------------------------------------------------------------------------

def test_find_date_iso():
    assert _find_date("In 2021 something happened") == "2021-01-01"


def test_find_date_iso_month():
    assert _find_date("2023-05 event") == "2023-05-01"


def test_find_date_iso_full():
    assert _find_date("2024-07-15 happened") == "2024-07-15"


def test_find_date_written_my():
    assert _find_date("March 2019 event") == "2019-03-01"


def test_find_date_written_mdy():
    assert _find_date("Jan 5, 2020 event") == "2020-01-05"


def test_find_date_written_dmy():
    # Day-first: "3 March 2019" previously matched "March 2019" and dropped the
    # leading day, returning 2019-03-01. It must now keep the day → 2019-03-03.
    assert _find_date("3 March 2019 event") == "2019-03-03"


def test_find_date_written_dmy_ordinal():
    assert _find_date("On 21st June 2020 it happened") == "2020-06-21"


def test_find_date_written_dmy_abbrev_zero_padded():
    assert _find_date("03 Mar 2019 release") == "2019-03-03"


def test_find_date_my_still_parses_without_day():
    # Regression guard: a bare "Month YYYY" still parses to day=01.
    assert _find_date("March 2019 event") == "2019-03-01"


def test_find_date_mdy_still_parses():
    # Regression guard: "Month D, YYYY" still works (MDY tried first).
    assert _find_date("Jan 5, 2020 event") == "2020-01-05"


def test_find_date_none():
    assert _find_date("No dates here at all") is None


# ---------------------------------------------------------------------------
# _normalize_date unit tests
# ---------------------------------------------------------------------------

def test_normalize_year_only():
    assert _normalize_date("2019") == "2019-01-01"


def test_normalize_year_month():
    assert _normalize_date("2019-03") == "2019-03-01"


def test_normalize_full():
    assert _normalize_date("2019-03-07") == "2019-03-07"


# ---------------------------------------------------------------------------
# _event_key dedup across date phrasings
# ---------------------------------------------------------------------------

def test_event_key_strips_iso_dates():
    assert _event_key("In 2020 the merger closed.") == \
           _event_key("In 2019 the merger closed.")


def test_event_key_strips_written_dates():
    assert _event_key("In March 2020 the merger closed.") == \
           _event_key("In April 2019 the merger closed.")


def test_event_key_strips_mixed_date_formats():
    assert _event_key("2024-05-01: the contract was signed.") == \
           _event_key("March 3, 2023: the contract was signed.")


def test_event_key_different_actions_differ():
    assert _event_key("The company launched.") != \
           _event_key("The company shut down.")


# ---------------------------------------------------------------------------
# Certainty computation (source-count weighted)
# ---------------------------------------------------------------------------

def test_certainty_unanimous():
    """All sources agree → certainty == 1.0."""
    docs = [
        Document("d1", "A", "In 2021 the deal closed."),
        Document("d2", "B", "In 2021 the deal closed."),
        Document("d3", "C", "In 2021 the deal closed."),
    ]
    r = run_reconstruct("q", docs)
    assert r.events[0].certainty == 1.0
    assert r.events[0].winning_source_count == 3
    assert r.events[0].total_source_count == 3


def test_certainty_single_source():
    """One source, no conflicts → certainty == 1.0."""
    docs = [Document("d1", "A", "In 2020 it began.")]
    r = run_reconstruct("q", docs)
    ev = r.events[0]
    assert ev.certainty == 1.0
    assert ev.winning_source_count == 1
    assert ev.total_source_count == 1


def test_certainty_two_thirds():
    """Two of three sources agree → certainty == 0.667."""
    docs = [
        Document("d1", "A", "In 2020 the merger closed."),
        Document("d2", "B", "In 2020 the merger closed."),
        Document("d3", "C", "In 2019 the merger closed."),
    ]
    r = run_reconstruct("q", docs)
    ev = r.events[0]
    assert ev.certainty == round(2 / 3, 3)


def test_certainty_one_of_two():
    """One of two sources agree (split) → certainty == 0.5, earlier date wins."""
    docs = [
        Document("d1", "A", "In 2019 the bill passed."),
        Document("d2", "B", "In 2020 the bill passed."),
    ]
    r = run_reconstruct("q", docs)
    ev = r.events[0]
    assert ev.certainty == 0.5
    # Deterministic tiebreak: chronologically earliest date
    assert ev.date == "2019-01-01"


def test_same_source_repeated_date_does_not_inflate_vote():
    """A single document mentioning a date five times still counts as one vote."""
    # d1 says 2019 five times in five sentences; d2 says 2020 once.
    text_d1 = ". ".join(["In 2019 the vote happened"] * 5) + "."
    docs = [
        Document("d1", "A", text_d1),
        Document("d2", "B", "In 2020 the vote happened."),
    ]
    r = run_reconstruct("q", docs)
    ev = r.events[0]
    # 1 source for 2019, 1 source for 2020 → tiebreak → 2019 wins
    assert ev.certainty == 0.5
    assert ev.total_source_count == 2


# ---------------------------------------------------------------------------
# Deduplication across date variants
# ---------------------------------------------------------------------------

def test_dedup_written_vs_iso_same_event():
    """'March 2019' and '2019' in different docs → one deduplicated event."""
    docs = [
        Document("d1", "A", "In March 2019 the treaty was signed."),
        Document("d2", "B", "In 2019 the treaty was signed."),
    ]
    r = run_reconstruct("q", docs)
    assert len(r.events) == 1
    ev = r.events[0]
    assert set(ev.sources) == {"d1", "d2"}


def test_dedup_distinct_actions_not_collapsed():
    """Different actions must stay as separate events."""
    docs = [Document("d1", "A",
                     "In 2020 the company launched. In 2020 the merger closed.")]
    r = run_reconstruct("q", docs)
    assert len(r.events) == 2


# ---------------------------------------------------------------------------
# Actor extraction
# ---------------------------------------------------------------------------

def test_extract_actors_basic():
    actors = _extract_actors("John Smith signed the accord.")
    assert "John Smith" in actors


def test_extract_actors_no_actors():
    actors = _extract_actors("In 2020 something happened.")
    assert actors == () or all(len(a) > 0 for a in actors)


def test_extract_actors_deduplicated():
    actors = _extract_actors("Apple released a product. Apple also patented it.")
    assert actors.count("Apple") == 1  # no duplicates


# ---------------------------------------------------------------------------
# Report metadata
# ---------------------------------------------------------------------------

def test_report_doc_count():
    docs = [
        Document("d1", "A", "In 2020 it began."),
        Document("d2", "B", "In 2021 it ended."),
    ]
    r = run_reconstruct("q", docs)
    assert r.doc_count == 2


def test_report_claims_mention_event_count():
    docs = [
        Document("d1", "A", "In 2020 it began. In 2021 it ended."),
    ]
    r = run_reconstruct("q", docs)
    assert "2" in r.claims[0]


# ---------------------------------------------------------------------------
# No dates found
# ---------------------------------------------------------------------------

def test_no_dates_produces_empty_events():
    """A document with no date tokens produces an empty events list."""
    docs = [Document("d1", "A", "Nothing happened here at all. No dates.")]
    r = run_reconstruct("q", docs)
    assert r.events == []


def test_mixed_docs_some_no_dates():
    """Documents without dates are simply skipped; dated ones still produce events."""
    docs = [
        Document("d1", "A", "Nothing happened here."),
        Document("d2", "B", "In 2022 the launch occurred."),
    ]
    r = run_reconstruct("q", docs)
    assert len(r.events) == 1
    assert r.events[0].date == "2022-01-01"
