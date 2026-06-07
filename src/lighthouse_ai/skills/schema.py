"""Skill manifest — the machine-readable contract for one research skill.

Every skill folder carries a ``manifest.toml`` parsed into a frozen
:class:`SkillManifest`. The manifest is the recommender's scoring surface, the
egress narrowing input, and the audit/grade source of truth. It is intentionally
declarative: a skill *declares* its tier, domains, and (if needed) Tier-C
escalation — it never ships evasion code (see ``SKILL_FRAMEWORK.md`` §Security).

Parsing uses stdlib ``tomllib`` (Python ≥3.11), so reading the catalog pulls no
optional dependency.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

# Fetch tiers (Part B of the audit). A = first-party APIs / clean fetch;
# B = in-process JS rendering (no evasion); C = real-browser-fingerprint tools,
# only behind an explicit per-domain trust grant. A skill declares the *highest*
# tier it may use; Tier-C must additionally set ``tierc_escalation``.
VALID_TIERS = ("A", "B", "C")
VALID_GRADES = ("A", "B", "C", "D")
# Corpus shape a skill yields — drives the recommender's per-mode scoring
# (Survey requires "enumerable"; "lookup" sources can't fill a PRISMA funnel).
VALID_OUTPUT_SHAPES = ("lookup", "enumerable", "graph", "stream")


class SkillManifestError(ValueError):
    """Raised when a ``manifest.toml`` is missing required fields or malformed."""


@dataclass(frozen=True)
class SkillManifest:
    """Declarative configuration for a research skill.

    Field groups:
      * identity — ``id`` (must equal the folder name), ``name``, ``version``,
        ``description``, ``category``.
      * routing — ``question_types`` and ``topics`` drive the recommender's
        rule-based score; ``enabled_by_default`` seeds the picker pre-selection.
      * fetch policy — ``tier``, ``base_url``, ``allowed_domains`` (narrowed
        against the platform allowlist by the runner), ``rate_limit_per_sec``,
        ``robots_policy``.
      * provenance — ``default_grade``, ``license``, ``signed`` (unsigned ⇒
        ``community`` audit tag + WEP downgrade), ``audit_tags``.
      * escalation — ``tierc_escalation`` + ``tierc_reason`` (declarative only).
      * wiring — ``entrypoint`` ``"module:func"`` resolved relative to the skill
        package (default ``"skill:run"``).
    """

    id: str
    name: str
    description: str
    category: str
    version: str = "0.1.0"
    tier: str = "A"
    base_url: str = ""
    allowed_domains: tuple[str, ...] = ()
    question_types: tuple[str, ...] = ()
    topics: tuple[str, ...] = ()
    default_grade: str = "B"
    license: str = "unknown"
    signed: bool = False
    enabled_by_default: bool = False
    # When true the skill is loadable/usable if explicitly named but is not
    # OFFERED by default — it's kept out of the recommender's candidate set and
    # the default ``/api/sources`` picker listing. Used to hide verticals that
    # fall outside the current wedge (legal/practice-support) without deleting
    # the manifest, so they can be re-surfaced later.
    hidden: bool = False
    rate_limit_per_sec: float = 1.0
    robots_policy: str = "obey"
    audit_tags: tuple[str, ...] = ()
    tierc_escalation: bool = False
    tierc_reason: str = ""
    entrypoint: str = "skill:run"
    # --- Mode↔Skill integration scoring surface (read by the recommender) ---
    # The recommender consumes these; it never branches on a skill by name. See
    # MODE_SKILL_INTEGRATION.md §2.2 for how each mode weights them.
    modes_natural_fit: tuple[str, ...] = ()   # mode keys this skill suits well
    modes_weak_fit: tuple[str, ...] = ()      # mode keys it serves poorly
    output_shape: str = "lookup"              # lookup | enumerable | graph | stream
    temporal_tools: bool = False              # exposes time-ordered queries (Reconstruct)
    perspective_lens: str = ""                # primary|regulatory|reproducibility|popular|... (Adjudicate)
    authority: str = ""                       # e.g. peer_reviewed (independence + diversity)
    # --- Watch (Pattern 2) ---
    watchable: bool = False                   # has ≥1 watchable tool (since= incremental)
    watchable_tools: tuple[str, ...] = ()
    # --- Auth (mandatory keys) ---
    # Environment variable(s) that MUST be set for this source to fetch at all.
    # Set only for sources that hard-fail without a key (e.g. FRED 400, BEA 403);
    # leave empty for keyless-capable sources so they are never needlessly blocked.
    # The runner pre-flights these and short-circuits with an actionable message
    # instead of firing a doomed request.
    requires_key_env: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.id:
            raise SkillManifestError("manifest is missing 'id'")
        if self.tier not in VALID_TIERS:
            raise SkillManifestError(
                f"skill {self.id!r}: tier {self.tier!r} not in {VALID_TIERS}"
            )
        if self.default_grade not in VALID_GRADES:
            raise SkillManifestError(
                f"skill {self.id!r}: default_grade {self.default_grade!r} invalid"
            )
        if self.tier == "C" and not self.tierc_escalation:
            raise SkillManifestError(
                f"skill {self.id!r}: tier C requires tierc_escalation=true with a reason"
            )
        if self.tierc_escalation and not self.tierc_reason:
            raise SkillManifestError(
                f"skill {self.id!r}: tierc_escalation requires a 'tierc_reason'"
            )
        if self.output_shape not in VALID_OUTPUT_SHAPES:
            raise SkillManifestError(
                f"skill {self.id!r}: output_shape {self.output_shape!r} not in {VALID_OUTPUT_SHAPES}"
            )
        if self.watchable and not self.watchable_tools:
            raise SkillManifestError(
                f"skill {self.id!r}: watchable=true requires at least one watchable_tools entry"
            )

    @property
    def is_community(self) -> bool:
        """Unsigned skills are community-grade: tagged + WEP-downgraded downstream."""
        return not self.signed

    def as_dict(self) -> dict:
        """JSON-serializable summary for the ``/api/sources`` catalog payload."""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "version": self.version,
            "tier": self.tier,
            "question_types": list(self.question_types),
            "topics": list(self.topics),
            "default_grade": self.default_grade,
            "license": self.license,
            "signed": self.signed,
            "community": self.is_community,
            "enabled_by_default": self.enabled_by_default,
            "hidden": self.hidden,
            "tierc_escalation": self.tierc_escalation,
            "modes_natural_fit": list(self.modes_natural_fit),
            "modes_weak_fit": list(self.modes_weak_fit),
            "output_shape": self.output_shape,
            "temporal_tools": self.temporal_tools,
            "perspective_lens": self.perspective_lens,
            "authority": self.authority,
            "watchable": self.watchable,
            "requires_key": bool(self.requires_key_env),
        }


def _as_tuple(value: object, field_name: str, skill_id: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, (list, tuple)):
        return tuple(str(v) for v in value)
    raise SkillManifestError(
        f"skill {skill_id!r}: field {field_name!r} must be a string or list of strings"
    )


def manifest_from_dict(data: dict, *, expected_id: str | None = None) -> SkillManifest:
    """Build a :class:`SkillManifest` from a parsed-TOML dict.

    Tolerant of missing optional keys (dataclass defaults apply); strict about
    types for the list-valued fields so a malformed manifest fails loudly at
    discovery rather than producing a silently-empty routing surface.
    """
    skill_id = str(data.get("id", expected_id or ""))
    if expected_id is not None and skill_id and skill_id != expected_id:
        raise SkillManifestError(
            f"manifest id {skill_id!r} does not match folder {expected_id!r}"
        )
    if not skill_id:
        skill_id = expected_id or ""

    return SkillManifest(
        id=skill_id,
        name=str(data.get("name", skill_id)),
        description=str(data.get("description", "")),
        category=str(data.get("category", "general")),
        version=str(data.get("version", "0.1.0")),
        tier=str(data.get("tier", "A")),
        base_url=str(data.get("base_url", "")),
        allowed_domains=_as_tuple(data.get("allowed_domains"), "allowed_domains", skill_id),
        # Accept the integration-spec key `supported_question_types` as the
        # canonical name, falling back to the shorter `question_types`.
        question_types=_as_tuple(
            data.get("supported_question_types", data.get("question_types")),
            "supported_question_types",
            skill_id,
        ),
        topics=_as_tuple(data.get("topics"), "topics", skill_id),
        default_grade=str(data.get("default_grade", "B")),
        license=str(data.get("license", "unknown")),
        signed=bool(data.get("signed", False)),
        enabled_by_default=bool(data.get("enabled_by_default", False)),
        hidden=bool(data.get("hidden", False)),
        rate_limit_per_sec=float(data.get("rate_limit_per_sec", 1.0)),
        robots_policy=str(data.get("robots_policy", "obey")),
        audit_tags=_as_tuple(data.get("audit_tags"), "audit_tags", skill_id),
        tierc_escalation=bool(data.get("tierc_escalation", False)),
        tierc_reason=str(data.get("tierc_reason", "")),
        entrypoint=str(data.get("entrypoint", "skill:run")),
        modes_natural_fit=_as_tuple(data.get("modes_natural_fit"), "modes_natural_fit", skill_id),
        modes_weak_fit=_as_tuple(data.get("modes_weak_fit"), "modes_weak_fit", skill_id),
        output_shape=str(data.get("output_shape", "lookup")),
        temporal_tools=bool(data.get("temporal_tools", False)),
        perspective_lens=str(data.get("perspective_lens", "")),
        authority=str(data.get("authority", "")),
        watchable=bool(data.get("watchable", False)),
        watchable_tools=_as_tuple(data.get("watchable_tools"), "watchable_tools", skill_id),
        requires_key_env=_as_tuple(data.get("requires_key_env"), "requires_key_env", skill_id),
    )


def load_manifest(path: Path | str, *, expected_id: str | None = None) -> SkillManifest:
    """Parse a ``manifest.toml`` file into a :class:`SkillManifest`."""
    p = Path(path)
    if not p.exists():
        raise SkillManifestError(f"no manifest at {p}")
    with p.open("rb") as fh:
        data = tomllib.load(fh)
    return manifest_from_dict(data, expected_id=expected_id)


# Field names a manifest.toml may contain. Re-exported so tooling/tests can
# validate authored manifests without instantiating the dataclass.
MANIFEST_FIELDS: frozenset[str] = frozenset(
    f.name for f in SkillManifest.__dataclass_fields__.values()  # type: ignore[attr-defined]
) | {"tierc_reason"}
