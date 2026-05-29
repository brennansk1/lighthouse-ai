"""Research-skills library — one importable subpackage per source.

Each subfolder with a ``manifest.toml`` is a skill (see
:mod:`lighthouse_ai.skills.registry`). Folder names must be valid Python
identifiers because the loader imports them as
``lighthouse_ai.skills.library.<id>``.
"""
