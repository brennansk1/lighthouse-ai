"""Pluggable notification channels (desktop, Discord, email).

Per design §19.5 each channel is a thin adapter over an external delivery
mechanism. They share a single ``send(title, body) -> bool`` contract so the
:class:`~lighthouse_ai.notify.dispatcher.Notifier` can treat them uniformly.

The design priority here is *testability*: nothing in this module performs a
real side effect at import time, and every effectful dependency (subprocess
runner, HTTP client, SMTP sender) is injectable. That lets the test-suite
exercise the full code path with fakes/respx and never touch a real desktop,
network socket, or mail server -- a hard constraint for a local-first tool
that must behave deterministically offline.
"""

from __future__ import annotations

import shutil
import smtplib
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from email.message import EmailMessage
from typing import Protocol, runtime_checkable

import httpx


@runtime_checkable
class Channel(Protocol):
    """A notification sink.

    Implementations return ``True`` when delivery is believed to have
    succeeded and ``False`` on any handled failure. They must not raise for
    ordinary delivery problems (a down SMTP server, a 4xx webhook) because the
    dispatcher fans out to several channels and one failure should not abort
    the others; raising is reserved for genuine programmer error.
    """

    def send(self, title: str, body: str) -> bool:  # pragma: no cover - protocol
        ...


# --- Desktop -----------------------------------------------------------------

# Type of the subprocess runner we depend on. Matching ``subprocess.run`` lets
# the default be the stdlib while tests pass a recording fake.
Runner = Callable[..., subprocess.CompletedProcess]


@dataclass(frozen=True)
class DesktopChannel:
    """Native desktop notifications.

    Uses ``terminal-notifier`` on macOS and ``notify-send`` on Linux. We probe
    for the binary rather than assuming a platform so a Linux box with
    ``terminal-notifier`` (or vice versa) still works, and so ``available()``
    can gate the channel honestly in :meth:`send` and in doctor checks.

    ``runner`` and ``which`` are injectable purely so tests never spawn a real
    process or depend on what happens to be installed on the CI host.
    """

    runner: Runner = subprocess.run
    which: Callable[[str], str | None] = shutil.which
    # Preference order; first binary found wins.
    binaries: Sequence[str] = ("terminal-notifier", "notify-send")

    def _resolve(self) -> str | None:
        for binary in self.binaries:
            if self.which(binary):
                return binary
        return None

    def available(self) -> bool:
        """Whether any supported notifier binary is on PATH."""
        return self._resolve() is not None

    def _argv(self, binary: str, title: str, body: str) -> list[str]:
        # The two tools take notably different flags for title/message.
        if binary == "terminal-notifier":
            return [binary, "-title", title, "-message", body]
        # notify-send takes positional summary + body.
        return [binary, title, body]

    def send(self, title: str, body: str) -> bool:
        binary = self._resolve()
        if binary is None:
            return False
        try:
            result = self.runner(
                self._argv(binary, title, body),
                check=False,
                capture_output=True,
            )
        except OSError:
            # Binary vanished between probe and exec, or exec failed.
            return False
        return result.returncode == 0


# --- Discord -----------------------------------------------------------------


@dataclass(frozen=True)
class DiscordChannel:
    """Discord incoming-webhook channel.

    Discord webhooks accept a JSON body with a ``content`` field. We combine
    title and body into a single markdown-ish message because webhooks have no
    separate subject. The httpx client is injectable so respx can intercept the
    request in tests; we construct a short-lived default client otherwise.
    """

    webhook_url: str
    client: httpx.Client | None = None
    timeout: float = 10.0

    def send(self, title: str, body: str) -> bool:
        if not self.webhook_url:
            return False
        content = f"**{title}**\n{body}" if title else body
        payload = {"content": content}
        client = self.client or httpx.Client(timeout=self.timeout)
        try:
            response = client.post(self.webhook_url, json=payload)
        except httpx.HTTPError:
            return False
        finally:
            # Only close clients we own; an injected client is the caller's.
            if self.client is None:
                client.close()
        # Discord returns 204 No Content on success, 200 with ?wait=true.
        return response.is_success


# --- Email -------------------------------------------------------------------

# A sender takes a built message and delivers it, returning nothing. The
# default uses smtplib; tests pass a fake that records the message.
Sender = Callable[[EmailMessage, "EmailChannel"], None]


def _smtp_sender(message: EmailMessage, channel: EmailChannel) -> None:
    """Default email transport using stdlib smtplib.

    Kept module-level (not a method) so it can be referenced as the dataclass
    default without binding ``self`` and so tests can substitute it trivially.
    """
    smtp_cls = smtplib.SMTP_SSL if channel.use_ssl else smtplib.SMTP
    with smtp_cls(channel.smtp_host, channel.smtp_port, timeout=channel.timeout) as smtp:
        if channel.use_starttls:
            smtp.starttls()
        if channel.username:
            smtp.login(channel.username, channel.password or "")
        smtp.send_message(message)


@dataclass(frozen=True)
class EmailChannel:
    """SMTP email channel.

    Builds an :class:`email.message.EmailMessage` (so headers/encoding are
    handled by the stdlib) and hands it to an injectable ``sender``. Isolating
    the actual transmission behind ``sender`` is what keeps the test-suite from
    ever opening a socket: the default ``_smtp_sender`` is the only place real
    smtplib lives, and tests replace it with a recorder.
    """

    smtp_host: str
    from_addr: str
    to_addrs: Sequence[str]
    smtp_port: int = 587
    username: str | None = None
    password: str | None = None
    use_starttls: bool = True
    use_ssl: bool = False
    timeout: float = 30.0
    sender: Sender = field(default=_smtp_sender)

    def build_message(self, title: str, body: str) -> EmailMessage:
        message = EmailMessage()
        message["Subject"] = title
        message["From"] = self.from_addr
        message["To"] = ", ".join(self.to_addrs)
        message.set_content(body)
        return message

    def send(self, title: str, body: str) -> bool:
        if not self.to_addrs:
            return False
        message = self.build_message(title, body)
        try:
            self.sender(message, self)
        except (OSError, smtplib.SMTPException):
            return False
        return True
