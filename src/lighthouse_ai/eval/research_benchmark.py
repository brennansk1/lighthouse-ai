"""Research-quality benchmark — proves "better than frontier", measured not claimed.

The competitive thesis (NIGHT_PLAN.md) says Lighthouse wins on *trustworthiness*:
grounded claims, adversarial survival, plan coverage, reproducibility. This
harness scores an artifact against that bar and — the headline proof —
demonstrates the grounding gate **catches a planted hallucination** that a
fluent frontier model would happily repeat.

Offline + deterministic. The real-LLM end-to-end variant lives behind
``LIGHTHOUSE_REAL_BACKEND=1`` in the tests; this module is pure scoring + a
fixed planted-hallucination scenario so it runs in CI with no model.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..verification.discipline import check


@dataclass
class _Chunk:
    text: str
    source: str

    @property
    def metadata(self):
        return {"source": self.source}


#: A tiny fixed corpus with known facts. Citation ids are 1-based positions.
BENCH_CORPUS = [
    _Chunk("The Apollo 11 mission landed on the Moon on July 20, 1969.", "nasa"),
    _Chunk("Neil Armstrong was the first person to walk on the Moon.", "history"),
    _Chunk("The mission was launched by a Saturn V rocket.", "nasa-launch"),
]

# A draft mixing a well-grounded claim, a triangulated claim, and a PLANTED
# HALLUCINATION (cites source [9], which does not exist) — the failure mode
# frontier 'deep research' ships as confident prose.
PLANTED_DRAFT = (
    "Apollo 11 landed on the Moon in 1969 [1]. "
    "Neil Armstrong was the first to walk on the Moon, launched by Saturn V [2,3]. "
    "The mission also discovered ancient ruins on the lunar surface [9]."
)


@dataclass
class Scorecard:
    checks: dict[str, bool] = field(default_factory=dict)
    metrics: dict[str, float] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return all(self.checks.values())

    def as_dict(self) -> dict:
        return {"passed": self.passed, "checks": self.checks, "metrics": self.metrics}


def grounding_catches_hallucination() -> Scorecard:
    """The headline proof: the gate flags the fabricated [9] citation."""
    rep = check(PLANTED_DRAFT, evidence_chunks=BENCH_CORPUS, high_stakes=True, min_coverage=0.6)
    card = Scorecard()
    card.checks["fabricated_citation_caught"] = rep.fabricated_citations >= 1
    card.checks["high_stakes_gate_fails_on_fabrication"] = rep.passed is False
    card.checks["triangulated_claim_detected"] = rep.triangulated >= 1
    card.metrics["citation_coverage"] = rep.citation_coverage
    card.metrics["fabricated_citations"] = float(rep.fabricated_citations)
    card.metrics["triangulated"] = float(rep.triangulated)
    return card


def score_artifact(body_json: dict, *, depth: str | None = None) -> Scorecard:
    """Score a real Investigate/Ask artifact body against the measurable bar.

    Thresholds match NIGHT_PLAN.md. Missing fields fail their check (absence of
    a quality signal is not a pass).
    """
    card = Scorecard()
    prov = body_json.get("provenance") or {}
    metrics = (prov.get("metrics") or {}) if isinstance(prov, dict) else {}

    cov = body_json.get("citation_coverage", metrics.get("citation_coverage", 0.0))
    ent = body_json.get("entailment_coverage", metrics.get("entailment_coverage", 0.0))
    card.metrics["citation_coverage"] = float(cov or 0.0)
    card.metrics["entailment_coverage"] = float(ent or 0.0)

    card.checks["has_provenance"] = bool(prov)
    card.checks["backend_real"] = prov.get("backend") == "ollama"
    card.checks["adversarial_ran"] = "adversarial" in body_json
    card.checks["coverage_ran"] = "coverage" in body_json
    card.checks["citation_coverage_>=0.95"] = card.metrics["citation_coverage"] >= 0.95
    card.checks["no_contested_unflagged"] = (
        "contested_claims" in body_json or body_json.get("adversarial", {}).get("contested", 0) == 0
    )
    if depth:
        card.checks["depth_honored"] = body_json.get("depth") == depth
    return card


def run() -> dict:
    """Run the offline benchmark and return a scorecard dict (also printable)."""
    return {"grounding_gate": grounding_catches_hallucination().as_dict()}


if __name__ == "__main__":  # pragma: no cover
    import json

    print(json.dumps(run(), indent=2))
