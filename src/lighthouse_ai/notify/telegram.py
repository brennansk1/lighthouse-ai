"""Telegram notification channel and the §24.10 kill-switch "airlock".

Per design §21.3 Telegram is the primary mobile surface: read-mostly with an
approve/confirm loop. This module provides two distinct pieces:

* :class:`TelegramChannel` -- a fire-and-forget :class:`~lighthouse_ai.notify.
  channels.Channel` adapter over the Bot API ``sendMessage`` method, used for
  stake notifications (digests, monitor alerts, staged-artifact review pings).

* :func:`request_confirmation` -- the §24.10 airlock. For high-impact
  destructive operations (delete topic, purge corpus, reset Position Registry)
  the agent must not act on an implicit "no reply". It posts a prompt asking the
  operator to reply ``YES`` within a deadline, polls ``getUpdates`` for that
  reply, and *auto-aborts* on timeout. Defaulting to abort (returning ``False``)
  is the safety-critical property: silence, a network failure, or any reply
  other than an explicit YES must never green-light a destructive action.

As with the other channels in this package the design priority is determinism
and testability. The httpx client, the wall clock, and even ``sleep`` are
injectable so the test-suite can drive the polling loop with a fake clock and a
no-op sleep -- never touching the real network and never actually waiting.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

import httpx

# The public Telegram Bot API root. The bot token is interpolated into the path
# (``/bot<token>/<method>``), per Telegram's scheme, so it is not a header.
API_ROOT = "https://api.telegram.org"

# Injectables typed for clarity. ``Clock`` returns monotonic-ish seconds; we use
# it only for relative deadline math so any consistent source works. ``Sleep``
# matches ``time.sleep`` so tests can pass a no-op and skip real waiting.
Clock = Callable[[], float]
Sleep = Callable[[float], None]


def _method_url(bot_token: str, method: str) -> str:
    """Build the Bot API URL for ``method``.

    Centralised so the channel and the confirmation helper agree on the scheme
    and so tests have a single place to mirror when mounting respx routes.
    """
    return f"{API_ROOT}/bot{bot_token}/{method}"


@dataclass(frozen=True)
class TelegramChannel:
    """Telegram Bot API ``sendMessage`` channel.

    Combines title and body into a single message because Telegram messages
    have no separate subject line. The httpx client is injectable so respx can
    intercept the request in tests; otherwise we build a short-lived client and
    close only the clients we own (an injected client belongs to the caller).
    """

    bot_token: str
    chat_id: str
    client: httpx.Client | None = None
    timeout: float = 10.0

    def available(self) -> bool:
        """Whether this channel is configured enough to attempt a send.

        Both a bot token and a destination chat id are required; without either
        the Bot API call cannot be addressed, so doctor checks and the
        dispatcher should treat the channel as unavailable rather than fail at
        send time.
        """
        return bool(self.bot_token) and bool(self.chat_id)

    def send(self, title: str, body: str) -> bool:
        text = f"*{title}*\n{body}" if title else body
        return self.send_text(text)

    def send_text(self, text: str, *, parse_mode: str | None = None) -> bool:
        """Send an already-composed message, optionally with a Telegram parse mode.

        :meth:`send` is the :class:`~lighthouse_ai.notify.channels.Channel`
        contract (title+body, no markup); ``send_text`` is the lower-level seam
        used by the artifact templates, which pre-render MarkdownV2 and pass
        ``parse_mode="MarkdownV2"`` so Telegram interprets the formatting. Both
        share the same delivery semantics: never raise on a delivery problem,
        only close a client we own.
        """
        if not self.available():
            return False
        payload: dict[str, object] = {"chat_id": self.chat_id, "text": text}
        if parse_mode:
            payload["parse_mode"] = parse_mode
        client = self.client or httpx.Client(timeout=self.timeout)
        try:
            response = client.post(_method_url(self.bot_token, "sendMessage"), json=payload)
        except httpx.HTTPError:
            # Network problems are an ordinary delivery failure for a fan-out
            # dispatcher; never raise (see the Channel protocol contract).
            return False
        finally:
            if self.client is None:
                client.close()
        return response.is_success


def _extract_messages(payload: object) -> list[dict]:
    """Pull the message objects out of a ``getUpdates`` response.

    Telegram wraps results in ``{"ok": true, "result": [ {update}, ... ]}`` and
    each update may carry a ``message`` (or ``edited_message``). We are liberal
    in what we accept and tolerant of malformed shapes -- a parse failure must
    degrade to "no confirmation seen" (and thus abort), never crash the airlock.
    """
    if not isinstance(payload, dict):
        return []
    results = payload.get("result")
    if not isinstance(results, list):
        return []
    messages: list[dict] = []
    for update in results:
        if not isinstance(update, dict):
            continue
        message = update.get("message") or update.get("edited_message")
        if isinstance(message, dict):
            messages.append(message)
    return messages


def _is_yes_from(message: dict, chat_id: str) -> bool:
    """Whether ``message`` is an explicit YES from the expected chat.

    The match is intentionally strict on origin (the chat id must match, so a
    reply from another chat cannot authorise the action) but lenient on the text
    itself: we accept any message whose text contains the token ``YES``
    (case-insensitive) so "yes", "YES!", or "yes do it" all confirm. Anything
    else -- a different word, an empty message, a sticker -- does not.
    """
    chat = message.get("chat")
    if not isinstance(chat, dict):
        return False
    # chat ids may arrive as int or str depending on client; compare as strings.
    if str(chat.get("id")) != str(chat_id):
        return False
    text = message.get("text")
    if not isinstance(text, str):
        return False
    return "YES" in text.upper()


def request_confirmation(
    bot_token: str,
    chat_id: str,
    prompt: str,
    *,
    timeout_s: float = 60,
    poll_interval_s: float = 2.0,
    client: httpx.Client | None = None,
    now: Clock | None = None,
    sleep: Sleep | None = None,
) -> bool:
    """Run the §24.10 airlock confirmation and return whether YES was received.

    The flow: send ``prompt`` (the caller should phrase it as "reply YES within
    60s, else aborted"), then poll ``getUpdates`` for a reply from ``chat_id``
    containing YES until the deadline. Returns ``True`` only on an explicit YES
    seen before timeout; returns ``False`` on timeout, on any other reply, or if
    the prompt itself could not be delivered.

    Defaulting to ``False`` everywhere is the whole point: this gates
    irreversible operations, so the absence of an affirmative answer -- whether
    from silence, a non-YES reply, or a network failure -- must abort.

    ``now`` and ``sleep`` are injected so tests can supply a fake clock and a
    no-op sleep, exercising the full polling loop deterministically without
    waiting in real time. ``client`` is injected so respx can mock the Bot API.
    """
    if not bot_token or not chat_id:
        return False

    clock: Clock = now or time.monotonic
    nap: Sleep = sleep or time.sleep

    owns_client = client is None
    http = client or httpx.Client(timeout=10.0)
    try:
        # Step 1: deliver the prompt. If we cannot even ask, we must not assume
        # consent, so abort.
        try:
            sent = http.post(
                _method_url(bot_token, "sendMessage"),
                json={"chat_id": chat_id, "text": prompt},
            )
        except httpx.HTTPError:
            return False
        if not sent.is_success:
            return False

        # Step 2: poll for the reply. ``offset`` advances past updates we have
        # already inspected so each one is considered once and we do not re-ack
        # stale messages. The deadline is computed once against the clock; the
        # loop runs at least once even if timeout_s is 0 so an already-waiting
        # YES can still be honoured.
        deadline = clock() + timeout_s
        offset: int | None = None
        while True:
            params: dict[str, object] = {"timeout": 0}
            if offset is not None:
                params["offset"] = offset
            try:
                response = http.get(_method_url(bot_token, "getUpdates"), params=params)
            except httpx.HTTPError:
                # A transient polling error should not abort early; keep trying
                # until the deadline, then fall through to the timeout abort.
                if clock() >= deadline:
                    return False
                nap(poll_interval_s)
                continue

            if response.is_success:
                try:
                    payload = response.json()
                except ValueError:
                    payload = None
                else:
                    for message in _extract_messages(payload):
                        if _is_yes_from(message, chat_id):
                            return True
                # Advance offset past the highest update_id we have seen so the
                # next poll only returns newer updates.
                offset = _next_offset(payload, offset)

            if clock() >= deadline:
                return False
            nap(poll_interval_s)
    finally:
        if owns_client:
            http.close()


def _next_offset(payload: object, current: int | None) -> int | None:
    """Compute the ``getUpdates`` offset to request next.

    Telegram expects ``offset = highest_seen_update_id + 1`` to acknowledge and
    skip already-delivered updates. We keep the current offset when the payload
    is empty or malformed so we never accidentally rewind and reprocess.
    """
    if not isinstance(payload, dict):
        return current
    results = payload.get("result")
    if not isinstance(results, list):
        return current
    highest = current - 1 if current is not None else None
    for update in results:
        if isinstance(update, dict) and isinstance(update.get("update_id"), int):
            uid = update["update_id"]
            if highest is None or uid > highest:
                highest = uid
    return highest + 1 if highest is not None else current
