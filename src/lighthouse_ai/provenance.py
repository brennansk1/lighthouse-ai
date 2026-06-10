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
        # Write the record and its newline in ONE ``write`` call. Two separate
        # writes can be interrupted by a crash between them, leaving a JSON
        # object with no trailing newline; the next append would then run onto
        # the same line and ``load_provenance`` would fail to parse the whole
        # file (losing *every* record, not just the last). A single write keeps
        # the "lose at most the final line" guarantee the module promises.
        with p.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, sort_keys=True) + "\n")

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
    raw_lines = p.read_text(encoding="utf-8").splitlines()
    out: list[dict[str, Any]] = []
    for i, line in enumerate(raw_lines):
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            # A crash mid-append can leave a torn *final* line. The module's
            # durability contract is "lose at most the final line", so we
            # tolerate an unparseable last line and stop. An unparseable line
            # in the *middle* is genuine corruption/tampering — re-raise it.
            if i == len(raw_lines) - 1:
                break
            raise
    return out


# ── per-run sidecar ────────────────────────────────────────────────────────────


def build_run_sidecar(
    *,
    draft_id: str,
    job_id: str,
    question: str,
    mode: str,
    backends: dict[str, str],
    source_count: int,
    content_hash: str | None = None,
    started_at: datetime | str | None = None,
    ended_at: datetime | str | None = None,
    models: list[str] | None = None,
    sampling: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a PROV-O JSON document for a single research run.

    WHY a separate sidecar (not just an appended JSONL entry): a per-run
    ``.prov.json`` file travels *with* the draft artefact. It is
    self-contained, human-readable, and addressable by draft_id, so claim
    traceability requires only the draft file + its sibling sidecar rather
    than a query against the global ``provenance.jsonl`` log.

    Structure (PROV-O §27.7):
    - ``prov:Activity`` — the research run (job_id), with start/end times.
    - ``prov:Agent`` entries — one per model/backend (``wasAttributedTo``).
    - ``prov:Entity`` entries — the draft artefact + source slots.
    - Top-level ``content_hash`` (SHA-256 of the body) for drift detection.

    ``sampling`` (optional) records the effective generation-steerability
    params — e.g. ``{"locked": true, "roles": {"planner": {"seed": 0,
    "temperature": 0.0, ...}}}`` from ``Gateway.sampling_provenance()`` — so a
    run is reproducible-on-paper: a researcher can re-pin the exact seed /
    temperature / top_p that produced this artefact. Omitting it (the default)
    leaves the sidecar shape unchanged.

    The document is a standard Python dict, ready for ``json.dumps``.
    """
    activity_id = f"run:{job_id}"
    draft_urn = _urn_for_generated(draft_id)

    # One agent URN per backend/model listed.
    agent_urns: list[dict[str, str]] = []
    for role, tag in (backends or {}).items():
        agent_urns.append(
            {"@id": _urn("agent", f"{role}:{tag}"), "prov:label": f"{role}={tag}"}
        )
    for m in models or []:
        agent_urns.append(
            {"@id": _urn_for_model(m), "@type": "prov:Agent", "prov:label": m}
        )

    # Source slot entities: we don't have individual source IDs at this call
    # site, so we mint ``source_count`` placeholder entity URNs keyed by index.
    # This preserves the PROV-O cardinality (used[] length matches source_count)
    # while remaining deterministic and offline.
    source_urns = [_urn("source", f"{job_id}:{i}") for i in range(source_count)]

    activity: dict[str, Any] = {
        "@context": PROV_CONTEXT,
        "@id": _urn("action", activity_id),
        "@type": "prov:Activity",
        "prov:wasAssociatedWith": [a["@id"] for a in agent_urns],
        "prov:used": source_urns,
        "prov:generated": draft_urn,
        "lighthouse:mode": mode,
        "lighthouse:jobId": job_id,
        "lighthouse:question": question,
    }
    started = _iso_utc(started_at)
    ended = _iso_utc(ended_at)
    if started is not None:
        activity["prov:startedAtTime"] = started
    if ended is not None:
        activity["prov:endedAtTime"] = ended

    draft_entity: dict[str, Any] = {
        "@id": draft_urn,
        "@type": "prov:Entity",
        "prov:wasGeneratedBy": _urn("action", activity_id),
        "lighthouse:draftId": draft_id,
    }
    if content_hash is not None:
        draft_entity["lighthouse:contentHash"] = content_hash

    source_entities: list[dict[str, str]] = [
        {"@id": u, "@type": "prov:Entity"} for u in source_urns
    ]

    if sampling is not None:
        # Record the steerability config on the activity (the thing the params
        # governed) and at top level for easy lookup by reproducibility tooling.
        activity["lighthouse:sampling"] = sampling

    sidecar: dict[str, Any] = {
        "@context": PROV_CONTEXT,
        "lighthouse:draftId": draft_id,
        "lighthouse:jobId": job_id,
        "lighthouse:sourceCount": source_count,
        "lighthouse:contentHash": content_hash,
        "activity": activity,
        "agents": agent_urns,
        "draftEntity": draft_entity,
        "sourceEntities": source_entities,
    }
    if sampling is not None:
        sidecar["lighthouse:sampling"] = sampling
    return sidecar


def write_run_sidecar(
    sidecar_path: str | Path,
    sidecar: dict[str, Any],
) -> None:
    """Write a PROV-O run sidecar to *sidecar_path*.

    The file is written atomically: we write to a ``.tmp`` sibling first and
    rename, so a crash mid-write never leaves a half-written sidecar that
    could confuse downstream readers. ``sort_keys=True`` keeps the output
    content-stable for diffing / hashing.

    WHY a plain ``.prov.json`` (not JSONL): the sidecar is a single document
    that travels with one artefact. JSONL is used for the global append-only
    log because appends are O(1); here we write exactly once per draft.
    """
    dest = Path(sidecar_path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    # Append ".tmp" to the FULL name: with_suffix() would replace only the
    # final suffix ("d-x.prov.json" → "d-x.prov.prov.tmp"), and two dests
    # differing only in their last suffix would collide on one tmp path.
    tmp = dest.with_name(dest.name + ".tmp")
    try:
        tmp.write_text(json.dumps(sidecar, sort_keys=True, indent=2), encoding="utf-8")
        tmp.replace(dest)
    finally:
        # Clean up the .tmp file if the rename didn't happen (e.g. on error).
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass


def load_run_sidecar(sidecar_path: str | Path) -> dict[str, Any]:
    """Read a per-run ``.prov.json`` sidecar back into a dict.

    Returns an empty dict when the file is missing, matching the tolerant
    contract of :func:`load_provenance`.
    """
    p = Path(sidecar_path)
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))  # type: ignore[return-value]
