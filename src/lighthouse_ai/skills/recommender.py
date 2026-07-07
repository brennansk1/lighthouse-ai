"""Zone A — the mode-aware source recommender.

One function, parameterized by mode: ``recommend(framed, mode, depth) ->
list[Recommendation]``. Modes change the *scoring weights*, never the codepath
(MODE_SKILL_INTEGRATION.md §0 corollary 1). The recommender consumes a skill's
declarative manifest fields (``question_types``/``topics``/``modes_natural_fit``/
``output_shape``/``default_grade``/``authority``/``perspective_lens``/
``temporal_tools`` …) plus an embedding similarity between the question and the
skill's ``SKILL.md`` text, blends them into one score, applies any matching
profile overlay, and always offers ``general_web`` as the universal fallback
(§5.2).

Design constraints honored here:

* **Fully offline-deterministic by default.** No network, no real LLM unless a
  ``gateway`` is supplied *and* online. When no ``embedder`` is given we fall
  back to a deterministic token-overlap similarity, so unit tests and offline
  mode get stable rankings.
* **Never crashes on an empty library.** ``discover_skills()`` returning ``{}``
  yields a single ``general_web`` fallback Recommendation (or an empty list if
  even that skill is unavailable and no candidates exist).
* **Manifests carry no SKILL.md text** — we load it lazily from
  ``LIBRARY_DIR / <id> / "SKILL.md"`` and tolerate it being missing.

The dispatcher / API zones call only :func:`recommend`. Mode branching:
``decide`` -> per-option, ``adjudicate`` -> perspective-diversity, everything
else -> fit.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path

from .registry import LIBRARY_DIR, all_skills
from .schema import SkillManifest

# Roles tracked on Recommendation.role — MODE_SKILL_INTEGRATION.md §5.2.
VALID_ROLES = (
    "primary",
    "fallback",
    "gap_filler",
    "breadth",
    "recency",
    "cross_check",
    "disambiguator",
)

GENERAL_WEB_ID = "general_web"

# A specialty skill must clear this blended score for general_web to step *down*
# from a primary fallback to a mere breadth role. Tuned for the offline path.
_FALLBACK_THRESHOLD = 0.30


@dataclass(frozen=True)
class Recommendation:
    """One ranked source suggestion. ``score`` is the blended rule+similarity
    value (post-overlay); ``reason`` is a short human string for the picker
    tooltip; ``role`` is one of :data:`VALID_ROLES` (or ``None``)."""

    skill_id: str
    score: float
    reason: str
    role: str | None = None


# --------------------------------------------------------------------------- #
# Per-mode scoring weights / rules (MODE_SKILL_INTEGRATION.md §2.2).
#
# Each entry is a plain dict the scorer reads. Keys:
#   rule_weight / sim_weight     — blend of rule score vs embedding similarity
#   prefer_grade_a               — bonus when default_grade == "A"
#   prefer_peer_reviewed         — bonus when authority == "peer_reviewed"
#   primary_lens_bonus           — bonus when perspective_lens == "primary"
#   require_output_shape         — hard filter (skill dropped unless it matches)
#   penalize_output_shape        — penalty for a given output_shape value
#   require_temporal_tools       — hard filter on temporal_tools
#   penalize_lookup_load_bearing — penalty applied to lookup-shape skills when
#                                   the question has load-bearing sub-questions
#   penalize_community_load_bearing — penalty for community (unsigned) skills on
#                                   load-bearing questions (orientation-ok, weak
#                                   for citation)
#   diversity                    — adjudicate maximizes distinct perspective_lens
# --------------------------------------------------------------------------- #
MODE_WEIGHTS: dict[str, dict] = {
    "investigate": {
        "rule_weight": 0.6,
        "sim_weight": 0.4,
        "prefer_grade_a": 0.35,
        "prefer_peer_reviewed": 0.30,
        "primary_lens_bonus": 0.20,
        "penalize_lookup_load_bearing": 0.25,
        "penalize_community_load_bearing": 0.30,
    },
    "survey": {
        "rule_weight": 0.6,
        "sim_weight": 0.4,
        "require_output_shape": "enumerable",
        "penalize_output_shape": ("lookup", 0.5),
    },
    "reconstruct": {
        "rule_weight": 0.6,
        "sim_weight": 0.4,
        "require_temporal_tools": True,
        "prefer_temporal": 0.25,
    },
    "decide": {
        "rule_weight": 0.6,
        "sim_weight": 0.4,
        "primary_lens_bonus": 0.10,
    },
    "adjudicate": {
        "rule_weight": 0.5,
        "sim_weight": 0.5,
        "diversity": True,
    },
    "watch": {
        "rule_weight": 0.6,
        "sim_weight": 0.4,
        "require_watchable": True,
    },
    "ask": {
        "rule_weight": 0.5,
        "sim_weight": 0.5,
    },
}

# Default blend used for any mode key not in MODE_WEIGHTS.
_DEFAULT_WEIGHTS = {"rule_weight": 0.6, "sim_weight": 0.4}


# --------------------------------------------------------------------------- #
# Question text + token utilities
# --------------------------------------------------------------------------- #
_TOKEN_RE = re.compile(r"[a-z0-9]+")

# When the user types a source's name, that's the strongest possible intent
# signal — far stronger than any topic/grade heuristic. We add this bonus to the
# blended score (mode-independent) so a named source reliably lands in the top
# picks instead of being buried under the high-base academic cluster.
_EXPLICIT_MENTION_BONUS = 0.8

# Generic tokens that appear in many source names; they must not, on their own,
# count as "the user named this source".
_GENERIC_NAME_TOKENS = frozenset(
    {
        "news",
        "data",
        "the",
        "web",
        "gov",
        "search",
        "org",
        "com",
        "st",
        "louis",
        "fed",
        "inc",
        "of",
        "and",
        "for",
        "world",
    }
)


def _tokens(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


def _explicit_mention(manifest: SkillManifest, question: str) -> bool:
    """True when the user explicitly named this source in the question.

    Two signals: the skill id with separators stripped appears as a substring of
    the de-spaced question (``clinical trials`` → ``clinicaltrials``; ``SEC
    EDGAR`` → ``secedgar``), or all of the source's distinctive name tokens are
    present. The id path requires length ≥ 4 so short/common ids (``who``) can't
    false-fire on the interrogative.
    """
    q_nospace = re.sub(r"[^a-z0-9]", "", question.lower())
    ident = manifest.id.replace("_", "")
    if len(ident) >= 4 and ident in q_nospace:
        return True
    name_tokens = set(_tokens(manifest.name)) - _GENERIC_NAME_TOKENS
    if name_tokens and name_tokens <= set(_tokens(question)):
        return True
    return False


def _question_text(framed) -> str:
    """Pull the searchable text out of whatever ``framed`` is.

    Accepts a FramedQuestion (use chosen framing + original + sub-questions),
    or a plain string, or anything with an ``original`` attribute.
    """
    if isinstance(framed, str):
        return framed
    parts: list[str] = []
    original = getattr(framed, "original", None)
    if original:
        parts.append(str(original))
    chosen = getattr(framed, "chosen", None)
    if chosen is not None:
        stmt = getattr(chosen, "statement", None)
        if stmt:
            parts.append(str(stmt))
    subs = getattr(framed, "sub_questions", None)
    if subs:
        parts.extend(str(s) for s in subs)
    return " ".join(parts) if parts else str(framed)


def _question_type_value(framed) -> str | None:
    qt = getattr(framed, "question_type", None)
    if qt is None:
        return None
    return getattr(qt, "value", str(qt))


def _is_load_bearing(framed) -> bool:
    """True when the framing carries any load-bearing sub-question.

    For a plain-string question (no framing) we conservatively treat it as
    load-bearing so the higher-stakes penalties (lookup/community) still apply.
    """
    lb = getattr(framed, "load_bearing", None)
    if lb is None:
        return True
    return bool(lb)


# --------------------------------------------------------------------------- #
# SKILL.md loading (lazy, tolerant of absence)
# --------------------------------------------------------------------------- #
def _skill_md_text(skill_id: str, library_dir: Path | None) -> str:
    """Read ``<library>/<id>/SKILL.md`` if present; '' otherwise. Never raises."""
    base = library_dir if library_dir is not None else LIBRARY_DIR
    try:
        path = base / skill_id / "SKILL.md"
        if path.exists():
            return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:  # pragma: no cover - defensive
        pass
    return ""


def _skill_corpus(manifest: SkillManifest, skill_md: str) -> str:
    """Concatenated text used for the embedding/token similarity to the question:
    the SKILL.md guide plus the manifest's routing fields."""
    bits = [
        skill_md,
        manifest.name,
        manifest.description,
        manifest.category,
        " ".join(manifest.question_types),
        " ".join(manifest.topics),
        " ".join(manifest.audit_tags),
        manifest.perspective_lens,
        manifest.authority,
    ]
    return " ".join(b for b in bits if b)


# --------------------------------------------------------------------------- #
# Similarity: embedder cosine, or deterministic token-overlap fallback
# --------------------------------------------------------------------------- #
def _token_overlap_similarity(question: str, doc: str) -> float:
    """Deterministic offline similarity in [0, 1]: cosine over token bags.

    Stable across runs and dependency-free so the recommender ranks identically
    whether or not an embedder is plugged in.
    """
    q = _tokens(question)
    d = _tokens(doc)
    if not q or not d:
        return 0.0
    qcount: dict[str, int] = {}
    dcount: dict[str, int] = {}
    for t in q:
        qcount[t] = qcount.get(t, 0) + 1
    for t in d:
        dcount[t] = dcount.get(t, 0) + 1
    dot = sum(qcount[t] * dcount.get(t, 0) for t in qcount)
    qn = math.sqrt(sum(v * v for v in qcount.values()))
    dn = math.sqrt(sum(v * v for v in dcount.values()))
    if qn == 0 or dn == 0:
        return 0.0
    return dot / (qn * dn)


def _embedder_similarity(embedder, question: str, docs: list[str]) -> list[float]:
    """Cosine similarity from the provided embedder; falls back to token overlap
    on any failure (offline-safe)."""
    try:
        vectors = embedder.embed([question, *docs])
        qv = vectors[0]
        out: list[float] = []
        for dv in vectors[1:]:
            num = sum(a * b for a, b in zip(qv, dv))
            na = math.sqrt(sum(a * a for a in qv))
            nb = math.sqrt(sum(b * b for b in dv))
            out.append(num / (na * nb) if na and nb else 0.0)
        return out
    except Exception:
        return [_token_overlap_similarity(question, d) for d in docs]


# --------------------------------------------------------------------------- #
# Rule-based scoring from manifest fields
# --------------------------------------------------------------------------- #
def _rule_score(
    manifest: SkillManifest,
    framed,
    mode: str,
    weights: dict,
    *,
    load_bearing: bool,
) -> tuple[float, list[str]]:
    """Return (rule_score, reason_fragments). rule_score is roughly [0, ~1.5]
    before the similarity blend; reasons explain the bonuses/penalties."""
    score = 0.0
    reasons: list[str] = []
    qtype = _question_type_value(framed)
    qtokens = set(_tokens(_question_text(framed)))

    # Question-type match against supported_question_types.
    if qtype and qtype in manifest.question_types:
        score += 0.25
        reasons.append(f"matches question type {qtype}")

    # Topic keyword overlap.
    topic_hits = [t for t in manifest.topics if set(_tokens(t)) & qtokens]
    if topic_hits:
        score += min(0.25, 0.10 * len(topic_hits))
        reasons.append("topic overlap: " + ", ".join(topic_hits))

    # Mode affinity.
    if mode in manifest.modes_natural_fit:
        score += 0.30
        reasons.append(f"natural fit for {mode}")
    elif mode in manifest.modes_weak_fit:
        score -= 0.15
        reasons.append(f"weak fit for {mode}")

    # Grade / authority preferences (Investigate-style).
    if weights.get("prefer_grade_a") and manifest.default_grade == "A":
        score += weights["prefer_grade_a"]
        reasons.append("grade A")
    if weights.get("prefer_peer_reviewed") and manifest.authority == "peer_reviewed":
        score += weights["prefer_peer_reviewed"]
        reasons.append("peer-reviewed authority")
    if weights.get("primary_lens_bonus") and manifest.perspective_lens == "primary":
        score += weights["primary_lens_bonus"]
        reasons.append("primary source")

    # Temporal preference (Reconstruct).
    if weights.get("prefer_temporal") and manifest.temporal_tools:
        score += weights["prefer_temporal"]
        reasons.append("temporal tools")

    # Output-shape penalty (Survey penalizes lookup).
    pen = weights.get("penalize_output_shape")
    if pen and manifest.output_shape == pen[0]:
        score -= pen[1]
        reasons.append(f"penalty: {pen[0]} output shape")

    # Load-bearing penalties (Investigate): lookup-shape & community.
    if load_bearing:
        lb_lookup = weights.get("penalize_lookup_load_bearing")
        if lb_lookup and manifest.output_shape == "lookup":
            score -= lb_lookup
            reasons.append("penalty: lookup-shape on load-bearing question")
        lb_comm = weights.get("penalize_community_load_bearing")
        if lb_comm and manifest.is_community:
            score -= lb_comm
            reasons.append("penalty: community skill on load-bearing question")

    return score, reasons


# --------------------------------------------------------------------------- #
# Candidate gathering + hard filters
# --------------------------------------------------------------------------- #
def _depth_allows_community(depth: str | None) -> bool:
    """Community (unsigned) skills are excluded entirely at thorough/deep
    (MODE_SKILL_INTEGRATION.md §2.2 Investigate)."""
    if depth is None:
        return True
    return depth.lower() not in ("thorough", "deep")


def _gather_candidates(skills, library_dir) -> list[SkillManifest]:
    if skills is not None:
        return list(skills)
    try:
        return all_skills(library_dir)
    except Exception:  # pragma: no cover - defensive
        return []


def _passes_hard_filters(
    manifest: SkillManifest, mode: str, weights: dict, *, allow_community: bool
) -> bool:
    """Hard requirements that drop a skill from the ranking entirely."""
    if manifest.id == GENERAL_WEB_ID:
        return False  # general_web is handled separately as the fallback
    # Composing utilities (e.g. retraction_watch) are integrity helpers invoked
    # BY other skills, not user-facing primary sources — never recommend them
    # directly. They pollute every ranking otherwise (a grade-A academic helper
    # that matches no topic still out-scores the source the user actually named).
    if "composing" in manifest.audit_tags:
        return False
    # Hidden skills (verticals outside the current wedge) are never OFFERED by
    # the recommender. They remain loadable/usable when explicitly named — a
    # caller that passes the manifest directly to the dispatcher bypasses this
    # ranking path entirely — but they don't pollute the default candidate set.
    if manifest.hidden:
        return False
    if not allow_community and manifest.is_community:
        return False
    req_shape = weights.get("require_output_shape")
    if req_shape and manifest.output_shape != req_shape:
        return False
    if weights.get("require_temporal_tools") and not manifest.temporal_tools:
        return False
    if weights.get("require_watchable") and not manifest.watchable:
        return False
    return True


# --------------------------------------------------------------------------- #
# Profile overlay (MODE_SKILL_INTEGRATION.md §2.4)
# --------------------------------------------------------------------------- #
def _matching_profiles(profiles, framed, mode: str) -> list[dict]:
    """Profiles whose ``mode`` matches and whose ``domain_pattern`` appears in
    the question text (case-insensitive substring; '*' / '' = match all)."""
    if not profiles:
        return []
    qtext = _question_text(framed).lower()
    out: list[dict] = []
    for prof in profiles:
        pmode = prof.get("mode")
        if pmode and pmode != mode:
            continue
        pattern = (prof.get("domain_pattern") or "").lower().strip()
        if pattern in ("", "*") or pattern in qtext:
            out.append(prof)
    return out


def _apply_profile_overlay(recs: list[Recommendation], profiles_matched: list[dict]):
    """Apply baseline (always-present), boosted (bonus), excluded (drop)."""
    if not profiles_matched:
        return recs

    excluded: set[str] = set()
    boosted: set[str] = set()
    baseline: set[str] = set()
    for prof in profiles_matched:
        excluded |= set(prof.get("excluded_skills") or [])
        boosted |= set(prof.get("boosted_skills") or [])
        baseline |= set(prof.get("baseline_skills") or [])

    by_id = {r.skill_id: r for r in recs}
    out: list[Recommendation] = []
    for r in recs:
        if r.skill_id in excluded:
            continue
        score = r.score
        reason = r.reason
        if r.skill_id in boosted:
            score += 0.5
            reason = (reason + "; profile-boosted").strip("; ")
        out.append(Recommendation(r.skill_id, score, reason, r.role))

    # Baseline skills are always pre-selected even if they scored below others
    # or were not candidates at all. Excluded wins over baseline.
    for sid in baseline:
        if sid in excluded or sid in by_id:
            continue
        out.append(Recommendation(sid, 1.0, "profile baseline (always included)", "primary"))

    out.sort(key=lambda r: r.score, reverse=True)
    return out


# --------------------------------------------------------------------------- #
# Optional LLM rerank (guarded; never required)
# --------------------------------------------------------------------------- #
def _maybe_llm_rerank(recs, framed, mode, gateway):
    """Reorder by an LLM signal when a gateway is supplied and reachable.

    Strictly optional and defensive: any failure (offline, bad JSON, missing
    method) returns the input unchanged so the offline path is unaffected.
    """
    if gateway is None or not recs:
        return recs
    try:
        available = getattr(gateway, "available", None)
        if callable(available) and not available():
            return recs
        listing = "\n".join(f"- {r.skill_id}: {r.reason}" for r in recs)
        prompt = (
            "Rank these research sources best-first for the question. Reply with "
            "ONLY a comma-separated list of skill ids, no commentary.\n"
            f"Mode: {mode}\nQuestion: {_question_text(framed)}\nSources:\n{listing}"
        )
        resp = gateway.complete("planner", prompt)
        order = [s.strip() for s in resp.text.split(",") if s.strip()]
        rank = {sid: i for i, sid in enumerate(order)}
        return sorted(recs, key=lambda r: rank.get(r.skill_id, len(order)))
    except Exception:
        return recs


# --------------------------------------------------------------------------- #
# Scoring a candidate set into Recommendations (the shared fit path)
# --------------------------------------------------------------------------- #
def _score_candidates(
    candidates: list[SkillManifest],
    framed,
    mode: str,
    weights: dict,
    *,
    embedder,
    library_dir,
    load_bearing: bool,
    default_role: str | None = "primary",
) -> list[Recommendation]:
    if not candidates:
        return []
    question = _question_text(framed)
    docs = [_skill_corpus(m, _skill_md_text(m.id, library_dir)) for m in candidates]
    sims = (
        _embedder_similarity(embedder, question, docs)
        if embedder is not None
        else [_token_overlap_similarity(question, d) for d in docs]
    )
    rule_w = weights.get("rule_weight", _DEFAULT_WEIGHTS["rule_weight"])
    sim_w = weights.get("sim_weight", _DEFAULT_WEIGHTS["sim_weight"])

    recs: list[Recommendation] = []
    for manifest, sim in zip(candidates, sims):
        rule, reasons = _rule_score(manifest, framed, mode, weights, load_bearing=load_bearing)
        score = rule_w * rule + sim_w * sim
        if _explicit_mention(manifest, question):
            score += _EXPLICIT_MENTION_BONUS
            reasons.append("explicitly named in the question")
        if sim > 0:
            reasons.append(f"similarity {sim:.2f}")
        reason = "; ".join(reasons) if reasons else "candidate source"
        recs.append(Recommendation(manifest.id, round(score, 4), reason, default_role))
    recs.sort(key=lambda r: r.score, reverse=True)
    return recs


# --------------------------------------------------------------------------- #
# Mode branches
# --------------------------------------------------------------------------- #
def _recommend_for_fit(candidates, framed, mode, weights, *, embedder, library_dir, load_bearing):
    """Default branch (Investigate / Survey / Reconstruct / Watch / Ask):
    rank candidates by blended fit score, best first."""
    return _score_candidates(
        candidates,
        framed,
        mode,
        weights,
        embedder=embedder,
        library_dir=library_dir,
        load_bearing=load_bearing,
    )


def _recommend_for_diversity(
    candidates, framed, mode, weights, *, embedder, library_dir, load_bearing
):
    """Adjudicate: maximize distinct ``perspective_lens`` coverage. We rank
    by fit, then greedily pick the best skill for each unseen lens so every
    adversarial perspective gets its own evidence base (§2.2)."""
    scored = _score_candidates(
        candidates,
        framed,
        mode,
        weights,
        embedder=embedder,
        library_dir=library_dir,
        load_bearing=load_bearing,
    )
    by_id = {m.id: m for m in candidates}
    seen_lenses: set[str] = set()
    diverse: list[Recommendation] = []
    leftovers: list[Recommendation] = []
    for rec in scored:  # already best-first
        lens = by_id[rec.skill_id].perspective_lens or ""
        if lens and lens not in seen_lenses:
            seen_lenses.add(lens)
            diverse.append(
                Recommendation(
                    rec.skill_id,
                    rec.score,
                    f"{rec.reason}; lens={lens} (diversity pick)".strip("; "),
                    "primary",
                )
            )
        else:
            leftovers.append(rec)
    # Diversity picks lead; remaining skills follow as secondary coverage.
    return diverse + leftovers


def _recommend_per_option(
    candidates, framed, mode, weights, *, embedder, library_dir, load_bearing
):
    """Decide: the recommender runs once per option, then option-level sets are
    merged with dedup into the job's selected_skills (§2.2).

    We derive options from the framing's sub-questions (each option-ish frame),
    score the candidate set against each, and merge keeping the max score per
    skill so a skill strong for any one option survives the merge.
    """
    options = _decide_options(framed)
    if not options:
        return _recommend_for_fit(
            candidates,
            framed,
            mode,
            weights,
            embedder=embedder,
            library_dir=library_dir,
            load_bearing=load_bearing,
        )
    best: dict[str, Recommendation] = {}
    for opt in options:
        for rec in _score_candidates(
            candidates,
            opt,
            mode,
            weights,
            embedder=embedder,
            library_dir=library_dir,
            load_bearing=load_bearing,
        ):
            cur = best.get(rec.skill_id)
            if cur is None or rec.score > cur.score:
                best[rec.skill_id] = rec
    merged = list(best.values())
    merged.sort(key=lambda r: r.score, reverse=True)
    return merged


def _decide_options(framed) -> list[str]:
    """Per-option texts for Decide. Uses sub-questions when available, else the
    single question text."""
    subs = getattr(framed, "sub_questions", None)
    if subs:
        return [str(s) for s in subs]
    return []


# --------------------------------------------------------------------------- #
# general_web fallback
# --------------------------------------------------------------------------- #
def _general_web_role(mode: str, top_specialty_score: float) -> str:
    """Pick the general_web role per §5.2 / §5.3."""
    if mode == "adjudicate":
        return "cross_check"  # popular lens
    if top_specialty_score < _FALLBACK_THRESHOLD:
        return "primary"  # nothing specialty fits → general_web leads
    return "breadth"  # specialty covers it; general_web adds breadth


def _general_web_available(candidates, library_dir, skills) -> bool:
    """general_web exists if it's among passed candidates/skills or on disk."""
    ids = {m.id for m in candidates}
    if GENERAL_WEB_ID in ids:
        return True
    if skills is not None:
        return any(getattr(m, "id", None) == GENERAL_WEB_ID for m in skills)
    base = library_dir if library_dir is not None else LIBRARY_DIR
    try:
        return (base / GENERAL_WEB_ID / "manifest.toml").exists()
    except OSError:  # pragma: no cover - defensive
        return False


_WEB_INTENT_RE = re.compile(
    r"\b(search the web|the open web|web search|across the web|on the web|"
    r"search online|google it)\b",
    re.I,
)


def _explicit_web_intent(question: str) -> bool:
    """True when the user explicitly asked to search the open web — then
    general_web is what they want, not a low-ranked fallback."""
    return bool(_WEB_INTENT_RE.search(question))


def _append_general_web(
    recs: list[Recommendation], mode: str, *, available: bool, question: str = ""
) -> list[Recommendation]:
    """Always offer general_web as a fallback Recommendation with the right role
    (§5.2). Skipped only if it's already present or genuinely unavailable."""
    if any(r.skill_id == GENERAL_WEB_ID for r in recs):
        return recs
    if not available:
        return recs
    top = recs[0].score if recs else 0.0
    if _explicit_web_intent(question):
        # The user said "search the web" — surface it at the top regardless of
        # how the specialty skills scored.
        reason = "explicitly requested open-web search"
        out = list(recs)
        out.append(Recommendation(GENERAL_WEB_ID, round(top + 0.01, 4), reason, "primary"))
        out.sort(key=lambda r: r.score, reverse=True)
        return out
    role = _general_web_role(mode, top)
    if role == "primary":
        reason = "universal fallback — no specialty skill scored above threshold"
        score = max(_FALLBACK_THRESHOLD, top + 0.01)
    elif role == "cross_check":
        reason = "open-web popular lens (cross-check)"
        score = min(top, _FALLBACK_THRESHOLD)
    else:
        reason = "open-web breadth / gap-filler fallback"
        score = min(top, _FALLBACK_THRESHOLD)
    out = list(recs)
    out.append(Recommendation(GENERAL_WEB_ID, round(score, 4), reason, role))
    out.sort(key=lambda r: r.score, reverse=True)
    return out


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #
def recommend(
    framed,
    mode: str,
    depth: str | None = None,
    *,
    skills=None,
    embedder=None,
    gateway=None,
    profiles=None,
    library_dir: Path | None = None,
) -> list[Recommendation]:
    """Rank research skills for a question under a given mode.

    Parameters
    ----------
    framed:
        A ``FramedQuestion`` or a plain question string. A string is run through
        :func:`framing.pipeline.run_framing` when a ``gateway`` is supplied,
        else through the deterministic ``classify_question`` heuristics — either
        way offline-safe.
    mode:
        One of the seven modes. ``decide`` -> per-option, ``adjudicate`` ->
        diversity, everything else -> fit.
    depth:
        ``quick`` | ``standard`` | ``thorough`` | ``deep`` (or ``None``).
        ``thorough``/``deep`` exclude community skills (§2.2 Investigate).
    skills:
        Explicit candidate manifests (tests / dispatcher overrides). When
        ``None`` we discover from ``library_dir`` (default :data:`LIBRARY_DIR`).
    embedder, gateway, profiles, library_dir:
        Optional. ``embedder`` provides cosine similarity (token-overlap
        fallback otherwise); ``gateway`` enables optional LLM framing + rerank;
        ``profiles`` overlay baseline/boosted/excluded (§2.4).

    Returns a ranked ``list[Recommendation]`` (best first), always including a
    ``general_web`` fallback with the appropriate role unless it's already a
    candidate or genuinely unavailable.
    """
    framed = _coerce_framed(framed, gateway)
    weights = MODE_WEIGHTS.get(mode, _DEFAULT_WEIGHTS)
    load_bearing = _is_load_bearing(framed)
    allow_community = _depth_allows_community(depth)

    raw_candidates = _gather_candidates(skills, library_dir)
    candidates = [
        m
        for m in raw_candidates
        if _passes_hard_filters(m, mode, weights, allow_community=allow_community)
    ]

    if mode == "decide":
        recs = _recommend_per_option(
            candidates,
            framed,
            mode,
            weights,
            embedder=embedder,
            library_dir=library_dir,
            load_bearing=load_bearing,
        )
    elif mode == "adjudicate":
        recs = _recommend_for_diversity(
            candidates,
            framed,
            mode,
            weights,
            embedder=embedder,
            library_dir=library_dir,
            load_bearing=load_bearing,
        )
    else:
        recs = _recommend_for_fit(
            candidates,
            framed,
            mode,
            weights,
            embedder=embedder,
            library_dir=library_dir,
            load_bearing=load_bearing,
        )

    # Profile overlay (§2.4): baseline always present, boosted +bonus, excluded out.
    recs = _apply_profile_overlay(recs, _matching_profiles(profiles, framed, mode))

    # Optional, guarded LLM rerank — no-op offline.
    recs = _maybe_llm_rerank(recs, framed, mode, gateway)

    # Always offer general_web as fallback with the right role (§5.2).
    gw_available = _general_web_available(raw_candidates, library_dir, skills)
    recs = _append_general_web(recs, mode, available=gw_available, question=_question_text(framed))
    return recs


def _coerce_framed(framed, gateway):
    """Accept a FramedQuestion or a plain string. Strings are framed via
    run_framing (offline-safe: deterministic when gateway is None)."""
    if isinstance(framed, str):
        # Import lazily so importing the recommender stays cheap and avoids any
        # import cycle with the framing package.
        from ..framing.pipeline import run_framing

        return run_framing(framed, gateway=gateway)
    return framed
