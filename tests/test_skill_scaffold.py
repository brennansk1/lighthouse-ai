"""Tests for the skill scaffold generator and the ``lighthouse skill`` CLI group.

Covers:
* ``scaffold_skill`` function: file creation, manifest validity, load_skill passes.
* Watchable scaffold generates run_watchable.
* Invalid skill_id (with hyphens) is rejected.
* Import guard: a hand-broken skill (forbidden import) is reported as failing.
* CLI commands: ``skill new``, ``skill list``, ``skill validate`` via CliRunner.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from lighthouse_ai.cli import app
from lighthouse_ai.skills.registry import load_skill
from lighthouse_ai.skills.scaffold import ScaffoldError, scaffold_skill
from lighthouse_ai.skills.schema import load_manifest

# ---------------------------------------------------------------------------
# scaffold_skill — unit tests
# ---------------------------------------------------------------------------


class TestScaffoldSkill:
    def test_creates_expected_files(self, tmp_path: Path) -> None:
        skill_dir = scaffold_skill("my_source", tmp_path)

        assert skill_dir == tmp_path / "my_source"
        assert (skill_dir / "__init__.py").exists()
        assert (skill_dir / "manifest.toml").exists()
        assert (skill_dir / "skill.py").exists()
        assert (skill_dir / "SKILL.md").exists()
        assert (skill_dir / "examples" / "example.md").exists()

    def test_manifest_is_valid(self, tmp_path: Path) -> None:
        scaffold_skill("my_source", tmp_path, name="My Source", category="academic")
        manifest = load_manifest(tmp_path / "my_source" / "manifest.toml",
                                 expected_id="my_source")
        assert manifest.id == "my_source"
        assert manifest.name == "My Source"
        assert manifest.category == "academic"
        assert manifest.tier == "A"
        assert manifest.signed is False
        assert manifest.version == "0.1.0"

    def test_load_skill_passes(self, tmp_path: Path) -> None:
        scaffold_skill("demo_skill", tmp_path)
        loaded = load_skill("demo_skill", library_dir=tmp_path)
        assert loaded.manifest.id == "demo_skill"
        assert callable(loaded.entrypoint)

    def test_import_guard_passes(self, tmp_path: Path) -> None:
        """The generated skill.py must contain no forbidden imports."""
        scaffold_skill("clean_skill", tmp_path)
        # load_skill internally calls _audit_skill_imports — if it raises, the guard failed
        loaded = load_skill("clean_skill", library_dir=tmp_path)
        assert loaded is not None

    def test_watchable_scaffold_has_run_watchable(self, tmp_path: Path) -> None:
        scaffold_skill("watch_skill", tmp_path, watchable=True)
        loaded = load_skill("watch_skill", library_dir=tmp_path)
        assert loaded.manifest.watchable is True
        assert callable(loaded.watchable_entrypoint)

    def test_non_watchable_has_no_run_watchable(self, tmp_path: Path) -> None:
        scaffold_skill("plain_skill", tmp_path, watchable=False)
        loaded = load_skill("plain_skill", library_dir=tmp_path)
        assert loaded.manifest.watchable is False
        assert loaded.watchable_entrypoint is None

    def test_default_name_title_cases_id(self, tmp_path: Path) -> None:
        scaffold_skill("my_cool_source", tmp_path)
        manifest = load_manifest(tmp_path / "my_cool_source" / "manifest.toml",
                                 expected_id="my_cool_source")
        assert manifest.name == "My Cool Source"

    def test_custom_tier(self, tmp_path: Path) -> None:
        scaffold_skill("tier_b_skill", tmp_path, tier="B")
        manifest = load_manifest(tmp_path / "tier_b_skill" / "manifest.toml",
                                 expected_id="tier_b_skill")
        assert manifest.tier == "B"

    def test_existing_folder_raises(self, tmp_path: Path) -> None:
        scaffold_skill("existing", tmp_path)
        with pytest.raises(ScaffoldError, match="already exists"):
            scaffold_skill("existing", tmp_path)

    def test_invalid_tier_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ScaffoldError, match="tier"):
            scaffold_skill("ok_id", tmp_path, tier="Z")


# ---------------------------------------------------------------------------
# Invalid skill_id rejection
# ---------------------------------------------------------------------------


class TestInvalidSkillId:
    def test_hyphenated_id_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(ScaffoldError, match="hyphen"):
            scaffold_skill("my-source", tmp_path)

    def test_spaces_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(ScaffoldError, match="space"):
            scaffold_skill("my source", tmp_path)

    def test_empty_id_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(ScaffoldError, match="empty"):
            scaffold_skill("", tmp_path)

    def test_python_keyword_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(ScaffoldError, match="keyword"):
            scaffold_skill("import", tmp_path)

    def test_leading_digit_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(ScaffoldError, match="identifier"):
            scaffold_skill("1bad", tmp_path)

    def test_valid_identifier_with_digits_accepted(self, tmp_path: Path) -> None:
        skill_dir = scaffold_skill("source2", tmp_path)
        assert skill_dir.exists()


# ---------------------------------------------------------------------------
# Import-guard enforcement on a hand-broken skill
# ---------------------------------------------------------------------------


class TestImportGuardEnforcement:
    def test_broken_skill_fails_to_load(self, tmp_path: Path) -> None:
        """A skill that imports a forbidden module must fail the import guard."""
        from lighthouse_ai.skills.registry import SkillLoadError

        scaffold_skill("broken_skill", tmp_path)
        skill_py = tmp_path / "broken_skill" / "skill.py"
        original = skill_py.read_text(encoding="utf-8")
        # Inject a forbidden import
        skill_py.write_text("import os\n" + original, encoding="utf-8")

        with pytest.raises(SkillLoadError, match="forbidden"):
            load_skill("broken_skill", library_dir=tmp_path)

    def test_skill_with_open_call_fails(self, tmp_path: Path) -> None:
        """A skill that calls open() must be rejected by the import guard."""
        from lighthouse_ai.skills.registry import SkillLoadError

        scaffold_skill("open_skill", tmp_path)
        skill_py = tmp_path / "open_skill" / "skill.py"
        # Append a forbidden bare call
        skill_py.write_text(
            skill_py.read_text(encoding="utf-8")
            + "\ndef _bad():\n    open('/etc/passwd')\n",
            encoding="utf-8",
        )
        with pytest.raises(SkillLoadError, match="forbidden"):
            load_skill("open_skill", library_dir=tmp_path)


# ---------------------------------------------------------------------------
# CLI: lighthouse skill new
# ---------------------------------------------------------------------------


class TestSkillNewCli:
    def test_skill_new_creates_folder(self, tmp_path: Path) -> None:
        runner = CliRunner()
        r = runner.invoke(app, ["skill", "new", "cli_skill", "--dir", str(tmp_path)])
        assert r.exit_code == 0, r.stdout
        assert (tmp_path / "cli_skill").is_dir()
        assert "created skill scaffold" in r.stdout

    def test_skill_new_with_name_and_category(self, tmp_path: Path) -> None:
        runner = CliRunner()
        r = runner.invoke(app, [
            "skill", "new", "cli_news",
            "--dir", str(tmp_path),
            "--name", "CLI News Source",
            "--category", "news",
        ])
        assert r.exit_code == 0, r.stdout
        manifest = load_manifest(tmp_path / "cli_news" / "manifest.toml",
                                 expected_id="cli_news")
        assert manifest.name == "CLI News Source"
        assert manifest.category == "news"

    def test_skill_new_watchable_flag(self, tmp_path: Path) -> None:
        runner = CliRunner()
        r = runner.invoke(app, [
            "skill", "new", "cli_watch",
            "--dir", str(tmp_path),
            "--watchable",
        ])
        assert r.exit_code == 0, r.stdout
        loaded = load_skill("cli_watch", library_dir=tmp_path)
        assert loaded.manifest.watchable is True

    def test_skill_new_rejects_hyphenated_id(self, tmp_path: Path) -> None:
        runner = CliRunner()
        r = runner.invoke(app, ["skill", "new", "bad-id", "--dir", str(tmp_path)])
        assert r.exit_code != 0
        assert "hyphen" in r.output.lower() or "scaffold error" in r.output.lower()

    def test_skill_new_prints_next_steps(self, tmp_path: Path) -> None:
        runner = CliRunner()
        r = runner.invoke(app, ["skill", "new", "hint_skill", "--dir", str(tmp_path)])
        assert r.exit_code == 0
        # The command should print guidance about editing manifest.toml
        assert "manifest.toml" in r.stdout or "Next steps" in r.stdout


# ---------------------------------------------------------------------------
# CLI: lighthouse skill list
# ---------------------------------------------------------------------------


class TestSkillListCli:
    def test_skill_list_shows_scaffolded_skill(self, tmp_path: Path) -> None:
        scaffold_skill("listed_skill", tmp_path, category="academic")
        runner = CliRunner()
        r = runner.invoke(app, ["skill", "list", "--dir", str(tmp_path)])
        assert r.exit_code == 0, r.stdout
        assert "listed_skill" in r.stdout

    def test_skill_list_empty_dir(self, tmp_path: Path) -> None:
        runner = CliRunner()
        r = runner.invoke(app, ["skill", "list", "--dir", str(tmp_path)])
        assert r.exit_code == 0
        assert "no skills" in r.stdout.lower()

    def test_skill_list_json_output(self, tmp_path: Path) -> None:
        import json

        scaffold_skill("json_skill", tmp_path)
        runner = CliRunner()
        r = runner.invoke(app, ["skill", "list", "--dir", str(tmp_path), "--json"])
        assert r.exit_code == 0, r.stdout
        data = json.loads(r.stdout)
        assert "json_skill" in data

    def test_skill_list_default_library(self) -> None:
        """Default (no --dir) scans the in-tree library; at least one skill exists."""
        runner = CliRunner()
        r = runner.invoke(app, ["skill", "list"])
        assert r.exit_code == 0, r.stdout
        # The in-tree library always has at least arxiv
        assert "arxiv" in r.stdout


# ---------------------------------------------------------------------------
# CLI: lighthouse skill validate
# ---------------------------------------------------------------------------


class TestSkillValidateCli:
    def test_validate_passes_for_clean_scaffold(self, tmp_path: Path) -> None:
        scaffold_skill("valid_skill", tmp_path)
        runner = CliRunner()
        r = runner.invoke(app, ["skill", "validate", "valid_skill", "--dir", str(tmp_path)])
        assert r.exit_code == 0, r.stdout
        assert "passes all checks" in r.stdout

    def test_validate_passes_for_in_tree_skill(self) -> None:
        runner = CliRunner()
        r = runner.invoke(app, ["skill", "validate", "arxiv"])
        assert r.exit_code == 0, r.stdout
        assert "arxiv" in r.stdout

    def test_validate_fails_for_unknown_skill(self, tmp_path: Path) -> None:
        runner = CliRunner()
        r = runner.invoke(app, [
            "skill", "validate", "no_such_skill", "--dir", str(tmp_path)
        ])
        assert r.exit_code != 0

    def test_validate_reports_broken_import(self, tmp_path: Path) -> None:
        """A skill with a forbidden import must report failure."""
        scaffold_skill("validate_broken", tmp_path)
        skill_py = tmp_path / "validate_broken" / "skill.py"
        skill_py.write_text("import socket\n" + skill_py.read_text(encoding="utf-8"),
                            encoding="utf-8")
        runner = CliRunner()
        r = runner.invoke(app, [
            "skill", "validate", "validate_broken", "--dir", str(tmp_path)
        ])
        assert r.exit_code != 0
        assert "error" in r.output.lower() or "forbidden" in r.output.lower()

    def test_validate_reports_broken_manifest(self, tmp_path: Path) -> None:
        """A skill with a malformed manifest.toml must report failure."""
        scaffold_skill("mf_broken", tmp_path)
        manifest_path = tmp_path / "mf_broken" / "manifest.toml"
        # Corrupt: set tier to an invalid value
        original = manifest_path.read_text(encoding="utf-8")
        manifest_path.write_text(original.replace('tier        = "A"', 'tier = "Z"'),
                                 encoding="utf-8")
        runner = CliRunner()
        r = runner.invoke(app, [
            "skill", "validate", "mf_broken", "--dir", str(tmp_path)
        ])
        assert r.exit_code != 0
