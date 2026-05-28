"""Deterministic pre-context payload compaction (OpenHuman §5, TokenJuice-style).

Mechanical, per-payload, LLM-free compaction of fetched sources and tool output
*before* they enter the LLM context — complementary to ReSum's semantic, per-round
compaction. Cuts tokens (cost + latency + context-rot) via JSON-configurable rules
with a three-layer overlay:

    builtin (packaged) < user (~/.config/lighthouse/compaction/) < project (./.lighthouse/compaction/)

Same-``id``, higher-layer wins. We re-implement the overlay architecture and ship
our own research-domain rules; we do NOT copy ``vincentkoc/tokenjuice``'s builtin
rule JSON (license must be cleared before lifting any rule files).

All transforms operate on ``str`` (Unicode code points), never bytes, so multi-byte
text (CJK, emoji) is never split mid-character.
"""

from __future__ import annotations

import html as _html
import json
import os
import re
from dataclasses import dataclass, field
from fnmatch import fnmatch
from pathlib import Path

__all__ = [
    "BUILTIN_RULES",
    "CompactionRule",
    "CompactionStats",
    "compact",
    "estimate_tokens",
    "load_rules",
    "looks_like_html",
]

_HTML_TAG_RE = re.compile(
    r"</?(html|body|head|div|p|span|script|style|a|table|tr|td|ul|ol|li|h[1-6]|br|img)\b",
    re.IGNORECASE,
)


def looks_like_html(text: str) -> bool:
    """True when the payload contains real HTML tags (not just a stray '<')."""
    return _HTML_TAG_RE.search(text) is not None


@dataclass(frozen=True)
class CompactionRule:
    id: str
    match: str  # glob against source domain / tool name / content-type ("*" = all)
    transform: str  # html2md | dedupe_lines | shorten_urls | strip_boilerplate | regex_sub
    params: dict = field(default_factory=dict)


@dataclass(frozen=True)
class CompactionStats:
    orig_tokens: int
    new_tokens: int

    @property
    def ratio(self) -> float:
        """Fraction of tokens removed (0.0 = no change, 1.0 = everything)."""
        if self.orig_tokens == 0:
            return 0.0
        return max(0.0, 1.0 - self.new_tokens / self.orig_tokens)


# Our own research-domain default ruleset (not copied from tokenjuice).
BUILTIN_RULES: list[CompactionRule] = [
    CompactionRule("html-to-markdown", "*", "html2md"),
    CompactionRule("strip-boilerplate", "*", "strip_boilerplate"),
    CompactionRule("dedupe-lines", "*", "dedupe_lines"),
    CompactionRule("shorten-urls", "*", "shorten_urls"),
]


def estimate_tokens(text: str) -> int:
    """Cheap, deterministic token proxy (~4 chars/token)."""
    return max(0, len(text) // 4)


# --- transforms ------------------------------------------------------------

_SCRIPT_STYLE_RE = re.compile(r"<(script|style)\b[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
_BLOCK_BREAK_RE = re.compile(r"</(p|div|li|h[1-6]|tr|br)\s*>|<br\s*/?>", re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")
_MULTI_BLANK_RE = re.compile(r"\n{3,}")
_URL_RE = re.compile(r"https?://([^\s/]+)(/\S*)?")

_BOILERPLATE_PATTERNS = [
    re.compile(r"^\s*skip to (main )?content\s*$", re.IGNORECASE),
    re.compile(r"^\s*cookie(s)? (policy|notice|settings).*$", re.IGNORECASE),
    re.compile(r"^\s*(all rights reserved|©|copyright \d{4}).*$", re.IGNORECASE),
    re.compile(r"^\s*(subscribe|sign up) (now|today|to our newsletter).*$", re.IGNORECASE),
    re.compile(r"^\s*(share|tweet|follow us) on (twitter|facebook|linkedin).*$", re.IGNORECASE),
]


def _html2md(text: str, params: dict) -> str:
    text = _SCRIPT_STYLE_RE.sub("", text)
    text = _BLOCK_BREAK_RE.sub("\n", text)
    text = _TAG_RE.sub("", text)
    text = _html.unescape(text)
    text = _MULTI_BLANK_RE.sub("\n\n", text)
    # Trim trailing whitespace per line without touching multi-byte content.
    text = "\n".join(line.rstrip() for line in text.split("\n"))
    return text.strip()


def _dedupe_lines(text: str, params: dict) -> str:
    # Drop a non-blank line equal to the previous non-blank kept line (even when
    # separated by blanks — common after HTML→text), and collapse blank runs.
    out: list[str] = []
    prev_nonblank: str | None = None
    for line in text.split("\n"):
        key = line.strip()
        if key == "":
            if out and out[-1].strip() == "":
                continue
            out.append(line)
            continue
        if key == prev_nonblank:
            continue
        out.append(line)
        prev_nonblank = key
    return "\n".join(out).strip()


def _shorten_urls(text: str, params: dict) -> str:
    # Keep the domain (provenance) but drop long path+query. Idempotent: the
    # replacement has no scheme, so it won't re-match.
    return _URL_RE.sub(lambda m: m.group(1), text)


def _strip_boilerplate(text: str, params: dict) -> str:
    extra = [re.compile(p, re.IGNORECASE) for p in params.get("patterns", [])]
    patterns = _BOILERPLATE_PATTERNS + extra
    out = [ln for ln in text.split("\n") if not any(p.match(ln) for p in patterns)]
    return "\n".join(out)


def _regex_sub(text: str, params: dict) -> str:
    pattern = params.get("pattern")
    if not pattern:
        return text
    repl = params.get("repl", "")
    flags = re.IGNORECASE if params.get("ignorecase") else 0
    return re.sub(pattern, repl, text, flags=flags)


_TRANSFORMS = {
    "html2md": _html2md,
    "dedupe_lines": _dedupe_lines,
    "shorten_urls": _shorten_urls,
    "strip_boilerplate": _strip_boilerplate,
    "regex_sub": _regex_sub,
}


# --- rule loading (three-layer overlay) ------------------------------------


def _read_rule_dir(directory: Path) -> list[CompactionRule]:
    rules: list[CompactionRule] = []
    if not directory.is_dir():
        return rules
    for path in sorted(directory.glob("*.json")):
        try:
            data = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        for entry in data if isinstance(data, list) else [data]:
            try:
                rules.append(CompactionRule(
                    id=entry["id"], match=entry.get("match", "*"),
                    transform=entry["transform"], params=entry.get("params", {}),
                ))
            except (KeyError, TypeError):
                continue
    return rules


def load_rules(
    *, user_dir: Path | None = None, project_dir: Path | None = None
) -> list[CompactionRule]:
    """Merge builtin < user < project rules; same-``id`` higher layer wins."""
    if user_dir is None:
        user_dir = Path(
            os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")
        ) / "lighthouse" / "compaction"
    if project_dir is None:
        project_dir = Path.cwd() / ".lighthouse" / "compaction"

    merged: dict[str, CompactionRule] = {r.id: r for r in BUILTIN_RULES}
    for r in _read_rule_dir(user_dir):
        merged[r.id] = r
    for r in _read_rule_dir(project_dir):
        merged[r.id] = r
    return list(merged.values())


# --- main entry ------------------------------------------------------------


def compact(
    payload: str,
    *,
    source: str = "",
    content_type: str = "",
    rules: list[CompactionRule] | None = None,
) -> tuple[str, CompactionStats]:
    """Apply matching rules in order; return (compacted_text, stats).

    A rule matches when its ``match`` glob hits ``source`` or ``content_type``
    (or is ``"*"``). Grapheme-safe: all transforms operate on ``str``.
    """
    if rules is None:
        rules = load_rules()
    orig = estimate_tokens(payload)
    text = payload
    for rule in rules:
        if not (rule.match == "*"
                or fnmatch(source, rule.match)
                or fnmatch(content_type, rule.match)):
            continue
        fn = _TRANSFORMS.get(rule.transform)
        if fn is None:
            continue
        text = fn(text, rule.params)
    return text, CompactionStats(orig_tokens=orig, new_tokens=estimate_tokens(text))
