"""Scope-gate tests — the reversible wedge feature flag (B).

The default UI OFFERS only ``investigate`` at the quick/standard/thorough tiers.
``deep`` and the other modes stay in the code (still resolvable by key) but are
hidden from the picker unless the config widens the enabled set.
"""

from __future__ import annotations

from lighthouse_ai.modes.depth import DEPTH_TIERS, resolve_depth
from lighthouse_ai.modes.registry import (
    WEDGE_DEPTH_TIERS,
    WEDGE_MODES,
    ScopeConfig,
    canonical,
    enabled_depth_tiers,
    enabled_modes,
    resolve,
)


def test_default_offers_only_investigate():
    """No config → wedge default: investigate is the only offered mode."""
    assert [m.key for m in enabled_modes()] == ["investigate"]
    assert [m.key for m in enabled_modes(None)] == ["investigate"]


def test_default_tiers_exclude_deep():
    tiers = enabled_depth_tiers()
    assert tiers == ["quick", "standard", "thorough"]
    assert "deep" not in tiers


def test_missing_keys_fall_back_to_wedge():
    """An otherwise-populated config with no [modes]/[depth] keys → wedge set."""
    cfg = {"lighthouse": {"version": "0.1.0"}}
    assert [m.key for m in enabled_modes(cfg)] == list(WEDGE_MODES)
    assert enabled_depth_tiers(cfg) == list(WEDGE_DEPTH_TIERS)


def test_scope_config_from_mapping_defaults():
    scope = ScopeConfig.from_mapping({})
    assert scope.modes == WEDGE_MODES
    assert scope.depth_tiers == WEDGE_DEPTH_TIERS


def test_widening_config_re_exposes_modes_and_deep():
    cfg = {
        "modes": {"enabled": ["investigate", "watch", "decide"]},
        "depth": {"enabled_tiers": ["quick", "standard", "thorough", "deep"]},
    }
    assert [m.key for m in enabled_modes(cfg)] == ["watch", "investigate", "decide"]
    assert enabled_depth_tiers(cfg) == ["quick", "standard", "thorough", "deep"]


def test_enabled_modes_is_alias_aware():
    """Config may name a mode by a legacy alias; it still resolves + is offered."""
    cfg = {"modes": {"enabled": ["deep-dive"]}}
    assert [m.key for m in enabled_modes(cfg)] == ["investigate"]


def test_unknown_config_entries_are_ignored_not_fatal():
    cfg = {
        "modes": {"enabled": ["investigate", "not_a_mode"]},
        "depth": {"enabled_tiers": ["standard", "bogus"]},
    }
    assert [m.key for m in enabled_modes(cfg)] == ["investigate"]
    # "bogus" canonicalizes to the default tier (standard) and is deduped away.
    assert enabled_depth_tiers(cfg) == ["standard"]


def test_gate_does_not_block_hidden_mode_or_tier_by_key():
    """The gate is about what is OFFERED, not a hard block on hidden things."""
    # A hidden mode still resolves when requested by explicit key.
    assert resolve("survey").key == "survey"
    assert canonical("debate") == "adjudicate"
    # The hidden Deep tier still resolves to real engine knobs.
    knobs = resolve_depth("deep")
    assert knobs["tier"] == "deep"
    assert knobs["recursive"] is True
    assert "deep" in DEPTH_TIERS


def test_from_config_file_reads_template(tmp_path):
    """from_config_file parses [modes]/[depth] tables; absent file → wedge."""
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        '[modes]\nenabled = ["investigate"]\n'
        '[depth]\nenabled_tiers = ["quick", "standard", "thorough"]\n'
    )
    scope = ScopeConfig.from_config_file(cfg_path)
    assert scope.modes == ("investigate",)
    assert scope.depth_tiers == ("quick", "standard", "thorough")
    assert [m.key for m in enabled_modes(scope)] == ["investigate"]
    assert enabled_depth_tiers(scope) == ["quick", "standard", "thorough"]

    missing = ScopeConfig.from_config_file(tmp_path / "nope.toml")
    assert missing.modes == WEDGE_MODES
    assert missing.depth_tiers == WEDGE_DEPTH_TIERS


def test_shipped_template_carries_wedge_defaults():
    """The packaged config.toml template encodes the wedge defaults verbatim.

    The template carries ``{placeholder}`` substitution slots and so is not
    valid TOML until rendered; assert on the wedge lines directly.
    """
    from importlib.resources import files

    raw = (files("lighthouse_ai.templates") / "config.toml").read_text()
    assert '[modes]' in raw
    assert 'enabled = ["investigate"]' in raw
    assert 'enabled_tiers = ["quick", "standard", "thorough"]' in raw
    assert '"deep"' not in raw.split("enabled_tiers")[1].split("\n")[0]
