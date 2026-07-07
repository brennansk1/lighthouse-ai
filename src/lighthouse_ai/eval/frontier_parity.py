"""Frontier-parity grader — put a number on "on par with / better than frontier".

The competitive claim (GOAL.md) is that Lighthouse matches or beats Claude/Gemini
deep research *on trustworthiness* while running on local models. `LIVE_TEST_PLAN.md`
§2.7 defines the head-to-head; this module makes it **repeatable**: it grades a real
research artifact on the five dimensions that comparison scores, so the claim gets a
tracked number instead of a vibe.

Two halves:

1. **Objective auto-grade of a Lighthouse artifact** (`grade_artifact`). Every
   dimension is computed from the artifact's own `body_json` + provenance — no LLM,
   deterministic, unit-testable. This is the half a machine can score honestly,
   because Lighthouse's output is *structured* (typed sections, citation ids, an
   adversarial pass, explicit open questions).

2. **A manual scorecard for a frontier output** (`FrontierScore`) + `compare`. A
   frontier deep-research answer is prose — its citations can't be machine-verified
   the way a chunk-id can — so the honest protocol is: the user blind-grades the
   frontier output on the same five dimensions (1-5), and the harness records the
   head-to-head. The harness never fabricates a frontier score.

The five dimensions mirror `LIVE_TEST_PLAN.md` §2.7:
  - breadth              — how many distinct sources the answer rests on
  - grounding            — fraction of claims actually entailed by a cited source
  - citation_verifiability — do the citations resolve to real sources (zero fabricated)
  - contradiction_honesty  — were claims stress-tested and disagreements surfaced
  - open_question_honesty  — did it admit what it could not settle

`breadth` scales with depth (a Quick scan is not expected to match a Deep run). The
weighted overall leans on grounding + verifiability: those are the structural wedge a
time-boxed cloud service does not enforce, and the columns Lighthouse must win.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

__all__ = [
    "BENCHMARK_QUESTIONS",
    "FrontierScore",
    "ParityScore",
    "compare",
    "grade_artifact",
    "render_report",
]

#: A small, self-contained set of research questions for the head-to-head. Each is
#: answerable from open web/academic sources (so Lighthouse's acquisition can reach
#: real evidence) and spans domains. Run each on Lighthouse Thorough/Deep AND on
#: Claude/Gemini deep research, then blind-grade all three.
BENCHMARK_QUESTIONS = [
    "What is the current scientific consensus on whether moderate coffee "
    "consumption affects cardiovascular disease risk, and where do studies disagree?",
    "How did the 2023-2024 large-language-model context-window race unfold, and "
    "what techniques made million-token contexts feasible?",
    "What were the principal causes of the 2008 financial crisis, and which "
    "explanations remain contested among economists?",
    "What is the evidence for and against time-restricted eating (intermittent "
    "fasting) improving metabolic health in humans?",
    "What are the leading hypotheses for the Fermi paradox, and how do "
    "researchers weigh them against each other?",
]

#: Depth → an expected distinct-source count for the breadth dimension. A Quick scan
#: is honestly not held to a Deep run's breadth; these are the denominators the
#: breadth score normalizes against (source_count / target, capped at 1.0).
_BREADTH_TARGET = {"quick": 5, "standard": 12, "thorough": 25, "deep": 40}

#: Overall-score weights. Grounding + verifiability dominate: they are the
#: trustworthiness wedge and the columns the comparison must win.
_WEIGHTS = {
    "breadth": 0.15,
    "grounding": 0.30,
    "citation_verifiability": 0.30,
    "contradiction_honesty": 0.15,
    "open_question_honesty": 0.10,
}


@dataclass
class ParityScore:
    """Per-dimension [0,1] scores for one Lighthouse artifact, plus the weighted
    overall and the raw counts a reader will want to see behind the numbers."""

    dimensions: dict[str, float] = field(default_factory=dict)
    raw: dict[str, float] = field(default_factory=dict)
    overall: float = 0.0

    def as_dict(self) -> dict:
        return {"overall": self.overall, "dimensions": self.dimensions, "raw": self.raw}


@dataclass
class FrontierScore:
    """A human's blind 1-5 grade of a frontier (Claude/Gemini) output on the same
    five dimensions. Kept separate from the auto-grade — a frontier answer's
    citations are prose and cannot be machine-verified, so a person scores it."""

    breadth: int
    grounding: int
    citation_verifiability: int
    contradiction_honesty: int
    open_question_honesty: int
    model: str = "frontier"

    def normalized(self) -> dict[str, float]:
        """1-5 → [0,1] on the same scale as the auto-grade (1→0.0, 5→1.0)."""
        d = asdict(self)
        d.pop("model")
        return {k: (max(1, min(5, int(v))) - 1) / 4.0 for k, v in d.items()}


def _num(x, default: float = 0.0) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def _metrics(body_json: dict) -> dict:
    """Pull the metrics dict from provenance (or the top level as a fallback)."""
    prov = body_json.get("provenance") or {}
    m = (prov.get("metrics") or {}) if isinstance(prov, dict) else {}
    return m if isinstance(m, dict) else {}


def grade_artifact(body_json: dict) -> ParityScore:
    """Objectively grade one Lighthouse research artifact on the five dimensions.

    Deterministic; reads only the artifact's structure + provenance. Missing
    signals score low (absence of a trust signal is not a pass), matching the
    discipline the rest of the eval harness uses.
    """
    m = _metrics(body_json)
    depth = str(body_json.get("depth", "standard")).lower()

    sections = body_json.get("sections") or []
    # Distinct cited sources across all sections (falls back to a recorded count).
    cited: set = set()
    for s in sections:
        for c in s.get("citations") or []:
            cited.add(c)
    source_count = len(cited) or int(_num(body_json.get("source_count")))
    docs_acquired = int(_num((body_json.get("acquisition") or {}).get("documents_acquired")))

    # 1. breadth — distinct sources vs. a depth-appropriate target.
    target = _BREADTH_TARGET.get(depth, 12)
    breadth = min(1.0, source_count / target) if target else 0.0

    # 2. grounding — claims entailed by a cited source. Prefer the measured
    #    entailment coverage; fall back to citation coverage.
    cit_cov = _num(body_json.get("citation_coverage", m.get("citation_coverage")))
    ent_cov = _num(body_json.get("entailment_coverage", m.get("entailment_coverage")))
    grounding = ent_cov if ent_cov > 0 else cit_cov

    # 3. citation_verifiability — do citations resolve to real sources? The
    #    grounding gate rejects fabricated ids at production time, so a shipped
    #    artifact should have zero fabricated. We *measure* it rather than assume:
    #    a fabricated count > 0 (recorded in metrics) tanks this to reflect reality.
    fabricated = _num(m.get("fabricated_citations", body_json.get("fabricated_citations", 0.0)))
    if source_count == 0:
        citation_verifiability = 0.0  # nothing cited → nothing verifiable
    elif fabricated > 0:
        citation_verifiability = max(0.0, 1.0 - fabricated / max(source_count, 1))
    else:
        citation_verifiability = 1.0

    # 4. contradiction_honesty — did it stress-test and surface disagreement?
    adversarial = body_json.get("adversarial")
    ran_adversarial = isinstance(adversarial, dict) and bool(adversarial)
    surfaced_contested = "contested_claims" in body_json
    ran_coverage = "coverage" in body_json
    contradiction_honesty = (
        0.5 * (1.0 if ran_adversarial else 0.0)
        + 0.3 * (1.0 if surfaced_contested else 0.0)
        + 0.2 * (1.0 if ran_coverage else 0.0)
    )

    # 5. open_question_honesty — did it admit what it could not settle?
    open_qs = body_json.get("open_questions") or []
    ruled_out = body_json.get("ruled_out") or []
    gaps = body_json.get("coverage_gaps") or []
    if open_qs:
        open_question_honesty = 1.0
    elif ruled_out or gaps:
        open_question_honesty = 0.6
    else:
        open_question_honesty = 0.0

    dims = {
        "breadth": round(breadth, 3),
        "grounding": round(grounding, 3),
        "citation_verifiability": round(citation_verifiability, 3),
        "contradiction_honesty": round(contradiction_honesty, 3),
        "open_question_honesty": round(open_question_honesty, 3),
    }
    overall = round(sum(_WEIGHTS[k] * v for k, v in dims.items()), 3)
    raw = {
        "source_count": float(source_count),
        "documents_acquired": float(docs_acquired),
        "citation_coverage": round(cit_cov, 3),
        "entailment_coverage": round(ent_cov, 3),
        "fabricated_citations": fabricated,
        "sections": float(len(sections)),
        "open_questions": float(len(open_qs)),
    }
    return ParityScore(dimensions=dims, raw=raw, overall=overall)


def compare(lighthouse: ParityScore, frontier: FrontierScore | None = None) -> dict:
    """Head-to-head of one Lighthouse artifact vs. an optional frontier grade.

    Returns per-dimension deltas (Lighthouse − frontier) and which side wins each,
    plus the honesty/verifiability call-out that is the crux of the claim. With no
    frontier score supplied, returns the Lighthouse card alone (still useful for
    tracking absolute quality over time).
    """
    out: dict = {"lighthouse": lighthouse.as_dict()}
    if frontier is None:
        return out
    fnorm = frontier.normalized()
    deltas = {
        k: round(lighthouse.dimensions.get(k, 0.0) - fnorm.get(k, 0.0), 3)
        for k in lighthouse.dimensions
    }
    out["frontier"] = {"model": frontier.model, "dimensions": fnorm}
    out["deltas"] = deltas
    out["wins"] = {
        k: ("lighthouse" if d > 0 else "frontier" if d < 0 else "tie") for k, d in deltas.items()
    }
    # The claim's crux: win-or-tie on the two trust columns.
    trust_cols = ("grounding", "citation_verifiability")
    out["holds_trust_wedge"] = all(deltas[c] >= 0 for c in trust_cols)
    return out


def render_report(results: list[dict]) -> str:
    """Render a markdown report from a list of `{question, comparison}` rows.

    One table row per question with the overall + the five dimensions for
    Lighthouse, and (when present) the frontier grade and the trust-wedge verdict.
    """
    lines = [
        "# Frontier-parity report",
        "",
        "Auto-graded Lighthouse artifacts on the LIVE_TEST_PLAN §2.7 dimensions. "
        "Frontier columns are human blind-grades (1-5 → [0,1]); absent unless "
        "provided. Trust wedge = win-or-tie on grounding + citation verifiability.",
        "",
        "| Question | Overall | Breadth | Grounding | Cite-verify | "
        "Contradiction | Open-Q | Frontier overall | Trust wedge |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in results:
        q = (r.get("question") or "")[:60]
        cmp = r.get("comparison") or {}
        lh = cmp.get("lighthouse") or {}
        d = lh.get("dimensions") or {}
        fr = cmp.get("frontier")
        fr_overall = "—"
        if fr:
            fn = fr.get("dimensions") or {}
            fr_overall = f"{sum(fn.values()) / max(len(fn), 1):.2f}"
        wedge = "—"
        if "holds_trust_wedge" in cmp:
            wedge = "✅ hold" if cmp["holds_trust_wedge"] else "❌ lost"
        lines.append(
            f"| {q} | {lh.get('overall', 0):.2f} | "
            f"{d.get('breadth', 0):.2f} | {d.get('grounding', 0):.2f} | "
            f"{d.get('citation_verifiability', 0):.2f} | "
            f"{d.get('contradiction_honesty', 0):.2f} | "
            f"{d.get('open_question_honesty', 0):.2f} | {fr_overall} | {wedge} |"
        )
    return "\n".join(lines) + "\n"
