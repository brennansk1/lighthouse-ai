"""Tests for the notifications subsystem.

All side effects are faked: no real desktop notification, SMTP socket, or
network request is ever made (Discord uses respx; email uses an injected
sender; desktop uses an injected subprocess runner + ``which`` probe).
"""

from __future__ import annotations

import subprocess
from email.message import EmailMessage

import httpx
import respx

from lighthouse_ai.notify import (
    Channel,
    ChannelResult,
    DesktopChannel,
    DiscordChannel,
    EmailChannel,
    Notifier,
)

# --- helpers -----------------------------------------------------------------


def _fake_runner(returncode: int = 0, record: list | None = None):
    def run(argv, **kwargs):
        if record is not None:
            record.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, returncode, b"", b"")
    return run


def _which_for(*present: str):
    present_set = set(present)
    return lambda name: f"/usr/bin/{name}" if name in present_set else None


# --- DesktopChannel ----------------------------------------------------------


def test_desktop_available_true_when_terminal_notifier_present():
    ch = DesktopChannel(which=_which_for("terminal-notifier"))
    assert ch.available() is True


def test_desktop_available_true_when_notify_send_present():
    ch = DesktopChannel(which=_which_for("notify-send"))
    assert ch.available() is True


def test_desktop_available_false_when_none_present():
    ch = DesktopChannel(which=_which_for())
    assert ch.available() is False


def test_desktop_send_false_when_unavailable():
    record: list = []
    ch = DesktopChannel(which=_which_for(), runner=_fake_runner(record=record))
    assert ch.send("t", "b") is False
    assert record == []  # never spawned anything


def test_desktop_send_terminal_notifier_argv():
    record: list = []
    ch = DesktopChannel(
        which=_which_for("terminal-notifier"),
        runner=_fake_runner(0, record),
    )
    assert ch.send("Title", "Body") is True
    argv = record[0][0]
    assert argv[0] == "terminal-notifier"
    assert "-title" in argv and "Title" in argv
    assert "-message" in argv and "Body" in argv


def test_desktop_send_notify_send_argv():
    record: list = []
    ch = DesktopChannel(
        which=_which_for("notify-send"),
        runner=_fake_runner(0, record),
    )
    assert ch.send("Title", "Body") is True
    argv = record[0][0]
    assert argv == ["notify-send", "Title", "Body"]


def test_desktop_prefers_terminal_notifier_over_notify_send():
    record: list = []
    ch = DesktopChannel(
        which=_which_for("terminal-notifier", "notify-send"),
        runner=_fake_runner(0, record),
    )
    ch.send("t", "b")
    assert record[0][0][0] == "terminal-notifier"


def test_desktop_send_false_on_nonzero_exit():
    ch = DesktopChannel(
        which=_which_for("notify-send"),
        runner=_fake_runner(returncode=1),
    )
    assert ch.send("t", "b") is False


def test_desktop_send_false_on_oserror():
    def boom(argv, **kwargs):
        raise OSError("exec failed")
    ch = DesktopChannel(which=_which_for("notify-send"), runner=boom)
    assert ch.send("t", "b") is False


# --- DiscordChannel ----------------------------------------------------------

WEBHOOK = "https://discord.test/api/webhooks/123/abc"


@respx.mock
def test_discord_send_success_204():
    route = respx.post(WEBHOOK).mock(return_value=httpx.Response(204))
    ch = DiscordChannel(webhook_url=WEBHOOK)
    assert ch.send("Title", "Body") is True
    assert route.called


@respx.mock
def test_discord_send_success_200():
    respx.post(WEBHOOK).mock(return_value=httpx.Response(200, json={"id": "1"}))
    ch = DiscordChannel(webhook_url=WEBHOOK)
    assert ch.send("Title", "Body") is True


@respx.mock
def test_discord_payload_combines_title_and_body():
    captured = {}

    def handler(request):
        captured["json"] = request.content
        return httpx.Response(204)

    respx.post(WEBHOOK).mock(side_effect=handler)
    ch = DiscordChannel(webhook_url=WEBHOOK)
    ch.send("Hello", "World")
    body = captured["json"].decode()
    assert "Hello" in body and "World" in body
    assert "content" in body


@respx.mock
def test_discord_send_false_on_4xx():
    respx.post(WEBHOOK).mock(return_value=httpx.Response(400))
    ch = DiscordChannel(webhook_url=WEBHOOK)
    assert ch.send("t", "b") is False


@respx.mock
def test_discord_send_false_on_transport_error():
    respx.post(WEBHOOK).mock(side_effect=httpx.ConnectError("no route"))
    ch = DiscordChannel(webhook_url=WEBHOOK)
    assert ch.send("t", "b") is False


def test_discord_send_false_on_empty_url():
    ch = DiscordChannel(webhook_url="")
    assert ch.send("t", "b") is False


@respx.mock
def test_discord_uses_injected_client_and_does_not_close_it():
    respx.post(WEBHOOK).mock(return_value=httpx.Response(204))
    client = httpx.Client()
    ch = DiscordChannel(webhook_url=WEBHOOK, client=client)
    assert ch.send("t", "b") is True
    # Injected client must remain usable (not closed by the channel).
    assert client.is_closed is False
    client.close()


# --- EmailChannel ------------------------------------------------------------


def test_email_build_message_headers():
    ch = EmailChannel(
        smtp_host="smtp.test",
        from_addr="from@test",
        to_addrs=["a@test", "b@test"],
    )
    msg = ch.build_message("Subj", "Body text")
    assert isinstance(msg, EmailMessage)
    assert msg["Subject"] == "Subj"
    assert msg["From"] == "from@test"
    assert msg["To"] == "a@test, b@test"
    assert msg.get_content().strip() == "Body text"


def test_email_send_calls_injected_sender():
    captured: list = []

    def fake_sender(message, channel):
        captured.append((message, channel))

    ch = EmailChannel(
        smtp_host="smtp.test",
        from_addr="from@test",
        to_addrs=["a@test"],
        sender=fake_sender,
    )
    assert ch.send("Subj", "Body") is True
    assert len(captured) == 1
    msg, chan = captured[0]
    assert msg["Subject"] == "Subj"
    assert chan is ch


def test_email_send_false_in_airgap(monkeypatch):
    """LIGHTHOUSE_AIRGAP must block SMTP egress before the sender is invoked."""
    monkeypatch.setenv("LIGHTHOUSE_AIRGAP", "1")
    called: list = []
    ch = EmailChannel(
        smtp_host="smtp.test",
        from_addr="from@test",
        to_addrs=["a@test"],
        sender=lambda m, c: called.append(m),
    )
    assert ch.send("Subj", "Body") is False
    assert called == []  # no transport attempted — no socket opened


def test_email_send_false_when_no_recipients():
    sent: list = []
    ch = EmailChannel(
        smtp_host="smtp.test",
        from_addr="from@test",
        to_addrs=[],
        sender=lambda m, c: sent.append(m),
    )
    assert ch.send("t", "b") is False
    assert sent == []


def test_email_send_false_on_oserror():
    def boom(message, channel):
        raise OSError("connection refused")

    ch = EmailChannel(
        smtp_host="smtp.test",
        from_addr="from@test",
        to_addrs=["a@test"],
        sender=boom,
    )
    assert ch.send("t", "b") is False


def test_email_send_false_on_smtp_exception():
    import smtplib

    def boom(message, channel):
        raise smtplib.SMTPException("bad")

    ch = EmailChannel(
        smtp_host="smtp.test",
        from_addr="from@test",
        to_addrs=["a@test"],
        sender=boom,
    )
    assert ch.send("t", "b") is False


# --- Channel protocol --------------------------------------------------------


def test_channels_satisfy_protocol():
    assert isinstance(DesktopChannel(), Channel)
    assert isinstance(DiscordChannel(webhook_url=WEBHOOK), Channel)
    assert isinstance(
        EmailChannel(smtp_host="h", from_addr="f", to_addrs=["t"]), Channel
    )


# --- Notifier dispatcher -----------------------------------------------------


class _RecordingChannel:
    def __init__(self, result: bool = True):
        self.result = result
        self.calls: list[tuple[str, str]] = []

    def send(self, title: str, body: str) -> bool:
        self.calls.append((title, body))
        return self.result


def _config(**overrides):
    base = {
        "desktop_enabled": True,
        "email_enabled": False,
        "discord_webhook_url": "",
        "events": ["draft_ready", "monitor_alert_high"],
    }
    base.update(overrides)
    return base


def test_notifier_sends_to_enabled_channel_for_allowed_event():
    desktop = _RecordingChannel()
    notifier = Notifier(_config(), [("desktop", desktop)])
    results = notifier.notify("draft_ready", "T", "B")
    assert results == [ChannelResult("desktop", attempted=True, delivered=True)]
    assert desktop.calls == [("T", "B")]


def test_notifier_skips_event_not_in_allowlist():
    desktop = _RecordingChannel()
    notifier = Notifier(_config(), [("desktop", desktop)])
    results = notifier.notify("some_unsubscribed_event", "T", "B")
    assert results == [ChannelResult("desktop", attempted=False, delivered=False)]
    assert desktop.calls == []


def test_notifier_skips_disabled_channel():
    email = _RecordingChannel()
    notifier = Notifier(_config(email_enabled=False), [("email", email)])
    results = notifier.notify("draft_ready", "T", "B")
    assert results[0].attempted is False
    assert email.calls == []


def test_notifier_discord_enabled_only_with_webhook_url():
    discord = _RecordingChannel()
    off = Notifier(_config(discord_webhook_url=""), [("discord", discord)])
    assert off.notify("draft_ready", "T", "B")[0].attempted is False

    on = Notifier(_config(discord_webhook_url=WEBHOOK), [("discord", discord)])
    assert on.notify("draft_ready", "T", "B")[0].attempted is True


def test_notifier_reports_delivery_failure():
    desktop = _RecordingChannel(result=False)
    notifier = Notifier(_config(), [("desktop", desktop)])
    result = notifier.notify("draft_ready", "T", "B")[0]
    assert result.attempted is True
    assert result.delivered is False


def test_notifier_fans_out_to_multiple_channels():
    desktop = _RecordingChannel()
    email = _RecordingChannel()
    discord = _RecordingChannel()
    notifier = Notifier(
        _config(email_enabled=True, discord_webhook_url=WEBHOOK),
        [("desktop", desktop), ("email", email), ("discord", discord)],
    )
    results = notifier.notify("monitor_alert_high", "T", "B")
    assert all(r.attempted and r.delivered for r in results)
    assert len(results) == 3


def test_notifier_unknown_channel_enabled_by_default():
    custom = _RecordingChannel()
    notifier = Notifier(_config(), [("telegram", custom)])
    result = notifier.notify("draft_ready", "T", "B")[0]
    assert result.attempted is True


def test_notifier_empty_events_blocks_everything():
    desktop = _RecordingChannel()
    notifier = Notifier(_config(events=[]), [("desktop", desktop)])
    assert notifier.notify("draft_ready", "T", "B")[0].attempted is False


def test_notifier_missing_events_key_blocks_everything():
    desktop = _RecordingChannel()
    cfg = {"desktop_enabled": True}
    notifier = Notifier(cfg, [("desktop", desktop)])
    assert notifier.notify("draft_ready", "T", "B")[0].attempted is False


def test_notifier_events_property():
    notifier = Notifier(_config(), [])
    assert notifier.events == {"draft_ready", "monitor_alert_high"}


def test_notifier_no_channels_returns_empty():
    notifier = Notifier(_config(), [])
    assert notifier.notify("draft_ready", "T", "B") == []


class _RaisingChannel:
    def send(self, title: str, body: str) -> bool:
        raise RuntimeError("channel exploded")


def test_notifier_raising_channel_does_not_block_others():
    # A channel that raises must be isolated: it is reported as a non-delivery
    # and the remaining channels still get their turn (fan-out failure
    # isolation -- one channel down doesn't take the rest with it).
    desktop = _RecordingChannel()
    boom = _RaisingChannel()
    notifier = Notifier(
        _config(email_enabled=True),
        [("email", boom), ("desktop", desktop)],
    )
    results = notifier.notify("draft_ready", "T", "B")
    assert results[0] == ChannelResult("email", attempted=True, delivered=False)
    assert results[1] == ChannelResult("desktop", attempted=True, delivered=True)
    # The healthy channel after the failing one still fired.
    assert desktop.calls == [("T", "B")]
