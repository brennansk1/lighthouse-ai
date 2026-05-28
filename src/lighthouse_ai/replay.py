"""Replay and reproducibility inspection over the audit log (design §27.8).

WHY: ``lighthouse replay <job_id>`` must reconstruct *exactly* which model
calls a job made, in order, and decide whether the job can be replayed
byte-for-byte against the models currently installed. A replay is only
byte-exact if every model the job used still has the same content digest as
the day it ran (§27 fingerprinting). If any model has drifted (re-pulled,
upgraded, cloud-sunset) the run is at best *structurally* reproducible.

This module is deliberately pure: it reads recorded ``model_call`` audit
events and compares their digests against an ``installed_digests`` map that
the *caller* supplies. It NEVER touches Ollama or loads a model — keeping the
inspection side-effect-free means it can run in CI, offline, or against an
archived audit.db with no runtime dependencies.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .persistence import open_db


@dataclass(frozen=True)
class ReplayStep:
    """One recorded model call within a job, in execution order.

    ``seq`` is the audit_events primary key — a monotonic surrogate that gives
    us a total order even when wall-clock ``ts`` values collide at second
    resolution. ``digest`` is the model's content fingerprint, the single
    value that determines byte-exact replayability.
    """

    seq: int
    job_id: str
    model: str
    digest: str
    backend: str | None
    prompt_tokens: int | None
    completion_tokens: int | None
    ts: str | None


@dataclass(frozen=True)
class ReplayTrace:
    """An ordered reconstruction of a job's model calls."""

    job_id: str
    steps: tuple[ReplayStep, ...]

    def __len__(self) -> int:
        return len(self.steps)

    @property
    def models(self) -> list[str]:
        """Distinct model strings used, in first-seen order.

        WHY first-seen order rather than sorted: replay planning cares about
        the sequence in which models are exercised, not the alphabet.
        """
        seen: list[str] = []
        for s in self.steps:
            if s.model not in seen:
                seen.append(s.model)
        return seen


@dataclass(frozen=True)
class StepVerdict:
    """Per-step replayability decision."""

    step: ReplayStep
    installed_digest: str | None
    replayable: bool
    drifted: bool

    @property
    def reason(self) -> str:
        if self.replayable:
            return "byte-exact: recorded digest matches installed digest"
        if self.installed_digest is None:
            return "not-installed: model has no installed digest"
        return "drifted: recorded digest differs from installed digest"


@dataclass(frozen=True)
class ReplayReport:
    """Aggregate verdict for a whole job."""

    job_id: str
    verdicts: tuple[StepVerdict, ...]

    @property
    def fully_replayable(self) -> bool:
        """True only if *every* step would replay byte-exact."""
        return all(v.replayable for v in self.verdicts)

    @property
    def drifted_steps(self) -> list[StepVerdict]:
        return [v for v in self.verdicts if v.drifted]

    @property
    def replayable_steps(self) -> list[StepVerdict]:
        return [v for v in self.verdicts if v.replayable]

    @property
    def first_divergence(self) -> StepVerdict | None:
        """The earliest non-replayable step, mirroring §27.8's "first divergence".

        WHY: when reporting to a user we lead with the first place the run
        stops being trustworthy; everything after it is suspect anyway.
        """
        for v in self.verdicts:
            if not v.replayable:
                return v
        return None


class ReplayDriftError(RuntimeError):
    """Raised by :func:`verify_replayable` when drift is found and not allowed.

    Carries the :class:`ReplayReport` so callers can still inspect exactly
    which steps drifted after catching the error.
    """

    def __init__(self, report: ReplayReport) -> None:
        self.report = report
        n = len(report.drifted_steps)
        super().__init__(
            f"job {report.job_id!r} is not byte-exact replayable: "
            f"{n} drifted step(s); pass allow_drift=True to proceed"
        )


def _extract_digest(payload: dict[str, Any]) -> str:
    """Pull the model content digest out of a ``model_call`` payload.

    The gateway records the digest under ``fingerprint.registry_digest_sha256``
    (see gateway ``_record``). We default to an empty string rather than raise
    so a malformed historical row degrades to "drifted" instead of aborting
    the whole trace.
    """
    fp = payload.get("fingerprint")
    if isinstance(fp, dict):
        digest = fp.get("registry_digest_sha256")
        if isinstance(digest, str):
            return digest
    return ""


def replay_job(audit_db: str | Path, job_id: str) -> ReplayTrace:
    """Reconstruct the ordered model-call trace for ``job_id``.

    Reads ``audit_events`` rows of type ``model_call`` whose payload carries a
    matching ``job_id`` and orders them by ``seq`` (the autoincrement PK),
    which is the authoritative insertion order.

    WHY filter in Python on ``job_id`` rather than via SQL JSON functions:
    ``json_extract`` availability varies by SQLite build, and the audit table
    has no job_id column. Reading model_call rows and decoding their payloads
    keeps us portable across whatever SQLite the host ships.
    """
    conn = open_db(audit_db)
    try:
        rows = conn.execute(
            "SELECT seq, ts, payload_json FROM audit_events "
            "WHERE event_type = 'model_call' ORDER BY seq ASC"
        ).fetchall()
    finally:
        conn.close()

    steps: list[ReplayStep] = []
    for seq, ts, payload_json in rows:
        try:
            payload = json.loads(payload_json)
        except (TypeError, json.JSONDecodeError):
            continue
        if payload.get("job_id") != job_id:
            continue
        fp = payload.get("fingerprint") if isinstance(payload.get("fingerprint"), dict) else {}
        steps.append(
            ReplayStep(
                seq=int(seq),
                job_id=job_id,
                model=str(payload.get("model", "")),
                digest=_extract_digest(payload),
                backend=payload.get("backend_used") or (fp.get("backend") if fp else None),
                prompt_tokens=payload.get("prompt_tokens"),
                completion_tokens=payload.get("completion_tokens"),
                ts=ts,
            )
        )
    return ReplayTrace(job_id=job_id, steps=tuple(steps))


def verify_replayable(
    audit_db: str | Path,
    job_id: str,
    *,
    installed_digests: dict[str, str],
    allow_drift: bool = False,
) -> ReplayReport:
    """Decide whether ``job_id`` can be replayed byte-exact.

    Compares each recorded step's model digest against ``installed_digests``
    (a ``model_string -> digest`` map the *caller* builds; this function never
    calls Ollama). A step is byte-exact replayable iff its model is installed
    *and* the installed digest equals the recorded digest.

    With ``allow_drift=False`` (the default, matching §27.8's refusal to
    replay against drifted models), any drift raises :class:`ReplayDriftError`.
    The error still carries the full report so callers can show the user what
    diverged. With ``allow_drift=True`` the report is returned unconditionally.
    """
    trace = replay_job(audit_db, job_id)
    verdicts: list[StepVerdict] = []
    for step in trace.steps:
        installed = installed_digests.get(step.model)
        replayable = installed is not None and installed == step.digest
        # "drifted" is the specific case where the model is present but
        # changed; a never-installed model is a separate failure mode.
        drifted = installed is not None and installed != step.digest
        verdicts.append(
            StepVerdict(
                step=step,
                installed_digest=installed,
                replayable=replayable,
                drifted=drifted,
            )
        )
    report = ReplayReport(job_id=job_id, verdicts=tuple(verdicts))
    if not allow_drift and not report.fully_replayable:
        raise ReplayDriftError(report)
    return report
