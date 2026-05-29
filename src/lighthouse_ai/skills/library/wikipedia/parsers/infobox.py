"""Wikipedia infobox parser — pure Python, deterministic, no network.

Parses the first ``{{Infobox ...}}`` template from raw wikitext into a plain
``dict[str, str]``.  The implementation handles:

* Nested templates (``{{...}}``) — treated as opaque and included verbatim in
  the value so callers can post-process them without losing data.
* Nested wiki links (``[[...|display]]``) — the display text (or the target if
  no pipe) is kept.
* Leading/trailing whitespace in field names and values.
* Multi-line values (value continues on lines not starting with ``|`` or ``}}``)
* Ref tags (``<ref>...</ref>``) — stripped, including multi-line.

This is intentionally a best-effort parser.  Wikipedia wikitext is not formally
parseable without the full MediaWiki parser stack; this covers the 95% case for
well-formed infoboxes.  Unknown or malformed infoboxes return an empty dict
rather than raising.

Usage::

    from lighthouse_ai.skills.library.wikipedia.parsers.infobox import parse_infobox
    fields = parse_infobox(wikitext)
"""

from __future__ import annotations

import re

# ---- public API ------------------------------------------------------------

def parse_infobox(wikitext: str) -> dict[str, str]:
    """Extract the first infobox from ``wikitext`` and return its fields.

    Parameters
    ----------
    wikitext:
        Raw wikitext string (as returned by the MediaWiki Action API
        ``rvprop=content``).

    Returns
    -------
    dict[str, str]
        Field name → cleaned value mapping.  Empty dict when no infobox is
        found or the wikitext cannot be parsed.
    """
    body = _extract_infobox_body(wikitext)
    if body is None:
        return {}
    return _parse_fields(body)


# ---- internals -------------------------------------------------------------

# Matches the opening of any {{Infobox ...}} or {{infobox ...}} template.
_INFOBOX_OPEN = re.compile(r"\{\{\s*[Ii]nfobox\b", re.IGNORECASE)


def _extract_infobox_body(wikitext: str) -> str | None:
    """Return the text *between* the outer {{ and }} of the first infobox.

    Walks through the wikitext counting brace depth so nested templates are
    included rather than confusing the brace matcher.
    """
    m = _INFOBOX_OPEN.search(wikitext)
    if m is None:
        return None

    start = m.start()
    depth = 0
    i = start
    end = len(wikitext)
    while i < end:
        if wikitext[i : i + 2] == "{{":
            depth += 1
            i += 2
        elif wikitext[i : i + 2] == "}}":
            depth -= 1
            i += 2
            if depth == 0:
                # Return everything after the opening {{ ... up to the closing }}
                return wikitext[start + 2 : i - 2]
        else:
            i += 1
    # Unbalanced braces — return what we have up to the end.
    return wikitext[start + 2 :]


# Strips <ref ...>...</ref> blocks (single-line and multi-line).
_REF_RE = re.compile(r"<ref[^>]*>.*?</ref>", re.DOTALL | re.IGNORECASE)
# Self-closing refs: <ref ... />
_REF_SELF_RE = re.compile(r"<ref[^/]*/\s*>", re.IGNORECASE)
# Strip HTML comment blocks
_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
# Strip any remaining HTML tags
_HTML_TAG_RE = re.compile(r"<[^>]+>")
# Wiki link [[Target|Display]] or [[Target]]
_WIKILINK_RE = re.compile(r"\[\[(?:[^|\]]*\|)?([^\]]+)\]\]")
# Wikitext bold/italic markers
_WIKI_MARKUP_RE = re.compile(r"'{2,5}")
# Collapse runs of whitespace (but preserve single newlines for multi-value fields)
_MULTI_SPACE_RE = re.compile(r"[ \t]{2,}")
_TRAILING_NEWLINES_RE = re.compile(r"\n{2,}")


def _parse_fields(body: str) -> dict[str, str]:
    """Parse the infobox body (everything between {{ and }}) into a dict."""
    # Split into "field" chunks by lines starting with | that are not inside
    # nested templates.
    chunks = _split_on_pipes(body)
    fields: dict[str, str] = {}
    for chunk in chunks:
        chunk = chunk.strip()
        if not chunk or chunk.startswith("!"):
            continue
        # A field line is of the form: name = value
        eq_pos = chunk.find("=")
        if eq_pos == -1:
            continue
        name = chunk[:eq_pos].strip().lstrip("|").strip()
        value = chunk[eq_pos + 1 :].strip()
        if not name:
            continue
        value = _clean_value(value)
        fields[name] = value
    return fields


def _split_on_pipes(body: str) -> list[str]:
    """Split the infobox body on pipe characters that are NOT inside {{ }}.

    Each resulting chunk corresponds to one ``| field = value`` declaration
    (potentially multi-line).
    """
    parts: list[str] = []
    current: list[str] = []
    depth = 0
    i = 0
    n = len(body)

    while i < n:
        ch = body[i]
        if body[i : i + 2] == "{{":
            depth += 1
            current.append(body[i : i + 2])
            i += 2
        elif body[i : i + 2] == "}}":
            depth -= 1
            current.append(body[i : i + 2])
            i += 2
        elif ch == "|" and depth == 0:
            parts.append("".join(current))
            current = []
            i += 1
        else:
            current.append(ch)
            i += 1

    if current:
        parts.append("".join(current))
    return parts


def _clean_value(value: str) -> str:
    """Strip wikitext markup from a field value."""
    # Remove refs
    value = _REF_RE.sub("", value)
    value = _REF_SELF_RE.sub("", value)
    # Remove comments
    value = _COMMENT_RE.sub("", value)
    # Resolve wikilinks: keep display text
    value = _WIKILINK_RE.sub(r"\1", value)
    # Strip remaining HTML tags
    value = _HTML_TAG_RE.sub("", value)
    # Strip wiki markup (bold/italic)
    value = _WIKI_MARKUP_RE.sub("", value)
    # Collapse whitespace
    value = _MULTI_SPACE_RE.sub(" ", value)
    value = _TRAILING_NEWLINES_RE.sub("\n", value)
    return value.strip()
