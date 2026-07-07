"""Event-to-channel routing for notifications.

The :class:`Notifier` is the single fan-out point used by the rest of
Lighthouse. It owns two pieces of policy from the ``[notifications]`` config
(design §30): which *events* the user opted into, and which *channels* are
enabled. Keeping that policy here -- rather than in each call site -- means a
producer just emits a semantic event (``draft_ready``, ``monitor_alert_high``)
and never has to know whether the user wants desktop vs Discord vs nothing.

Channels are passed in already constructed (dependency injection at the edges)
so this module stays free of subprocess/network/SMTP concerns and is trivial
to unit test.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from .channels import Channel

_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ChannelResult:
    """Outcome of attempting one channel for one event."""

    channel: str
    attempted: bool
    delivered: bool


class Notifier:
    """Routes events to the enabled channels.

    A channel pairing is ``(name, channel)`` where ``name`` matches a config
    flag convention: ``desktop`` -> ``desktop_enabled``, ``email`` ->
    ``email_enabled``, ``discord`` -> truthy ``discord_webhook_url``. Names not
    recognized fall back to being enabled (the caller chose to register them).
    """

    def __init__(
        self,
        config: Mapping[str, object],
        channels: Sequence[tuple[str, Channel]],
    ) -> None:
        self._config = dict(config)
        self._channels = list(channels)

    @property
    def events(self) -> set[str]:
        raw = self._config.get("events", []) or []
        if not isinstance(raw, (list, tuple, set, frozenset)):
            return set()
        return {str(e) for e in raw}

    def _channel_enabled(self, name: str) -> bool:
        cfg = self._config
        if name == "desktop":
            return bool(cfg.get("desktop_enabled", False))
        if name == "email":
            return bool(cfg.get("email_enabled", False))
        if name == "discord":
            return bool(cfg.get("discord_webhook_url", ""))
        # Unknown channel: trust that registering it was intentional.
        return True

    def notify(self, event: str, title: str, body: str) -> list[ChannelResult]:
        """Dispatch ``event`` to every enabled, opted-in channel.

        Returns a per-channel result so callers/tests can see exactly what
        happened. A channel is *attempted* only when both the event is in the
        configured ``events`` allow-list and the channel is enabled; otherwise
        it is reported as ``attempted=False, delivered=False``.
        """
        event_allowed = event in self.events
        results: list[ChannelResult] = []
        for name, channel in self._channels:
            if not (event_allowed and self._channel_enabled(name)):
                results.append(ChannelResult(name, attempted=False, delivered=False))
                continue
            # Failure isolation: a channel that raises (a buggy adapter, an
            # unexpected error the channel failed to handle) must not abort the
            # fan-out to the remaining channels. Treat it as a non-delivery.
            try:
                delivered = bool(channel.send(title, body))
            except Exception:
                _log.warning("notify channel %r raised; treating as failed", name, exc_info=True)
                delivered = False
            results.append(ChannelResult(name, attempted=True, delivered=delivered))
        return results
