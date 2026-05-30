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
from .telegram import TelegramChannel, request_confirmation
from .templates import (
    escape_md,
    notify_artifact_staged,
    notify_monitor_alert,
    render_artifact,
)

__all__ = [
    "Channel",
    "ChannelResult",
    "DesktopChannel",
    "DiscordChannel",
    "EmailChannel",
    "Notifier",
    "TelegramChannel",
    "escape_md",
    "notify_artifact_staged",
    "notify_monitor_alert",
    "render_artifact",
    "request_confirmation",
]
