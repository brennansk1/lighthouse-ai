"""Unit tests for scripts/run_parity.py.

Asserts that running the parity script in mock/offline mode executes cleanly
and produces the expected files.
"""

from __future__ import annotations


def test_parity_runner_main_mock(monkeypatch, tmp_path):
    from scripts import run_parity

    # Override directories to work in temp test space
    monkeypatch.setattr(run_parity, "DROPZONE_DIR", tmp_path / "dropzone")
    monkeypatch.setattr(run_parity, "REPORT_PATH", tmp_path / "frontier_parity_report.md")

    # Ensure real backend env var is off
    monkeypatch.setenv("LIGHTHOUSE_REAL_BACKEND", "0")

    # Execute main
    exit_code = run_parity.main()
    assert exit_code == 0

    # Check drop-zone created and populated with default json
    assert (tmp_path / "dropzone" / "frontier_scores.json").exists()

    # Check report compiled
    report_file = tmp_path / "frontier_parity_report.md"
    assert report_file.exists()
    report_text = report_file.read_text()
    assert "# Frontier-parity report" in report_text
    assert "Trust wedge" in report_text
