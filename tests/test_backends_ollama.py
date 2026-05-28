"""Unit + integration tests for the Ollama backend."""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from lighthouse_ai.backends.ollama import (
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
    mocked.post("/api/chat").respond(200, json={
        "model": "qwen3:8b",
        "message": {"role": "assistant", "content": "Hello world."},
        "prompt_eval_count": 5,
        "eval_count": 3,
        "done_reason": "stop",
    })
    resp = _backend(mocked).chat("qwen3:8b", "hi")
    assert resp.text == "Hello world."
    assert resp.prompt_tokens == 5
    assert resp.completion_tokens == 3
    assert resp.done_reason == "stop"


def test_chat_passes_sampling_options(mocked):
    route = mocked.post("/api/chat").respond(200, json={
        "model": "qwen3:8b",
        "message": {"content": "ok"},
        "prompt_eval_count": 1,
        "eval_count": 1,
    })
    _backend(mocked).chat(
        "qwen3:8b", "p",
        sampling={"temperature": 0.2, "top_p": 0.9, "max_tokens": 128, "seed": 42},
    )
    body = json.loads(route.calls.last.request.content)
    assert body["model"] == "qwen3:8b"
    assert body["stream"] is False
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


@pytest.mark.integration
@pytest.mark.skipif(not _REAL_BACKEND_OK, reason=_REAL_BACKEND_SKIP_REASON)
def test_real_ollama_chat_returns_tokens():
    with OllamaBackend() as b:
        models = [m.name for m in b.list_models()]
        if not models:
            pytest.skip("no models pulled — run `ollama pull qwen3:8b` first")
        # Pick the smallest model present for speed.
        model = sorted(models, key=lambda n: n)[0]
        resp = b.chat(model, "Reply with the single word: ok.",
                      sampling={"temperature": 0.0, "max_tokens": 8})
    assert resp.text
    assert resp.completion_tokens > 0
