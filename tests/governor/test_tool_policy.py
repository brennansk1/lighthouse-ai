"""Tests for tool-policy risk tiers (OpenHuman §6 integration)."""

from __future__ import annotations

import pytest

from lighthouse_ai.governor.tool_policy import (
    DEFAULT_EXPOSURE_CEILING,
    TaskProfile,
    Tool,
    ToolCapability,
    ToolPolicyViolation,
    decide,
    enforce,
    visible_tools,
)
from lighthouse_ai.schema import kinds_for

R = ToolCapability.READ_ONLY
W = ToolCapability.LOCAL_WRITE
N = ToolCapability.NETWORK_FETCH
M = ToolCapability.MUTATING


def _tools() -> list[Tool]:
    return [
        Tool("search", R), Tool("read_file", R), Tool("write_note", W),
        Tool("fetch_url", N), Tool("delete_corpus", M),
    ]


# --- pure policy -----------------------------------------------------------


def test_within_ceiling_allowed() -> None:
    prof = TaskProfile("synth", max_capability=N)
    assert decide(prof, Tool("fetch_url", N)).allowed is True


def test_above_ceiling_refused() -> None:
    prof = TaskProfile("synth", max_capability=W)
    d = decide(prof, Tool("delete_corpus", M))
    assert d.allowed is False
    assert "exceeds" in d.reason


def test_from_content_clamped_to_read_only() -> None:
    # Even with a high task ceiling, content-derived steps may only read.
    prof = TaskProfile("reasoner", max_capability=M, from_content=True)
    assert decide(prof, Tool("read_file", R)).allowed is True
    assert decide(prof, Tool("write_note", W)).allowed is False
    assert decide(prof, Tool("delete_corpus", M)).allowed is False


# --- prompt-visibility filter ----------------------------------------------


def test_visible_tools_filters_out_of_policy() -> None:
    prof = TaskProfile("researcher", max_capability=N)
    names = {t.name for t in visible_tools(prof, _tools())}
    assert "delete_corpus" not in names  # mutating excluded
    assert {"search", "read_file", "write_note", "fetch_url"} <= names


def test_visible_tools_respects_exposure_ceiling() -> None:
    prof = TaskProfile("researcher", max_capability=M, exposure_ceiling=2)
    visible = visible_tools(prof, _tools())
    assert len(visible) == 2
    # Safer (lower-capability) tools are preferred when the ceiling forces a cut.
    assert all(t.capability is R for t in visible)


def test_default_exposure_ceiling_is_seven() -> None:
    assert DEFAULT_EXPOSURE_CEILING == 7
    prof = TaskProfile("x", max_capability=M)
    many = [Tool(f"t{i}", R) for i in range(20)]
    assert len(visible_tools(prof, many)) == 7


def test_from_content_visibility_is_read_only() -> None:
    prof = TaskProfile("reasoner", max_capability=M, from_content=True)
    visible = visible_tools(prof, _tools())
    assert all(t.capability is R for t in visible)


# --- runtime enforcement ---------------------------------------------------


def test_enforce_allows_in_policy() -> None:
    prof = TaskProfile("synth", max_capability=N)
    assert enforce(prof, Tool("fetch_url", N)).allowed is True


def test_enforce_raises_on_violation() -> None:
    prof = TaskProfile("synth", max_capability=R)
    with pytest.raises(ToolPolicyViolation):
        enforce(prof, Tool("write_note", W))


def test_from_content_runtime_refuses_mutating_even_if_model_emits_it() -> None:
    # The prompt-injection hole: fetched content tells the model to call a
    # mutating tool. Runtime enforcement refuses it regardless.
    prof = TaskProfile("reasoner", max_capability=M, from_content=True)
    with pytest.raises(ToolPolicyViolation):
        enforce(prof, Tool("delete_corpus", M))


def test_enforce_logs_refusal_to_audit_chain(migrated_paths) -> None:
    from lighthouse_ai.verification.audit_chain import verify_audit_chain

    audit_db = kinds_for(migrated_paths)["audit"]
    secret = b"test-secret-key"
    prof = TaskProfile("reasoner", max_capability=R)
    with pytest.raises(ToolPolicyViolation):
        enforce(prof, Tool("delete_corpus", M), audit_db=audit_db, secret=secret)
    # The refusal landed as a tamper-evident audit event.
    assert verify_audit_chain(audit_db, secret=secret) == []  # chain intact
    from lighthouse_ai.persistence import open_db

    conn = open_db(audit_db)
    try:
        rows = conn.execute(
            "SELECT event_type FROM audit_events WHERE event_type='tool_policy_refused'"
        ).fetchall()
    finally:
        conn.close()
    assert len(rows) == 1
