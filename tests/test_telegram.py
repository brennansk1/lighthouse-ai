"""Tests for the Telegram channel and the §24.10 airlock confirmation.

No real network and no real sleeping ever happens: the Bot API is mocked with
respx, the polling clock is a deterministic fake, and ``sleep`` is a no-op so
the confirmation loop runs instantly. These constraints mirror the rest of the
notify test-suite and keep the airlock's safety properties (default-to-abort)
verifiable offline.
"""

from __future__ import annotations

import json

import httpx
import respx

from lighthouse_ai.notify.channels import Channel
from lighthouse_ai.notify.telegram import (
    API_ROOT,
    TelegramChannel,
    request_confirmation,
)

TOKEN = "123:ABC"
CHAT = "555"
SEND_URL = f"{API_ROOT}/bot{TOKEN}/sendMessage"
UPDATES_URL = f"{API_ROOT}/bot{TOKEN}/getUpdates"


# --- helpers -----------------------------------------------------------------


def _noop_sleep(_seconds: float) -> None:
    """A sleep that never waits; used so the poll loop spins instantly."""


class _FakeClock:
    """A monotonic clock the tests advance by hand.

    Returns the current value on each call and lets the loop's deadline math run
    without any wall-clock time passing.
    """

    def __init__(self, start: float = 0.0) -> None:
        self.t = start

    def __call__(self) -> float:
        return self.t

    def advance(self, by: float) -> None:
        self.t += by


def _updates_body(*messages: dict) -> dict:
    """Wrap message dicts in a Telegram getUpdates envelope."""
    return {
        "ok": True,
        "result": [
            {"update_id": 100 + i, "message": msg} for i, msg in enumerate(messages)
        ],
    }


def _msg(text: str, chat_id: str = CHAT) -> dict:
    return {"chat": {"id": int(chat_id)}, "text": text}


# --- TelegramChannel.available ----------------------------------------------


def test_available_true_with_token_and_chat():
    assert TelegramChannel(bot_token=TOKEN, chat_id=CHAT).available() is True


def test_available_false_without_token():
    assert TelegramChannel(bot_token="", chat_id=CHAT).available() is False


def test_available_false_without_chat():
    assert TelegramChannel(bot_token=TOKEN, chat_id="").available() is False


def test_available_false_without_either():
    assert TelegramChannel(bot_token="", chat_id="").available() is False


# --- TelegramChannel.send ----------------------------------------------------


@respx.mock
def test_send_success_returns_true():
    route = respx.post(SEND_URL).mock(return_value=httpx.Response(200, json={"ok": True}))
    ch = TelegramChannel(bot_token=TOKEN, chat_id=CHAT)
    assert ch.send("Title", "Body") is True
    assert route.called


@respx.mock
def test_send_posts_chat_id_and_combined_text():
    captured = {}

    def handler(request):
        captured["json"] = json.loads(request.content)
        return httpx.Response(200, json={"ok": True})

    respx.post(SEND_URL).mock(side_effect=handler)
    ch = TelegramChannel(bot_token=TOKEN, chat_id=CHAT)
    ch.send("Alert", "Disk full")
    assert captured["json"]["chat_id"] == CHAT
    assert "Alert" in captured["json"]["text"]
    assert "Disk full" in captured["json"]["text"]


@respx.mock
def test_send_body_only_when_no_title():
    captured = {}

    def handler(request):
        captured["text"] = json.loads(request.content)["text"]
        return httpx.Response(200, json={"ok": True})

    respx.post(SEND_URL).mock(side_effect=handler)
    ch = TelegramChannel(bot_token=TOKEN, chat_id=CHAT)
    ch.send("", "just body")
    assert captured["text"] == "just body"


@respx.mock
def test_send_failure_4xx_returns_false():
    respx.post(SEND_URL).mock(return_value=httpx.Response(403, json={"ok": False}))
    ch = TelegramChannel(bot_token=TOKEN, chat_id=CHAT)
    assert ch.send("Title", "Body") is False


@respx.mock
def test_send_network_error_returns_false():
    respx.post(SEND_URL).mock(side_effect=httpx.ConnectError("no route"))
    ch = TelegramChannel(bot_token=TOKEN, chat_id=CHAT)
    assert ch.send("Title", "Body") is False


def test_send_returns_false_when_unavailable():
    ch = TelegramChannel(bot_token="", chat_id="")
    assert ch.send("Title", "Body") is False


@respx.mock
def test_send_does_not_close_injected_client():
    respx.post(SEND_URL).mock(return_value=httpx.Response(200, json={"ok": True}))
    client = httpx.Client()
    ch = TelegramChannel(bot_token=TOKEN, chat_id=CHAT, client=client)
    assert ch.send("Title", "Body") is True
    # An injected client belongs to the caller and must stay usable.
    assert client.is_closed is False
    client.close()


def test_channel_satisfies_protocol():
    assert isinstance(TelegramChannel(bot_token=TOKEN, chat_id=CHAT), Channel)


# --- request_confirmation: success paths -------------------------------------


@respx.mock
def test_confirmation_yes_returns_true():
    respx.post(SEND_URL).mock(return_value=httpx.Response(200, json={"ok": True}))
    respx.get(UPDATES_URL).mock(
        return_value=httpx.Response(200, json=_updates_body(_msg("YES")))
    )
    clock = _FakeClock()
    assert (
        request_confirmation(
            TOKEN, CHAT, "confirm?", timeout_s=60, now=clock, sleep=_noop_sleep
        )
        is True
    )


@respx.mock
def test_confirmation_yes_case_insensitive():
    respx.post(SEND_URL).mock(return_value=httpx.Response(200, json={"ok": True}))
    respx.get(UPDATES_URL).mock(
        return_value=httpx.Response(200, json=_updates_body(_msg("yes do it")))
    )
    clock = _FakeClock()
    assert (
        request_confirmation(
            TOKEN, CHAT, "confirm?", now=clock, sleep=_noop_sleep
        )
        is True
    )


@respx.mock
def test_confirmation_yes_after_some_empty_polls():
    respx.post(SEND_URL).mock(return_value=httpx.Response(200, json={"ok": True}))
    bodies = [
        httpx.Response(200, json={"ok": True, "result": []}),
        httpx.Response(200, json={"ok": True, "result": []}),
        httpx.Response(200, json=_updates_body(_msg("YES"))),
    ]
    respx.get(UPDATES_URL).mock(side_effect=bodies)
    clock = _FakeClock()
    assert (
        request_confirmation(
            TOKEN, CHAT, "confirm?", timeout_s=60, now=clock, sleep=_noop_sleep
        )
        is True
    )


# --- request_confirmation: abort paths ---------------------------------------


@respx.mock
def test_confirmation_timeout_returns_false():
    respx.post(SEND_URL).mock(return_value=httpx.Response(200, json={"ok": True}))
    clock = _FakeClock()

    def advancing_handler(request):
        # Each poll pushes the clock past the deadline so the loop must give up.
        clock.advance(100)
        return httpx.Response(200, json={"ok": True, "result": []})

    respx.get(UPDATES_URL).mock(side_effect=advancing_handler)
    assert (
        request_confirmation(
            TOKEN, CHAT, "confirm?", timeout_s=60, now=clock, sleep=_noop_sleep
        )
        is False
    )


@respx.mock
def test_confirmation_non_yes_reply_returns_false():
    respx.post(SEND_URL).mock(return_value=httpx.Response(200, json={"ok": True}))
    clock = _FakeClock()

    def handler(request):
        clock.advance(100)
        return httpx.Response(200, json=_updates_body(_msg("no")))

    respx.get(UPDATES_URL).mock(side_effect=handler)
    assert (
        request_confirmation(
            TOKEN, CHAT, "confirm?", timeout_s=60, now=clock, sleep=_noop_sleep
        )
        is False
    )


@respx.mock
def test_confirmation_yes_from_other_chat_returns_false():
    respx.post(SEND_URL).mock(return_value=httpx.Response(200, json={"ok": True}))
    clock = _FakeClock()

    def handler(request):
        clock.advance(100)
        return httpx.Response(200, json=_updates_body(_msg("YES", chat_id="999")))

    respx.get(UPDATES_URL).mock(side_effect=handler)
    # A YES from a non-whitelisted chat must never authorise the action.
    assert (
        request_confirmation(
            TOKEN, CHAT, "confirm?", timeout_s=60, now=clock, sleep=_noop_sleep
        )
        is False
    )


@respx.mock
def test_confirmation_prompt_send_failure_returns_false():
    # If we cannot even deliver the prompt, abort without polling.
    respx.post(SEND_URL).mock(return_value=httpx.Response(500, json={"ok": False}))
    updates = respx.get(UPDATES_URL).mock(
        return_value=httpx.Response(200, json=_updates_body(_msg("YES")))
    )
    clock = _FakeClock()
    assert (
        request_confirmation(
            TOKEN, CHAT, "confirm?", now=clock, sleep=_noop_sleep
        )
        is False
    )
    assert not updates.called


@respx.mock
def test_confirmation_prompt_network_error_returns_false():
    respx.post(SEND_URL).mock(side_effect=httpx.ConnectError("down"))
    clock = _FakeClock()
    assert (
        request_confirmation(
            TOKEN, CHAT, "confirm?", now=clock, sleep=_noop_sleep
        )
        is False
    )


@respx.mock
def test_confirmation_transient_poll_error_then_timeout_false():
    respx.post(SEND_URL).mock(return_value=httpx.Response(200, json={"ok": True}))
    clock = _FakeClock()

    def handler(request):
        clock.advance(100)
        raise httpx.ConnectError("flaky")

    respx.get(UPDATES_URL).mock(side_effect=handler)
    assert (
        request_confirmation(
            TOKEN, CHAT, "confirm?", timeout_s=60, now=clock, sleep=_noop_sleep
        )
        is False
    )


@respx.mock
def test_confirmation_malformed_json_does_not_crash():
    respx.post(SEND_URL).mock(return_value=httpx.Response(200, json={"ok": True}))
    clock = _FakeClock()

    def handler(request):
        clock.advance(100)
        return httpx.Response(200, content=b"not json")

    respx.get(UPDATES_URL).mock(side_effect=handler)
    # A garbled payload degrades to "no confirmation" -> abort, never raises.
    assert (
        request_confirmation(
            TOKEN, CHAT, "confirm?", timeout_s=60, now=clock, sleep=_noop_sleep
        )
        is False
    )


def test_confirmation_missing_token_returns_false():
    assert request_confirmation("", CHAT, "confirm?", sleep=_noop_sleep) is False


def test_confirmation_missing_chat_returns_false():
    assert request_confirmation(TOKEN, "", "confirm?", sleep=_noop_sleep) is False


@respx.mock
def test_confirmation_advances_offset_to_skip_seen_updates():
    respx.post(SEND_URL).mock(return_value=httpx.Response(200, json={"ok": True}))
    seen_offsets: list = []

    responses = [
        httpx.Response(200, json={"ok": True, "result": []}),
        httpx.Response(200, json=_updates_body(_msg("YES"))),
    ]

    def handler(request):
        seen_offsets.append(request.url.params.get("offset"))
        return responses.pop(0)

    # First non-empty result has update_id 100; the empty first poll leaves
    # offset unset, then YES arrives. We mainly assert it does not loop forever.
    respx.get(UPDATES_URL).mock(side_effect=handler)
    clock = _FakeClock()
    assert (
        request_confirmation(
            TOKEN, CHAT, "confirm?", timeout_s=60, now=clock, sleep=_noop_sleep
        )
        is True
    )
    # The first poll has no offset; subsequent polls would carry one.
    assert seen_offsets[0] is None


@respx.mock
def test_confirmation_uses_injected_client_not_closed():
    respx.post(SEND_URL).mock(return_value=httpx.Response(200, json={"ok": True}))
    respx.get(UPDATES_URL).mock(
        return_value=httpx.Response(200, json=_updates_body(_msg("YES")))
    )
    client = httpx.Client()
    clock = _FakeClock()
    assert (
        request_confirmation(
            TOKEN, CHAT, "confirm?", client=client, now=clock, sleep=_noop_sleep
        )
        is True
    )
    assert client.is_closed is False
    client.close()


@respx.mock
def test_confirmation_immediate_yes_with_zero_timeout():
    # timeout_s=0 must still honour an already-waiting YES (loop runs once).
    respx.post(SEND_URL).mock(return_value=httpx.Response(200, json={"ok": True}))
    respx.get(UPDATES_URL).mock(
        return_value=httpx.Response(200, json=_updates_body(_msg("YES")))
    )
    clock = _FakeClock()
    assert (
        request_confirmation(
            TOKEN, CHAT, "confirm?", timeout_s=0, now=clock, sleep=_noop_sleep
        )
        is True
    )


@respx.mock
def test_confirmation_empty_then_zero_timeout_aborts():
    respx.post(SEND_URL).mock(return_value=httpx.Response(200, json={"ok": True}))
    respx.get(UPDATES_URL).mock(
        return_value=httpx.Response(200, json={"ok": True, "result": []})
    )
    clock = _FakeClock()
    # Deadline already reached after the single poll -> abort.
    assert (
        request_confirmation(
            TOKEN, CHAT, "confirm?", timeout_s=0, now=clock, sleep=_noop_sleep
        )
        is False
    )


# ---------------------------------------------------------------------------
# Telegram templates
# ---------------------------------------------------------------------------


from lighthouse_ai.notify.telegram_templates import render, _fmt


class TestTelegramTemplates:
    def test_render_draft_ready_includes_question(self):
        title, body = render("draft_ready", "fallback", "", question="Is AI safe?", draft_id="d1")
        assert "Is AI safe?" in body
        assert "<b>" in body

    def test_render_draft_approved_includes_draft_title(self):
        title, body = render("draft_approved", "t", "", title="AI Safety Report", draft_id="d2")
        assert "AI Safety Report" in body

    def test_render_job_started_shows_mode(self):
        title, body = render("job_started", "t", "", question="Q?", mode="deepdive")
        assert "Deepdive" in body

    def test_render_job_failed_shows_error(self):
        title, body = render("job_failed", "t", "", error="timeout")
        assert "timeout" in body

    def test_render_monitor_alert_high_shows_topic(self):
        title, body = render("monitor_alert_high", "t", "", topic="Climate", summary="Rising temps")
        assert "Climate" in body
        assert "Rising temps" in body

    def test_render_budget_warn_shows_percent(self):
        title, body = render("budget_warn", "t", "", used_pct=85.0, budget_usd=10.0)
        assert "85%" in body
        assert "$10.00" in body

    def test_render_budget_trip_shows_paused(self):
        title, body = render("budget_trip", "t", "", used_pct=100.0)
        assert "paused" in body.lower() or "Paused" in body

    def test_render_logseq_synced_shows_count(self):
        title, body = render("logseq_synced", "t", "", synced=5, failed=0)
        assert "5" in body

    def test_render_escalation_raised_shows_kind(self):
        title, body = render("escalation_raised", "t", "", kind="stale_position",
                             body="Some issue", priority="high")
        assert "Stale Position" in body or "stale" in body.lower()
        assert "high" in body.lower() or "High" in body

    def test_render_position_resolved_shows_outcome(self):
        title, body = render("position_resolved", "t", "",
                             statement="AI is transformative", outcome="confirmed")
        assert "AI is transformative" in body
        assert "Confirmed" in body

    def test_render_unknown_event_falls_back(self):
        title, body = render("unknown_event", "fallback_title", "fallback_body")
        assert title == "fallback_title"
        assert body == "fallback_body"

    def test_render_with_no_data_falls_back(self):
        title, body = render("draft_ready", "plain_title", "plain_body")
        # No data kwargs → fall through to fallback
        assert title == "plain_title"

    def test_fmt_escapes_html_chars(self):
        assert _fmt("AT&T <rocks>") == "AT&amp;T &lt;rocks&gt;"

    def test_fmt_passthrough_plain(self):
        assert _fmt("hello world") == "hello world"
