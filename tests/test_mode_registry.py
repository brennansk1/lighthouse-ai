"""Tests for the mode registry (single source of truth for research modes)."""

from __future__ import annotations

import pytest

from lighthouse_ai.modes.registry import (
    REGISTRY,
    ArtifactType,
    all_modes,
    canonical,
    load_engine,
    resolve,
)


def test_seven_primary_modes_present():
    keys = {m.key for m in all_modes()}
    assert keys == {
        "watch", "ask", "investigate", "survey",
        "reconstruct", "decide", "adjudicate",
    }


def test_every_spec_has_engine_and_artifact_type():
    for spec in REGISTRY.values():
        assert ":" in spec.engine
        assert isinstance(spec.artifact_type, ArtifactType)
        assert spec.label and spec.summary


def test_legacy_aliases_resolve_to_canonical_keys():
    assert canonical("Deep-Dive") == "investigate"
    assert canonical("deepdive") == "investigate"
    assert canonical("Monitor") == "watch"
    assert canonical("QUC") == "ask"
    assert canonical("Quick Answer") == "ask"
    assert canonical("Debate") == "adjudicate"
    # Canonical keys map to themselves.
    assert canonical("watch") == "watch"


def test_unknown_mode_raises():
    with pytest.raises(KeyError):
        canonical("not_a_mode")


def test_resolve_returns_spec():
    spec = resolve("decide")
    assert spec.key == "decide"
    assert spec.artifact_type is ArtifactType.MATRIX
    assert "options" in spec.requires and "criteria" in spec.requires


def test_load_engine_imports_callable():
    fn = load_engine("investigate")
    assert callable(fn)
    assert fn.__name__ == "run_deepdive"
