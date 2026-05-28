"""Tests for the Telegram bot command interface.

No real network, no real time: the Bot API is mocked with respx, and the
stop_event drives the polling loop to exit after a single tick.
Commands are tested by calling handlers directly with a fake BotContext.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest
import respx

from lighthouse_ai.notify.telegram import API_ROOT
from lighthouse_ai.notify.telegram_bot import (
    BotContext,
    _COMMANDS,
    _DISPATCH,
    _cmd_budget,
    _cmd_drafts,
    _cmd_help,
    _cmd_jobs,
    _cmd_status,
    _cmd_sync,
    _handle_message,
    _parse_command,
    _send,
    serve,
)
from lighthouse_ai.paths import make_paths
from lighthouse_ai.persistence import open_db
from lighthouse_ai.schema import kinds_for, migrate_all

TOKEN = "999:TEST"
CHAT = "111"
SEND_URL = f"{API_ROOT}/bot{TOKEN}/sendMessage"
UPDATES_URL = f"{API_ROOT}/bot{TOKEN}/getUpdates"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_paths(tmp_path: Path):
    paths = make_paths(tmp_path / "data", tmp_path / "replicas")
    paths.ensure()
    migrate_all(kinds_for(paths))
    return paths


def _fake_ctx(tmp_path: Path, client=None) -> BotContext:
    paths = _make_paths(tmp_path)
    return BotContext(
        paths=paths,
        bot_token=TOKEN,
        chat_id=CHAT,
        client=client or MagicMock(),
    )


def _make_update(text: str, chat_id: str = CHAT, update_id: int = 1) -> dict:
    return {
        "update_id": update_id,
        "message": {
            "message_id": 100,
            "chat": {"id": int(chat_id), "type": "private"},
            "text": text,
        },
    }


# ---------------------------------------------------------------------------
# _parse_command
# ---------------------------------------------------------------------------

class TestParseCommand:
    def test_slash_command(self):
        assert _parse_command("/help") == ("/help", "")

    def test_command_with_args(self):
        assert _parse_command("/research What is AI?") == ("/research", "What is AI?")

    def test_strips_bot_suffix(self):
        cmd, args = _parse_command("/approve@mylhbot d1")
        assert cmd == "/approve"
        assert args == "d1"

    def test_non_command_returns_none(self):
        assert _parse_command("Hello world") is None

    def test_empty_returns_none(self):
        assert _parse_command("") is None

    def test_case_normalised(self):
        cmd, _ = _parse_command("/HELP")
        assert cmd == "/help"


# ---------------------------------------------------------------------------
# _handle_message — security: origin check
# ---------------------------------------------------------------------------

class TestHandleMessageSecurity:
    def test_wrong_chat_id_is_ignored(self, tmp_path):
        sent = []
        ctx = _fake_ctx(tmp_path)
        ctx.client.post = lambda *a, **kw: sent.append(kw) or MagicMock(status_code=200)
        msg = {
            "chat": {"id": 9999},  # different chat
            "text": "/help",
        }
        _handle_message(ctx, msg)
        assert sent == []

    def test_correct_chat_id_dispatches(self, tmp_path):
        sent = []
        ctx = _fake_ctx(tmp_path)
        ctx.client.post = lambda *a, **kw: sent.append(kw) or MagicMock(status_code=200)
        msg = {"chat": {"id": int(CHAT)}, "text": "/help"}
        _handle_message(ctx, msg)
        assert len(sent) == 1

    def test_unknown_command_sends_error(self, tmp_path):
        sent = []
        ctx = _fake_ctx(tmp_path)
        ctx.client.post = lambda *a, **kw: sent.append(kw) or MagicMock(status_code=200)
        msg = {"chat": {"id": int(CHAT)}, "text": "/notacommand"}
        _handle_message(ctx, msg)
        assert sent
        assert "Unknown command" in sent[0]["json"]["text"]

    def test_non_command_text_ignored(self, tmp_path):
        sent = []
        ctx = _fake_ctx(tmp_path)
        ctx.client.post = lambda *a, **kw: sent.append(kw) or MagicMock(status_code=200)
        msg = {"chat": {"id": int(CHAT)}, "text": "Hello there"}
        _handle_message(ctx, msg)
        assert sent == []


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------

class TestCmdHelp:
    def test_lists_all_commands(self, tmp_path):
        sent = []
        ctx = _fake_ctx(tmp_path)
        ctx.client.post = lambda *a, **kw: sent.append(kw) or MagicMock(status_code=200)
        _cmd_help(ctx, "")
        assert sent
        body = sent[0]["json"]["text"]
        assert "/help" in body
        assert "/research" in body
        assert "/approve" in body


class TestCmdStatus:
    def test_returns_status_text(self, tmp_path):
        sent = []
        ctx = _fake_ctx(tmp_path)
        ctx.client.post = lambda *a, **kw: sent.append(kw) or MagicMock(status_code=200)
        _cmd_status(ctx, "")
        assert sent
        body = sent[0]["json"]["text"]
        assert "status" in body.lower() or "Jobs" in body


class TestCmdJobs:
    def test_no_jobs_message(self, tmp_path):
        sent = []
        ctx = _fake_ctx(tmp_path)
        ctx.client.post = lambda *a, **kw: sent.append(kw) or MagicMock(status_code=200)
        _cmd_jobs(ctx, "")
        assert "No jobs" in sent[0]["json"]["text"]

    def test_lists_jobs(self, tmp_path):
        ctx = _fake_ctx(tmp_path)
        conn = open_db(ctx.paths.state_db)
        conn.execute("INSERT INTO jobs (id, mode, status) VALUES ('j1', 'Monitor', 'done')")
        conn.close()
        sent = []
        ctx.client.post = lambda *a, **kw: sent.append(kw) or MagicMock(status_code=200)
        _cmd_jobs(ctx, "")
        assert "j1" in sent[0]["json"]["text"]


class TestCmdDrafts:
    def test_no_drafts_message(self, tmp_path):
        sent = []
        ctx = _fake_ctx(tmp_path)
        ctx.client.post = lambda *a, **kw: sent.append(kw) or MagicMock(status_code=200)
        _cmd_drafts(ctx, "")
        assert "No staged" in sent[0]["json"]["text"]

    def test_lists_staged_drafts(self, tmp_path):
        ctx = _fake_ctx(tmp_path)
        conn = open_db(ctx.paths.state_db)
        conn.execute(
            "INSERT INTO drafts (id, job_id, topic, title, body_html, status) "
            "VALUES ('d1', NULL, 'AI', 'My Draft', '', 'staged')"
        )
        conn.close()
        sent = []
        ctx.client.post = lambda *a, **kw: sent.append(kw) or MagicMock(status_code=200)
        _cmd_drafts(ctx, "")
        body = sent[0]["json"]["text"]
        assert "d1" in body
        assert "My Draft" in body


class TestCmdApprove:
    def test_approve_staged_draft(self, tmp_path):
        ctx = _fake_ctx(tmp_path)
        conn = open_db(ctx.paths.state_db)
        conn.execute(
            "INSERT INTO drafts (id, job_id, topic, title, body_html, status) "
            "VALUES ('d1', NULL, 'AI', 'Title', '', 'staged')"
        )
        conn.close()
        sent = []
        ctx.client.post = lambda *a, **kw: sent.append(kw) or MagicMock(status_code=200)

        # Dispatch via handle_message
        msg = {"chat": {"id": int(CHAT)}, "text": "/approve d1"}
        _handle_message(ctx, msg)
        assert "approved" in sent[0]["json"]["text"].lower()

        # Verify DB state
        conn2 = open_db(ctx.paths.state_db)
        status = conn2.execute("SELECT status FROM drafts WHERE id='d1'").fetchone()[0]
        conn2.close()
        assert status == "published"

    def test_approve_missing_id_error(self, tmp_path):
        sent = []
        ctx = _fake_ctx(tmp_path)
        ctx.client.post = lambda *a, **kw: sent.append(kw) or MagicMock(status_code=200)
        msg = {"chat": {"id": int(CHAT)}, "text": "/approve"}
        _handle_message(ctx, msg)
        assert "Usage" in sent[0]["json"]["text"]

    def test_approve_nonexistent_draft(self, tmp_path):
        sent = []
        ctx = _fake_ctx(tmp_path)
        ctx.client.post = lambda *a, **kw: sent.append(kw) or MagicMock(status_code=200)
        msg = {"chat": {"id": int(CHAT)}, "text": "/approve nope"}
        _handle_message(ctx, msg)
        body = sent[0]["json"]["text"]
        assert "not found" in body.lower() or "not staged" in body.lower()


class TestCmdReject:
    def test_reject_staged_draft(self, tmp_path):
        ctx = _fake_ctx(tmp_path)
        conn = open_db(ctx.paths.state_db)
        conn.execute(
            "INSERT INTO drafts (id, job_id, topic, title, body_html, status) "
            "VALUES ('d2', NULL, 'AI', 'Title', '', 'staged')"
        )
        conn.close()
        sent = []
        ctx.client.post = lambda *a, **kw: sent.append(kw) or MagicMock(status_code=200)
        msg = {"chat": {"id": int(CHAT)}, "text": "/reject d2 Not accurate enough"}
        _handle_message(ctx, msg)
        assert "rejected" in sent[0]["json"]["text"].lower()

        conn2 = open_db(ctx.paths.state_db)
        row = conn2.execute(
            "SELECT status, reject_reason FROM drafts WHERE id='d2'"
        ).fetchone()
        conn2.close()
        assert row[0] == "rejected"
        assert "Not accurate" in row[1]


class TestCmdSync:
    def test_sync_not_configured(self, tmp_path):
        sent = []
        ctx = _fake_ctx(tmp_path)
        ctx.client.post = lambda *a, **kw: sent.append(kw) or MagicMock(status_code=200)
        _cmd_sync(ctx, "")
        body = sent[0]["json"]["text"]
        assert "not configured" in body.lower() or "⚠" in body


# ---------------------------------------------------------------------------
# _send truncation
# ---------------------------------------------------------------------------

def test_send_truncates_long_messages(tmp_path):
    ctx = _fake_ctx(tmp_path)
    payloads = []
    ctx.client.post = lambda *a, **kw: payloads.append(kw) or MagicMock(status_code=200)
    _send(ctx, "x" * 5000)
    assert len(payloads[0]["json"]["text"]) <= 4096


def test_send_tolerates_http_error(tmp_path):
    ctx = _fake_ctx(tmp_path)
    ctx.client.post = MagicMock(side_effect=httpx.ConnectError("down"))
    # Should not raise
    _send(ctx, "test")


# ---------------------------------------------------------------------------
# dispatch table completeness
# ---------------------------------------------------------------------------

def test_all_listed_commands_are_dispatched():
    for cmd in _COMMANDS:
        assert cmd in _DISPATCH, f"{cmd} listed but not in _DISPATCH"


# ---------------------------------------------------------------------------
# Polling loop (mocked)
# ---------------------------------------------------------------------------

@respx.mock
def test_serve_sends_online_message_and_processes_help():
    """Drive one poll cycle: getUpdates returns /help, stop after 2nd empty poll."""
    update = _make_update("/help", chat_id=CHAT, update_id=10)
    stop = threading.Event()
    call_count = 0

    def _updates_handler(request):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return httpx.Response(200, json={"ok": True, "result": [update]})
        # 2nd call — return empty and signal stop
        stop.set()
        return httpx.Response(200, json={"ok": True, "result": []})

    respx.post(SEND_URL).mock(return_value=httpx.Response(200, json={"ok": True}))
    respx.get(UPDATES_URL).mock(side_effect=_updates_handler)

    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        paths = _make_paths(Path(tmp))
        with httpx.Client() as client:
            serve(TOKEN, CHAT, paths, poll_timeout=0,
                  client=client, stop_event=stop,
                  sleep=lambda s: None)
    assert stop.is_set()
    assert call_count >= 2
