"""Budget/loop-guard notifications: a stopped run pings the user."""

from __future__ import annotations

import lighthouse_ai.notify as notify_pkg
from lighthouse_ai.dispatcher import _is_guard_trip, _notify_budget_trip
from lighthouse_ai.gateway import LoopTripped
from lighthouse_ai.notify import notify_budget_trip


# --- template helper ---------------------------------------------------------
def test_notify_budget_trip_noop_when_disabled():
    assert notify_budget_trip("r", bot_token="x", chat_id="y", enabled=False) is False


def test_notify_budget_trip_noop_when_unaddressable():
    assert notify_budget_trip("r", bot_token="", chat_id="", enabled=True) is False


# --- trip classification -----------------------------------------------------
def test_is_guard_trip_loop_and_budget_true():
    assert _is_guard_trip(LoopTripped("per-job cap reached"))
    assert _is_guard_trip(ValueError("usd monthly would underflow by 3.0"))
    assert _is_guard_trip(RuntimeError("governor tripped"))


def test_is_guard_trip_ordinary_error_false():
    assert not _is_guard_trip(ValueError("parser blew up"))
    assert not _is_guard_trip(KeyError("missing field"))


# --- application-edge wiring -------------------------------------------------
def test_budget_trip_noop_without_config(migrated_paths):
    # No config / notify disabled → silent no-op, never raises.
    _notify_budget_trip(migrated_paths, "usd monthly would underflow")


def test_budget_trip_fires_when_enabled(migrated_paths, monkeypatch):
    migrated_paths.config_file.parent.mkdir(parents=True, exist_ok=True)
    migrated_paths.config_file.write_text(
        '[ui]\nnotify_enabled = true\ntelegram_bot_token = "tok"\ntelegram_chat_id = "chat"\n',
        encoding="utf-8",
    )
    captured = {}

    def _fake(reason, *, bot_token, chat_id, enabled, client=None):
        captured.update(reason=reason, bot_token=bot_token, chat_id=chat_id, enabled=enabled)
        return True

    monkeypatch.setattr(notify_pkg, "notify_budget_trip", _fake)
    _notify_budget_trip(migrated_paths, "tokens daily would underflow by 100")
    assert "underflow" in captured["reason"]
    assert captured["enabled"] is True
    assert captured["bot_token"] == "tok" and captured["chat_id"] == "chat"
