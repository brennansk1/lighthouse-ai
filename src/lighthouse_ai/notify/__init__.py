"""Notifications subsystem: pluggable channels + event dispatcher.

See design §19.5 (channels) and §30 (``[notifications]`` config). Producers
should depend only on :class:`Notifier`; channel construction belongs at the
application edge where config/secrets are available.
"""

from __future__ import annotations

from .channels import (
    Channel,
    DesktopChannel,
    DiscordChannel,
    EmailChannel,
)
from .dispatcher import ChannelResult, Notifier

__all__ = [
    "Channel",
    "DesktopChannel",
    "DiscordChannel",
    "EmailChannel",
    "Notifier",
    "ChannelResult",
]
