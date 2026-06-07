"""Tests for the Contradiction artifact + discipline integration (§6)."""

from __future__ import annotations

import json
from datetime import datetime

from lighthouse_ai.verification import contradiction as C
from lighthouse_ai.verification.contradiction import (
    ChunkRef,
    Contradiction,
    detect,
    should_auto_adjudicate,
    to_audit_record,
)
from lighthouse_ai.verification.discipline import (
    Claim,
    check,
    distinct_skills,
)

FIXED_TS = datetime(2026, 5, 29, 12, 0, 0)


# --------------------------------------------------------------------------- #
# Fakes
# --------------------------------------------------------------------------- #

class _Chunk:
    """Minimal stand-in for a Chunk with metadata.skill_id + entailment."""

    def __init__(self, cid, *, skill_id=None, source="doc", entailment=None,
                 text="evidence"):
        self.id = cid
        self.document_id = cid
        self.text = text
        meta = {"source": source}
        if skill_id is not None:
            meta["skill_id"] = skill_id
        if entailment is not None:
            meta["entailment_score"] = entailment
        self.metadata = meta


def _ev(cid, skill_id, source, entailment):
    return _Chunk(cid, skill_id=skill_id, source=source, entailment=entailment)


# --------------------------------------------------------------------------- #
# Dataclass shape
# --------------------------------------------------------------------------- #

def test_contradiction_dataclass_fields():
    c = Contradiction(
        contradiction_id="x",
        claim="claim",
        supporting_chunks=[],
        opposing_chunks=[],
        detection_layer="chunk",
        severity="low",
        detected_at=FIXED_TS,
        detected_in_job="job-1",
    )
    assert c.resolution_status == "unresolved"   # defaults
    assert c.resolution_ref is None


def test_no_clock_call_in_code():
    # The module must not stamp a clock value at import or runtime; detected_at
    # is an input. Strip docstrings/comments and assert no now()/utcnow() call.
    import ast
    from pathlib import Path

    src = Path(C.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    calls = [
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    ]
    assert "now" not in calls
    assert "utcnow" not in calls


# --------------------------------------------------------------------------- #
# Detection layers
# --------------------------------------------------------------------------- #

def test_cross_skill_disagreement_elevated_vs_intra_skill():
    claim = "Remote work increases team productivity"

    # Cross-skill: supporting chunk from skill A, opposing from skill B.
    cross = detect(
        [claim],
        [
            _ev("c1", "skill-a", "arxiv", 0.9),    # supports
            _ev("c2", "skill-b", "pubmed", 0.1),   # opposes
        ],
        job_id="job-x",
        detected_at=FIXED_TS,
        load_bearing=True,
    )
    assert len(cross) == 1
    assert cross[0].detection_layer == "cross_skill"
    assert cross[0].severity == "high"   # balanced + load-bearing + cross-skill

    # Intra-skill: both chunks from the SAME skill → claim layer, not elevated.
    intra = detect(
        [claim],
        [
            _ev("c1", "skill-a", "arxiv", 0.9),
            _ev("c2", "skill-a", "pubmed", 0.1),
        ],
        job_id="job-y",
        detected_at=FIXED_TS,
        load_bearing=True,
    )
    assert len(intra) == 1
    assert intra[0].detection_layer == "claim"

    # Same balance + load-bearing, but cross-skill is the stronger signal.
    order = {"low": 0, "medium": 1, "high": 2}
    # intra here is also high (balanced+load_bearing), but a NON-load-bearing
    # cross-skill still outranks a non-load-bearing intra-skill:
    cross_nlb = detect([claim],
                       [_ev("c1", "skill-a", "arxiv", 0.9),
                        _ev("c2", "skill-b", "pubmed", 0.1)],
                       job_id="j", detected_at=FIXED_TS, load_bearing=False)
    intra_nlb = detect([claim],
                       [_ev("c1", "skill-a", "arxiv", 0.9),
                        _ev("c2", "skill-a", "pubmed", 0.1)],
                       job_id="j", detected_at=FIXED_TS, load_bearing=False)
    assert order[cross_nlb[0].severity] > order[intra_nlb[0].severity]


def test_no_contradiction_when_evidence_agrees():
    out = detect(
        ["Vaccine is effective"],
        [_ev("c1", "skill-a", "arxiv", 0.9), _ev("c2", "skill-b", "pubmed", 0.8)],
        job_id="j", detected_at=FIXED_TS,
    )
    assert out == []


def test_chunk_layer_polarity_heuristic_degrades_without_entailment():
    # No entailment scores anywhere → only the polarity heuristic can fire.
    claims = [
        Claim(text="Remote work increases team productivity"),
        Claim(text="Remote work decreases team productivity"),
    ]
    out = detect(claims, [], job_id="j", detected_at=FIXED_TS, load_bearing=True)
    assert len(out) >= 1
    assert all(c.detection_layer == "chunk" for c in out)


def test_chunk_layer_flags_legal_antonym_affirmed_reversed():
    # Legal-wedge antonym pair: an appellate court "affirmed" vs "reversed" the
    # same ruling. Shared subject tokens + opposing legal polarity → chunk layer.
    claims = [
        Claim(text="The appellate court affirmed the district court ruling."),
        Claim(text="The appellate court reversed the district court ruling."),
    ]
    out = detect(claims, [], job_id="j", detected_at=FIXED_TS, load_bearing=True)
    chunk_hits = [c for c in out if c.detection_layer == "chunk"]
    assert chunk_hits, "expected affirmed/reversed to flag a chunk contradiction"


def test_chunk_layer_flags_legal_antonym_guilty_acquitted():
    # guilty vs acquitted over a shared defendant/charge subject.
    claims = [
        Claim(text="The jury found the defendant guilty on the fraud charge."),
        Claim(text="The jury found the defendant acquitted on the fraud charge."),
    ]
    out = detect(claims, [], job_id="j", detected_at=FIXED_TS, load_bearing=False)
    chunk_hits = [c for c in out if c.detection_layer == "chunk"]
    assert chunk_hits
    # A flagged opposing pair is a real disagreement → at least 'medium'.
    order = {"low": 0, "medium": 1, "high": 2}
    assert all(order[c.severity] >= order["medium"] for c in chunk_hits)


def test_chunk_layer_flags_multitoken_antonym_upheld_struck_down():
    # Multi-token phrase member ("struck down") must require all its tokens.
    claims = [
        Claim(text="The supreme court upheld the contested statute."),
        Claim(text="The supreme court struck down the contested statute."),
    ]
    out = detect(claims, [], job_id="j", detected_at=FIXED_TS, load_bearing=True)
    assert any(c.detection_layer == "chunk" for c in out)


def test_layer_hint_restricts_detection():
    claim = "Remote work increases team productivity"
    out = detect([claim],
                 [_ev("c1", "skill-a", "arxiv", 0.9),
                  _ev("c2", "skill-b", "pubmed", 0.1)],
                 job_id="j", detected_at=FIXED_TS, load_bearing=True,
                 layer_hint="claim")
    # cross_skill suppressed by the hint → falls to claim layer
    assert len(out) == 1
    assert out[0].detection_layer == "claim"


# --------------------------------------------------------------------------- #
# Auto-Adjudicate (§6.4) — true only under all five conditions
# --------------------------------------------------------------------------- #

def _high_cross_skill() -> Contradiction:
    return Contradiction(
        contradiction_id="x", claim="c",
        supporting_chunks=[ChunkRef("c1", "a", 0.9, "t")],
        opposing_chunks=[ChunkRef("c2", "b", 0.1, "t")],
        detection_layer="cross_skill", severity="high",
        detected_at=FIXED_TS, detected_in_job="job",
    )


def test_should_auto_adjudicate_all_conditions():
    c = _high_cross_skill()
    assert should_auto_adjudicate(c, depth_tier="thorough") is True
    assert should_auto_adjudicate(c, depth_tier="deep") is True


def test_should_auto_adjudicate_fails_each_condition():
    base = _high_cross_skill()

    # 1: wrong layer
    claim_layer = Contradiction(**{**base.__dict__, "detection_layer": "claim"})
    assert should_auto_adjudicate(claim_layer, depth_tier="thorough") is False

    # 3: not high severity (also encodes 'load-bearing/balanced')
    medium = Contradiction(**{**base.__dict__, "severity": "medium"})
    assert should_auto_adjudicate(medium, depth_tier="thorough") is False

    # 4: shallow depth tier
    assert should_auto_adjudicate(base, depth_tier="quick") is False
    assert should_auto_adjudicate(base, depth_tier="standard") is False

    # 5: user disabled
    assert should_auto_adjudicate(base, depth_tier="deep", user_disabled=True) is False


def test_non_load_bearing_cross_skill_does_not_auto_adjudicate():
    # §6.4 condition 2: the claim must be load-bearing. A balanced cross-skill
    # clash on a NON-load-bearing claim must NOT reach 'high' severity (which is
    # the only thing should_auto_adjudicate keys off for load-bearing), and so
    # must NOT auto-adjudicate even at the deepest tier.
    out = detect(
        ["Remote work increases team productivity"],
        [_ev("c1", "skill-a", "arxiv", 0.9), _ev("c2", "skill-b", "pubmed", 0.1)],
        job_id="j", detected_at=FIXED_TS, load_bearing=False,
    )
    assert len(out) == 1
    assert out[0].detection_layer == "cross_skill"
    assert out[0].severity != "high"
    assert should_auto_adjudicate(out[0], depth_tier="deep") is False


def test_flagged_chunk_contradiction_is_at_least_medium():
    # The chunk-layer polarity heuristic has no per-chunk balance, but a flagged
    # opposing pair is a real disagreement and must surface at >= 'medium'
    # regardless of load-bearing (otherwise a flagged contradiction reads 'low').
    claims = [
        Claim(text="Remote work increases team productivity"),
        Claim(text="Remote work decreases team productivity"),
    ]
    out = detect(claims, [], job_id="j", detected_at=FIXED_TS, load_bearing=False)
    chunk_hits = [c for c in out if c.detection_layer == "chunk"]
    assert chunk_hits
    order = {"low": 0, "medium": 1, "high": 2}
    assert all(order[c.severity] >= order["medium"] for c in chunk_hits)


# --------------------------------------------------------------------------- #
# Audit record
# --------------------------------------------------------------------------- #

def test_to_audit_record_is_json_serializable():
    c = _high_cross_skill()
    rec = to_audit_record(c)
    # round-trips through json with the timestamp as isoformat string
    blob = json.dumps(rec)
    parsed = json.loads(blob)
    assert parsed["detected_at"] == FIXED_TS.isoformat()
    assert parsed["kind"] == "contradiction"
    assert parsed["detection_layer"] == "cross_skill"
    assert parsed["supporting_chunks"][0]["skill_id"] == "a"


# --------------------------------------------------------------------------- #
# distinct_skills — counts skill_id, not domain
# --------------------------------------------------------------------------- #

def test_distinct_skills_counts_skill_id_not_domain():
    chunks = [
        _ev("c1", "skill-a", "arxiv", None),
        _ev("c2", "skill-a", "pubmed", None),   # same skill, different domain
        _ev("c3", "skill-b", "arxiv", None),     # different skill, same domain as c1
    ]
    assert distinct_skills(chunks) == 2


def test_distinct_skills_ignores_unattributed():
    chunks = [_Chunk("c1", source="arxiv"), _ev("c2", "skill-a", "pubmed", None)]
    assert distinct_skills(chunks) == 1


def test_same_skill_two_domains_not_triangulated():
    # Both cited chunks share skill_id → not independent even though domains
    # differ. Triangulation must NOT count this claim.
    ev = [_ev("c1", "skill-a", "doc-a", None), _ev("c2", "skill-a", "doc-b", None)]
    rep = check("The finding replicates [1,2].", evidence_chunks=ev,
                min_coverage=0.0)
    assert rep.triangulated == 0
    assert rep.distinct_skills == 1


def test_distinct_skills_surfaced_on_report():
    ev = [_ev("c1", "skill-a", "doc-a", None), _ev("c2", "skill-b", "doc-b", None)]
    rep = check("The finding replicates [1,2].", evidence_chunks=ev,
                min_coverage=0.0)
    assert rep.distinct_skills == 2
    assert rep.triangulated == 1   # distinct domains AND distinct skills
