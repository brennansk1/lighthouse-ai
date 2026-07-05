"""Ollama HTTP backend — chat, embed, model management.

Ollama serves a small REST surface on ``127.0.0.1:11434`` by default. This
adapter talks to it directly via ``httpx`` (no ``litellm`` indirection,
so timeouts and the streaming path stay predictable).

The class is intentionally narrow: chat / embed / pull / list / delete.
``chat`` streams when given an ``on_token`` callback (the SSE dashboard's
live-synthesis feed); without one it is a single blocking request.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

import httpx

DEFAULT_HOST = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
DEFAULT_CONNECT_TIMEOUT = 60.0
#: Deep-dive synthesis can take minutes on a 30B model; allow a generous read.
DEFAULT_READ_TIMEOUT = 600.0
#: Generation watchdog (incident 2026-06-10): max seconds a *streaming* chat
#: may go with no bytes from the server before we call the backend stalled.
#: Generous because prompt-eval on a big model is silent until the first
#: token — but a healthy generation never pauses 5 minutes mid-stream, while
#: a wedged-but-listening daemon stays silent forever.
DEFAULT_STALL_TIMEOUT = float(os.environ.get("LIGHTHOUSE_STALL_TIMEOUT_S", "300"))
#: Embeds finish in seconds; a dedicated short read timeout means a wedged
#: daemon surfaces from /api/embed in ~2 minutes, not 10.
DEFAULT_EMBED_READ_TIMEOUT = float(os.environ.get("LIGHTHOUSE_EMBED_TIMEOUT_S", "120"))


class OllamaUnavailable(RuntimeError):
    """Raised when the Ollama daemon can't be reached or returns 5xx."""


class BackendStalled(OllamaUnavailable):
    """The daemon accepted the request but produced no bytes for too long.

    A wedged-but-listening backend (TCP up, generation dead) must fail loudly
    and quickly — it is the one failure the generic degrade-to-mock fallback
    must never swallow, or an eternally-silent daemon looks like an
    eternally-running job.
    """

    def __init__(self, message: str, *, model: str,
                 stalled_after_s: float, call: str):
        super().__init__(message)
        self.model = model
        self.stalled_after_s = stalled_after_s
        self.call = call  # "chat" | "embed"


@dataclass(frozen=True)
class ChatResponse:
    text: str
    prompt_tokens: int
    completion_tokens: int
    model: str
    done_reason: str | None = None


@dataclass(frozen=True)
class EmbeddingResponse:
    vectors: list[list[float]]
    model: str


@dataclass(frozen=True)
class ModelInfo:
    name: str
    size_bytes: int
    digest: str
    modified_at: str | None = None


class OllamaBackend:
    """Thin wrapper around the Ollama REST API."""

    def __init__(self, host: str = DEFAULT_HOST, *,
                 connect_timeout: float = DEFAULT_CONNECT_TIMEOUT,
                 read_timeout: float = DEFAULT_READ_TIMEOUT,
                 stall_timeout: float = DEFAULT_STALL_TIMEOUT,
                 embed_read_timeout: float = DEFAULT_EMBED_READ_TIMEOUT,
                 client: httpx.Client | None = None):
        self.host = host.rstrip("/")
        self._connect_timeout = connect_timeout
        self.stall_timeout = stall_timeout
        self.embed_read_timeout = embed_read_timeout
        self._timeout = httpx.Timeout(connect=connect_timeout, read=read_timeout,
                                      write=read_timeout, pool=connect_timeout)
        self._owns_client = client is None
        self._client = client or httpx.Client(base_url=self.host, timeout=self._timeout)

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> OllamaBackend:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ----------------------------------------------------- availability --
    def available(self) -> bool:
        """Cheap probe: GET /api/tags. False on any connection error or 5xx."""
        try:
            r = self._client.get("/api/tags", timeout=2.0)
            return r.status_code < 500
        except httpx.HTTPError:
            return False

    def loaded_models(self) -> list[str]:
        """Names of models currently resident in RAM (GET /api/ps)."""
        try:
            r = self._client.get("/api/ps", timeout=2.0)
            if r.status_code != 200:
                return []
            return [m["name"] for m in r.json().get("models", [])]
        except httpx.HTTPError:
            return []

    # ----------------------------------------------------- model mgmt ---
    def list_models(self) -> list[ModelInfo]:
        try:
            r = self._client.get("/api/tags")
        except httpx.HTTPError as exc:
            raise OllamaUnavailable(f"GET /api/tags failed: {exc}") from exc
        if r.status_code != 200:
            raise OllamaUnavailable(f"GET /api/tags → {r.status_code}: {r.text}")
        out: list[ModelInfo] = []
        for m in r.json().get("models", []):
            out.append(ModelInfo(
                name=m["name"],
                size_bytes=int(m.get("size", 0)),
                digest=str(m.get("digest", "")),
                modified_at=m.get("modified_at"),
            ))
        return out

    def pull(self, model: str, *, progress_cb=None) -> None:
        """Pull a model. Streams progress JSON-lines from Ollama.

        ``progress_cb`` (optional) receives each parsed status dict — wire it
        to a rich progress bar in the CLI.
        """
        try:
            with self._client.stream(
                "POST", "/api/pull",
                json={"model": model, "stream": True},
                timeout=httpx.Timeout(connect=60.0, read=None, write=60.0, pool=60.0),
            ) as r:
                if r.status_code != 200:
                    body = r.read().decode(errors="replace")
                    raise OllamaUnavailable(
                        f"POST /api/pull → {r.status_code}: {body}"
                    )
                for line in r.iter_lines():
                    if not line:
                        continue
                    try:
                        msg = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if progress_cb is not None:
                        progress_cb(msg)
                    if msg.get("status") == "success":
                        return
        except httpx.HTTPError as exc:
            raise OllamaUnavailable(f"pull {model!r} failed: {exc}") from exc

    def delete(self, model: str) -> None:
        try:
            r = self._client.request("DELETE", "/api/delete", json={"model": model})
        except httpx.HTTPError as exc:
            raise OllamaUnavailable(f"DELETE /api/delete failed: {exc}") from exc
        if r.status_code not in (200, 404):
            raise OllamaUnavailable(
                f"DELETE /api/delete → {r.status_code}: {r.text}"
            )

    # ----------------------------------------------------- chat ---------
    def chat(self, model: str, prompt: str, *,
             sampling: dict[str, Any] | None = None,
             system: str | None = None,
             on_token: Callable[[str], None] | None = None) -> ChatResponse:
        """Single-turn chat. Returns the full completion.

        The request always streams (JSON-lines), whether or not ``on_token``
        is supplied — streaming is what makes the generation watchdog possible:
        each chunk is an observable progress tick, so a wedged-but-listening
        daemon trips :class:`BackendStalled` after ``stall_timeout`` seconds of
        silence instead of hiding behind the full read timeout. It also means
        total generation time is bounded per-chunk, not overall — a legitimate
        long synthesis is never killed just for taking more than the old
        read-timeout total. With ``on_token`` supplied, each content chunk is
        additionally handed to the callback (a UI sink; its exceptions are
        swallowed so a broken sink can never kill the model call). Either way
        the chunks are assembled into one :class:`ChatResponse`, including the
        token counts from Ollama's final frame.
        """
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        body = {
            "model": model,
            "messages": messages,
            "stream": True,
            "options": _sampling_to_options(sampling or {}),
        }
        return self._chat_stream(model, body, on_token)

    def _chat_stream(self, model: str, body: dict[str, Any],
                     on_token: Callable[[str], None] | None) -> ChatResponse:
        """Streaming chat — JSON-lines, same shape as ``pull``.

        The per-read timeout is ``stall_timeout``: on a streaming response
        httpx applies it between chunks, which is exactly the generation
        watchdog — silence longer than the deadline raises
        :class:`BackendStalled`.
        """
        parts: list[str] = []
        prompt_tokens = 0
        completion_tokens = 0
        model_name = model
        done_reason: str | None = None
        stall = httpx.Timeout(connect=self._connect_timeout,
                              read=self.stall_timeout,
                              write=self.stall_timeout,
                              pool=self._connect_timeout)
        try:
            with self._client.stream("POST", "/api/chat", json=body,
                                     timeout=stall) as r:
                if r.status_code != 200:
                    detail = r.read().decode(errors="replace")[:300]
                    raise OllamaUnavailable(
                        f"POST /api/chat → {r.status_code}: {detail}"
                    )
                for line in r.iter_lines():
                    if not line:
                        continue
                    try:
                        chunk = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    tok = (chunk.get("message", {}) or {}).get("content", "")
                    if tok:
                        parts.append(tok)
                        if on_token is not None:
                            try:
                                on_token(tok)
                            except Exception:
                                pass
                    if chunk.get("done"):
                        prompt_tokens = int(chunk.get("prompt_eval_count", 0))
                        completion_tokens = int(chunk.get("eval_count", 0))
                        model_name = str(chunk.get("model", model))
                        done_reason = chunk.get("done_reason")
        except httpx.ReadTimeout as exc:
            raise BackendStalled(
                f"backend stalled: no progress for {self.stall_timeout:.0f}s "
                f"on POST /api/chat model={model}",
                model=model, stalled_after_s=self.stall_timeout,
                call="chat") from exc
        except httpx.HTTPError as exc:
            raise OllamaUnavailable(f"POST /api/chat failed: {exc}") from exc
        return ChatResponse(
            text="".join(parts),
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            model=model_name,
            done_reason=done_reason,
        )

    # ----------------------------------------------------- embed --------
    def embed(self, model: str, texts: Iterable[str]) -> EmbeddingResponse:
        """Batch embed. Ollama's /api/embed accepts a list of strings."""
        texts_list = list(texts)
        if not texts_list:
            return EmbeddingResponse(vectors=[], model=model)
        embed_to = httpx.Timeout(connect=self._connect_timeout,
                                 read=self.embed_read_timeout,
                                 write=self.embed_read_timeout,
                                 pool=self._connect_timeout)
        try:
            r = self._client.post(
                "/api/embed",
                json={"model": model, "input": texts_list},
                timeout=embed_to,
            )
        except httpx.ReadTimeout as exc:
            raise BackendStalled(
                f"backend stalled: no response for {self.embed_read_timeout:.0f}s "
                f"on POST /api/embed model={model}",
                model=model, stalled_after_s=self.embed_read_timeout,
                call="embed") from exc
        except httpx.HTTPError as exc:
            raise OllamaUnavailable(f"POST /api/embed failed: {exc}") from exc
        if r.status_code != 200:
            raise OllamaUnavailable(
                f"POST /api/embed → {r.status_code}: {r.text[:300]}"
            )
        data = r.json()
        return EmbeddingResponse(
            vectors=[list(v) for v in data.get("embeddings", [])],
            model=str(data.get("model", model)),
        )


def _sampling_to_options(sampling: dict[str, Any]) -> dict[str, Any]:
    """Translate the gateway's sampling dict to Ollama's options shape."""
    out: dict[str, Any] = {}
    if "temperature" in sampling:
        out["temperature"] = float(sampling["temperature"])
    if "top_p" in sampling:
        out["top_p"] = float(sampling["top_p"])
    if "max_tokens" in sampling:
        out["num_predict"] = int(sampling["max_tokens"])
    if "seed" in sampling:
        out["seed"] = int(sampling["seed"])
    return out
