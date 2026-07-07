"""Scrapability pre-flight — verify a URL is lawfully and reliably monitorable.

This is the genuinely-new capability behind Watch v2 (``FUTURE_FEATURES.md``
§1, step 2): before Lighthouse accepts a user-pasted website as a monitor it
runs a one-time check and returns a clear, reason-bearing verdict. The check
*composes* primitives that already exist rather than re-implementing them:

  * **robots.txt** — :class:`lighthouse_ai.net_politeness.RobotsPolicy` answers
    allow/deny and exposes the declared ``Crawl-delay``.
  * **reachability** — :meth:`lighthouse_ai.governor.egress_proxy.EgressProxy.is_allowed_host`
    decides whether the host is already inside the egress allowlist (or whether
    the user must ``trust add`` it first).
  * **extractability** — :func:`lighthouse_ai.ingest.extract_text` (trafilatura /
    stdlib) tells us whether a *static* fetch yields real prose (≥ N tokens) or
    whether the page is JS-only and needs Tier-B rendering.
  * **change-detectability** — a header/body probe picks the cheapest reliable
    change signal: a declared feed link, an ``ETag``/``Last-Modified`` header,
    or (last resort) a content-hash diff.

The whole module is **offline-deterministic**: every byte comes from an injected
``fetch`` callable (or pre-supplied ``robots_bytes``), so tests drive it with
canned responses and the package never opens a socket here. ``fetch`` returns a
small :class:`FetchResult` (status, headers, body) — the caller adapts whatever
real client it has into that shape; tests pass a closure.

No ``datetime.now()`` runs at import time and the verdict carries no timestamps,
so the module is import-safe and trivially testable.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlsplit

from ..governor.egress_proxy import DEFAULT_ALLOWED_DOMAINS, EgressProxy
from ..ingest import extract_text
from ..net_politeness import RobotsPolicy

# Minimum number of whitespace tokens a static extract must yield before we
# trust the page as "statically scrapable". Below this we assume the real
# content is rendered client-side (JS) and a static fetch only sees a shell.
DEFAULT_MIN_TOKENS = 50

# Substrings in an HTML body that hint at a syndication feed we can monitor more
# cheaply than diffing rendered content.
_FEED_TYPE_HINTS = (
    "application/rss+xml",
    "application/atom+xml",
    "application/feed+json",
)


@dataclass(frozen=True)
class FetchResult:
    """The minimal fetch shape :func:`verify_scrapable` needs.

    A real caller adapts its HTTP response into this; tests construct it
    directly. ``headers`` is matched case-insensitively. ``ok`` defaults to
    True so a canned 200 needs only ``body``.
    """

    status: int = 200
    headers: Mapping[str, str] = field(default_factory=dict)
    body: bytes = b""
    content_type: str | None = None

    def header(self, name: str) -> str | None:
        """Case-insensitive header lookup."""
        lower = name.lower()
        for key, value in self.headers.items():
            if key.lower() == lower:
                return value
        return None


FetchFn = Callable[[str], FetchResult]


@dataclass(frozen=True)
class ScrapeVerdict:
    """The pre-flight verdict surfaced to the user (one source, one decision).

    Attributes
    ----------
    robots_ok:
        ``robots.txt`` permits fetching this exact path for our user-agent.
    crawl_delay:
        Declared ``Crawl-delay`` in seconds (0.0 when none / unknown).
    reachable:
        Host is on the egress allowlist (``EgressProxy.is_allowed_host``). When
        False the caller can offer a one-click ``trust add`` using
        :attr:`trust_add_hint`.
    trust_add_hint:
        The bare host to pass to ``lighthouse trust add <host>`` when not
        reachable; empty when already reachable.
    extract_tier:
        ``"static"`` — static fetch + extractor yields ≥ N tokens;
        ``"js"`` — static yields < N tokens, so it needs Tier-B JS rendering;
        ``"none"`` — nothing extractable (not fetched / empty / error).
    change_method:
        Cheapest reliable change signal: ``"feed"`` (a feed link was declared),
        ``"etag"`` (an ``ETag`` or ``Last-Modified`` header is present), or
        ``"diff"`` (must hash + diff rendered content).
    feed_url:
        Absolute URL of the discovered feed when ``change_method == "feed"``.
    verdict:
        ``"good"`` — monitorable now (ideally via feed/etag);
        ``"limited"`` — monitorable but heavier (needs JS render and/or
        content-diff, or needs a ``trust add``);
        ``"blocked"`` — cannot monitor (robots disallows / unreachable+blocked /
        no extractable content).
    reason:
        Human-readable explanation — visibility-with-reason, never silent.
    """

    robots_ok: bool
    crawl_delay: float
    reachable: bool
    extract_tier: str
    change_method: str
    verdict: str
    reason: str
    trust_add_hint: str = ""
    feed_url: str = ""

    def as_dict(self) -> dict[str, object]:
        """Serialise for the Watch UI / audit log."""
        return {
            "robots_ok": self.robots_ok,
            "crawl_delay": self.crawl_delay,
            "reachable": self.reachable,
            "extract_tier": self.extract_tier,
            "change_method": self.change_method,
            "verdict": self.verdict,
            "reason": self.reason,
            "trust_add_hint": self.trust_add_hint,
            "feed_url": self.feed_url,
        }


def _token_count(text: str) -> int:
    """Whitespace-token count — the cheap, deterministic ``≥ N`` proxy."""
    return len(text.split())


def _detect_feed(body: bytes, *, base_url: str) -> str:
    """Return an absolute feed URL discovered in *body*, or ``""``.

    Looks for ``<link ... type="application/rss+xml" href="...">`` style
    declarations (and the Atom / JSON-feed variants). Intentionally a small,
    documented substring/regex scan — not a full HTML parse — so it stays
    dependency-free and deterministic. It also recognises a body that *is*
    already a feed (root ``<rss``/``<feed`` element).
    """
    if not body:
        return ""
    try:
        text = body.decode("utf-8", errors="replace")
    except Exception:  # pragma: no cover - decode is lenient
        return ""
    lowered = text.lower()

    # The body itself is a feed document.
    head = lowered[:512].lstrip()
    if head.startswith("<?xml"):
        head = head[head.find("?>") + 2 :].lstrip() if "?>" in head else head
    if head.startswith("<rss") or head.startswith("<feed"):
        return base_url

    # A declared <link rel="alternate" type="application/rss+xml" href=...>.
    import re

    for match in re.finditer(r"<link\b[^>]*>", lowered):
        tag = match.group(0)
        if not any(hint in tag for hint in _FEED_TYPE_HINTS):
            continue
        href_match = re.search(r"""href\s*=\s*['"]([^'"]+)['"]""", tag)
        if href_match:
            return urljoin(base_url, href_match.group(1))
    return ""


def _detect_change_method(result: FetchResult, *, base_url: str) -> tuple[str, str]:
    """Pick the cheapest change signal. Returns ``(method, feed_url)``.

    Order of preference (cheapest / most reliable first):
      1. ``feed`` — a declared feed link or a body that is itself a feed.
      2. ``etag`` — an ``ETag`` or ``Last-Modified`` response header.
      3. ``diff`` — fall back to hashing + diffing rendered content.
    """
    feed_url = _detect_feed(result.body, base_url=base_url)
    if feed_url:
        return "feed", feed_url
    if result.header("etag") or result.header("last-modified"):
        return "etag", ""
    return "diff", ""


def verify_scrapable(
    url: str,
    *,
    robots_bytes: bytes | None = None,
    fetch: FetchFn | None = None,
    allowlist: frozenset[str] | set[str] | None = None,
    min_tokens: int = DEFAULT_MIN_TOKENS,
    user_agent: str = "LighthouseBot",
) -> ScrapeVerdict:
    """Run the one-time scrapability pre-flight for *url*.

    Parameters
    ----------
    url:
        The page the user wants to monitor.
    robots_bytes:
        Pre-supplied ``robots.txt`` bytes for the host. When given, the robots
        check is fully offline (no robots fetch). When ``None`` and *fetch* is
        supplied, ``robots.txt`` is fetched via *fetch*; when both are ``None``
        the robots policy is permissive (allows everything, delay 0).
    fetch:
        Injected ``(url) -> FetchResult`` used to fetch the page itself (and,
        when *robots_bytes* is ``None``, ``robots.txt``). ``None`` means no page
        fetch happens → ``extract_tier="none"``, ``change_method="diff"``.
    allowlist:
        Egress allowlist of hostnames. Defaults to the platform
        :data:`DEFAULT_ALLOWED_DOMAINS`. The host's membership sets
        :attr:`ScrapeVerdict.reachable`.
    min_tokens:
        Token floor for the ``static`` vs ``js`` extract tier.
    user_agent:
        User-agent presented to the robots parser.

    Returns
    -------
    ScrapeVerdict
        A frozen verdict with every signal plus a roll-up ``verdict``/``reason``.

    Notes
    -----
    The function never raises for a reachable failure mode — a fetch error or a
    blocked robots rule is reported *in the verdict*, not as an exception, so the
    Watch UI always has something explicit to show (§1: "never silent failure").
    """
    host = urlsplit(url).netloc.lower().split("@")[-1].split(":")[0]

    # --- 1. robots.txt -----------------------------------------------------
    robots_fetcher: Callable[[str], bytes] | None = None
    if robots_bytes is not None:
        # A closure that always returns the supplied bytes for this host's
        # robots.txt — fully offline.
        def robots_fetcher(_robots_url: str) -> bytes:
            return robots_bytes  # type: ignore[return-value]

    elif fetch is not None:

        def robots_fetcher(robots_url: str) -> bytes:
            try:
                return fetch(robots_url).body  # type: ignore[union-attr]
            except Exception:
                return b""

    robots = RobotsPolicy(robots_fetcher, user_agent=user_agent)
    robots_ok = robots.allowed(url, user_agent)
    crawl_delay = robots.crawl_delay(host)

    # --- 2. reachability (egress allowlist) --------------------------------
    proxy = EgressProxy(frozenset(allowlist) if allowlist is not None else DEFAULT_ALLOWED_DOMAINS)
    reachable = bool(host) and proxy.is_allowed_host(host)
    trust_hint = "" if reachable else host

    # --- 3 + 4. extractability + change-detectability (one page fetch) -----
    extract_tier = "none"
    change_method = "diff"
    feed_url = ""
    fetch_failed = False

    if fetch is not None:
        try:
            result = fetch(url)
        except Exception:
            result = None
            fetch_failed = True

        if result is not None and 200 <= result.status < 300 and result.body:
            ct = result.content_type or result.header("content-type")
            text = extract_text(result.body, ct, None)
            tokens = _token_count(text)
            extract_tier = "static" if tokens >= min_tokens else "js"
            change_method, feed_url = _detect_change_method(result, base_url=url)
        elif result is not None and result.body:
            # Non-2xx but a body came back: still probe change signals so a
            # 304/redirect page can advertise a feed; extract stays "none".
            change_method, feed_url = _detect_change_method(result, base_url=url)

    # --- roll-up verdict ---------------------------------------------------
    verdict, reason = _roll_up(
        robots_ok=robots_ok,
        reachable=reachable,
        extract_tier=extract_tier,
        change_method=change_method,
        fetch_failed=fetch_failed,
        host=host,
        trust_hint=trust_hint,
    )

    return ScrapeVerdict(
        robots_ok=robots_ok,
        crawl_delay=crawl_delay,
        reachable=reachable,
        extract_tier=extract_tier,
        change_method=change_method,
        verdict=verdict,
        reason=reason,
        trust_add_hint=trust_hint,
        feed_url=feed_url,
    )


def _roll_up(
    *,
    robots_ok: bool,
    reachable: bool,
    extract_tier: str,
    change_method: str,
    fetch_failed: bool,
    host: str,
    trust_hint: str,
) -> tuple[str, str]:
    """Collapse the individual signals into ``(verdict, reason)``.

    Precedence (hardest blocker first):
      * robots disallow → ``blocked``;
      * fetch failed outright → ``blocked``;
      * not reachable → ``limited`` (offer ``trust add``) — it *can* be monitored
        once the user grants the domain, so it is not a hard block;
      * no extractable content AND no feed → ``blocked`` (nothing to diff);
      * needs JS render or content-diff → ``limited`` (heavier but workable);
      * feed or etag + static extract → ``good``.
    """
    if not robots_ok:
        return "blocked", f"robots.txt disallows monitoring {host!r}"
    if fetch_failed:
        return "blocked", "page could not be fetched (network/transport error)"
    if not reachable:
        return (
            "limited",
            f"host {host!r} is not on the egress allowlist — "
            f"run `lighthouse trust add {trust_hint}` to enable monitoring",
        )
    if extract_tier == "none" and change_method != "feed":
        return (
            "blocked",
            "no extractable content and no feed — page likely paywalled, "
            "empty, or fully client-rendered",
        )

    if change_method == "feed":
        return "good", "good to monitor (feed available)"
    if extract_tier == "static" and change_method == "etag":
        return "good", "good to monitor (ETag/Last-Modified change signal)"
    if extract_tier == "static":
        return "limited", "monitorable via content-diff (no feed/ETag — heavier)"
    # extract_tier == "js"
    if change_method == "etag":
        return (
            "limited",
            "needs JS rendering for content, but an ETag/Last-Modified header "
            "gives a cheap change signal",
        )
    return (
        "limited",
        "needs Tier-B JS rendering and content-diff (heaviest reliable path)",
    )
