"""Packaged templates rendered into ``~/.lighthouse`` and OS service dirs."""

from __future__ import annotations

from importlib import resources
from pathlib import Path


def template_text(name: str) -> str:
    """Load a template by filename from this package."""
    return (resources.files(__package__) / name).read_text()


def render(name: str, **subs: object) -> str:
    """Simple ``str.format``-style substitution."""
    return template_text(name).format(**subs)


def write_rendered(name: str, dest: Path, **subs: object) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(render(name, **subs))
    return dest
