"""Skill scaffold generator — create a new skill folder from a template.

Produces a standards-compliant, import-guard-clean skill skeleton that:

* passes ``load_skill(skill_id, library_dir=dest_dir)`` immediately,
* follows the §8 checklist in ``SKILL_FRAMEWORK.md``,
* contains sensible stubs the author fills in.

Usage (library):

    from lighthouse_ai.skills.scaffold import scaffold_skill
    path = scaffold_skill("my_source", dest_dir=Path("/tmp/skills"))
    # → /tmp/skills/my_source/  (manifest.toml, skill.py, __init__.py, …)

Usage (CLI):

    lighthouse skill new my_source [--dir /tmp/skills] [--name "My Source"]
                                   [--category general] [--watchable]
"""

from __future__ import annotations

import keyword
from pathlib import Path

__all__ = ["ScaffoldError", "scaffold_skill"]

# ---------------------------------------------------------------------------
# Public exceptions
# ---------------------------------------------------------------------------


class ScaffoldError(ValueError):
    """Raised when scaffolding is refused (e.g. invalid skill_id)."""


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def _validate_skill_id(skill_id: str) -> None:
    """Raise :class:`ScaffoldError` if *skill_id* is not a safe Python identifier.

    Rules (mirrors the registry loader requirement):
    - Non-empty string.
    - Valid Python identifier (``str.isidentifier()``).
    - Not a Python keyword.
    - No hyphens or spaces (these are the most common authoring mistakes).
    """
    if not skill_id:
        raise ScaffoldError("skill_id must not be empty")
    if "-" in skill_id:
        raise ScaffoldError(
            f"skill_id {skill_id!r} contains a hyphen — use underscores instead "
            f"(e.g. {skill_id.replace('-', '_')!r})"
        )
    if " " in skill_id:
        raise ScaffoldError(f"skill_id {skill_id!r} contains spaces — use underscores instead")
    if not skill_id.isidentifier():
        raise ScaffoldError(f"skill_id {skill_id!r} is not a valid Python identifier")
    if keyword.iskeyword(skill_id):
        raise ScaffoldError(f"skill_id {skill_id!r} is a Python keyword — choose a different name")


# ---------------------------------------------------------------------------
# File content templates
# ---------------------------------------------------------------------------


def _manifest_toml(
    skill_id: str,
    name: str,
    category: str,
    tier: str,
    watchable: bool,
) -> str:
    """Generate a valid ``manifest.toml`` for the new skill."""
    watchable_block = ""
    if watchable:
        watchable_block = (
            "\n# --- Watch (Pattern-2) ---\n"
            "watchable       = true\n"
            f'watchable_tools = ["{skill_id}_recent"]\n'
        )

    return f"""\
id          = "{skill_id}"
name        = "{name}"
description = "TODO: one-sentence description of this source."
category    = "{category}"
version     = "0.1.0"

# --- fetch policy ---
tier        = "{tier}"
base_url    = "https://example.com"
allowed_domains = ["example.com"]
rate_limit_per_sec = 1.0
robots_policy = "obey"

# --- provenance ---
default_grade = "B"
license       = "unknown"
signed        = false
enabled_by_default = false

# --- recommender scoring surface ---
supported_question_types = [
    "exploratory_survey",
]
topics      = []
modes_natural_fit  = ["investigate"]
modes_weak_fit     = []
output_shape       = "lookup"
temporal_tools     = false
perspective_lens   = ""
authority          = ""
{watchable_block}
"""


def _skill_py(skill_id: str, watchable: bool) -> str:
    """Generate a ``skill.py`` entrypoint stub."""
    datetime_import_line = "\nfrom datetime import datetime\n" if watchable else ""
    watchable_note = " and ``run_watchable``" if watchable else ""

    # Build the base module text using concatenation to avoid .format() conflicts
    # with the curly-brace examples inside the docstring.
    lines = [
        f'"""{skill_id} skill entrypoint — ``run``{watchable_note}.',
        "",
        "All network access must be delegated to the ``SkillContext`` passed in;",
        "direct imports of httpx / requests / urllib / socket / os / pathlib are",
        "forbidden and will cause the import guard to reject this skill at load time.",
        "",
        "See SKILL.md for the planner's guide (when to use, query translation, biases).",
        '"""',
        "",
        "from __future__ import annotations",
        datetime_import_line,
        "from typing import TYPE_CHECKING",
        "",
        "if TYPE_CHECKING:",
        "    from lighthouse_ai.rag.chunker import Document",
        "    from lighthouse_ai.skills.capabilities import SkillContext",
        "",
        "",
        "def run(",
        "    ctx: SkillContext,",
        "    question: str,",
        "    *,",
        "    max_results: int = 5,",
        ") -> list[Document]:",
        f'    """Research a question using {skill_id}.',
        "",
        "    Parameters",
        "    ----------",
        "    ctx:",
        "        Capability-restricted context. Use ``ctx.fetch``,",
        "        ``ctx.fetch_and_document``, ``ctx.document_from_bytes``, or",
        "        ``ctx.make_document`` -- never import network/filesystem libraries",
        "        directly.",
        "    question:",
        "        The user's research question or keyword query.",
        "    max_results:",
        "        Maximum number of Documents to return.",
        '    """',
        "    # TODO: implement real fetch + document wrapping.",
        "    # Example -- wrap a plain text payload from a vetted adapter:",
        "    #",
        "    #   tagged = ctx.make_document(",
        f'    #       doc_id=f"{skill_id}:example-1",',
        '    #       text="Placeholder document text.",',
        f'    #       metadata={{"source": "{skill_id}", "title": "Example"}},',
        "    #   )",
        "    #   return [tagged]",
        "    #",
        "    _ = ctx, question, max_results  # suppress until implemented",
        "    return []",
    ]

    if watchable:
        lines += [
            "",
            "",
            "def run_watchable(",
            "    ctx: SkillContext,",
            "    query: str,",
            "    *,",
            "    since: datetime | None = None,",
            "    max_results: int = 5,",
            ") -> list[Document]:",
            f'    """Watch {skill_id} for new results relevant to *query*.',
            "",
            "    Pattern-2 (continuous coverage): return documents newer than *since*.",
            "    When *since* is None, include all returned results (first tick).",
            "",
            "    TODO: implement incremental fetch filtered to items published after *since*.",
            '    """',
            "    # TODO: replace with real incremental fetch logic",
            "    _ = ctx, query, since, max_results",
            "    return []",
        ]

    lines.append("")  # trailing newline
    return "\n".join(lines)


def _skill_md(skill_id: str, name: str, category: str) -> str:
    """Generate a ``SKILL.md`` planner guide template."""
    return f"""\
# {name} — Planner Guide

## When to use this skill

TODO: Describe the source and the research scenarios where it excels.

**Use {name} for:**
- TODO: bullet list of appropriate use cases.

**Do NOT rely on {name} for:**
- TODO: bullet list of inappropriate use cases (scope limits, paywalls, biases).

---

## Translating a question into a {name} query

TODO: Describe the query language / field prefixes / URL patterns this source uses.

| Goal | Query form | Example |
|---|---|---|
| TODO topic search | `keyword` | `example query` |

---

## Tool playbook

| Task | Entrypoint | Notes |
|---|---|---|
| Search for items | `run(ctx, question)` | Returns up to `max_results` Documents |

---

## Known biases and limitations

1. TODO: list coverage gaps, politeness constraints, authentication requirements, etc.

---

## Citation format

TODO: Describe how to cite documents returned by this skill.
Example: `{name}: <title> (<date>). <url>`

---

## Category

`{category}`
"""


def _example_md(skill_id: str, name: str) -> str:
    """Generate a starter ``examples/example.md``."""
    return f"""\
# Example — Basic lookup with {name}

## Question type
`exploratory_survey`

## Mode
`investigate`

## Tool sequence

```python
# Step 1: Search with a keyword query
docs = run(ctx, "example keyword query", max_results=5)
# → list of Documents, each with the source's text + metadata

# Step 2: Planner screens results for relevance
```

## Expected document metadata

```json
{{
  "source": "{skill_id}",
  "title": "Example result title",
  "url": "https://example.com/result",
  "grade": "B",
  "skill_id": "{skill_id}",
  "skill_version": "0.1.0"
}}
```

## Notes

TODO: replace this example with a real worked query + realistic expected output.
"""


def _init_py() -> str:
    return '"""Auto-generated skill package — see skill.py and SKILL.md."""\n'


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def scaffold_skill(
    skill_id: str,
    dest_dir: Path,
    *,
    name: str | None = None,
    category: str = "general",
    tier: str = "A",
    watchable: bool = False,
) -> Path:
    """Create a new skill scaffold at ``dest_dir/<skill_id>/``.

    Parameters
    ----------
    skill_id:
        The skill's identifier.  Must be a valid Python identifier with no
        hyphens or spaces (e.g. ``my_source``, not ``my-source``).
    dest_dir:
        Parent directory where the skill folder will be created.  The folder
        ``dest_dir/<skill_id>/`` must not already exist.
    name:
        Human-readable display name (defaults to a title-cased version of
        *skill_id*, e.g. ``"My Source"``).
    category:
        Manifest ``category`` field — e.g. ``"academic"``, ``"news"``,
        ``"government"``, ``"general"`` (default).
    tier:
        Manifest fetch tier: ``"A"`` (default) · ``"B"`` · ``"C"``.
        Tier C additionally requires ``tierc_escalation`` + ``tierc_reason``
        which you must add manually after scaffolding.
    watchable:
        If ``True``, add ``watchable = true`` + a ``run_watchable`` stub to
        the generated files.

    Returns
    -------
    Path
        Absolute path to the created skill folder.

    Raises
    ------
    ScaffoldError
        If *skill_id* is invalid or the target folder already exists.
    """
    _validate_skill_id(skill_id)

    if tier not in ("A", "B", "C"):
        raise ScaffoldError(f"tier {tier!r} must be 'A', 'B', or 'C'")

    display_name = name if name else skill_id.replace("_", " ").title()

    skill_dir = dest_dir / skill_id
    if skill_dir.exists():
        raise ScaffoldError(
            f"skill folder already exists at {skill_dir} — delete it first or choose a different id"
        )

    # Create the directory tree
    skill_dir.mkdir(parents=True, exist_ok=False)
    examples_dir = skill_dir / "examples"
    examples_dir.mkdir()

    # Write files
    (skill_dir / "__init__.py").write_text(_init_py(), encoding="utf-8")
    (skill_dir / "manifest.toml").write_text(
        _manifest_toml(skill_id, display_name, category, tier, watchable),
        encoding="utf-8",
    )
    (skill_dir / "skill.py").write_text(
        _skill_py(skill_id, watchable),
        encoding="utf-8",
    )
    (skill_dir / "SKILL.md").write_text(
        _skill_md(skill_id, display_name, category),
        encoding="utf-8",
    )
    (examples_dir / "example.md").write_text(
        _example_md(skill_id, display_name),
        encoding="utf-8",
    )

    return skill_dir
