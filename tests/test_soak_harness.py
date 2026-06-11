"""Unit tests for the soak harness leak detector (scripts/soak.py).

Regression for a live false-positive: a 90s loaded soak flagged "possible FD
leak: fds rose 7→11 monotonically" — but a per-fd probe showed that rise is
connection-pool/kqueue warmup that plateaus at ~10. The detector must skip the
warmup prefix and require an absolute rise big enough to matter.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

_SOAK = Path(__file__).resolve().parents[1] / "scripts" / "soak.py"
_spec = importlib.util.spec_from_file_location("soak", _SOAK)
assert _spec is not None and _spec.loader is not None
soak = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(soak)

growth = soak._is_monotonic_growth


def test_warmup_then_plateau_is_not_a_leak():
    # The live trace: fds 7→10 in the first samples, then flat for the rest.
    series = [7.0, 9.0, 10.0] + [10.0] * 17
    assert not growth(series, min_frac=0.5, min_abs=20.0)


def test_short_run_warmup_is_not_a_leak():
    # The exact 90s shakeout that mis-flagged: 6 samples, all warmup.
    series = [7.0, 8.0, 9.0, 10.0, 11.0, 11.0]
    assert not growth(series, min_frac=0.5, min_abs=20.0)


def test_steady_post_warmup_growth_is_a_leak():
    # A genuine leak: keeps climbing well past warmup, large absolute rise.
    series = [float(10 + 3 * i) for i in range(40)]
    assert growth(series, min_frac=0.5, min_abs=20.0)


def test_small_absolute_drift_is_noise_even_if_monotonic():
    # 8→14 fds over a long run is +75% relative but only +6 absolute.
    series = [8.0] * 10 + [float(8 + i * 0.5) for i in range(12)]
    assert not growth(series, min_frac=0.5, min_abs=20.0)


def test_rss_leak_still_detected_with_min_abs():
    # RSS 60MB→200MB sustained: must trip with min_abs=50.
    series = [float(60 + 6 * i) for i in range(24)]
    assert growth(series, min_frac=0.5, min_abs=50.0)


def test_non_monotonic_bumps_are_not_a_leak():
    # GC sawtooth: rises and falls — never flagged regardless of net.
    series = [100.0, 140.0, 90.0, 150.0, 95.0, 160.0, 100.0, 110.0]
    assert not growth(series, min_frac=0.5, min_abs=0.0)
