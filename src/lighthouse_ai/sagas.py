"""Saga compensator registry (§25.4).

A compensator is a callable ``(intent: Intent) -> None`` that undoes the
side-effect a previously-applied intent caused on its target. Compensators
are registered per-target via :func:`register`. The Effector calls
:func:`compensate` to run the right one for an intent.

This is deliberately a tiny module — most of the policy lives in the
``intents`` table (target name, compensator JSON hint) and the Effector.
"""

from __future__ import annotations

from typing import Callable, Iterable

from .intents import Intent

Compensator = Callable[[Intent], None]

_REGISTRY: dict[str, Compensator] = {}


def register(target: str, fn: Compensator) -> None:
    """Register a compensator for ``target``. Overwrites silently — last wins."""
    _REGISTRY[target] = fn


def unregister(target: str) -> None:
    _REGISTRY.pop(target, None)


def clear() -> None:
    _REGISTRY.clear()


def known_targets() -> Iterable[str]:
    return tuple(_REGISTRY.keys())


def compensate(intent: Intent) -> None:
    """Run the compensator for ``intent.target``. No-op when absent."""
    fn = _REGISTRY.get(intent.target)
    if fn is None:
        return
    fn(intent)
