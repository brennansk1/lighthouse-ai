"""Unit + integration tests for the Ollama backend."""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from lighthouse_ai.backends.ollama import (
    BackendStalled,
    OllamaBackend,
    OllamaUnavailable,
    _sampling_to_options,
)

# ============================== unit (mocked HTTP) ==============================

HOST = "http://test-ollama"


@pytest.fixture
def mocked():
    """respx patches *all* httpx clients globally inside the with-block, so
    we just construct a regular httpx client and respx intercepts."""
    with respx.mock(base_url=HOST, assert_all_called=False) as mock:
        yield mock


def _backend(mock: respx.MockRouter) -> OllamaBackend:
    return OllamaBackend(HOST)


def test_available_true_on_200(mocked):
    mocked.get("/api/tags").respond(200, json={"models": []})
    b = _backend(mocked)
    assert b.available() is True


def test_available_false_on_5xx(mocked):
    mocked.get("/api/tags").respond(500)
    assert _backend(mocked).available() is False


def test_available_false_on_network_error(mocked):
    mocked.get("/api/tags").side_effect = httpx.ConnectError("nope")
    assert _backend(mocked).available() is False


def test_list_models_parses_tags(mocked):
    mocked.get("/api/tags").respond(200, json={
        "models": [
            {"name": "qwen3:8b", "size": 5_500_000_000,
             "digest": "sha256:abc", "modified_at": "2026-01-01T00:00:00Z"},
            {"name": "nomic-embed-text:latest", "size": 274_000_000,
             "digest": "sha256:def"},
        ]
    })
    out = _backend(mocked).list_models()
    assert [m.name for m in out] == ["qwen3:8b", "nomic-embed-text:latest"]
    assert out[0].size_bytes == 5_500_000_000
    assert out[0].digest == "sha256:abc"


def test_list_models_raises_unavailable_on_non_200(mocked):
    mocked.get("/api/tags").respond(503)
    with pytest.raises(OllamaUnavailable):
        _backend(mocked).list_models()


def test_chat_parses_completion(mocked):
    # chat() always streams now (the generation watchdog needs a per-chunk
    # progress signal); without on_token it still returns the identical
    # ChatResponse, assembled from the JSON-lines frames.
    mocked.post("/api/chat").respond(200, text=_stream_body(
        {"message": {"role": "assistant", "content": "Hello world."},
         "done": False},
        {"message": {"content": ""}, "done": True, "model": "qwen3:8b",
         "prompt_eval_count": 5, "eval_count": 3, "done_reason": "stop"},
    ))
    resp = _backend(mocked).chat("qwen3:8b", "hi")
    assert resp.text == "Hello world."
    assert resp.prompt_tokens == 5
    assert resp.completion_tokens == 3
    assert resp.done_reason == "stop"


def test_chat_passes_sampling_options(mocked):
    route = mocked.post("/api/chat").respond(200, text=_stream_body(
        {"message": {"content": "ok"}, "done": True,
         "model": "qwen3:8b", "prompt_eval_count": 1, "eval_count": 1},
    ))
    _backend(mocked).chat(
        "qwen3:8b", "p",
        sampling={"temperature": 0.2, "top_p": 0.9, "max_tokens": 128, "seed": 42},
    )
    body = json.loads(route.calls.last.request.content)
    assert body["model"] == "qwen3:8b"
    assert body["stream"] is True
    assert body["options"]["temperature"] == 0.2
    assert body["options"]["num_predict"] == 128
    assert body["options"]["seed"] == 42


def test_chat_with_system_message(mocked):
    route = mocked.post("/api/chat").respond(200, json={
        "model": "x", "message": {"content": ""},
        "prompt_eval_count": 0, "eval_count": 0,
    })
    _backend(mocked).chat("x", "p", system="be terse")
    msgs = json.loads(route.calls.last.request.content)["messages"]
    assert msgs[0]["role"] == "system" and msgs[0]["content"] == "be terse"
    assert msgs[1]["role"] == "user" and msgs[1]["content"] == "p"


def test_chat_raises_on_non_200(mocked):
    mocked.post("/api/chat").respond(400, text="bad request")
    with pytest.raises(OllamaUnavailable):
        _backend(mocked).chat("x", "p")


def test_chat_raises_on_network_error(mocked):
    mocked.post("/api/chat").side_effect = httpx.ConnectError("down")
    with pytest.raises(OllamaUnavailable):
        _backend(mocked).chat("x", "p")


# --- chat streaming (on_token) -------------------------------------------

def _stream_body(*chunks: dict) -> str:
    """Ollama streams newline-delimited JSON frames."""
    return "\n".join(json.dumps(c) for c in chunks)


def test_chat_streams_with_on_token(mocked):
    route = mocked.post("/api/chat").respond(200, text=_stream_body(
        {"message": {"content": "Hel"}, "done": False},
        {"message": {"content": "lo."}, "done": False},
        {"message": {"content": ""}, "done": True, "model": "qwen3:8b",
         "prompt_eval_count": 11, "eval_count": 2, "done_reason": "stop"},
    ))
    got: list[str] = []
    resp = _backend(mocked).chat("qwen3:8b", "hi", on_token=got.append)
    # The streamed result is identical in shape to the non-streaming one.
    assert resp.text == "Hello."
    assert got == ["Hel", "lo."]
    assert resp.prompt_tokens == 11
    assert resp.completion_tokens == 2
    assert resp.done_reason == "stop"
    body = json.loads(route.calls.last.request.content)
    assert body["stream"] is True


def test_chat_stream_sink_errors_never_break_the_call(mocked):
    """A broken UI sink must not kill the model call (best-effort contract)."""
    mocked.post("/api/chat").respond(200, text=_stream_body(
        {"message": {"content": "ok"}, "done": False},
        {"message": {"content": ""}, "done": True,
         "prompt_eval_count": 1, "eval_count": 1},
    ))

    def _boom(_tok: str) -> None:
        raise RuntimeError("sink crashed")

    resp = _backend(mocked).chat("x", "p", on_token=_boom)
    assert resp.text == "ok"


def test_chat_stream_skips_malformed_frames(mocked):
    mocked.post("/api/chat").respond(200, text=(
        "not-json\n"
        + _stream_body(
            {"message": {"content": "fine"}, "done": True,
             "prompt_eval_count": 1, "eval_count": 1})
    ))
    got: list[str] = []
    resp = _backend(mocked).chat("x", "p", on_token=got.append)
    assert resp.text == "fine"
    assert got == ["fine"]


def test_chat_stream_raises_on_non_200(mocked):
    mocked.post("/api/chat").respond(500, text="boom")
    with pytest.raises(OllamaUnavailable):
        _backend(mocked).chat("x", "p", on_token=lambda _t: None)


def test_chat_stream_raises_on_network_error(mocked):
    mocked.post("/api/chat").side_effect = httpx.ConnectError("down")
    with pytest.raises(OllamaUnavailable):
        _backend(mocked).chat("x", "p", on_token=lambda _t: None)


# --- generation watchdog (BackendStalled) --------------------------------
# A wedged-but-listening daemon accepts the request but never produces bytes;
# httpx surfaces that as a ReadTimeout on the streaming read. The backend must
# translate it into BackendStalled with the diagnostic attrs the dispatcher
# audits — not the generic OllamaUnavailable, and never a silent hang.

def test_chat_stall_raises_backend_stalled_with_attrs(mocked):
    mocked.post("/api/chat").side_effect = httpx.ReadTimeout("no bytes")
    b = OllamaBackend(HOST, stall_timeout=0.5)
    with pytest.raises(BackendStalled) as ei:
        b.chat("qwen3:8b", "hi")
    assert ei.value.call == "chat"
    assert ei.value.model == "qwen3:8b"
    assert ei.value.stalled_after_s == 0.5
    # It is-a OllamaUnavailable, so existing broad handlers still catch it.
    assert isinstance(ei.value, OllamaUnavailable)


def test_chat_stall_raises_even_with_on_token(mocked):
    mocked.post("/api/chat").side_effect = httpx.ReadTimeout("no bytes")
    with pytest.raises(BackendStalled):
        OllamaBackend(HOST).chat("x", "p", on_token=lambda _t: None)


def test_embed_stall_raises_backend_stalled(mocked):
    mocked.post("/api/embed").side_effect = httpx.ReadTimeout("silent")
    b = OllamaBackend(HOST, embed_read_timeout=0.25)
    with pytest.raises(BackendStalled) as ei:
        b.embed("bge-m3", ["a", "b"])
    assert ei.value.call == "embed"
    assert ei.value.stalled_after_s == 0.25


def test_embed_non_timeout_error_stays_unavailable(mocked):
    # A plain connection drop is NOT a stall — it must stay OllamaUnavailable
    # (and specifically not the BackendStalled subclass the dispatcher escalates).
    mocked.post("/api/embed").side_effect = httpx.ConnectError("refused")
    with pytest.raises(OllamaUnavailable) as ei:
        OllamaBackend(HOST).embed("bge-m3", ["a"])
    assert not isinstance(ei.value, BackendStalled)


def test_embed_returns_vectors(mocked):
    mocked.post("/api/embed").respond(200, json={
        "model": "nomic", "embeddings": [[0.1, 0.2], [0.3, 0.4]],
    })
    resp = _backend(mocked).embed("nomic", ["a", "b"])
    assert resp.vectors == [[0.1, 0.2], [0.3, 0.4]]


def test_embed_empty_input_short_circuits(mocked):
    # No HTTP request should be issued on empty list.
    resp = _backend(mocked).embed("nomic", [])
    assert resp.vectors == []
    assert mocked.calls.call_count == 0


def test_embed_raises_on_non_200(mocked):
    mocked.post("/api/embed").respond(500, text="boom")
    with pytest.raises(OllamaUnavailable):
        _backend(mocked).embed("nomic", ["x"])


def test_pull_streams_progress_to_callback(mocked):
    mocked.post("/api/pull").respond(200, text=(
        '{"status":"pulling manifest"}\n'
        '{"status":"downloading","completed":50}\n'
        '{"status":"success"}\n'
    ))
    seen: list[dict] = []
    _backend(mocked).pull("qwen3:8b", progress_cb=seen.append)
    assert seen[-1]["status"] == "success"
    assert any(s["status"] == "downloading" for s in seen)


def test_pull_raises_on_non_200(mocked):
    mocked.post("/api/pull").respond(404, text="not found")
    with pytest.raises(OllamaUnavailable):
        _backend(mocked).pull("nope")


def test_delete_accepts_200_and_404(mocked):
    mocked.delete("/api/delete").respond(200)
    _backend(mocked).delete("x")  # 200 path
    mocked.delete("/api/delete").respond(404)
    _backend(mocked).delete("x")  # 404 path = already gone


def test_delete_raises_on_other_codes(mocked):
    mocked.delete("/api/delete").respond(500, text="boom")
    with pytest.raises(OllamaUnavailable):
        _backend(mocked).delete("x")


def test_sampling_translation():
    out = _sampling_to_options({"temperature": 0.3, "top_p": 1.0,
                                "max_tokens": 256, "seed": 7})
    assert out == {"temperature": 0.3, "top_p": 1.0, "num_predict": 256, "seed": 7}


def test_sampling_translation_ignores_unknown_keys():
    assert _sampling_to_options({"frequency_penalty": 0.5}) == {}


# ============================== integration (real Ollama) ==============================

def _ollama_reachable() -> bool:
    try:
        with httpx.Client(timeout=1.0) as c:
            r = c.get("http://127.0.0.1:11434/api/tags")
            return r.status_code == 200
    except httpx.HTTPError:
        return False


# Opt-in only: even when Ollama is running, real-backend tests load a
# model into RAM and can OOM a daily-driver laptop. Set
# LIGHTHOUSE_REAL_BACKEND=1 to enable.
import os as _os

_REAL_BACKEND_OK = (_os.environ.get("LIGHTHOUSE_REAL_BACKEND") == "1"
                    and _ollama_reachable())
_REAL_BACKEND_SKIP_REASON = (
    "set LIGHTHOUSE_REAL_BACKEND=1 and have ollama on 127.0.0.1:11434"
)


@pytest.mark.integration
@pytest.mark.skipif(not _REAL_BACKEND_OK, reason=_REAL_BACKEND_SKIP_REASON)
def test_real_ollama_lists_models():
    with OllamaBackend() as b:
        models = b.list_models()
    # Any list (possibly empty) is fine; we just want the round-trip to work.
    assert isinstance(models, list)


def _is_embedding_model(name: str) -> bool:
    """Embedding-only models can't serve /api/chat (they 400 with "does not
    support chat"). Exclude them from the chat smoke. Covers bge-*, nomic-embed,
    mxbai-embed, *-embed*, all-minilm, arctic-embed, etc."""
    low = name.lower()
    return (
        low.startswith("bge")
        or "embed" in low
        or "all-minilm" in low
        or "arctic-embed" in low
    )


@pytest.mark.integration
@pytest.mark.skipif(not _REAL_BACKEND_OK, reason=_REAL_BACKEND_SKIP_REASON)
def test_real_ollama_chat_returns_tokens():
    with OllamaBackend() as b:
        models = [m.name for m in b.list_models()]
        # A chat smoke must use a chat-capable model — an embedding model like
        # bge-m3 (often alphabetically first) 400s with "does not support chat".
        chat_models = [m for m in models if not _is_embedding_model(m)]
        if not chat_models:
            pytest.skip(
                "no chat-capable models pulled — run `ollama pull qwen3:8b` first"
            )
        # Honor an explicit pin first (LIGHTHOUSE_FORCE_MODEL), so this smoke
        # uses the same model the rest of the real-backend suite is pinned to.
        forced = _os.environ.get("LIGHTHOUSE_FORCE_MODEL", "").strip()
        if forced and forced in models:
            model = forced
        else:
            # Prefer a genuinely small model for speed. Match on parameter-count
            # suffixes only — brand names like "mistral-small:24b" / "devstral-
            # small" contain "small" but are 15-24 GB, so never match on "small".
            small = [m for m in chat_models if any(
                s in m.lower()
                for s in ("0.5b", "1b", "1.5b", "2b", "3b", "4b", "7b", "8b", "9b", "mini")
            )]
            model = sorted(small or chat_models)[0]
        # Reasoning models (e.g. qwen3.5) emit <think>…</think> tokens that the
        # backend strips, so a small max_tokens budget can be spent entirely on
        # thinking and leave empty visible text. Give generous headroom so a
        # one-word answer can land after any thinking.
        resp = b.chat(model, "Reply with the single word: ok.",
                      sampling={"temperature": 0.0, "max_tokens": 256})
    # The real signal: the chat round-trip generated tokens.
    assert resp.completion_tokens > 0
    # Visible text is expected — unless a reasoning model spent the whole budget
    # on stripped <think> tokens and was cut off mid-thought (done_reason=length).
    assert resp.text.strip() or resp.done_reason == "length", (
        f"empty text and not truncated from {model} (done_reason="
        f"{resp.done_reason}, completion_tokens={resp.completion_tokens})"
    )
