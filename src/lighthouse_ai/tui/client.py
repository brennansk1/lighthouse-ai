"""Tiny synchronous HTTP client the TUI uses to talk to the control plane.

Localhost JSON payloads are sub-millisecond, so synchronous calls inside
Textual handlers are fine — no thread pool needed. Tests inject a
:class:`FakeClient` so screens render without a live supervisor.
"""

from __future__ import annotations

from typing import Any, Protocol

import httpx


class Client(Protocol):
    def get(self, path: str, **params: Any) -> dict[str, Any]: ...
    def post(self, path: str, json: dict | None = None) -> dict[str, Any]: ...


class SupervisorOffline(RuntimeError):
    pass


class LighthouseClient:
    def __init__(self, base_url: str = "http://127.0.0.1:8765", timeout: float = 5.0):
        self.base_url = base_url.rstrip("/")
        self._client = httpx.Client(base_url=self.base_url, timeout=timeout)

    def get(self, path: str, **params: Any) -> dict[str, Any]:
        try:
            r = self._client.get(path, params=params or None)
        except httpx.HTTPError as exc:
            raise SupervisorOffline(str(exc)) from exc
        r.raise_for_status()
        return r.json()

    def post(self, path: str, json: dict | None = None) -> dict[str, Any]:
        try:
            r = self._client.post(path, json=json)
        except httpx.HTTPError as exc:
            raise SupervisorOffline(str(exc)) from exc
        r.raise_for_status()
        return r.json()

    def available(self) -> bool:
        try:
            self._client.get("/health", timeout=1.0)
            return True
        except httpx.HTTPError:
            return False

    def close(self) -> None:
        self._client.close()


class FakeClient:
    """In-memory client for tests — canned GET responses + recorded POSTs."""

    def __init__(self, responses: dict[str, dict[str, Any]] | None = None):
        self.responses = responses or {}
        self.posts: list[tuple[str, dict | None]] = []

    def get(self, path: str, **params: Any) -> dict[str, Any]:
        # Exact match first, then path without query.
        if path in self.responses:
            return self.responses[path]
        base = path.split("?")[0]
        return self.responses.get(base, {})

    def post(self, path: str, json: dict | None = None) -> dict[str, Any]:
        self.posts.append((path, json))
        return {"ok": True}

    def available(self) -> bool:
        return True

    def close(self) -> None:
        pass
