"""Tool-policy risk tiers (OpenHuman §6).

Formalises the design's "build broad, expose narrow" rule with **two-point
enforcement**: a tool is hidden from the prompt *and* refused at runtime if it's
out of policy for the current task. This closes the prompt-injection hole where
fetched content tries to invoke a tool the agent shouldn't have — reasoning steps
derived ``from_content`` may only ever touch read-only tools.

There is no tool-calling runtime yet; this is the reusable substrate the design
calls for, ready to wire into the gateway/executor when tools land.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

__all__ = [
    "DEFAULT_EXPOSURE_CEILING",
    "TaskProfile",
    "Tool",
    "ToolCapability",
    "ToolPolicyDecision",
    "ToolPolicyViolation",
    "decide",
    "enforce",
    "visible_tools",
]

DEFAULT_EXPOSURE_CEILING = 7  # ≤7 tools per agent (design)


class ToolCapability(str, Enum):
    """A tool's blast radius, lowest → highest."""

    READ_ONLY = "read_only"
    LOCAL_WRITE = "local_write"
    NETWORK_FETCH = "network_fetch"
    MUTATING = "mutating"


_RANK = {
    ToolCapability.READ_ONLY: 0,
    ToolCapability.LOCAL_WRITE: 1,
    ToolCapability.NETWORK_FETCH: 2,
    ToolCapability.MUTATING: 3,
}


@dataclass(frozen=True)
class Tool:
    name: str
    capability: ToolCapability


@dataclass(frozen=True)
class TaskProfile:
    """The policy boundary for one agent/task.

    ``max_capability`` is the highest tool capability the task may use.
    ``from_content`` marks reasoning derived from fetched/untrusted content —
    such steps are clamped to read-only regardless of ``max_capability``.
    """

    name: str
    max_capability: ToolCapability = ToolCapability.READ_ONLY
    exposure_ceiling: int = DEFAULT_EXPOSURE_CEILING
    from_content: bool = False


@dataclass(frozen=True)
class ToolPolicyDecision:
    tool: str
    allowed: bool
    reason: str


class ToolPolicyViolation(RuntimeError):
    """Raised when an out-of-policy tool is invoked at runtime."""


def decide(profile: TaskProfile, tool: Tool) -> ToolPolicyDecision:
    """Pure policy check for a single tool under a task profile."""
    if profile.from_content and tool.capability is not ToolCapability.READ_ONLY:
        return ToolPolicyDecision(
            tool.name,
            False,
            "content-derived step may only call read_only tools",
        )
    if _RANK[tool.capability] > _RANK[profile.max_capability]:
        return ToolPolicyDecision(
            tool.name,
            False,
            f"{tool.capability.value} exceeds task ceiling {profile.max_capability.value}",
        )
    return ToolPolicyDecision(tool.name, True, "within policy")


def visible_tools(profile: TaskProfile, tools: list[Tool]) -> list[Tool]:
    """Prompt-visibility filter: in-policy tools, capped at the exposure ceiling.

    Lower-capability (safer) tools are preferred when the ceiling forces a cut,
    with registration order broken deterministically.
    """
    allowed = [t for t in tools if decide(profile, t).allowed]
    allowed.sort(key=lambda t: _RANK[t.capability])  # stable: ties keep input order
    return allowed[: profile.exposure_ceiling]


def enforce(
    profile: TaskProfile,
    tool: Tool,
    *,
    audit_db=None,
    secret: bytes | None = None,
) -> ToolPolicyDecision:
    """Runtime enforcement: return the decision or raise on violation.

    When an audit db + secret are supplied, refusals are appended to the HMAC
    audit chain so policy violations are tamper-evidently logged.
    """
    decision = decide(profile, tool)
    if not decision.allowed:
        if audit_db is not None and secret is not None:
            try:
                from ..verification.audit_chain import append_event

                append_event(
                    audit_db,
                    actor=profile.name,
                    event_type="tool_policy_refused",
                    payload={
                        "tool": tool.name,
                        "capability": tool.capability.value,
                        "reason": decision.reason,
                    },
                    secret=secret,
                )
            except Exception:
                pass  # never let audit logging mask the refusal
        raise ToolPolicyViolation(f"{tool.name}: {decision.reason}")
    return decision
