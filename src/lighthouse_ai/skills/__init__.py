"""Research-skills library — per-source mastery composed from platform primitives.

A *skill* teaches Lighthouse how to research one source well. It welds together
two things usually kept apart: **knowledge** (``SKILL.md`` — a guide the planner
reads) and **capability** (a small ``run`` entrypoint that composes the
platform's vetted primitives — fetch, broker, ingest — into a source-specific
toolkit). Neither half works alone.

The platform stays small and trusted (the fetch path, the broker, the
capability surface, the audit chain, the discipline gate). The library scales:
adding a source is a new folder under :mod:`lighthouse_ai.skills.library`, no
core change. See ``SKILL_FRAMEWORK.md`` for the full contract.

This package deliberately imports nothing heavy at module load — discovery reads
``manifest.toml`` files (stdlib ``tomllib``) and entrypoints are imported lazily
by :func:`load_skill`, mirroring :mod:`lighthouse_ai.modes.registry`.
"""

from __future__ import annotations

from .capabilities import SkillContext, build_context
from .registry import (
    LIBRARY_DIR,
    LoadedSkill,
    SkillNotFound,
    all_skills,
    discover_skills,
    load_skill,
)
from .runner import SkillRun, run_skill, run_watchable
from .schema import SkillManifest, SkillManifestError, load_manifest

__all__ = [
    "LIBRARY_DIR",
    "LoadedSkill",
    "SkillContext",
    "SkillManifest",
    "SkillManifestError",
    "SkillNotFound",
    "SkillRun",
    "all_skills",
    "build_context",
    "discover_skills",
    "load_manifest",
    "load_skill",
    "run_skill",
    "run_watchable",
]
