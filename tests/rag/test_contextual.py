"""Unit tests for the contextual retrieval preamble helpers (design §14.3).

Covers:
  - default_preamble: deterministic preamble from chunk metadata.
  - prepend_context: prepends the preamble to each chunk's text.
  - llm_preamble_fn: returns a PreambleFn backed by a mock LLM gateway.
  - Fallback when the gateway raises.
  - gate=None path (nullcontext) does not crash.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from lighthouse_ai.rag.chunker import Chunk
from lighthouse_ai.rag.contextual import (
    default_preamble,
    llm_preamble_fn,
    prepend_context,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_chunk(text: str = "Sample text.", **metadata) -> Chunk:
    return Chunk(id="c1", document_id="d1", text=text, position=0, metadata=metadata)


# ---------------------------------------------------------------------------
# default_preamble
# ---------------------------------------------------------------------------


def test_default_preamble_includes_source():
    chunk = _make_chunk(source="Reuters")
    preamble = default_preamble(chunk)
    assert "Source: Reuters" in preamble


def test_default_preamble_includes_grade():
    chunk = _make_chunk(grade="A")
    preamble = default_preamble(chunk)
    assert "grade A" in preamble


def test_default_preamble_includes_published_date():
    chunk = _make_chunk(published_date="2024-01-15")
    preamble = default_preamble(chunk)
    assert "published 2024-01-15" in preamble


def test_default_preamble_includes_stakes():
    chunk = _make_chunk(stakes="high")
    preamble = default_preamble(chunk)
    assert "stakes: high" in preamble


def test_default_preamble_empty_when_no_metadata():
    chunk = _make_chunk()
    assert default_preamble(chunk) == ""


def test_default_preamble_format():
    chunk = _make_chunk(source="AP", grade="B")
    preamble = default_preamble(chunk)
    assert preamble.startswith("[")
    assert preamble.endswith("] ")


# ---------------------------------------------------------------------------
# prepend_context
# ---------------------------------------------------------------------------


def test_prepend_context_adds_preamble_to_text():
    chunk = _make_chunk("Body text.", source="Bloomberg")
    result = prepend_context([chunk])
    assert len(result) == 1
    assert result[0].text.startswith("[Source: Bloomberg]")
    assert "Body text." in result[0].text


def test_prepend_context_skips_empty_preamble():
    """Chunks with no metadata should pass through unchanged."""
    chunk = _make_chunk("Just the body.")
    result = prepend_context([chunk])
    assert result[0].text == "Just the body."


def test_prepend_context_returns_new_chunk_objects():
    chunk = _make_chunk("original", source="Test")
    result = prepend_context([chunk])
    # Should be a different object (dataclasses.replace), not in-place mutation.
    assert result[0] is not chunk


def test_prepend_context_custom_preamble_fn():
    chunk = _make_chunk("body text")
    result = prepend_context([chunk], preamble_fn=lambda c: "CUSTOM: ")
    assert result[0].text.startswith("CUSTOM: ")


# ---------------------------------------------------------------------------
# llm_preamble_fn — mock gateway
# ---------------------------------------------------------------------------


def test_llm_preamble_fn_returns_callable():
    gw = MagicMock()
    fn = llm_preamble_fn(gw, document_text="doc context")
    assert callable(fn)


def test_llm_preamble_fn_uses_gateway_response():
    gw = MagicMock()
    gw.complete.return_value = MagicMock(
        text="This chunk discusses quarterly revenue figures from Q3 2023."
    )
    fn = llm_preamble_fn(gw, document_text="Annual report text here.")
    chunk = _make_chunk("Revenue was $1.2B in Q3 2023.")
    preamble = fn(chunk)
    assert preamble.startswith("[Context:")
    assert "quarterly revenue" in preamble


def test_llm_preamble_fn_prepends_result_via_prepend_context():
    """End-to-end: use the LLM-backed fn through prepend_context."""
    gw = MagicMock()
    gw.complete.return_value = MagicMock(text="Context sentence.")
    fn = llm_preamble_fn(gw)
    chunk = _make_chunk("The chunk text.")
    result = prepend_context([chunk], preamble_fn=fn)
    assert "[Context: Context sentence.]" in result[0].text


def test_llm_preamble_fn_gateway_called_with_aux_context_role():
    gw = MagicMock()
    gw.complete.return_value = MagicMock(text="Preamble.")
    fn = llm_preamble_fn(gw, document_text="doc")
    fn(_make_chunk("text"))
    gw.complete.assert_called_once()
    role_arg = gw.complete.call_args[0][0]
    assert role_arg == "aux_context"


# ---------------------------------------------------------------------------
# llm_preamble_fn — fallback when gateway raises
# ---------------------------------------------------------------------------


def test_llm_preamble_fn_falls_back_on_gateway_exception():
    """When the gateway raises any exception, fall back to default_preamble."""
    gw = MagicMock()
    gw.complete.side_effect = RuntimeError("service unavailable")
    fn = llm_preamble_fn(gw, document_text="doc")
    chunk = _make_chunk("chunk body", source="FallbackSource")
    preamble = fn(chunk)
    # Must not raise; should return default_preamble output
    assert "FallbackSource" in preamble


def test_llm_preamble_fn_falls_back_when_response_empty():
    """An empty response text should also trigger the fallback."""
    gw = MagicMock()
    gw.complete.return_value = MagicMock(text="   ")  # blank after strip
    fn = llm_preamble_fn(gw)
    chunk = _make_chunk("body", source="MySrc")
    preamble = fn(chunk)
    assert "MySrc" in preamble


# ---------------------------------------------------------------------------
# gate=None path — nullcontext
# ---------------------------------------------------------------------------


def test_llm_preamble_fn_gate_none_does_not_crash():
    """gate=None should use nullcontext and not raise."""
    gw = MagicMock()
    gw.complete.return_value = MagicMock(text="Context preamble here.")
    fn = llm_preamble_fn(gw, gate=None)
    chunk = _make_chunk("some content")
    preamble = fn(chunk)
    assert preamble  # non-empty preamble returned


def test_llm_preamble_fn_gate_provided_is_called():
    """When gate is provided, gate.permit() context manager is entered."""
    gw = MagicMock()
    gw.complete.return_value = MagicMock(text="Preamble text.")
    gate = MagicMock()
    # gate.permit() must return a context manager
    ctx_mgr = MagicMock()
    ctx_mgr.__enter__ = MagicMock(return_value=None)
    ctx_mgr.__exit__ = MagicMock(return_value=False)
    gate.permit.return_value = ctx_mgr

    fn = llm_preamble_fn(gw, gate=gate)
    fn(_make_chunk("body"))
    gate.permit.assert_called_once()
