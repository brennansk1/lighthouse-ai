"""PROV-O sidecar tests (closes "PROV-O sidecar not yet emitted per run").

All tests are offline/deterministic — no network, no model load.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from lighthouse_ai.paths import Paths, make_paths
from lighthouse_ai.pipeline import PipelineConfig, ResearchPipeline
from lighthouse_ai.provenance import (
    build_run_sidecar,
    load_run_sidecar,
    write_run_sidecar,
)
from lighthouse_ai.schema import kinds_for, migrate_all

# ---------------------------------------------------------------------------
# helpers / fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def migrated_paths(tmp_path: Path) -> Paths:
    paths = make_paths(tmp_path / "data", tmp_path / "replicas")
    paths.ensure()
    migrate_all(kinds_for(paths))
    return paths


def _run_offline(migrated_paths: Paths, question: str = "What is entropy?") -> tuple:
    """Run a minimal offline deep-dive, return (result, pipeline)."""
    pipe = ResearchPipeline(
        migrated_paths,
        config=PipelineConfig(offline=True, mode="deep-dive"),
    )
    pipe.ingest_text("doc1", "Entropy measures disorder in a thermodynamic system.")
    result = pipe.research(question)
    return result, pipe


# ---------------------------------------------------------------------------
# unit tests: build_run_sidecar
# ---------------------------------------------------------------------------


class TestBuildRunSidecar:
    """Pure function tests — no I/O."""

    def test_returns_dict(self) -> None:
        s = build_run_sidecar(
            draft_id="d-abc123",
            job_id="job-001",
            question="What is X?",
            mode="deep-dive",
            backends={"embedder": "hash-stub", "gateway": "mock"},
            source_count=2,
        )
        assert isinstance(s, dict)

    def test_contains_required_top_level_keys(self) -> None:
        s = build_run_sidecar(
            draft_id="d-abc123",
            job_id="job-001",
            question="What is X?",
            mode="deep-dive",
            backends={"embedder": "hash-stub"},
            source_count=1,
        )
        assert "activity" in s
        assert "agents" in s
        assert "draftEntity" in s
        assert "sourceEntities" in s
        assert "lighthouse:draftId" in s
        assert "lighthouse:jobId" in s

    def test_draft_id_and_job_id_stored(self) -> None:
        s = build_run_sidecar(
            draft_id="d-xyz",
            job_id="j-999",
            question="Q?",
            mode="quc",
            backends={},
            source_count=0,
        )
        assert s["lighthouse:draftId"] == "d-xyz"
        assert s["lighthouse:jobId"] == "j-999"

    def test_content_hash_in_sidecar_and_entity(self) -> None:
        h = "a" * 64
        s = build_run_sidecar(
            draft_id="d-hash",
            job_id="j-h",
            question="Q?",
            mode="deep-dive",
            backends={},
            source_count=0,
            content_hash=h,
        )
        assert s["lighthouse:contentHash"] == h
        assert s["draftEntity"]["lighthouse:contentHash"] == h

    def test_content_hash_none_is_allowed(self) -> None:
        s = build_run_sidecar(
            draft_id="d-nohash",
            job_id="j-nh",
            question="Q?",
            mode="deep-dive",
            backends={},
            source_count=0,
            content_hash=None,
        )
        # Key present but None is fine; callers may not always have a hash.
        assert s.get("lighthouse:contentHash") is None

    def test_source_entities_count_matches_source_count(self) -> None:
        s = build_run_sidecar(
            draft_id="d-src",
            job_id="j-src",
            question="Q?",
            mode="deep-dive",
            backends={},
            source_count=5,
        )
        assert len(s["sourceEntities"]) == 5

    def test_agent_urns_from_backends(self) -> None:
        s = build_run_sidecar(
            draft_id="d-ag",
            job_id="j-ag",
            question="Q?",
            mode="deep-dive",
            backends={"embedder": "hash-stub", "gateway": "mock"},
            source_count=0,
        )
        agent_ids = [a["@id"] for a in s["agents"]]
        assert any("embedder" in aid for aid in agent_ids)
        assert any("gateway" in aid for aid in agent_ids)

    def test_activity_contains_mode(self) -> None:
        s = build_run_sidecar(
            draft_id="d-m",
            job_id="j-m",
            question="Q?",
            mode="survey",
            backends={},
            source_count=0,
        )
        assert s["activity"]["lighthouse:mode"] == "survey"

    def test_timestamps_stored(self) -> None:
        from datetime import UTC, datetime

        t = datetime(2025, 6, 1, 12, 0, 0, tzinfo=UTC)
        s = build_run_sidecar(
            draft_id="d-ts",
            job_id="j-ts",
            question="Q?",
            mode="deep-dive",
            backends={},
            source_count=0,
            started_at=t,
            ended_at=t,
        )
        assert s["activity"]["prov:startedAtTime"] == "2025-06-01T12:00:00Z"
        assert s["activity"]["prov:endedAtTime"] == "2025-06-01T12:00:00Z"

    def test_draft_entity_has_prov_type(self) -> None:
        s = build_run_sidecar(
            draft_id="d-e",
            job_id="j-e",
            question="Q?",
            mode="deep-dive",
            backends={},
            source_count=0,
        )
        assert s["draftEntity"]["@type"] == "prov:Entity"

    def test_activity_generated_points_to_draft(self) -> None:
        s = build_run_sidecar(
            draft_id="d-gen",
            job_id="j-gen",
            question="Q?",
            mode="deep-dive",
            backends={},
            source_count=0,
        )
        assert "d-gen" in s["activity"]["prov:generated"]

    def test_json_serialisable(self) -> None:
        s = build_run_sidecar(
            draft_id="d-ser",
            job_id="j-ser",
            question="Q?",
            mode="deep-dive",
            backends={"embedder": "hash-stub"},
            source_count=3,
            content_hash="c" * 64,
        )
        text = json.dumps(s)
        assert json.loads(text) == s


# ---------------------------------------------------------------------------
# unit tests: write_run_sidecar / load_run_sidecar
# ---------------------------------------------------------------------------


class TestWriteAndLoadSidecar:
    def test_write_creates_file(self, tmp_path: Path) -> None:
        s = build_run_sidecar(
            draft_id="d-w",
            job_id="j-w",
            question="Q?",
            mode="deep-dive",
            backends={},
            source_count=0,
        )
        p = tmp_path / "d-w.prov.json"
        write_run_sidecar(p, s)
        assert p.exists()

    def test_round_trip(self, tmp_path: Path) -> None:
        s = build_run_sidecar(
            draft_id="d-rt",
            job_id="j-rt",
            question="Round-trip?",
            mode="deep-dive",
            backends={"embedder": "hash-stub", "gateway": "mock"},
            source_count=2,
            content_hash="d" * 64,
        )
        p = tmp_path / "d-rt.prov.json"
        write_run_sidecar(p, s)
        loaded = load_run_sidecar(p)
        assert loaded == s

    def test_load_missing_file_returns_empty_dict(self, tmp_path: Path) -> None:
        result = load_run_sidecar(tmp_path / "nonexistent.prov.json")
        assert result == {}

    def test_written_file_is_valid_json(self, tmp_path: Path) -> None:
        s = build_run_sidecar(
            draft_id="d-vj",
            job_id="j-vj",
            question="Q?",
            mode="deep-dive",
            backends={},
            source_count=0,
        )
        p = tmp_path / "d-vj.prov.json"
        write_run_sidecar(p, s)
        parsed = json.loads(p.read_text(encoding="utf-8"))
        assert isinstance(parsed, dict)

    def test_write_creates_parent_dirs(self, tmp_path: Path) -> None:
        s = build_run_sidecar(
            draft_id="d-d",
            job_id="j-d",
            question="Q?",
            mode="deep-dive",
            backends={},
            source_count=0,
        )
        p = tmp_path / "nested" / "deep" / "d-d.prov.json"
        write_run_sidecar(p, s)
        assert p.exists()

    def test_tmp_file_cleaned_up_after_write(self, tmp_path: Path) -> None:
        s = build_run_sidecar(
            draft_id="d-cl",
            job_id="j-cl",
            question="Q?",
            mode="deep-dive",
            backends={},
            source_count=0,
        )
        p = tmp_path / "d-cl.prov.json"
        write_run_sidecar(p, s)
        tmp = p.with_suffix(".prov.tmp")
        assert not tmp.exists()


# ---------------------------------------------------------------------------
# integration tests: sidecar emitted by pipeline
# ---------------------------------------------------------------------------


class TestPipelineSidecarEmission:
    def test_sidecar_written_after_research(self, migrated_paths: Paths) -> None:
        result, _ = _run_offline(migrated_paths)
        sidecar_path = migrated_paths.staging_dir / f"{result.draft_id}.prov.json"
        assert sidecar_path.exists(), (
            f"Expected sidecar at {sidecar_path}, but it was not created."
        )

    def test_sidecar_is_valid_json(self, migrated_paths: Paths) -> None:
        result, _ = _run_offline(migrated_paths)
        sidecar_path = migrated_paths.staging_dir / f"{result.draft_id}.prov.json"
        text = sidecar_path.read_text(encoding="utf-8")
        parsed = json.loads(text)
        assert isinstance(parsed, dict)

    def test_sidecar_contains_draft_id(self, migrated_paths: Paths) -> None:
        result, _ = _run_offline(migrated_paths)
        sidecar_path = migrated_paths.staging_dir / f"{result.draft_id}.prov.json"
        doc = load_run_sidecar(sidecar_path)
        assert doc["lighthouse:draftId"] == result.draft_id

    def test_sidecar_contains_activity_with_mode(self, migrated_paths: Paths) -> None:
        result, _ = _run_offline(migrated_paths)
        sidecar_path = migrated_paths.staging_dir / f"{result.draft_id}.prov.json"
        doc = load_run_sidecar(sidecar_path)
        assert "activity" in doc
        # "deep-dive" canonicalises to "investigate" in the mode registry.
        mode = doc["activity"]["lighthouse:mode"]
        assert isinstance(mode, str)
        assert len(mode) > 0

    def test_sidecar_contains_agents(self, migrated_paths: Paths) -> None:
        result, _ = _run_offline(migrated_paths)
        sidecar_path = migrated_paths.staging_dir / f"{result.draft_id}.prov.json"
        doc = load_run_sidecar(sidecar_path)
        assert isinstance(doc["agents"], list)
        assert len(doc["agents"]) >= 1

    def test_sidecar_contains_entities(self, migrated_paths: Paths) -> None:
        result, _ = _run_offline(migrated_paths)
        sidecar_path = migrated_paths.staging_dir / f"{result.draft_id}.prov.json"
        doc = load_run_sidecar(sidecar_path)
        assert "draftEntity" in doc
        assert doc["draftEntity"]["@type"] == "prov:Entity"

    def test_sidecar_contains_content_hash(self, migrated_paths: Paths) -> None:
        result, _ = _run_offline(migrated_paths)
        sidecar_path = migrated_paths.staging_dir / f"{result.draft_id}.prov.json"
        doc = load_run_sidecar(sidecar_path)
        # content_hash must be a 64-char hex string (SHA-256)
        h = doc.get("lighthouse:contentHash")
        assert h is not None
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)

    def test_sidecar_content_hash_matches_body(self, migrated_paths: Paths) -> None:
        """The hash in the sidecar must equal SHA-256(body_html)."""
        import hashlib

        from lighthouse_ai.persistence import open_db

        result, _ = _run_offline(migrated_paths)
        # Retrieve body_html from the DB.
        conn = open_db(migrated_paths.state_db)
        try:
            row = conn.execute(
                "SELECT body_html FROM drafts WHERE id=?", (result.draft_id,)
            ).fetchone()
        finally:
            conn.close()
        expected_hash = hashlib.sha256(row[0].encode()).hexdigest()
        sidecar_path = migrated_paths.staging_dir / f"{result.draft_id}.prov.json"
        doc = load_run_sidecar(sidecar_path)
        assert doc["lighthouse:contentHash"] == expected_hash

    def test_sidecar_source_entities_count(self, migrated_paths: Paths) -> None:
        result, _ = _run_offline(migrated_paths)
        sidecar_path = migrated_paths.staging_dir / f"{result.draft_id}.prov.json"
        doc = load_run_sidecar(sidecar_path)
        assert len(doc["sourceEntities"]) == doc["lighthouse:sourceCount"]

    def test_sidecar_round_trips_through_load_run_sidecar(
        self, migrated_paths: Paths
    ) -> None:
        result, _ = _run_offline(migrated_paths)
        sidecar_path = migrated_paths.staging_dir / f"{result.draft_id}.prov.json"
        doc = load_run_sidecar(sidecar_path)
        # Re-serialise and re-parse — must equal original.
        reparsed = json.loads(json.dumps(doc, sort_keys=True))
        assert reparsed["lighthouse:draftId"] == result.draft_id
        assert reparsed["activity"]["lighthouse:jobId"] is not None

    def test_sidecar_write_failure_does_not_crash_run(
        self, migrated_paths: Paths
    ) -> None:
        """If writing the sidecar fails, the research run must still succeed.

        ``write_run_sidecar`` is imported inside the function body, so we patch
        it at its definition site (``lighthouse_ai.provenance`).
        """

        def _raise(*args, **kwargs):
            raise OSError("simulated disk full")

        with patch(
            "lighthouse_ai.provenance.write_run_sidecar",
            side_effect=_raise,
        ):
            pipe = ResearchPipeline(
                migrated_paths,
                config=PipelineConfig(offline=True, mode="deep-dive"),
            )
            pipe.ingest_text("doc1", "Entropy measures disorder.")
            result = pipe.research("What is entropy?")
        # Run completed normally despite the sidecar error.
        assert result.draft_id.startswith("d-")

    def test_quc_mode_also_emits_sidecar(self, migrated_paths: Paths) -> None:
        pipe = ResearchPipeline(
            migrated_paths,
            config=PipelineConfig(offline=True, mode="quc"),
        )
        pipe.ingest_text("doc1", "The Fed sets rates via the discount window.")
        result = pipe.research("How does the Fed set rates?")
        sidecar_path = migrated_paths.staging_dir / f"{result.draft_id}.prov.json"
        assert sidecar_path.exists()
        doc = load_run_sidecar(sidecar_path)
        assert doc["lighthouse:draftId"] == result.draft_id
