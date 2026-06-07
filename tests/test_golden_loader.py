"""Tests for the JSON golden-set loader + the legal starter set.

Two contracts:
  1. ``load_golden_from_json`` parses the documented schema, validates gold
     doc-id referential integrity, and round-trips through ``save_golden_to_json``.
  2. The shipped ``legal_gold.json`` starter set loads, is self-consistent
     (every gold id exists; contradiction cases are well-formed), and the
     real ``evaluate()`` runs over it offline and reports sane metrics.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from lighthouse_ai.eval import (
    ContradictionCase,
    GoldenCase,
    GoldenSet,
    build_index,
    evaluate,
    golden_to_json_dict,
    load_golden_from_json,
    save_golden_to_json,
)
from lighthouse_ai.rag.chunker import Document

LEGAL_GOLD = (
    Path(__file__).resolve().parent.parent
    / "src"
    / "lighthouse_ai"
    / "eval"
    / "data"
    / "legal_gold.json"
)


# --- the shipped legal starter set -----------------------------------------


def test_legal_gold_file_exists() -> None:
    assert LEGAL_GOLD.is_file()


def test_legal_gold_loads() -> None:
    golden = load_golden_from_json(LEGAL_GOLD)
    # Starter set targets ~30-40 docs, ~25-30 queries, 10 contradictions.
    assert len(golden.documents) >= 25
    assert len(golden.cases) >= 25
    assert len(golden.contradictions) == 10


def test_legal_gold_doc_ids_unique() -> None:
    golden = load_golden_from_json(LEGAL_GOLD)
    ids = [d.id for d in golden.documents]
    assert len(ids) == len(set(ids))


def test_legal_gold_relevant_ids_all_exist() -> None:
    # Referential integrity: every gold id must point at a real document.
    golden = load_golden_from_json(LEGAL_GOLD)
    doc_ids = {d.id for d in golden.documents}
    for case in golden.cases:
        assert case.relevant_doc_ids
        assert case.relevant_doc_ids <= doc_ids


def test_legal_gold_contradictions_well_formed() -> None:
    golden = load_golden_from_json(LEGAL_GOLD)
    for c in golden.contradictions:
        assert isinstance(c, ContradictionCase)
        assert c.claim and c.supporting_passage and c.contradicting_passage
        # Supporting and contradicting passages must actually differ.
        assert c.supporting_passage != c.contradicting_passage


def test_evaluate_runs_offline_over_legal_gold() -> None:
    # The real contract: the loaded set drives the real evaluate() harness
    # offline and emits in-range metrics. Not a production bar.
    golden = load_golden_from_json(LEGAL_GOLD)
    report = evaluate(build_index(golden), golden)
    assert set(report) == {"precision@5", "recall@5", "mrr"}
    for value in report.values():
        assert 0.0 <= value <= 1.0
        assert not math.isnan(value)


def test_evaluate_over_legal_gold_finds_relevant_docs() -> None:
    # Queries reuse their gold document's vocabulary, so a working lexical
    # pipeline should rank the right passage near the top.
    golden = load_golden_from_json(LEGAL_GOLD)
    report = evaluate(build_index(golden), golden)
    assert report["mrr"] > 0.5
    assert report["recall@5"] > 0.0


def test_evaluate_over_legal_gold_deterministic() -> None:
    golden = load_golden_from_json(LEGAL_GOLD)
    hybrid = build_index(golden)
    assert evaluate(hybrid, golden) == evaluate(hybrid, golden)


# --- round-trip ------------------------------------------------------------


def test_round_trip_legal_gold(tmp_path: Path) -> None:
    # load -> save -> load is lossless for the modelled fields.
    golden = load_golden_from_json(LEGAL_GOLD)
    out = tmp_path / "rt.json"
    save_golden_to_json(golden, out, name="legal-gold")
    again = load_golden_from_json(out)

    assert {d.id: d.text for d in again.documents} == {
        d.id: d.text for d in golden.documents
    }
    assert {c.query: c.relevant_doc_ids for c in again.cases} == {
        c.query: c.relevant_doc_ids for c in golden.cases
    }
    assert [c.claim for c in again.contradictions] == [
        c.claim for c in golden.contradictions
    ]


def test_round_trip_synthetic(tmp_path: Path) -> None:
    golden = GoldenSet(
        documents=(
            Document(id="d1", text="alpha beta", metadata={"k": "v"}),
            Document(id="d2", text="gamma delta"),
        ),
        cases=(
            GoldenCase(query="alpha beta", relevant_doc_ids=frozenset({"d1"})),
        ),
        contradictions=(
            ContradictionCase(
                claim="the sky is blue",
                supporting_passage="the sky is blue today",
                contradicting_passage="the sky is green today",
                id="c1",
            ),
        ),
    )
    out = tmp_path / "g.json"
    save_golden_to_json(golden, out)
    again = load_golden_from_json(out)
    assert again == golden


def test_to_json_dict_emits_documented_schema() -> None:
    golden = GoldenSet(
        documents=(Document(id="d1", text="x"),),
        cases=(GoldenCase(query="x", relevant_doc_ids=frozenset({"d1"})),),
    )
    payload = golden_to_json_dict(golden, name="tiny")
    assert payload["version"] == 1
    assert payload["name"] == "tiny"
    assert payload["documents"] == [{"id": "d1", "text": "x", "metadata": {}}]
    assert payload["queries"] == [{"query": "x", "relevant_doc_ids": ["d1"]}]
    # No contradictions key when the subset is empty.
    assert "contradictions" not in payload


# --- malformed inputs fail loudly ------------------------------------------


def test_load_rejects_dangling_relevant_id(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text(
        json.dumps(
            {
                "documents": [{"id": "d1", "text": "x"}],
                "queries": [{"query": "x", "relevant_doc_ids": ["nope"]}],
            }
        )
    )
    with pytest.raises(ValueError, match="unknown doc ids"):
        load_golden_from_json(bad)


def test_load_rejects_missing_documents(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"queries": []}))
    with pytest.raises(ValueError, match="documents"):
        load_golden_from_json(bad)


def test_load_rejects_document_without_id(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"documents": [{"text": "x"}], "queries": []}))
    with pytest.raises(ValueError, match="id"):
        load_golden_from_json(bad)


def test_load_rejects_malformed_contradiction(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text(
        json.dumps(
            {
                "documents": [{"id": "d1", "text": "x"}],
                "queries": [],
                "contradictions": [{"claim": "only a claim"}],
            }
        )
    )
    with pytest.raises(ValueError):
        load_golden_from_json(bad)
