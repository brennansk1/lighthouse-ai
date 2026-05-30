"""Content-diff + trigger-criteria evaluation for Watch v2 (FUTURE_FEATURES §1).

Once a website passes the scrapability pre-flight
(:mod:`lighthouse_ai.sources.scrapability`), the Watch engine takes a periodic
:class:`Snapshot` of the page and asks: *did this change in a way the user said
they care about?* That decision is a small, pure rule engine — this module.

Everything here is **pure and deterministic**: no I/O, no clock, no hidden
state. The caller (the watchable skill / monitor session) is responsible for
fetching, building snapshots, and persisting the previous snapshot; this module
only compares two snapshots against a criteria spec.

Supported trigger kinds (``criteria["kind"]``):

  * ``any_change`` — the content hash differs.
  * ``keyword`` — the *new* text contains one of ``terms`` that the old text
    did not (``require_new=False`` matches on mere presence in the new text).
  * ``selector_text`` — a named, simple text *region* changed. To stay usable by
    non-technical users (and dependency-free) a "selector" here is a documented
    substring/anchor pair, not raw XPath: ``before``/``after`` delimit the region
    of interest, and we compare the slice between them. If no region is found the
    trigger reports ``matched=False`` with a reason (a broken selector
    self-reports instead of silently passing).
  * ``threshold`` — a numeric value parsed from the page (the first number after
    an optional ``label``, or matched by ``pattern``) crosses a bound
    (``above`` / ``below`` / ``equals`` / ``changed``).

Plus :func:`content_diff` — an added/removed line summary used both by the
``any_change`` surfacing and by the UI's "what changed" panel.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# Snapshot
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Snapshot:
    """One observation of a monitored page.

    ``fetched_at`` is supplied by the caller (ISO-8601 string) — this module
    never calls a clock, so a snapshot is fully reproducible from its inputs.
    ``content_hash`` is derived from ``text`` when not supplied explicitly.
    """

    text: str
    fetched_at: str
    content_hash: str = ""
    url: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.content_hash:
            object.__setattr__(self, "content_hash", hash_text(self.text))

    def as_dict(self) -> dict[str, Any]:
        """Serialise for persistence in ``state.db`` (per-monitor snapshot)."""
        return {
            "text": self.text,
            "fetched_at": self.fetched_at,
            "content_hash": self.content_hash,
            "url": self.url,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Snapshot:
        """Rebuild a snapshot the caller previously persisted via :meth:`as_dict`."""
        return cls(
            text=data.get("text", ""),
            fetched_at=data.get("fetched_at", ""),
            content_hash=data.get("content_hash", ""),
            url=data.get("url", ""),
            metadata=dict(data.get("metadata", {})),
        )


def hash_text(text: str) -> str:
    """Stable SHA-256 of normalised page text (the content-hash change signal)."""
    return hashlib.sha256(text.strip().encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# TriggerResult
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TriggerResult:
    """Outcome of evaluating one criteria spec against a snapshot pair."""

    matched: bool
    kind: str
    reason: str
    details: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "matched": self.matched,
            "kind": self.kind,
            "reason": self.reason,
            "details": dict(self.details),
        }


# ---------------------------------------------------------------------------
# content_diff
# ---------------------------------------------------------------------------


def content_diff(old_text: str, new_text: str) -> dict[str, Any]:
    """Return an added/removed line summary between two text blobs.

    Line-oriented and set-based (order-insensitive within the changed set), which
    is the right granularity for "what showed up / what dropped off" on a page —
    a new headline, a removed status row. Blank lines are ignored.

    Returns a dict with ``added``, ``removed`` (lists of lines), and the
    convenience counts ``n_added`` / ``n_removed`` / ``changed`` (bool).
    """
    old_lines = [ln.strip() for ln in old_text.splitlines() if ln.strip()]
    new_lines = [ln.strip() for ln in new_text.splitlines() if ln.strip()]
    old_set = set(old_lines)
    new_set = set(new_lines)
    # Preserve first-seen order from the respective source for readability.
    added = [ln for ln in new_lines if ln not in old_set]
    removed = [ln for ln in old_lines if ln not in new_set]
    # De-dup while preserving order.
    added = list(dict.fromkeys(added))
    removed = list(dict.fromkeys(removed))
    return {
        "added": added,
        "removed": removed,
        "n_added": len(added),
        "n_removed": len(removed),
        "changed": bool(added or removed),
    }


# ---------------------------------------------------------------------------
# evaluate_trigger
# ---------------------------------------------------------------------------


def evaluate_trigger(
    old_snapshot: Snapshot | None,
    new_snapshot: Snapshot,
    criteria: dict[str, Any],
) -> TriggerResult:
    """Evaluate *criteria* against the (old, new) snapshot pair.

    Dispatches on ``criteria["kind"]``. ``old_snapshot=None`` means "first tick,
    no prior observation"; by convention the first tick does **not** fire an
    alert (there is nothing to compare against) — it establishes the baseline.
    The one exception is ``keyword`` with ``require_new=False``, which can match
    on mere presence in the new text even on the first tick.

    Unknown kinds return a non-matching result with an explanatory reason rather
    than raising, so a malformed criteria spec degrades visibly, not silently.
    """
    kind = str(criteria.get("kind", "")).lower()

    if kind == "any_change":
        return _eval_any_change(old_snapshot, new_snapshot)
    if kind == "keyword":
        return _eval_keyword(old_snapshot, new_snapshot, criteria)
    if kind == "selector_text":
        return _eval_selector_text(old_snapshot, new_snapshot, criteria)
    if kind == "threshold":
        return _eval_threshold(old_snapshot, new_snapshot, criteria)

    return TriggerResult(
        matched=False,
        kind=kind or "unknown",
        reason=f"unknown trigger kind {kind!r}",
    )


def _eval_any_change(
    old: Snapshot | None, new: Snapshot
) -> TriggerResult:
    if old is None:
        return TriggerResult(
            matched=False,
            kind="any_change",
            reason="first tick — baseline established, no prior snapshot",
        )
    changed = old.content_hash != new.content_hash
    diff = content_diff(old.text, new.text) if changed else {}
    return TriggerResult(
        matched=changed,
        kind="any_change",
        reason="content hash changed" if changed else "content hash unchanged",
        details={"diff": diff} if changed else {},
    )


def _eval_keyword(
    old: Snapshot | None, new: Snapshot, criteria: dict[str, Any]
) -> TriggerResult:
    terms_raw = criteria.get("terms") or criteria.get("term") or []
    if isinstance(terms_raw, str):
        terms = [terms_raw]
    else:
        terms = [str(t) for t in terms_raw]
    if not terms:
        return TriggerResult(
            matched=False, kind="keyword", reason="no terms supplied"
        )
    require_new = bool(criteria.get("require_new", True))
    case_sensitive = bool(criteria.get("case_sensitive", False))

    new_text = new.text if case_sensitive else new.text.lower()
    old_text = (
        (old.text if case_sensitive else old.text.lower()) if old is not None else ""
    )

    hits: list[str] = []
    for term in terms:
        needle = term if case_sensitive else term.lower()
        in_new = needle in new_text
        if not in_new:
            continue
        if require_new:
            # Only fire if the term is newly present (absent before).
            if old is not None and needle in old_text:
                continue
        hits.append(term)

    matched = bool(hits)
    if matched:
        reason = f"matched keyword(s): {', '.join(hits)}"
    elif require_new and old is None:
        reason = "no matching keywords (first tick, require_new)"
    else:
        reason = "no matching keywords"
    return TriggerResult(
        matched=matched,
        kind="keyword",
        reason=reason,
        details={"hits": hits},
    )


def _extract_region(text: str, before: str, after: str) -> str | None:
    """Return the text slice between *before* and *after* anchors.

    Empty *before* means "from start"; empty *after* means "to end". Returns
    ``None`` when an anchor is present but not found — a broken selector.
    """
    start = 0
    if before:
        idx = text.find(before)
        if idx == -1:
            return None
        start = idx + len(before)
    if after:
        idx = text.find(after, start)
        if idx == -1:
            return None
        return text[start:idx]
    return text[start:]


def _eval_selector_text(
    old: Snapshot | None, new: Snapshot, criteria: dict[str, Any]
) -> TriggerResult:
    name = str(criteria.get("name", "region"))
    before = str(criteria.get("before", ""))
    after = str(criteria.get("after", ""))
    contains = criteria.get("contains")

    new_region = _extract_region(new.text, before, after)
    if new_region is None:
        return TriggerResult(
            matched=False,
            kind="selector_text",
            reason=(
                f"selector {name!r} not found on the page — the region anchors "
                "may have broken (layout change); monitor needs re-checking"
            ),
            details={"selector": name, "broken": True},
        )
    new_region = new_region.strip()

    # Mode A: watch for a substring appearing in the region.
    if contains is not None:
        needle = str(contains)
        present = needle in new_region
        old_present = False
        if old is not None:
            old_region = _extract_region(old.text, before, after)
            old_present = old_region is not None and needle in old_region
        matched = present and not old_present
        return TriggerResult(
            matched=matched,
            kind="selector_text",
            reason=(
                f"selector {name!r} now contains {needle!r}"
                if matched
                else f"selector {name!r} unchanged w.r.t. {needle!r}"
            ),
            details={"selector": name, "region": new_region},
        )

    # Mode B: watch for the region's text changing at all.
    if old is None:
        return TriggerResult(
            matched=False,
            kind="selector_text",
            reason=f"first tick — baseline captured for selector {name!r}",
            details={"selector": name, "region": new_region},
        )
    old_region = _extract_region(old.text, before, after)
    old_norm = old_region.strip() if old_region is not None else None
    changed = old_norm != new_region
    return TriggerResult(
        matched=changed,
        kind="selector_text",
        reason=(
            f"selector {name!r} text changed"
            if changed
            else f"selector {name!r} text unchanged"
        ),
        details={"selector": name, "old": old_norm, "new": new_region},
    )


_NUMBER_RE = re.compile(r"[-+]?\d[\d,]*(?:\.\d+)?")


def _parse_number(
    text: str, *, label: str = "", pattern: str = ""
) -> float | None:
    """Parse a numeric value from *text*.

    With ``pattern`` (a regex with one capture group) the captured group is
    parsed. With ``label`` the first number *after* the label substring is
    taken. Otherwise the first number anywhere in the text. Returns ``None``
    when no number is found.
    """
    target = text
    if pattern:
        m = re.search(pattern, text)
        if not m:
            return None
        target = m.group(1) if m.groups() else m.group(0)
        num = _NUMBER_RE.search(target)
        return _to_float(num.group(0)) if num else _to_float(target)
    if label:
        idx = text.find(label)
        if idx == -1:
            return None
        target = text[idx + len(label) :]
    m = _NUMBER_RE.search(target)
    return _to_float(m.group(0)) if m else None


def _to_float(raw: str) -> float | None:
    try:
        return float(raw.replace(",", ""))
    except ValueError:  # pragma: no cover - guarded by the regex
        return None


def _eval_threshold(
    old: Snapshot | None, new: Snapshot, criteria: dict[str, Any]
) -> TriggerResult:
    label = str(criteria.get("label", ""))
    pattern = str(criteria.get("pattern", ""))
    new_val = _parse_number(new.text, label=label, pattern=pattern)
    if new_val is None:
        return TriggerResult(
            matched=False,
            kind="threshold",
            reason="no numeric value found on the page for this threshold",
            details={"label": label, "pattern": pattern},
        )

    details: dict[str, Any] = {"value": new_val}

    if "above" in criteria:
        bound = float(criteria["above"])
        matched = new_val > bound
        return TriggerResult(
            matched=matched,
            kind="threshold",
            reason=(
                f"value {new_val} is above {bound}"
                if matched
                else f"value {new_val} is not above {bound}"
            ),
            details={**details, "bound": bound, "op": "above"},
        )
    if "below" in criteria:
        bound = float(criteria["below"])
        matched = new_val < bound
        return TriggerResult(
            matched=matched,
            kind="threshold",
            reason=(
                f"value {new_val} is below {bound}"
                if matched
                else f"value {new_val} is not below {bound}"
            ),
            details={**details, "bound": bound, "op": "below"},
        )
    if "equals" in criteria:
        bound = float(criteria["equals"])
        matched = new_val == bound
        return TriggerResult(
            matched=matched,
            kind="threshold",
            reason=(
                f"value {new_val} equals {bound}"
                if matched
                else f"value {new_val} does not equal {bound}"
            ),
            details={**details, "bound": bound, "op": "equals"},
        )

    # "changed" — the parsed value moved since the prior snapshot.
    if old is None:
        return TriggerResult(
            matched=False,
            kind="threshold",
            reason="first tick — baseline value captured",
            details={**details, "op": "changed"},
        )
    old_val = _parse_number(old.text, label=label, pattern=pattern)
    matched = old_val is not None and old_val != new_val
    return TriggerResult(
        matched=matched,
        kind="threshold",
        reason=(
            f"value changed {old_val} → {new_val}"
            if matched
            else f"value unchanged ({new_val})"
        ),
        details={**details, "old": old_val, "op": "changed"},
    )
