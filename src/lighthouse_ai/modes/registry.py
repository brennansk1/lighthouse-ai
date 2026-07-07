"""Mode registry — the single source of truth for Lighthouse's research modes.

Lighthouse solidifies on seven research modes, each producing one typed
*artifact*. The registry declares each mode once: its canonical key, display
label, the artifact it yields, the engine entrypoint, and the legacy aliases
that older ``jobs.mode`` rows (and the old UI) may still use.

Nothing here imports an engine eagerly — ``engine`` is a ``"module:func"``
dotted path resolved lazily by :func:`load_engine`. That keeps this module
import-cheap and free of cycles (engines import the gateway, RAG, etc.).
"""

from __future__ import annotations

import importlib
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum


class ArtifactType(str, Enum):
    REPORT = "report"  # prose investigation
    DIGEST = "digest"  # rolled-up feed of items
    TABLE = "table"  # evidence/comparison grid (Survey)
    TIMELINE = "timeline"  # sourced chronology (Reconstruct)
    MATRIX = "matrix"  # options x criteria scoring (Decide)
    VERDICT = "verdict"  # adjudicated debate
    TRANSCRIPT = "transcript"  # conversational Q&A (Ask)


@dataclass(frozen=True)
class ModeSpec:
    key: str  # canonical internal key (stable; do not rename)
    label: str  # display label for the UI
    verb: str  # short imperative verb
    artifact_type: ArtifactType
    engine: str  # "module:function" dotted path
    summary: str  # one-sentence purpose (Info tab + picker)
    aliases: tuple[str, ...] = ()  # legacy keys that normalize to this mode
    requires: tuple[str, ...] = ()  # required input fields beyond topic/question

    def as_dict(self) -> dict:
        return {
            "key": self.key,
            "label": self.label,
            "verb": self.verb,
            "artifact_type": self.artifact_type.value,
            "summary": self.summary,
            "aliases": list(self.aliases),
            "requires": list(self.requires),
        }


# Order here is the canonical display order in the Research picker / Info tab.
_SPECS: tuple[ModeSpec, ...] = (
    ModeSpec(
        key="watch",
        label="Watch",
        verb="Monitor",
        artifact_type=ArtifactType.DIGEST,
        engine="lighthouse_ai.modes.monitor:run_monitor",
        summary="Monitor named entities and sources over time, surfacing salient items.",
        aliases=("monitor",),
    ),
    ModeSpec(
        key="ask",
        label="Ask",
        verb="Ask",
        artifact_type=ArtifactType.TRANSCRIPT,
        engine="lighthouse_ai.modes.quc:ask",
        summary="Hold a cited, conversational Q&A grounded in the corpus.",
        aliases=("quc", "quick-answer", "quick_answer"),
    ),
    ModeSpec(
        key="investigate",
        label="Investigate",
        verb="Investigate",
        artifact_type=ArtifactType.REPORT,
        engine="lighthouse_ai.modes.deepdive:run_deepdive",
        summary="Produce a bounded, sourced report answering a research question.",
        aliases=("deepdive", "deep-dive", "deep_dive"),
    ),
    ModeSpec(
        key="survey",
        label="Survey",
        verb="Survey",
        artifact_type=ArtifactType.TABLE,
        engine="lighthouse_ai.modes.survey:run_survey",
        summary="Screen many documents into a sortable evidence table with a PRISMA flow.",
    ),
    ModeSpec(
        key="reconstruct",
        label="Reconstruct",
        verb="Reconstruct",
        artifact_type=ArtifactType.TIMELINE,
        engine="lighthouse_ai.modes.reconstruct:run_reconstruct",
        summary="Assemble a sourced chronology of events from the corpus.",
    ),
    ModeSpec(
        key="decide",
        label="Decide",
        verb="Decide",
        artifact_type=ArtifactType.MATRIX,
        engine="lighthouse_ai.modes.decide:run_decide",
        summary="Score options against weighted criteria and surface the decisive crux.",
        requires=("options", "criteria"),
    ),
    ModeSpec(
        key="adjudicate",
        label="Adjudicate",
        verb="Adjudicate",
        artifact_type=ArtifactType.VERDICT,
        engine="lighthouse_ai.modes.debate:run_debate",
        summary="Run a structured multi-perspective debate and name the crux of disagreement.",
        aliases=("debate",),
    ),
    # Digest is a derived rollup, not a primary picker mode, but it is a real
    # mode key that jobs may carry — register it so canonical() resolves it.
    ModeSpec(
        key="digest",
        label="Digest",
        verb="Digest",
        artifact_type=ArtifactType.DIGEST,
        engine="lighthouse_ai.modes.digest:aggregate_digest",
        summary="Aggregate monitor reports into a periodic digest.",
    ),
)

REGISTRY: dict[str, ModeSpec] = {s.key: s for s in _SPECS}

# Build the alias → canonical-key lookup (case-insensitive). Every canonical
# key also maps to itself so canonical("watch") works.
_ALIAS_TO_KEY: dict[str, str] = {}
for _s in _SPECS:
    _ALIAS_TO_KEY[_s.key.lower()] = _s.key
    for _a in _s.aliases:
        _ALIAS_TO_KEY[_a.lower()] = _s.key
# A few extra human-facing labels seen in older data / the previous UI.
_ALIAS_TO_KEY.setdefault("event monitor", "watch")
_ALIAS_TO_KEY.setdefault("deep research", "investigate")
_ALIAS_TO_KEY.setdefault("quick answer", "ask")


def canonical(name: str) -> str:
    """Map any mode name/alias to its canonical key.

    Raises ``KeyError`` for an unknown mode so callers can reject it.
    """
    if name is None:
        raise KeyError("mode is required")
    key = _ALIAS_TO_KEY.get(name.strip().lower())
    if key is None:
        raise KeyError(f"unknown mode: {name!r}")
    return key


def resolve(name: str) -> ModeSpec:
    """Return the :class:`ModeSpec` for a mode name/alias."""
    return REGISTRY[canonical(name)]


def all_modes() -> list[ModeSpec]:
    """Primary modes in display order (excludes the derived ``digest`` rollup)."""
    return [s for s in _SPECS if s.key != "digest"]


# --- scope gate (reversible feature flag) ------------------------------------
# The default UI ships a wedge: it OFFERS only ``investigate`` at the
# quick/standard/thorough tiers. Everything else stays in the code and remains
# runnable when requested by explicit key — these helpers only filter what is
# *offered* in the picker (see config.toml ``[modes]``/``[depth]``).

#: Wedge defaults applied when a config key is missing.
WEDGE_MODES: tuple[str, ...] = ("investigate",)
WEDGE_DEPTH_TIERS: tuple[str, ...] = ("quick", "standard", "thorough")


@dataclass(frozen=True)
class ScopeConfig:
    """Typed view of the ``[modes].enabled`` / ``[depth].enabled_tiers`` flags."""

    modes: tuple[str, ...] = WEDGE_MODES
    depth_tiers: tuple[str, ...] = WEDGE_DEPTH_TIERS

    @classmethod
    def from_mapping(cls, data: dict | None) -> ScopeConfig:
        """Build from a parsed config mapping; missing keys → wedge defaults."""
        data = data or {}
        modes = data.get("modes", {}).get("enabled")
        tiers = data.get("depth", {}).get("enabled_tiers")
        return cls(
            modes=tuple(modes) if modes else WEDGE_MODES,
            depth_tiers=tuple(tiers) if tiers else WEDGE_DEPTH_TIERS,
        )

    @classmethod
    def from_config_file(cls, path) -> ScopeConfig:
        """Read the scope flags from a config.toml; wedge defaults if absent."""
        try:
            import tomllib  # type: ignore[import-not-found]
        except ModuleNotFoundError:  # py<3.11
            import tomli as tomllib  # type: ignore[no-redef]
        try:
            with open(path, "rb") as fh:
                data = tomllib.load(fh)
        except (FileNotFoundError, OSError):
            return cls()
        return cls.from_mapping(data)


def enabled_modes(config: dict | ScopeConfig | None = None) -> list[ModeSpec]:
    """Primary modes the UI should OFFER, filtered to the config's enabled set.

    Resolution is alias-aware (config may name a mode by any alias) and preserves
    canonical display order. An empty/absent config yields the wedge default
    (``investigate`` only). This gates what is *offered*, never what can run:
    a hidden mode is still resolvable via :func:`resolve` when requested by key.
    """
    scope = config if isinstance(config, ScopeConfig) else ScopeConfig.from_mapping(config)
    wanted: set[str] = set()
    for name in scope.modes:
        try:
            wanted.add(canonical(name))
        except KeyError:
            continue  # unknown mode name in config → ignore, don't crash
    return [s for s in all_modes() if s.key in wanted]


def enabled_depth_tiers(config: dict | ScopeConfig | None = None) -> list[str]:
    """Depth tiers the UI should OFFER, filtered to the config's enabled set.

    Returns canonical tier keys in their canonical (quick→deep) order, filtered
    to known tiers. An empty/absent config yields the wedge default (excludes
    ``deep``). Gating is about what is offered; :mod:`lighthouse_ai.modes.depth`
    still resolves a hidden tier when one is explicitly requested.
    """
    from .depth import DEPTH_TIERS, canonical_tier

    scope = config if isinstance(config, ScopeConfig) else ScopeConfig.from_mapping(config)
    wanted = {canonical_tier(t) for t in scope.depth_tiers}
    return [t for t in DEPTH_TIERS if t in wanted]


def load_engine(name: str) -> Callable:
    """Import and return the engine callable for a mode."""
    spec = resolve(name)
    module_path, _, func_name = spec.engine.partition(":")
    module = importlib.import_module(module_path)
    return getattr(module, func_name)
