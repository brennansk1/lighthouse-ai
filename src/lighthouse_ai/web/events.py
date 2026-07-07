"""In-process SSE event bus (design webapp_tui_design.md §4.1).

A single :class:`EventBus` instance lives on the FastAPI app. Producers
(the API write handlers, the effector, the governor) call ``publish``;
subscribers (each open ``/api/events`` SSE connection, and the TUI's SSE
client) get an ``asyncio.Queue`` via ``subscribe``.

Because Lighthouse is single-user / single-process, this is deliberately
tiny: no Redis, no external broker. If we ever split the supervisor from
the control plane, swap this for a Unix-socket fan-out — the public
surface (`publish` / `subscribe`) stays the same.

``publish`` is thread-safe-ish: producers may be in worker threads, while
the asyncio queues live on the event loop. We hop onto the loop via
``call_soon_threadsafe`` when a loop is set.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any

KNOWN_EVENTS = {
    "job.progress",
    "job.status",
    "job.step",
    "draft.staged",
    "draft.approved",
    "draft.rejected",
    "position.created",
    "position.resolved",
    "audit.appended",
    "governor.tier",
    "governor.tripped",
    "doctor.changed",
    "intent.dead",
    "control.status",
    "chat.token",
    "chat.turn",
}

#: Sentinel enqueued to a subscriber that overflowed its queue — the SSE stream
#: generator recognizes it (by identity) and ends the response so the browser's
#: EventSource reconnects with a fresh queue instead of hanging on a dead one.
_OVERFLOW: dict[str, Any] = {"event": "__overflow__", "data": {}}


@dataclass
class EventBus:
    _subscribers: set[asyncio.Queue] = field(default_factory=set)
    _loop: asyncio.AbstractEventLoop | None = None
    max_queue: int = 256

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Called once the event loop is running (FastAPI startup)."""
        self._loop = loop

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=self.max_queue)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subscribers.discard(q)

    def publish(self, event: str, data: dict[str, Any] | None = None) -> None:
        """Fan a message out to every subscriber. Safe to call from any thread.

        Unknown event names are allowed but logged-by-convention only — we
        don't raise, so a producer can't crash on a typo.
        """
        msg = {"event": event, "data": data or {}}

        def _deliver() -> None:
            for q in list(self._subscribers):
                try:
                    q.put_nowait(msg)
                except asyncio.QueueFull:
                    # The subscriber fell behind. Silently discarding it (the old
                    # behavior) left its SSE generator blocked forever on an
                    # orphaned queue — the connection never closed, so the browser
                    # never fired onerror and never reconnected, and that tab
                    # silently stopped receiving all live updates. Instead: make
                    # room and enqueue a close sentinel the generator acts on, so
                    # the response ends and the client reconnects with a fresh queue.
                    try:
                        q.get_nowait()  # drop the oldest queued message
                        q.put_nowait(_OVERFLOW)
                    except Exception:
                        self._subscribers.discard(q)

        loop = self._loop
        if loop is not None and loop.is_running():
            try:
                loop.call_soon_threadsafe(_deliver)
                return
            except RuntimeError:
                pass
        # No running loop (tests, or pre-startup): deliver inline.
        _deliver()

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)


def sse_format(msg: dict[str, Any]) -> str:
    """Encode one bus message as an SSE wire frame."""
    return f"event: {msg['event']}\ndata: {json.dumps(msg['data'])}\n\n"
