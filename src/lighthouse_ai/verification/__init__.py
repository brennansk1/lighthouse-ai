"""Verification + calibration + compounding knowledge (design §22, §23)."""

from .wep import WEP_BANDS, WEPBand, band_for_probability, parse_band
from .brier import brier_score, mean_brier
from .audit_chain import (
    append_event,
    seal_event_chain,
    verify_audit_chain,
)
from .positions import Position, record_position, resolve_position, score_all
from .hypotheses import (
    Hypothesis,
    add_hypothesis,
    list_hypotheses,
    update_hypothesis,
)
from .skills import (
    Skill,
    add_skill,
    list_skills,
    increment_use,
)

__all__ = [
    "Hypothesis",
    "Position",
    "Skill",
    "WEPBand",
    "WEP_BANDS",
    "add_hypothesis",
    "add_skill",
    "append_event",
    "band_for_probability",
    "brier_score",
    "increment_use",
    "list_hypotheses",
    "list_skills",
    "mean_brier",
    "parse_band",
    "record_position",
    "resolve_position",
    "score_all",
    "seal_event_chain",
    "update_hypothesis",
    "verify_audit_chain",
]
