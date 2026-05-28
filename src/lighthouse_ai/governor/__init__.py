"""Governor — the single cross-cutting runtime guardrail (design §24).

  * Hierarchical token buckets (monthly→weekly→daily→per-job) — buckets.py
  * Degradation tiers + trip/reset — buckets.py
  * Loop detection (§24.6) — loop_detector.py
  * Prompt-injection gate + spotlighting (§24.8) — injection_gate.py
  * Egress proxy: allowlist + privacy tiers + connection log (§24.9) — egress_proxy.py
"""

from __future__ import annotations

from .buckets import (
    BUDGET_DEFAULTS,
    BudgetConfig,
    BudgetTripped,
    Governor,
    GovernorDecision,
    degradation_tier,
)
from .egress_proxy import EgressDecision, EgressProxy, PrivacyTier
from .injection_gate import InjectionGate, InjectionVerdict, spotlight
from .loop_detector import LoopConfig, LoopDecision, LoopDetector
from .scheduler_gate import (
    PauseReason,
    Policy,
    SchedulerGate,
    SchedulerGateConfig,
    Signals,
    current_policy,
    sample_signals,
)
from .tool_policy import (
    TaskProfile,
    Tool,
    ToolCapability,
    ToolPolicyDecision,
    ToolPolicyViolation,
    decide,
    enforce,
    visible_tools,
)

__all__ = [
    "BUDGET_DEFAULTS",
    "BudgetConfig",
    "BudgetTripped",
    "EgressDecision",
    "EgressProxy",
    "Governor",
    "GovernorDecision",
    "InjectionGate",
    "InjectionVerdict",
    "LoopConfig",
    "LoopDecision",
    "LoopDetector",
    "PauseReason",
    "Policy",
    "PrivacyTier",
    "SchedulerGate",
    "SchedulerGateConfig",
    "Signals",
    "TaskProfile",
    "Tool",
    "ToolCapability",
    "ToolPolicyDecision",
    "ToolPolicyViolation",
    "current_policy",
    "decide",
    "degradation_tier",
    "enforce",
    "sample_signals",
    "spotlight",
    "visible_tools",
]
