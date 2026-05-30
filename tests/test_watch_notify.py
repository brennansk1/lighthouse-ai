"""Watch-alert notifications: a fired web-monitor trigger pings the user."""

from __future__ import annotations

import lighthouse_ai.notify as notify_pkg
from lighthouse_ai.notify import notify_monitor_alert
from lighthouse_ai.supervisor import _notify_web_alert


def test_notify_monitor_alert_noop_when_disabled():
    assert notify_monitor_alert("t", "b", bot_token="x", chat_id="y", enabled=False) is False


def test_notify_monitor_alert_noop_when_unaddressable():
    assert notify_monitor_alert("t", "b", bot_token="", chat_id="", enabled=True) is False


def test_web_alert_noop_without_config(migrated_paths):
    # No config file (or notify disabled) → silent no-op, never raises.
    _notify_web_alert(migrated_paths, {"name": "Example", "reason": "changed"})


def test_web_alert_fires_when_enabled(migrated_paths, monkeypatch):
    # Write a [ui] config that enables notifications.
    migrated_paths.config_file.parent.mkdir(parents=True, exist_ok=True)
    migrated_paths.config_file.write_text(
        '[ui]\nnotify_enabled = true\n'
        'telegram_bot_token = "tok"\ntelegram_chat_id = "chat"\n',
        encoding="utf-8",
    )
    captured = {}

    def _fake(title, body, *, bot_token, chat_id, enabled, client=None):
        captured.update(title=title, body=body, bot_token=bot_token,
                        chat_id=chat_id, enabled=enabled)
        return True

    monkeypatch.setattr(notify_pkg, "notify_monitor_alert", _fake)
    _notify_web_alert(migrated_paths, {"name": "Example site", "reason": "mentions 'recall'"})
    assert "Example site" in captured["title"]
    assert "recall" in captured["body"]
    assert captured["enabled"] is True
    assert captured["bot_token"] == "tok" and captured["chat_id"] == "chat"
