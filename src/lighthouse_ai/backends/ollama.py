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


class OllamaUnavailable(RuntimeError):
    """Raised when the Ollama daemon can't be reached or returns 5xx."""


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
                 client: httpx.Client | None = None):
        self.host = host.rstrip("/")
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

        With ``on_token`` supplied the request streams: each content chunk is
        handed to the callback as it arrives (a UI sink; its exceptions are
        swallowed so a broken sink can never kill the model call) and the
        chunks are assembled into the same :class:`ChatResponse` the
        non-streaming path returns — callers see an identical result either
        way, including the token counts from Ollama's final frame.
        """
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        body = {
            "model": model,
            "messages": messages,
            "stream": on_token is not None,
            "options": _sampling_to_options(sampling or {}),
        }
        if on_token is not None:
            return self._chat_stream(model, body, on_token)
        try:
            r = self._client.post("/api/chat", json=body)
        except httpx.HTTPError as exc:
            raise OllamaUnavailable(f"POST /api/chat failed: {exc}") from exc
        if r.status_code != 200:
            raise OllamaUnavailable(
                f"POST /api/chat → {r.status_code}: {r.text[:300]}"
            )
        data = r.json()
        msg = data.get("message", {}) or {}
        return ChatResponse(
            text=msg.get("content", ""),
            prompt_tokens=int(data.get("prompt_eval_count", 0)),
            completion_tokens=int(data.get("eval_count", 0)),
            model=str(data.get("model", model)),
            done_reason=data.get("done_reason"),
        )

    def _chat_stream(self, model: str, body: dict[str, Any],
                     on_token: Callable[[str], None]) -> ChatResponse:
        """Streaming twin of :meth:`chat` — JSON-lines, same shape as ``pull``."""
        parts: list[str] = []
        prompt_tokens = 0
        completion_tokens = 0
        model_name = model
        done_reason: str | None = None
        try:
            with self._client.stream("POST", "/api/chat", json=body) as r:
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
                        try:
                            on_token(tok)
                        except Exception:
                            pass
                    if chunk.get("done"):
                        prompt_tokens = int(chunk.get("prompt_eval_count", 0))
                        completion_tokens = int(chunk.get("eval_count", 0))
                        model_name = str(chunk.get("model", model))
                        done_reason = chunk.get("done_reason")
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
        try:
            r = self._client.post(
                "/api/embed",
                json={"model": model, "input": texts_list},
            )
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
