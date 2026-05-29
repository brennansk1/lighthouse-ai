"""Tests for the per-artifact Telegram templates and the staged-review path.

Two layers under test:

* :func:`render_artifact` is pure — string in, string out — so these assertions
  are plain equality/containment checks on the rendered MarkdownV2, one per
  artifact type, plus the escaping and degrade-gracefully behaviour.
* :func:`notify_artifact_staged` is the effectful wrapper; it is exercised with a
  respx-mocked Bot API (the disabled/unconfigured no-op paths never even build a
  client) so the real network is never touched.
"""

from __future__ import annotations

import json

import httpx
import respx

from lighthouse_ai.notify.telegram import API_ROOT
from lighthouse_ai.notify.templates import (
    escape_md,
    notify_artifact_staged,
    render_artifact,
)

TOKEN = "123:ABC"
CHAT = "555"
SEND_URL = f"{API_ROOT}/bot{TOKEN}/sendMessage"


# --- escape_md ---------------------------------------------------------------


def test_escape_md_escapes_all_specials():
    # Each reserved MarkdownV2 char must be backslash-prefixed.
    assert escape_md("a_b*c[d]") == r"a\_b\*c\[d\]"


def test_escape_md_coerces_none_and_numbers():
    assert escape_md(None) == ""
    assert escape_md(3) == "3"
    assert escape_md(0.5) == "0\\.5"  # the '.' is reserved


# --- render_artifact: matrix (Decide) ----------------------------------------


def test_render_matrix_has_winner_margin_crux():
    body = {"winner": "Option A", "margin": 0.42,
            "crux": "Cost dominates", "runner_up": "Option B"}
    msg = render_artifact("matrix", "Pick a DB", body)
    assert "Winner" in msg and "Option A" in msg
    assert "0\\.42" in msg  # margin (the '.' is MarkdownV2-escaped)
    assert "Crux" in msg and "Cost dominates" in msg


def test_render_matrix_tolerates_missing_fields():
    msg = render_artifact("matrix", "T", {})
    assert "no winner" in msg  # degrades, does not raise


# --- render_artifact: verdict (Adjudicate) -----------------------------------


def test_render_verdict_has_verdict_and_crux():
    body = {
        "judge_summary": "2/3 perspectives agree the claim holds",
        "disputes": ["base rate is too optimistic"],
        "responses": [{"perspective": {"name": "skeptic"}}, {}, {}],
    }
    msg = render_artifact("verdict", "Will X happen?", body)
    assert "Verdict" in msg
    assert "perspectives agree" in msg
    assert "Crux" in msg and "base rate" in msg
    assert "3 perspectives weighed" in msg


def test_render_verdict_prefers_explicit_crux():
    body = {"judge_summary": "summary", "crux": "the real crux",
            "disputes": ["a dispute"], "responses": []}
    msg = render_artifact("verdict", "Q", body)
    assert "the real crux" in msg


# --- render_artifact: report (Investigate) -----------------------------------


def test_render_report_section_count_coverage_top_finding():
    body = {
        "question": "What is X?",
        "sections": [
            {"title": "Background", "body": "X is a thing.",
             "citations": ["c1"], "is_load_bearing": False},
            {"title": "Core", "body": "The load-bearing finding.",
             "citations": ["c2", "c3"], "is_load_bearing": True},
        ],
    }
    msg = render_artifact("report", "Investigation of X", body)
    assert "Sections" in msg and "2" in msg
    assert "Citation coverage" in msg and "100%" in msg  # both sections cited
    # Load-bearing section surfaces as the top finding.
    assert "load\\-bearing finding" in msg


def test_render_report_uses_explicit_citation_coverage():
    body = {"sections": [{"title": "S", "body": "b", "citations": []}],
            "citation_coverage": 0.5}
    msg = render_artifact("report", "T", body)
    assert "50%" in msg


# --- render_artifact: table (Survey) -----------------------------------------


def test_render_table_prisma_counts():
    body = {"prisma": {"identified": 40, "included": 7, "screened": 40, "excluded": 33}}
    msg = render_artifact("table", "Lit review", body)
    assert "included 7 of 40 identified" in msg


# --- render_artifact: timeline (Reconstruct) ---------------------------------


def test_render_timeline_event_count_and_span():
    body = {"events": [
        {"date": "2020-01-01", "action": "start"},
        {"date": "2022-06-15", "action": "milestone"},
        {"date": "2021-03-03", "action": "middle"},
    ]}
    msg = render_artifact("timeline", "History of X", body)
    assert "Events" in msg and "3" in msg
    assert "2020\\-01\\-01" in msg and "2022\\-06\\-15" in msg  # span endpoints


def test_render_timeline_single_date_no_arrow():
    body = {"events": [{"date": "2020-01-01", "action": "only"}]}
    msg = render_artifact("timeline", "T", body)
    assert "→" not in msg


# --- render_artifact: transcript (Ask) ---------------------------------------


def test_render_transcript_question_and_answer():
    body = {
        "topic": "What is the capital of France?",
        "turns": [
            {"role": "user", "text": "What is the capital of France?"},
            {"role": "assistant", "text": "Paris is the capital."},
        ],
    }
    msg = render_artifact("transcript", "Ask", body)
    assert "capital of France" in msg
    assert "Paris is the capital" in msg


# --- render_artifact: digest (Watch) -----------------------------------------


def test_render_digest_item_count_and_top():
    body = {
        "alerts": [{"item": {"title": "Big news", "url": "u1"}, "salience": 0.9}],
        "digest": [{"item": {"title": "Minor note", "url": "u2"}, "salience": 0.3}],
    }
    msg = render_artifact("digest", "My watch", body)
    assert "Items" in msg and "2" in msg
    assert "1 alert" in msg  # singular
    assert "Big news" in msg  # top item is the alert


# --- render_artifact: generic + robustness -----------------------------------


def test_render_unknown_type_degrades_gracefully():
    msg = render_artifact("mystery", "Some title", {"x": 1})
    assert "Staged for review" in msg and "Some title" in msg


def test_render_non_dict_body_does_not_raise():
    assert "T" in render_artifact("matrix", "T", None)
    assert "T" in render_artifact("matrix", "T", ["not", "a", "dict"])


def test_render_escapes_malicious_title():
    # A title with reserved chars must not break / inject markup.
    msg = render_artifact("matrix", "Pick *this* [now]", {"winner": "A"})
    assert "Pick \\*this\\* \\[now\\]" in msg


# --- notify_artifact_staged: disabled / unconfigured no-ops ------------------


def test_notify_disabled_returns_false_and_does_not_send():
    with respx.mock:
        route = respx.post(SEND_URL).mock(return_value=httpx.Response(200, json={"ok": True}))
        sent = notify_artifact_staged(
            "matrix", "T", {"winner": "A"},
            bot_token=TOKEN, chat_id=CHAT, enabled=False,
        )
        assert sent is False
        assert not route.called  # never even attempted


def test_notify_missing_token_returns_false():
    with respx.mock:
        route = respx.post(SEND_URL).mock(return_value=httpx.Response(200, json={"ok": True}))
        sent = notify_artifact_staged(
            "matrix", "T", {"winner": "A"},
            bot_token="", chat_id=CHAT, enabled=True,
        )
        assert sent is False
        assert not route.called


def test_notify_missing_chat_returns_false():
    sent = notify_artifact_staged(
        "matrix", "T", {"winner": "A"},
        bot_token=TOKEN, chat_id="", enabled=True,
    )
    assert sent is False


# --- notify_artifact_staged: enabled path uses the (injected) client ---------


@respx.mock
def test_notify_enabled_sends_rendered_markdownv2():
    captured = {}

    def handler(request):
        captured["json"] = json.loads(request.content)
        return httpx.Response(200, json={"ok": True})

    respx.post(SEND_URL).mock(side_effect=handler)
    sent = notify_artifact_staged(
        "matrix", "Pick a DB",
        {"winner": "Postgres", "margin": 0.3, "crux": "ops cost"},
        bot_token=TOKEN, chat_id=CHAT, enabled=True,
    )
    assert sent is True
    payload = captured["json"]
    assert payload["chat_id"] == CHAT
    assert payload["parse_mode"] == "MarkdownV2"
    assert "Postgres" in payload["text"]
    assert "ops cost" in payload["text"]


@respx.mock
def test_notify_uses_injected_client_no_network():
    # Injecting the client is the seam that keeps tests off the real network.
    respx.post(SEND_URL).mock(return_value=httpx.Response(200, json={"ok": True}))
    client = httpx.Client()
    sent = notify_artifact_staged(
        "digest", "Watch", {"alerts": [], "digest": []},
        bot_token=TOKEN, chat_id=CHAT, enabled=True, client=client,
    )
    assert sent is True
    # An injected client belongs to the caller and must remain open.
    assert client.is_closed is False
    client.close()


@respx.mock
def test_notify_returns_false_on_delivery_failure():
    respx.post(SEND_URL).mock(return_value=httpx.Response(403, json={"ok": False}))
    sent = notify_artifact_staged(
        "matrix", "T", {"winner": "A"},
        bot_token=TOKEN, chat_id=CHAT, enabled=True,
    )
    assert sent is False
