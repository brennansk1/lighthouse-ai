"""Focused unit tests for ``lighthouse_ai.provenance`` (PROV-O emission, §27.7).

Complements ``tests/test_provenance_sidecar.py``, which covers
``build_run_sidecar``/``write_run_sidecar``/``load_run_sidecar`` and the
pipeline integration. Here we pin the lower-level building blocks:

  * ``prov_activity`` record shape, URN minting, and optional-field handling;
  * timestamp normalisation (naive → UTC, tz conversion, microsecond drop);
  * ``ProvenanceLog`` append/load round-trips, ordering, and determinism;
  * ``load_provenance`` tolerance contracts (missing file, blank lines, torn
    final line) and its corruption error path;
  * sidecar details the integration tests skip (sampling block, model agents,
    unicode payloads, write failure atomicity).

All tests are offline and deterministic — no network, no model load.
"""

from __future__ import annotations

import dataclasses
import json
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from lighthouse_ai.provenance import (
    PROV_CONTEXT,
    URN_PREFIX,
    ProvenanceLog,
    build_run_sidecar,
    load_provenance,
    prov_activity,
    write_run_sidecar,
)

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _minimal_activity(**overrides: Any) -> dict[str, Any]:
    """Build a prov_activity with only the required args, plus overrides."""
    kwargs: dict[str, Any] = {"activity_id": "act-1", "agent": "section_researcher"}
    kwargs.update(overrides)
    return prov_activity(**kwargs)


# ---------------------------------------------------------------------------
# prov_activity: record shape and URN minting
# ---------------------------------------------------------------------------


def test_activity_minimal_record_shape() -> None:
    rec = _minimal_activity()
    assert rec["@context"] == PROV_CONTEXT
    assert rec["@id"] == f"{URN_PREFIX}:action:act-1"
    assert rec["@type"] == "prov:Activity"
    assert rec["prov:wasAssociatedWith"] == f"{URN_PREFIX}:agent:section_researcher"


def test_activity_optional_fields_omitted_when_absent() -> None:
    rec = _minimal_activity()
    for key in (
        "prov:generated",
        "prov:wasAttributedTo",
        "prov:startedAtTime",
        "prov:endedAtTime",
    ):
        assert key not in rec


def test_activity_used_defaults_to_empty_list() -> None:
    rec = _minimal_activity()
    assert rec["prov:used"] == []


def test_activity_used_mints_input_urns_for_bare_values() -> None:
    rec = _minimal_activity(used=["tool:search", "doc1"])
    assert rec["prov:used"] == [
        f"{URN_PREFIX}:input:tool:search",
        f"{URN_PREFIX}:input:doc1",
    ]


def test_activity_used_preserves_existing_urns() -> None:
    existing = f"{URN_PREFIX}:source:sha256:abc"
    rec = _minimal_activity(used=[existing])
    assert rec["prov:used"] == [existing]  # never double-prefixed


def test_activity_used_accepts_any_iterable() -> None:
    rec = _minimal_activity(used=(f"s{i}" for i in range(3)))
    assert len(rec["prov:used"]) == 3


def test_activity_generated_mints_artifact_urn() -> None:
    rec = _minimal_activity(generated="d-123")
    assert rec["prov:generated"] == f"{URN_PREFIX}:artifact:d-123"


def test_activity_generated_preserves_existing_urn() -> None:
    existing = f"{URN_PREFIX}:artifact:d-123"
    rec = _minimal_activity(generated=existing)
    assert rec["prov:generated"] == existing


def test_activity_attribution_is_keyed_by_sha256_digest() -> None:
    rec = _minimal_activity(attributed_to="deadbeef" * 8)
    assert rec["prov:wasAttributedTo"] == f"{URN_PREFIX}:model:sha256:{'deadbeef' * 8}"


def test_activity_attribution_preserves_existing_urn() -> None:
    existing = f"{URN_PREFIX}:model:sha256:abc"
    rec = _minimal_activity(attributed_to=existing)
    assert rec["prov:wasAttributedTo"] == existing


def test_activity_is_deterministic_for_same_inputs() -> None:
    kwargs: dict[str, Any] = {
        "activity_id": "a",
        "agent": "g",
        "used": ["s1", "s2"],
        "generated": "d",
        "attributed_to": "ff" * 32,
        "started_at": datetime(2025, 6, 1, tzinfo=UTC),
        "ended_at": datetime(2025, 6, 1, 0, 0, 5, tzinfo=UTC),
    }
    a = prov_activity(**kwargs)
    b = prov_activity(**kwargs)
    assert a == b
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


# ---------------------------------------------------------------------------
# prov_activity: timestamp normalisation (_iso_utc via the public API)
# ---------------------------------------------------------------------------


def test_naive_datetime_is_treated_as_utc() -> None:
    rec = _minimal_activity(started_at=datetime(2025, 1, 2, 3, 4, 5))
    assert rec["prov:startedAtTime"] == "2025-01-02T03:04:05Z"


def test_aware_datetime_is_converted_to_utc() -> None:
    plus_two = timezone(timedelta(hours=2))
    rec = _minimal_activity(ended_at=datetime(2025, 1, 2, 14, 0, 0, tzinfo=plus_two))
    assert rec["prov:endedAtTime"] == "2025-01-02T12:00:00Z"


def test_microseconds_are_dropped_for_stability() -> None:
    rec = _minimal_activity(started_at=datetime(2025, 1, 2, 3, 4, 5, 999_999, tzinfo=UTC))
    assert rec["prov:startedAtTime"] == "2025-01-02T03:04:05Z"


def test_string_timestamps_pass_through_verbatim() -> None:
    rec = _minimal_activity(started_at="2025-06-01T00:00:00Z")
    assert rec["prov:startedAtTime"] == "2025-06-01T00:00:00Z"


# ---------------------------------------------------------------------------
# ProvenanceLog: append / load round-trips
# ---------------------------------------------------------------------------


def test_log_append_then_load_round_trips(tmp_path: Path) -> None:
    log = ProvenanceLog(tmp_path)
    rec = _minimal_activity(used=["s1"], generated="d-1")
    log.append(rec)
    assert log.load() == [rec]


def test_log_preserves_write_order(tmp_path: Path) -> None:
    log = ProvenanceLog(tmp_path)
    records = [prov_activity(activity_id=f"a{i}", agent="g") for i in range(5)]
    for rec in records:
        log.append(rec)
    assert log.load() == records


def test_log_append_creates_parent_dirs(tmp_path: Path) -> None:
    log = ProvenanceLog(tmp_path / "nested" / "deep")
    log.append({"k": "v"})
    assert log.path.exists()
    assert log.load() == [{"k": "v"}]


def test_log_path_combines_dir_and_filename(tmp_path: Path) -> None:
    log = ProvenanceLog(tmp_path, filename="custom.jsonl")
    assert log.path == tmp_path / "custom.jsonl"


def test_log_is_frozen(tmp_path: Path) -> None:
    log = ProvenanceLog(tmp_path)
    with pytest.raises(dataclasses.FrozenInstanceError):
        log.dir = tmp_path / "elsewhere"  # type: ignore[misc]


def test_log_load_missing_file_returns_empty_list(tmp_path: Path) -> None:
    log = ProvenanceLog(tmp_path / "never-written")
    assert log.load() == []


def test_log_lines_are_byte_stable_across_appends(tmp_path: Path) -> None:
    """sort_keys must make identical records serialise to identical lines."""
    rec = _minimal_activity(used=["s1"], generated="d-1")
    log_a = ProvenanceLog(tmp_path / "a")
    log_b = ProvenanceLog(tmp_path / "b")
    log_a.append(rec)
    log_b.append(dict(reversed(rec.items())))  # same data, different key order
    assert log_a.path.read_bytes() == log_b.path.read_bytes()


def test_log_each_record_is_one_line(tmp_path: Path) -> None:
    log = ProvenanceLog(tmp_path)
    log.append(_minimal_activity())
    log.append(_minimal_activity(activity_id="act-2"))
    lines = log.path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert all(json.loads(line) for line in lines)


def test_log_append_activity_builds_appends_and_returns(tmp_path: Path) -> None:
    log = ProvenanceLog(tmp_path)
    rec = log.append_activity(activity_id="act-9", agent="judge", generated="d-9")
    assert rec["@id"] == f"{URN_PREFIX}:action:act-9"
    assert log.load() == [rec]


def test_log_unicode_round_trips(tmp_path: Path) -> None:
    log = ProvenanceLog(tmp_path)
    rec = _minimal_activity(
        activity_id="résumé-Δ",
        agent="агент-研究",
        used=["café ☕", "naïve—source"],
    )
    log.append(rec)
    assert log.load() == [rec]


# ---------------------------------------------------------------------------
# load_provenance: tolerance contracts and the corruption error path
# ---------------------------------------------------------------------------


def test_load_provenance_missing_file_returns_empty_list(tmp_path: Path) -> None:
    assert load_provenance(tmp_path / "nope.jsonl") == []


def test_load_provenance_accepts_str_path(tmp_path: Path) -> None:
    p = tmp_path / "p.jsonl"
    p.write_text('{"a": 1}\n', encoding="utf-8")
    assert load_provenance(str(p)) == [{"a": 1}]


def test_load_provenance_skips_blank_lines(tmp_path: Path) -> None:
    p = tmp_path / "p.jsonl"
    p.write_text('\n{"a": 1}\n\n   \n{"b": 2}\n\n', encoding="utf-8")
    assert load_provenance(p) == [{"a": 1}, {"b": 2}]


def test_load_provenance_empty_file_returns_empty_list(tmp_path: Path) -> None:
    p = tmp_path / "p.jsonl"
    p.write_text("", encoding="utf-8")
    assert load_provenance(p) == []


def test_load_provenance_tolerates_torn_final_line(tmp_path: Path) -> None:
    """Crash mid-append loses at most the final record, never the whole file."""
    p = tmp_path / "p.jsonl"
    p.write_text('{"a": 1}\n{"b": 2}\n{"torn": tru', encoding="utf-8")
    assert load_provenance(p) == [{"a": 1}, {"b": 2}]


def test_load_provenance_raises_on_corrupt_middle_line(tmp_path: Path) -> None:
    """Garbage *between* valid records is tampering/corruption — must raise."""
    p = tmp_path / "p.jsonl"
    p.write_text('{"a": 1}\nnot json at all\n{"b": 2}\n', encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        load_provenance(p)


# ---------------------------------------------------------------------------
# build_run_sidecar: details not covered by test_provenance_sidecar.py
# ---------------------------------------------------------------------------


def _sidecar(**overrides: Any) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "draft_id": "d-1",
        "job_id": "j-1",
        "question": "Q?",
        "mode": "deep-dive",
        "backends": {},
        "source_count": 0,
    }
    kwargs.update(overrides)
    return build_run_sidecar(**kwargs)


def test_sidecar_models_become_sha256_keyed_agents() -> None:
    digest = "ab" * 32
    s = _sidecar(models=[digest])
    model_agents = [a for a in s["agents"] if a["@id"].startswith(f"{URN_PREFIX}:model:")]
    assert model_agents == [
        {
            "@id": f"{URN_PREFIX}:model:sha256:{digest}",
            "@type": "prov:Agent",
            "prov:label": digest,
        }
    ]


def test_sidecar_activity_associated_with_all_agents() -> None:
    s = _sidecar(backends={"embedder": "hash-stub", "gateway": "mock"}, models=["ff" * 32])
    assert s["activity"]["prov:wasAssociatedWith"] == [a["@id"] for a in s["agents"]]
    assert len(s["agents"]) == 3


def test_sidecar_source_urns_are_deterministic_and_job_scoped() -> None:
    s = _sidecar(job_id="j-77", source_count=3)
    expected = [f"{URN_PREFIX}:source:j-77:{i}" for i in range(3)]
    assert s["activity"]["prov:used"] == expected
    assert [e["@id"] for e in s["sourceEntities"]] == expected


def test_sidecar_sampling_omitted_by_default() -> None:
    s = _sidecar()
    assert "lighthouse:sampling" not in s
    assert "lighthouse:sampling" not in s["activity"]


def test_sidecar_sampling_recorded_on_activity_and_top_level() -> None:
    sampling = {"locked": True, "roles": {"planner": {"seed": 0, "temperature": 0.0}}}
    s = _sidecar(sampling=sampling)
    assert s["lighthouse:sampling"] == sampling
    assert s["activity"]["lighthouse:sampling"] == sampling


def test_sidecar_empty_inputs_yield_empty_collections() -> None:
    s = _sidecar(backends={}, source_count=0)
    assert s["agents"] == []
    assert s["sourceEntities"] == []
    assert s["activity"]["prov:wasAssociatedWith"] == []
    assert s["activity"]["prov:used"] == []


def test_sidecar_timestamps_omitted_when_absent() -> None:
    s = _sidecar()
    assert "prov:startedAtTime" not in s["activity"]
    assert "prov:endedAtTime" not in s["activity"]


def test_sidecar_unicode_question_survives_write_and_load(tmp_path: Path) -> None:
    question = "Qu'est-ce que l'entropie — 熵とは何か? ∑pᵢ·log(pᵢ)"
    s = _sidecar(question=question)
    p = tmp_path / "d-1.prov.json"
    write_run_sidecar(p, s)
    loaded = json.loads(p.read_text(encoding="utf-8"))
    assert loaded["activity"]["lighthouse:question"] == question


def test_sidecar_draft_entity_links_back_to_activity() -> None:
    s = _sidecar()
    assert s["draftEntity"]["prov:wasGeneratedBy"] == s["activity"]["@id"]


# ---------------------------------------------------------------------------
# write_run_sidecar: failure atomicity
# ---------------------------------------------------------------------------


def test_write_sidecar_failure_leaves_no_files(tmp_path: Path) -> None:
    """A failed write must leave neither the destination nor a stray .tmp."""
    dest = tmp_path / "d-bad.prov.json"
    not_serialisable = {"oops": object()}
    with pytest.raises(TypeError):
        write_run_sidecar(dest, not_serialisable)
    assert not dest.exists()
    assert list(tmp_path.iterdir()) == []  # no .tmp residue


def test_write_sidecar_overwrites_existing_file(tmp_path: Path) -> None:
    dest = tmp_path / "d-ow.prov.json"
    write_run_sidecar(dest, {"v": 1})
    write_run_sidecar(dest, {"v": 2})
    assert json.loads(dest.read_text(encoding="utf-8")) == {"v": 2}


def test_write_sidecar_accepts_str_path(tmp_path: Path) -> None:
    dest = tmp_path / "d-str.prov.json"
    write_run_sidecar(str(dest), {"v": 1})
    assert json.loads(dest.read_text(encoding="utf-8")) == {"v": 1}
