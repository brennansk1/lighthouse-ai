"""Skill runner — execute a loaded skill against a question, safely.

The runner is the platform's side of the contract:

  1. Build a capability-restricted :class:`SkillContext` (domains narrowed to the
     platform allowlist, broker attached, audit hook wired).
  2. Invoke the skill's ``run(ctx, question, *, max_results)`` entrypoint.
  3. Guarantee every returned ``Document`` is stamped with ``skill_id`` /
     ``skill_version`` and — for unsigned **community** skills — the
     ``community`` tag that triggers the downstream WEP downgrade (the same
     mechanism Tier-C fetches use, applied in ``verification/discipline.py``).
  4. Never let a misbehaving skill take down a job: a raising skill yields an
     empty :class:`SkillRun` with ``error`` set, so the dispatcher can fall back
     to the General Web skill.

A skill's ``run`` returns ``list[Document]``; the runner does not interpret the
documents, only attributes them. Mode engines consume the documents unchanged.
"""

from __future__ import annotations

import datetime as _dt
import inspect
import os
from dataclasses import dataclass, field
from typing import Any

import structlog

from ..rag.chunker import Document
from .capabilities import AuditHook, SkillContext, build_context
from .registry import LoadedSkill

log = structlog.get_logger(__name__)


@dataclass
class SkillRun:
    """Result of running one skill: its documents plus attribution/diagnostics."""

    skill_id: str
    documents: list[Document] = field(default_factory=list)
    fetches: int = 0
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None

    @property
    def thin(self) -> bool:
        """True when the skill returned (almost) nothing — the dispatcher's cue
        to fall back to the General Web skill (CRAG-style mid-loop fill)."""
        return not self.documents


def _call_entrypoint(skill: LoadedSkill, ctx: SkillContext, question: str, max_results: int) -> Any:
    """Invoke the skill entrypoint, passing ``max_results`` only if accepted."""
    try:
        params = inspect.signature(skill.entrypoint).parameters
        if "max_results" in params:
            return skill.entrypoint(ctx, question, max_results=max_results)
        return skill.entrypoint(ctx, question)
    except (TypeError, ValueError):
        # Signature introspection failed (e.g. builtins); try the rich call,
        # then the minimal one.
        try:
            return skill.entrypoint(ctx, question, max_results=max_results)
        except TypeError:
            return skill.entrypoint(ctx, question)


def _missing_key_message(manifest: Any) -> str | None:
    """Pre-flight: an actionable message when a mandatory API key is unset, else None.

    A source declaring ``requires_key_env`` hard-fails without a key, so firing the
    request just to collect a 400/401/403 is wasted effort and a confusing failure.
    Instead we short-circuit with plain-language guidance. Sources that work keyless
    declare no env and are never affected.
    """
    envs = tuple(getattr(manifest, "requires_key_env", ()) or ())
    if not envs or any(os.environ.get(e) for e in envs):
        return None
    primary = envs[0]
    return (
        f"{manifest.name} needs a free API key to fetch. Set the {primary} "
        f"environment variable (see this source's guide), then try again."
    )


def run_skill(
    skill: LoadedSkill,
    question: str,
    *,
    broker: Any,
    platform_allowlist: frozenset[str] | None = None,
    gateway: Any | None = None,
    audit: AuditHook | None = None,
    max_results: int = 5,
    client: Any | None = None,
) -> SkillRun:
    """Run ``skill`` against ``question`` and return a :class:`SkillRun`.

    All keyword args mirror :func:`capabilities.build_context`; ``max_results``
    is a hint the skill may honor. Exceptions are caught and reported on the
    result rather than propagated.
    """
    key_msg = _missing_key_message(skill.manifest)
    if key_msg is not None:
        log.info("skills.key_required", skill=skill.manifest.id)
        return SkillRun(skill_id=skill.manifest.id, error=key_msg)
    ctx = build_context(
        skill.manifest,
        broker=broker,
        platform_allowlist=platform_allowlist,
        gateway=gateway,
        audit=audit,
        client=client,
    )
    try:
        result = _call_entrypoint(skill, ctx, question, max_results)
    except Exception as exc:
        log.warning("skills.run_failed", skill=skill.manifest.id, error=repr(exc))
        return SkillRun(skill_id=skill.manifest.id, fetches=ctx._fetch_count, error=repr(exc))

    documents = _coerce_documents(result, ctx)
    return SkillRun(
        skill_id=skill.manifest.id,
        documents=documents,
        fetches=ctx._fetch_count,
    )


def run_watchable(
    skill: LoadedSkill,
    query: str,
    *,
    since: _dt.datetime | None,
    broker: Any,
    platform_allowlist: frozenset[str] | None = None,
    gateway: Any | None = None,
    audit: AuditHook | None = None,
    max_results: int = 5,
    client: Any | None = None,
) -> SkillRun:
    """Pattern-2 (Watch) invocation: incremental, time-ordered fetch since a tick.

    Requires the skill to declare ``watchable=true`` (the registry then resolves
    ``run_watchable(ctx, query, *, since, max_results)``). Raises nothing — a
    non-watchable skill or a raising entrypoint yields a :class:`SkillRun` with
    ``error`` set, mirroring :func:`run_skill`.
    """
    if skill.watchable_entrypoint is None:
        return SkillRun(
            skill_id=skill.manifest.id,
            error="skill is not watchable (no run_watchable entrypoint)",
        )
    key_msg = _missing_key_message(skill.manifest)
    if key_msg is not None:
        log.info("skills.key_required", skill=skill.manifest.id)
        return SkillRun(skill_id=skill.manifest.id, error=key_msg)
    ctx = build_context(
        skill.manifest,
        broker=broker,
        platform_allowlist=platform_allowlist,
        gateway=gateway,
        audit=audit,
        client=client,
    )
    try:
        result = skill.watchable_entrypoint(ctx, query, since=since, max_results=max_results)
    except Exception as exc:
        log.warning("skills.watch_failed", skill=skill.manifest.id, error=repr(exc))
        return SkillRun(skill_id=skill.manifest.id, fetches=ctx._fetch_count, error=repr(exc))

    documents = _coerce_documents(result, ctx)
    return SkillRun(skill_id=skill.manifest.id, documents=documents, fetches=ctx._fetch_count)


# Attribution keys the platform owns: a skill may never override these by
# pre-stamping a bare Document. Crucially this includes ``community`` — letting a
# skill suppress its own community flag would defeat the downstream WEP downgrade
# (verification/discipline.py) — and ``skill_id``/``skill_version``/
# ``fetch_backend``/``audit_tags`` so provenance can't be forged. ``grade`` is
# omitted on purpose: it is a *default* a skill may legitimately refine per-doc.
_AUTHORITATIVE_META_KEYS: frozenset[str] = frozenset(
    {"skill_id", "skill_version", "fetch_backend", "community", "audit_tags"}
)


def _coerce_documents(result: Any, ctx: SkillContext) -> list[Document]:
    """Validate the skill output and ensure every Document is attributed.

    Documents produced through the context are already tagged; this re-stamps
    defensively so a skill that constructs a bare ``Document`` (bypassing
    ``ctx.make_document``) still carries its skill identity and community flag.
    Platform-owned attribution (:data:`_AUTHORITATIVE_META_KEYS`) is force-set so
    a skill cannot forge provenance or strip its community downgrade; other keys
    (e.g. ``grade``) are filled only if the skill left them unset.
    """
    if result is None:
        return []
    if isinstance(result, Document):
        result = [result]
    if not isinstance(result, (list, tuple)):
        log.warning("skills.bad_output", skill=ctx.skill_id, type=type(result).__name__)
        return []

    docs: list[Document] = []
    stamp = ctx._skill_meta()
    for item in result:
        if not isinstance(item, Document):
            log.warning("skills.bad_document", skill=ctx.skill_id, type=type(item).__name__)
            continue
        for key, value in stamp.items():
            if key in _AUTHORITATIVE_META_KEYS:
                item.metadata[key] = value  # platform wins — non-forgeable
            else:
                item.metadata.setdefault(key, value)
        docs.append(item)
    return docs
