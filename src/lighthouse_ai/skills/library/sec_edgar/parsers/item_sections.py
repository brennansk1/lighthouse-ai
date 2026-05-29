"""10-K Item-section segmenters — pure Python, deterministic, no network.

Extracts named Item sections from SEC 10-K filing text (plain text or
lightly-stripped HTML).  The approach is deterministic text-segmentation:
locate the *start* of the target Item header, then locate the *end* at the
next Item header of equal or higher numbering, and return the slice between.

Design decisions
----------------
* **Plain text and HTML both work.** EDGAR filings come as either bare .txt
  files or as HTML exhibits.  This parser strips HTML tags with a simple regex
  before matching, so callers can pass either form.
* **Robust header matching.** Item headers appear in many typographic variants:
  "ITEM 1A.", "Item 1A.", "Item 1A —", "Item 1A Risk Factors" (no period),
  with varying amounts of surrounding whitespace, sometimes all-caps.  The
  regex patterns accept the common variants seen in real filings.
* **Section boundary.** The parser stops at the next Item header that is a
  *sibling* (same Part) or later in document order.  This avoids including
  later Items in the output.  A small boundary corpus is encoded in the
  ``_NEXT_ITEM_PATTERNS`` dicts — only patterns *after* the target in standard
  10-K Part order are included.
* **Empty / not-found returns empty string.** Callers should treat an empty
  return as "section not found or could not be extracted".

Usage::

    from lighthouse_ai.skills.library.sec_edgar.parsers.item_sections import (
        parse_10k_item_1a,
        parse_10k_item_7,
    )

    text = open("apple_10k.txt").read()
    risk_factors = parse_10k_item_1a(text)
    mda = parse_10k_item_7(text)
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# HTML strip
# ---------------------------------------------------------------------------

_HTML_TAG_RE = re.compile(r"<[^>]+>", re.DOTALL)
_NBSP_RE = re.compile(r"&nbsp;|&#160;", re.IGNORECASE)
_AMP_RE = re.compile(r"&amp;", re.IGNORECASE)
_HTML_ENTITY_RE = re.compile(r"&[a-zA-Z]{2,8};")
_MULTI_BLANK_LINES_RE = re.compile(r"\n{3,}")


def _strip_html(text: str) -> str:
    """Remove HTML tags and common entities; normalise whitespace."""
    text = _HTML_TAG_RE.sub(" ", text)
    text = _NBSP_RE.sub(" ", text)
    text = _AMP_RE.sub("&", text)
    text = _HTML_ENTITY_RE.sub(" ", text)
    # Collapse runs of more than two blank lines
    text = _MULTI_BLANK_LINES_RE.sub("\n\n", text)
    return text


# ---------------------------------------------------------------------------
# Header pattern helpers
# ---------------------------------------------------------------------------

# A single compiled pattern that matches an "Item N" or "Item NA" header line.
# Groups:
#   1 — the item number/letter token (e.g. "1a", "7", "9a")
#
# The pattern tolerates:
#   • ITEM / Item (case-insensitive via flag)
#   • optional whitespace between "Item" and the number/letter
#   • number optionally followed by a letter (e.g. 1A, 9A)
#   • optional period, dash, or em-dash after the token
#   • the header may appear on its own line or inline (we use re.MULTILINE +
#     look for start-of-line optionally preceded only by whitespace)
_ITEM_HEADER_RE = re.compile(
    r"(?m)^[ \t]*(?:ITEM|Item)\s+(\d+[A-Za-z]?)\b",
)


def _make_item_start_pattern(item_token: str) -> re.Pattern[str]:
    """Compile a pattern matching the opening header of a specific Item.

    ``item_token`` should be the canonical form like "1A" or "7".
    The pattern is case-insensitive.
    """
    # Escape the token in case it contains regex metacharacters (it won't, but
    # defensive programming is cheap here).
    tok = re.escape(item_token)
    return re.compile(
        rf"(?im)^[ \t]*(?:ITEM|Item)\s+{tok}\b[^\n]*",
    )


def _find_section(text: str, start_token: str, end_tokens: list[str]) -> str:
    """Return the text slice between the start-Item header and the first end-Item header.

    Parameters
    ----------
    text:
        Pre-processed (HTML-stripped) filing text.
    start_token:
        The Item identifier to start at (e.g. "1A", "7").  Case-insensitive.
    end_tokens:
        Ordered list of Item identifiers that delimit the end of the target
        section (e.g. ["1B", "2", "3"] for Item 1A).  The earliest match wins.

    Returns
    -------
    str
        The extracted section text, stripped of leading/trailing whitespace.
        Empty string if the start header is not found.
    """
    start_pat = _make_item_start_pattern(start_token)
    start_match = start_pat.search(text)
    if start_match is None:
        return ""

    # Begin scanning from the *end* of the start-header line so the header
    # itself is included in the output.
    section_start = start_match.start()

    # Find the earliest end-token match after section_start.
    end_pos: int | None = None
    for token in end_tokens:
        end_pat = _make_item_start_pattern(token)
        end_match = end_pat.search(text, section_start + len(start_match.group()))
        if end_match is not None:
            if end_pos is None or end_match.start() < end_pos:
                end_pos = end_match.start()

    if end_pos is not None:
        return text[section_start:end_pos].strip()
    # No end marker found — return to end of document.
    return text[section_start:].strip()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_10k_item_1a(filing_text: str) -> str:
    """Extract Item 1A — Risk Factors from a 10-K filing.

    Parameters
    ----------
    filing_text:
        The raw text or HTML of the 10-K (or a relevant exhibit).  HTML is
        automatically stripped before parsing.

    Returns
    -------
    str
        The text of the Risk Factors section, beginning with the Item 1A
        header line and ending just before Item 1B (Unresolved Staff
        Comments) or Item 2 (Properties), whichever appears first.
        Returns an empty string if the section cannot be located.

    Notes
    -----
    The standard 10-K structure (Part I) is::

        Item 1.   Business
        Item 1A.  Risk Factors          ← this function returns this section
        Item 1B.  Unresolved Staff Comments
        Item 2.   Properties
        ...

    Some smaller filers omit Item 1B; in that case the boundary is Item 2.
    """
    clean = _strip_html(filing_text)
    return _find_section(clean, "1A", ["1B", "2", "3", "4", "5", "6", "7", "8", "9"])


def parse_10k_item_7(filing_text: str) -> str:
    """Extract Item 7 — MD&A (Management's Discussion and Analysis) from a 10-K.

    Parameters
    ----------
    filing_text:
        The raw text or HTML of the 10-K (or a relevant exhibit).  HTML is
        automatically stripped before parsing.

    Returns
    -------
    str
        The text of the MD&A section, beginning with the Item 7 header line
        and ending just before Item 7A (Quantitative and Qualitative
        Disclosures About Market Risk) or Item 8 (Financial Statements),
        whichever appears first.
        Returns an empty string if the section cannot be located.

    Notes
    -----
    The standard 10-K structure (Part II) is::

        Item 5.   Market for Registrant's Common Equity...
        Item 6.   [Reserved] / Selected Financial Data
        Item 7.   MD&A                          ← this function returns this section
        Item 7A.  Quantitative / Qualitative Disclosures About Market Risk
        Item 8.   Financial Statements and Supplementary Data
        ...
    """
    clean = _strip_html(filing_text)
    return _find_section(clean, "7", ["7A", "8", "9", "9A", "10", "11", "12", "13", "14", "15"])
