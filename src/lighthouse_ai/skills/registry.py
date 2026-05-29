"""Skill registry — discover skills on disk and load them safely.

Discovery is a directory scan over :data:`LIBRARY_DIR`: any subfolder holding a
``manifest.toml`` is a skill. This is what makes the library *compounding* — a
new source is a new folder, no core edit, no central list to append to.

Loading a skill's Python entrypoint is the trust boundary. Before importing a
skill we statically scan its ``.py`` files for forbidden imports (raw ``httpx``,
``requests``, ``urllib``, ``socket``, ``subprocess``, ``ctypes`` …). A skill that
tries to bypass the capability surface **fails to load** rather than running with
unrestricted reach (see ``SKILL_FRAMEWORK.md`` §Security). This is a denylist
guard for V1; a stricter import-hook sandbox is the documented V2.
"""

from __future__ import annotations

import ast
import importlib
import importlib.util
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

import structlog

from .schema import SkillManifest, SkillManifestError, load_manifest

log = structlog.get_logger(__name__)

LIBRARY_DIR = Path(__file__).parent / "library"

# Modules a skill's own source may NOT import directly: anything that could
# reach the network, filesystem, or a subprocess outside the capability surface.
# Skills must use SkillContext for all of that. Vetted lighthouse modules
# (sources/*, skills.capabilities, etc.) are allowed — the guard only inspects
# the skill's own files, not transitive imports of trusted code.
FORBIDDEN_IMPORT_ROOTS: frozenset[str] = frozenset(
    {
        "httpx",
        "requests",
        "urllib",
        "urllib3",
        "http",
        "socket",
        "ssl",
        "subprocess",
        "multiprocessing",
        "ctypes",
        "asyncio",
        "aiohttp",
        "ftplib",
        "telnetlib",
        "smtplib",
        "pickle",
        "shutil",
        "tempfile",
    }
)


class SkillNotFound(KeyError):
    """Raised when a skill id has no folder under the library directory."""


class SkillLoadError(RuntimeError):
    """Raised when a skill fails the import guard or its entrypoint is missing."""


@dataclass(frozen=True)
class LoadedSkill:
    """A skill whose manifest is parsed and whose entrypoints are imported.

    ``entrypoint`` is the Pattern-1/3 ``run(ctx, question, *, max_results)``.
    ``watchable_entrypoint`` is the Pattern-2 ``run_watchable(ctx, query, *,
    since, max_results)`` resolved from the same module when the manifest sets
    ``watchable=true`` (``None`` otherwise).
    """

    manifest: SkillManifest
    entrypoint: Callable[..., list]
    path: Path
    watchable_entrypoint: Callable[..., list] | None = None


def _forbidden_imports(source: str) -> list[str]:
    """Return the forbidden top-level module names imported by ``source``.

    Parses the file and checks ``import x`` / ``from x import y`` against
    :data:`FORBIDDEN_IMPORT_ROOTS` by first dotted segment. Syntax errors are
    surfaced as a forbidden marker so a malformed skill also fails to load.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:  # pragma: no cover - defensive
        return [f"<syntax-error: {exc}>"]

    bad: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".", 1)[0]
                if root in FORBIDDEN_IMPORT_ROOTS:
                    bad.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            # Relative imports (level>0) stay within the skill/lighthouse tree.
            if node.level == 0 and node.module:
                root = node.module.split(".", 1)[0]
                if root in FORBIDDEN_IMPORT_ROOTS:
                    bad.append(node.module)
    return bad


def _audit_skill_imports(skill_dir: Path) -> None:
    """Raise :class:`SkillLoadError` if any ``.py`` file imports a forbidden module."""
    offenders: dict[str, list[str]] = {}
    for py in sorted(skill_dir.rglob("*.py")):
        bad = _forbidden_imports(py.read_text(encoding="utf-8"))
        if bad:
            offenders[str(py.relative_to(skill_dir))] = bad
    if offenders:
        raise SkillLoadError(
            f"skill at {skill_dir.name} imports forbidden modules "
            f"(use SkillContext instead): {offenders}"
        )


def discover_skills(library_dir: Path | None = None) -> dict[str, SkillManifest]:
    """Scan the library directory and return ``{id: SkillManifest}``.

    A subfolder is a skill iff it contains ``manifest.toml``. Folders whose
    manifest fails validation are skipped with a warning rather than crashing
    discovery — one broken community skill must not break the whole catalog.
    """
    base = library_dir if library_dir is not None else LIBRARY_DIR
    out: dict[str, SkillManifest] = {}
    if not base.exists():
        return out
    for child in sorted(base.iterdir()):
        if not child.is_dir():
            continue
        manifest_path = child / "manifest.toml"
        if not manifest_path.exists():
            continue
        try:
            manifest = load_manifest(manifest_path, expected_id=child.name)
        except SkillManifestError as exc:
            log.warning("skills.discover_skipped", skill=child.name, error=str(exc))
            continue
        out[manifest.id] = manifest
    return out


def all_skills(library_dir: Path | None = None) -> list[SkillManifest]:
    """All discovered manifests, sorted by id (stable catalog order)."""
    return [m for _, m in sorted(discover_skills(library_dir).items())]


def _import_entry_module(
    skill_id: str, skill_dir: Path, base: Path, module_name: str
) -> ModuleType:
    """Import a skill's entry module, in-tree by dotted path or by file path.

    In-tree skills (under :data:`LIBRARY_DIR`) import as
    ``lighthouse_ai.skills.library.<id>.<module>`` so their relative imports
    (``from .tools import x``) resolve. Out-of-tree library dirs — chiefly tests
    using a temp directory — are loaded directly from the entry ``.py`` file;
    such skills must use absolute imports only.
    """
    mod = module_name or "skill"
    if base == LIBRARY_DIR:
        dotted = f"{__package__}.library.{skill_id}.{mod}"
        return importlib.import_module(dotted)

    mod_file = skill_dir / f"{mod}.py"
    if not mod_file.exists():
        raise SkillLoadError(f"skill {skill_id!r}: no entry module {mod_file}")
    spec = importlib.util.spec_from_file_location(f"_lh_skill_{skill_id}_{mod}", mod_file)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise SkillLoadError(f"skill {skill_id!r}: cannot build import spec for {mod_file}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_skill(skill_id: str, library_dir: Path | None = None) -> LoadedSkill:
    """Validate, import, and return a :class:`LoadedSkill` for ``skill_id``.

    Steps: locate the folder → parse manifest → run the import guard → import
    the ``entrypoint`` (``"module:func"`` relative to the skill package).
    """
    base = library_dir if library_dir is not None else LIBRARY_DIR
    skill_dir = base / skill_id
    manifest_path = skill_dir / "manifest.toml"
    if not manifest_path.exists():
        raise SkillNotFound(skill_id)

    manifest = load_manifest(manifest_path, expected_id=skill_id)
    _audit_skill_imports(skill_dir)

    module_name, _, func_name = manifest.entrypoint.partition(":")
    func_name = func_name or "run"
    try:
        module = _import_entry_module(skill_id, skill_dir, base, module_name)
    except ImportError as exc:
        raise SkillLoadError(
            f"skill {skill_id!r}: cannot import entrypoint module for {manifest.entrypoint!r}: {exc}"
        ) from exc
    entry = getattr(module, func_name, None)
    if entry is None or not callable(entry):
        raise SkillLoadError(
            f"skill {skill_id!r}: entrypoint {manifest.entrypoint!r} not callable"
        )

    watch_entry = None
    if manifest.watchable:
        watch_entry = getattr(module, "run_watchable", None)
        if watch_entry is None or not callable(watch_entry):
            raise SkillLoadError(
                f"skill {skill_id!r}: watchable=true but its entry module has no "
                "callable run_watchable(ctx, query, *, since, max_results)"
            )

    return LoadedSkill(
        manifest=manifest, entrypoint=entry, path=skill_dir, watchable_entrypoint=watch_entry
    )
