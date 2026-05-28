"""Event-to-channel routing for notifications.

The :class:`Notifier` is the single fan-out point used by the rest of
Lighthouse. It owns two pieces of policy from the ``[notifications]`` config
(design §30): which *events* the user opted into, and which *channels* are
enabled. Keeping that policy here -- rather than in each call site -- means a
producer just emits a semantic event (``draft_ready``, ``budget_trip``) and
never has to know whether the user wants desktop vs Discord vs nothing.

Channels are passed in already constructed (dependency injection at the edges)
so this module stays free of subprocess/network/SMTP concerns and is trivial
to unit test.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from .channels import Channel


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
        return {str(e) for e in raw}  # type: ignore[union-attr]

    def _channel_enabled(self, name: str) -> bool:
        cfg = self._config
        if name == "desktop":
            return bool(cfg.get("desktop_enabled", False))
        if name == "email":
            return bool(cfg.get("email_enabled", False))
        if name == "discord":
            return bool(cfg.get("discord_webhook_url", ""))
        if name == "telegram":
            return bool(cfg.get("telegram_bot_token", "") and cfg.get("telegram_chat_id", ""))
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
            delivered = bool(channel.send(title, body))
            results.append(ChannelResult(name, attempted=True, delivered=delivered))
        return results
