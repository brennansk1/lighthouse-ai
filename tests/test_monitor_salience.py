"""Zone S — tests for interest-relative salience and cross-source contradiction
escalation in Mode A (Monitor).

All tests are offline-deterministic: no real LLM calls, no datetime.now().
A fake gateway scorer is injected to verify that gateway-backed salience
reranks items by interest relative to the topic rather than by the length+
keyword heuristic.  The contradiction escalation tests verify that items from
different sources that disagree are promoted to category "escalation".
"""

from __future__ import annotations

from datetime import datetime

from lighthouse_ai.modes.monitor import (
    ClassifiedItem,
    MonitorItem,
    MonitorState,
    _escalate_contradictions,
    default_salience,
    make_gateway_salience,
    run_monitor,
)

FIXED_TS = datetime(2026, 5, 29, 12, 0, 0)


# --------------------------------------------------------------------------- #
# Helpers / fakes
# --------------------------------------------------------------------------- #


def _item(url: str, title: str, body: str, source: str = "src") -> MonitorItem:
    return MonitorItem(source=source, url=url, title=title, body=body)


class _FakeCompletionResponse:
    def __init__(self, text: str) -> None:
        self.text = text


class _FakeGateway:
    """Minimal stub that returns interest-based scores deterministically.

    Score is 0.9 when the item title (extracted from the "Item title:" line in
    the prompt) contains the interest keyword, else 0.1.  This lets tests verify
    that gateway scoring reranks items by topic interest rather than by
    length/keyword heuristics.
    """

    def __init__(self, interest_keyword: str = "policy") -> None:
        self._kw = interest_keyword
        self.calls: list[str] = []

    def complete(self, role: str, prompt: str, *, job_id: str | None = None):
        self.calls.append(role)
        # Extract the title line to score only the item title, not the interests string.
        import re

        title_match = re.search(r"Item title:\s*(.+)", prompt)
        title = title_match.group(1).strip() if title_match else ""
        score = 0.9 if self._kw.lower() in title.lower() else 0.1
        category = "alert" if score >= 0.7 else "noise"
        import json

        return _FakeCompletionResponse(json.dumps({"score": score, "category": category}))


class _BrokenGateway:
    """A gateway that always raises — used to verify fallback to default_salience."""

    def complete(self, role: str, prompt: str, *, job_id: str | None = None):
        raise RuntimeError("backend down")


# --------------------------------------------------------------------------- #
# make_gateway_salience
# --------------------------------------------------------------------------- #


def test_gateway_salience_high_score_for_matching_interest():
    gw = _FakeGateway(interest_keyword="policy")
    scorer = make_gateway_salience(gw, "AI regulation, EU AI Act, policy")
    item = _item("u1", "Major AI policy overhaul announced", "Long body " * 20)
    score, category = scorer(item)
    assert score >= 0.7, "gateway scorer should return high score for matching interest"
    assert category == "alert"


def test_gateway_salience_low_score_for_off_topic():
    gw = _FakeGateway(interest_keyword="policy")
    scorer = make_gateway_salience(gw, "AI regulation, EU AI Act, policy")
    item = _item("u2", "New cat video uploaded", "Cats playing " * 20)
    score, category = scorer(item)
    assert score < 0.5, "gateway scorer should return low score for off-topic item"
    assert category == "noise"


def test_gateway_salience_falls_back_on_error():
    """When the gateway raises, make_gateway_salience falls back to default_salience."""
    scorer = make_gateway_salience(_BrokenGateway(), "policy topics")
    # Use a long "breaking" item — default_salience should fire.
    item = _item("u3", "x", "breaking major development " + "word " * 50)
    heuristic_score, heuristic_cat = default_salience(item)
    score, category = scorer(item)
    # The fallback should match the heuristic exactly.
    assert score == heuristic_score
    assert category == heuristic_cat


def test_gateway_salience_uses_aux_context_role():
    gw = _FakeGateway()
    scorer = make_gateway_salience(gw, "quantum computing", job_id="test-job")
    scorer(_item("u4", "quantum research", "body"))
    assert gw.calls == ["aux_context"]


def test_gateway_salience_clamps_score_to_0_1():
    """Even if the model returns an out-of-range value, score is clamped."""

    class _OutOfRangeGateway:
        def complete(self, role, prompt, *, job_id=None):
            return _FakeCompletionResponse('{"score": 999.9, "category": "alert"}')

    scorer = make_gateway_salience(_OutOfRangeGateway(), "anything")
    score, _ = scorer(_item("u5", "x", "y"))
    assert 0.0 <= score <= 1.0


# --------------------------------------------------------------------------- #
# run_monitor: gateway path reranks vs heuristic
# --------------------------------------------------------------------------- #


def test_run_monitor_gateway_scorer_reranks_by_interest():
    """Gateway-backed salience should put the on-topic item first."""
    gw = _FakeGateway(interest_keyword="policy")
    items = [
        _item("https://a/1", "Cats and dogs video", "Short off-topic body."),
        _item("https://a/2", "Major AI policy change", "Long important policy body " * 10),
    ]
    report = run_monitor(
        "AI policy",
        items,
        gateway=gw,
        topic_interests="AI regulation, EU AI Act, policy",
    )
    # The policy item should score higher (alert territory).
    # At least one item should be an alert (score >= 0.7 from the fake gateway).
    assert any(c.item.url == "https://a/2" for c in report.alerts), (
        "on-topic item should be promoted to alert by gateway salience"
    )


def test_run_monitor_without_gateway_uses_heuristic():
    """When gateway=None the heuristic is unchanged."""
    items = [
        _item("https://x/1", "Breaking news", "breaking " + "word " * 30),
    ]
    report = run_monitor("test", items)
    assert report.alerts or report.digest  # something was processed


def test_run_monitor_explicit_salience_fn_takes_precedence():
    """An explicitly supplied salience_fn is honoured even when gateway is present."""
    gw = _FakeGateway(interest_keyword="policy")

    def always_noise(it):
        return (0.0, "noise")

    items = [_item("https://x/1", "AI policy update", "important policy " * 20)]
    report = run_monitor(
        "test",
        items,
        salience_fn=always_noise,  # type: ignore[arg-type]
        gateway=gw,
        topic_interests="policy",
    )
    # Explicit fn returns 0.0 → everything should be in digest, nothing alert.
    assert not report.alerts
    assert len(report.digest) == 1


# --------------------------------------------------------------------------- #
# Cross-source contradiction escalation
# --------------------------------------------------------------------------- #


def test_escalate_contradictions_promotes_disagreeing_sources():
    """Items from different sources with contradicting titles → escalation."""
    # Contradiction detector uses the polarity heuristic (increases vs decreases).
    items = [
        ClassifiedItem(
            item=_item("u1", "Remote work increases team productivity", "body", source="src_a"),
            salience=0.4,
            category="informational",
        ),
        ClassifiedItem(
            item=_item("u2", "Remote work decreases team productivity", "body", source="src_b"),
            salience=0.3,
            category="informational",
        ),
    ]
    result = _escalate_contradictions(items, contradiction_timestamp=FIXED_TS)
    escalated = [c for c in result if c.category == "escalation"]
    # At least one item should be escalated due to the polarity contradiction.
    assert escalated, "contradicting items from different sources should be escalated"


def test_escalate_contradictions_bumps_salience():
    """Escalated items should have salience >= 0.85."""
    items = [
        ClassifiedItem(
            item=_item("u1", "AI increases employment", "body", source="src_a"),
            salience=0.2,
            category="informational",
        ),
        ClassifiedItem(
            item=_item("u2", "AI decreases employment", "body", source="src_b"),
            salience=0.1,
            category="informational",
        ),
    ]
    result = _escalate_contradictions(items, contradiction_timestamp=FIXED_TS)
    for c in result:
        if c.category == "escalation":
            assert c.salience >= 0.85


def test_escalate_contradictions_no_op_when_no_disagreement():
    """Items that agree should not be escalated."""
    items = [
        ClassifiedItem(
            item=_item("u1", "Quantum computers are useful", "body", source="src_a"),
            salience=0.4,
            category="informational",
        ),
        ClassifiedItem(
            item=_item("u2", "Quantum computers are valuable tools", "body", source="src_b"),
            salience=0.4,
            category="informational",
        ),
    ]
    result = _escalate_contradictions(items, contradiction_timestamp=FIXED_TS)
    escalated = [c for c in result if c.category == "escalation"]
    # Non-contradicting items should remain unchanged.
    assert not escalated


def test_escalate_contradictions_single_item_is_noop():
    items = [
        ClassifiedItem(
            item=_item("u1", "Something interesting", "body", source="src_a"),
            salience=0.5,
            category="informational",
        ),
    ]
    result = _escalate_contradictions(items, contradiction_timestamp=FIXED_TS)
    assert result == items


def test_run_monitor_contradiction_escalation_end_to_end():
    """run_monitor with contradiction_timestamp fires the escalation hook."""
    items = [
        _item(
            "https://a/1",
            "Remote work increases team productivity",
            "body about productivity",
            source="source_a",
        ),
        _item(
            "https://a/2",
            "Remote work decreases team productivity",
            "body about productivity",
            source="source_b",
        ),
    ]
    report = run_monitor(
        "remote work",
        items,
        contradiction_timestamp=FIXED_TS,
    )
    all_classified = report.alerts + report.digest
    escalated = [c for c in all_classified if c.category == "escalation"]
    assert escalated, "contradicting items from different sources should be escalated"


def test_run_monitor_no_escalation_without_timestamp():
    """Without contradiction_timestamp the escalation step is skipped."""
    items = [
        _item("https://a/1", "Remote work increases team productivity", "body", source="source_a"),
        _item("https://a/2", "Remote work decreases team productivity", "body", source="source_b"),
    ]
    report = run_monitor("remote work", items)  # no contradiction_timestamp
    all_classified = report.alerts + report.digest
    escalated = [c for c in all_classified if c.category == "escalation"]
    assert not escalated, "no escalation when contradiction_timestamp is not supplied"


def test_run_monitor_escalation_can_be_disabled():
    items = [
        _item("https://a/1", "Remote work increases team productivity", "body", source="source_a"),
        _item("https://a/2", "Remote work decreases team productivity", "body", source="source_b"),
    ]
    report = run_monitor(
        "remote work",
        items,
        contradiction_timestamp=FIXED_TS,
        enable_contradiction_escalation=False,
    )
    all_classified = report.alerts + report.digest
    escalated = [c for c in all_classified if c.category == "escalation"]
    assert not escalated


# --------------------------------------------------------------------------- #
# Signatures remain stable
# --------------------------------------------------------------------------- #


def test_default_salience_signature_stable():
    """default_salience(item) -> (float, str) — no extra args required."""
    item = _item("u", "title", "body")
    result = default_salience(item)
    assert isinstance(result, tuple) and len(result) == 2
    assert isinstance(result[0], float)
    assert isinstance(result[1], str)


def test_run_monitor_existing_signature_still_works():
    """Existing callers with no new args are unaffected."""
    items = [_item("https://x/1", "Breaking development", "breaking " + "word " * 30)]
    state = MonitorState()
    report = run_monitor("topic", items, state=state)
    assert report.total_seen == 1


# --------------------------------------------------------------------------- #
# Hotness-backed salience (make_hotness_salience)
# --------------------------------------------------------------------------- #


def test_hotness_salience_custom_extractor_untracked_entity_is_noise():
    """A custom extractor returning only entities NOT in ``tracked`` must not
    crash with ``max() arg is an empty sequence``.

    Regression: the ``e in tracked`` filter inside ``max(...)`` could empty the
    sequence while ``mentioned`` itself was non-empty, raising ValueError. Such
    items carry no tracked hotness signal and must score 0.0 / "noise".
    """
    from lighthouse_ai.modes.monitor import make_hotness_salience

    sal = make_hotness_salience({}, extract_entities=lambda it: ["ghost"], now_ms=0)
    score, category = sal(_item("u", "title", "body"))
    assert score == 0.0
    assert category == "noise"


def test_hotness_salience_mixed_tracked_and_untracked():
    """When the extractor returns a mix, only tracked entities drive the score;
    untracked ones are ignored, not crash-inducing."""
    from lighthouse_ai.compounding.hotness import EntityStats
    from lighthouse_ai.modes.monitor import make_hotness_salience

    tracked = {
        "alpha": EntityStats(
            mention_count_30d=50, distinct_sources=8, last_seen_ms=0, query_hits_30d=10
        ),
    }
    sal = make_hotness_salience(tracked, extract_entities=lambda it: ["alpha", "ghost"], now_ms=0)
    score, category = sal(_item("u", "title", "body"))
    assert 0.0 < score <= 1.0
    assert category in ("alert", "informational")
