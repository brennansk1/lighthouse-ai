"""PROV-O JSON-LD provenance emission (design §27.7).

WHY: Reproducibility requires more than a flat audit log. The W3C PROV-O
ontology gives every significant agent action a machine-readable lineage
record — which agent ran it, which sources and tools it *used*, what artefact
it *generated*, and which model it was *attributed to*. Emitting these as
JSON-LD means the records are self-describing and can be exported alongside
research outputs as a ``provenance.json`` / ``provenance.jsonl`` sidecar and
ingested by external PROV-aware tooling without a bespoke schema.

We store records as JSON Lines (``provenance.jsonl``) rather than a single
JSON array so that appends are O(1) and a crash mid-write at worst loses the
final line instead of corrupting the whole document.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# The PROV-O namespace is the W3C Recommendation context. Using the canonical
# URL keeps records interoperable with external PROV consumers.
PROV_CONTEXT = "https://www.w3.org/ns/prov"

# URN prefixes give every entity a stable, dereferenceable-looking identifier
# without committing to a live HTTP namespace (this is a local-first tool).
URN_PREFIX = "urn:lighthouse"


def _urn(kind: str, value: str) -> str:
    """Build a Lighthouse URN, e.g. ``urn:lighthouse:agent:section_researcher``.

    WHY: PROV-O references are IRIs. We mint opaque URNs so provenance records
    never leak filesystem paths or other host-specific detail.
    """
    return f"{URN_PREFIX}:{kind}:{value}"


def _iso_utc(ts: datetime | str | None) -> str | None:
    """Normalise a timestamp to an ISO-8601 UTC string with a ``Z`` suffix.

    WHY: PROV ``startedAtTime``/``endedAtTime`` are xsd:dateTime. Mixing naive
    and aware datetimes is the classic reproducibility footgun, so we force
    UTC and a literal ``Z`` to keep records byte-stable across machines.
    """
    if ts is None:
        return None
    if isinstance(ts, str):
        return ts
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    ts = ts.astimezone(UTC)
    # Drop microseconds for stable, second-resolution timestamps.
    return ts.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def prov_activity(
    *,
    activity_id: str,
    agent: str,
    used: Iterable[str] | None = None,
    generated: str | None = None,
    attributed_to: str | None = None,
    started_at: datetime | str | None = None,
    ended_at: datetime | str | None = None,
) -> dict[str, Any]:
    """Build a single PROV-O ``prov:Activity`` record as a JSON-LD dict.

    Parameters mirror §27.7. Callers pass plain identifiers (an agent name, a
    list of source/tool ids, a model digest); this builder wraps them into
    canonical Lighthouse URNs so the wider system never has to remember the
    URN scheme.

    WHY each field:
      * ``wasAssociatedWith`` — the agent (software) that performed the action.
      * ``used`` — inputs consumed (sources, tools); a list per PROV.
      * ``generated`` — the artefact produced (a claim, draft, etc.).
      * ``wasAttributedTo`` — the *model* the output is attributed to, keyed by
        its content digest so drift is detectable from provenance alone.
      * start/end times bound the activity for latency / ordering analysis.
    """
    used_urns = [_urn_for_used(u) for u in (used or [])]
    record: dict[str, Any] = {
        "@context": PROV_CONTEXT,
        "@id": _urn("action", activity_id),
        "@type": "prov:Activity",
        "prov:wasAssociatedWith": _urn("agent", agent),
        "prov:used": used_urns,
    }
    if generated is not None:
        record["prov:generated"] = _urn_for_generated(generated)
    if attributed_to is not None:
        record["prov:wasAttributedTo"] = _urn_for_model(attributed_to)
    started = _iso_utc(started_at)
    ended = _iso_utc(ended_at)
    if started is not None:
        record["prov:startedAtTime"] = started
    if ended is not None:
        record["prov:endedAtTime"] = ended
    return record


def _urn_for_used(value: str) -> str:
    """Map a ``used`` input to a URN, preserving any caller-supplied URN.

    WHY: callers may already hold a full URN (e.g. a source digest). We only
    mint a new one when given a bare value so we never double-prefix.
    """
    if value.startswith(URN_PREFIX + ":"):
        return value
    return _urn("input", value)


def _urn_for_generated(value: str) -> str:
    if value.startswith(URN_PREFIX + ":"):
        return value
    return _urn("artifact", value)


def _urn_for_model(value: str) -> str:
    if value.startswith(URN_PREFIX + ":"):
        return value
    # Model attribution is keyed by content digest per §27 fingerprinting.
    return _urn("model", f"sha256:{value}")


@dataclass(frozen=True)
class ProvenanceLog:
    """Append-only writer/reader for ``provenance.jsonl`` under ``dir``.

    Frozen because the log's location is fixed at construction; mutating where
    we write provenance mid-run would itself be a reproducibility hazard.
    """

    dir: Path
    filename: str = "provenance.jsonl"

    @property
    def path(self) -> Path:
        return Path(self.dir) / self.filename

    def append(self, record: dict[str, Any]) -> None:
        """Append one PROV record as a single JSON line.

        WHY ``sort_keys``: stable key order makes the file content-addressable
        and diff-friendly, which matters when provenance is itself audited.
        """
        p = self.path
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, sort_keys=True))
            fh.write("\n")

    def append_activity(self, **kwargs: Any) -> dict[str, Any]:
        """Convenience: build a ``prov_activity`` and append it, returning it."""
        record = prov_activity(**kwargs)
        self.append(record)
        return record

    def load(self) -> list[dict[str, Any]]:
        """Read every record back, in write order."""
        return load_provenance(self.path)


def load_provenance(path: str | Path) -> list[dict[str, Any]]:
    """Read a ``provenance.jsonl`` file into a list of records, in order.

    WHY tolerant of a missing file: a job that emitted no provenance should
    yield an empty list rather than crash the replay/inspection tooling. Blank
    lines are skipped so a trailing newline never produces a spurious record.
    """
    p = Path(path)
    if not p.exists():
        return []
    out: list[dict[str, Any]] = []
    with p.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            out.append(json.loads(line))
    return out
