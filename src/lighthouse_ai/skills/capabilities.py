"""SkillContext — the vetted primitive surface a skill is allowed to touch.

A skill never imports ``httpx``, never opens a socket, never reads the
filesystem, never spawns a subprocess (the runner's import guard enforces this
statically). Everything a skill does to reach the world goes through a
:class:`SkillContext`, which exposes exactly three platform primitives:

  * :meth:`SkillContext.fetch` — egress-guarded HTTP GET. The host is checked
    against the skill's *effective* domains (its declared ``allowed_domains``
    **narrowed to the platform allowlist** by the runner), so a skill can never
    widen its reach past what the platform/user already permits.
  * :meth:`SkillContext.fetch_and_document` — fetch → :class:`SandboxBroker`
    admit → :func:`ingest.ingest_bytes` parse → tagged ``Document``. The broker
    is non-bypassable: every fetched byte passes through it before parsing.
  * :meth:`SkillContext.make_document` — wrap already-parsed *first-party API*
    text (e.g. an arXiv abstract returned by a vetted ``sources/`` adapter) into
    a ``Document``. Use only for trusted-API metadata you did NOT fetch as a web
    page; web bytes must go through :meth:`fetch_and_document`.

Every primitive emits an audit line via the optional ``audit`` hook, stamped
with ``skill_id`` + ``skill_version`` so the chain attributes each fetch.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import structlog

from ..governor.egress_proxy import (
    DEFAULT_ALLOWED_DOMAINS,
    EgressProxy,
    PrivacyTier,
)
from ..ingest import ingest_bytes
from ..net import guarded_get
from ..rag.chunker import Document
from ..sandbox.broker import SandboxBroker

if TYPE_CHECKING:  # pragma: no cover - typing only
    import httpx

    from .schema import SkillManifest

log = structlog.get_logger(__name__)

AuditHook = Callable[[dict[str, Any]], None]


def _effective_domains(
    declared: tuple[str, ...] | frozenset[str],
    platform_allowlist: frozenset[str],
) -> frozenset[str]:
    """Intersect a skill's declared domains with the platform allowlist.

    The platform allowlist is the ceiling: a skill may *narrow* its reach but
    never widen it. A skill declaring ``evil.com`` gets it filtered out unless
    the platform (or the user, via ``lighthouse trust add``) already permits it.
    Subdomain semantics match :meth:`EgressProxy.is_allowed_host`, so declaring
    ``wikipedia.org`` against an allowlisted ``wikipedia.org`` keeps it (and
    ``en.wikipedia.org`` then resolves through the guard).
    """
    ceiling = EgressProxy(platform_allowlist)
    return frozenset(d for d in declared if ceiling.is_allowed_host(d))


@dataclass
class SkillContext:
    """Capability-restricted handle passed to a skill's ``run`` entrypoint."""

    skill_id: str
    skill_version: str
    effective_domains: frozenset[str]
    broker: SandboxBroker
    gateway: Any | None = None
    default_grade: str = "B"
    community: bool = False
    tier: str = "A"
    audit_tags: tuple[str, ...] = ()
    audit: AuditHook | None = None
    # Injectable transport so tests can drive skills with respx/mock clients
    # without the network. Production leaves this None (guarded_get owns one).
    client: httpx.Client | None = None
    _fetch_count: int = field(default=0, init=False)

    # -- audit ---------------------------------------------------------------

    def _emit(self, event: str, **fields: Any) -> None:
        record = {
            "event": event,
            "skill_id": self.skill_id,
            "skill_version": self.skill_version,
            **fields,
        }
        # structlog takes the event name positionally; passing it again in
        # kwargs collides, so log the remaining fields only.
        log.info(event, skill_id=self.skill_id, skill_version=self.skill_version, **fields)
        if self.audit is not None:
            self.audit(record)

    # -- primitives ----------------------------------------------------------

    def fetch(self, url: str, *, privacy: PrivacyTier = PrivacyTier.PUBLIC_OK) -> httpx.Response:
        """Egress-guarded GET, restricted to the skill's effective domains."""
        self._fetch_count += 1
        self._emit("skill.fetch", url=url, tier=self.tier)
        return guarded_get(
            url,
            allowed_domains=self.effective_domains,
            privacy=privacy,
            client=self.client,
        )

    def _skill_meta(self) -> dict[str, Any]:
        meta: dict[str, Any] = {
            "skill_id": self.skill_id,
            "skill_version": self.skill_version,
            "fetch_backend": "tier-" + self.tier.lower(),
        }
        if self.default_grade:
            meta["grade"] = self.default_grade
        if self.community:
            meta["community"] = True
        if self.audit_tags:
            meta["audit_tags"] = list(self.audit_tags)
        return meta

    def _tag(self, doc: Document | None, extra_meta: dict[str, Any] | None) -> Document | None:
        if doc is None:
            return None
        # Document is frozen but its metadata dict is mutable in place.
        doc.metadata.update(self._skill_meta())
        if extra_meta:
            doc.metadata.update(extra_meta)
        return doc

    def fetch_and_document(
        self,
        url: str,
        *,
        content_type: str | None = None,
        filename: str | None = None,
        extra_meta: dict[str, Any] | None = None,
        privacy: PrivacyTier = PrivacyTier.PUBLIC_OK,
    ) -> Document | None:
        """Fetch a web URL, run it through the broker, and parse to a Document.

        Returns ``None`` if the broker REJECTs the payload (the skill should
        treat that as "source declined") — identical semantics to
        :func:`ingest.ingest_bytes`.
        """
        resp = self.fetch(url, privacy=privacy)
        ct = content_type or resp.headers.get("content-type")
        doc = ingest_bytes(
            resp.content, url=url, filename=filename, content_type=ct, broker=self.broker
        )
        self._emit("skill.document", url=url, admitted=doc is not None)
        return self._tag(doc, extra_meta)

    def document_from_bytes(
        self,
        payload: bytes,
        *,
        url: str | None = None,
        content_type: str | None = None,
        filename: str | None = None,
        extra_meta: dict[str, Any] | None = None,
    ) -> Document | None:
        """Broker + parse bytes a skill already obtained through ``fetch``.

        For adapters that need the raw response (e.g. to choose a filename) but
        still must honor the non-bypassable broker gate.
        """
        doc = ingest_bytes(
            payload, url=url, filename=filename, content_type=content_type, broker=self.broker
        )
        self._emit("skill.document", url=url, admitted=doc is not None)
        return self._tag(doc, extra_meta)

    def make_document(
        self,
        *,
        doc_id: str,
        text: str,
        metadata: dict[str, Any] | None = None,
    ) -> Document:
        """Wrap trusted first-party API text into a tagged Document.

        Use ONLY for structured metadata returned by a vetted ``sources/``
        adapter (arXiv/OpenAlex/etc.) — content you did not fetch as a web page.
        Web bytes must use :meth:`fetch_and_document` so the broker sees them.
        """
        meta = dict(metadata or {})
        meta.update(self._skill_meta())
        self._emit("skill.make_document", doc_id=doc_id)
        return Document(id=doc_id, text=text, metadata=meta)


def build_context(
    manifest: SkillManifest,
    *,
    broker: SandboxBroker,
    platform_allowlist: frozenset[str] | None = None,
    gateway: Any | None = None,
    audit: AuditHook | None = None,
    client: httpx.Client | None = None,
) -> SkillContext:
    """Construct a :class:`SkillContext` for a skill, narrowing its domains.

    ``platform_allowlist`` defaults to
    :data:`~lighthouse_ai.governor.egress_proxy.DEFAULT_ALLOWED_DOMAINS`; callers
    holding a configured allowlist (e.g. with user ``trust add`` domains) should
    pass it so a skill's effective reach reflects the running policy.
    """
    ceiling = platform_allowlist if platform_allowlist is not None else DEFAULT_ALLOWED_DOMAINS
    effective = _effective_domains(manifest.allowed_domains, ceiling)
    return SkillContext(
        skill_id=manifest.id,
        skill_version=manifest.version,
        effective_domains=effective,
        broker=broker,
        gateway=gateway,
        default_grade=manifest.default_grade,
        community=manifest.is_community,
        tier=manifest.tier,
        audit_tags=manifest.audit_tags,
        audit=audit,
        client=client,
    )
