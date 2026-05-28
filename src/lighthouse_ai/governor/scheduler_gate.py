"""Scheduler Gate — host-courtesy throttle for background LLM work (§24, OpenHuman §1).

The Governor meters *budget* (token buckets) and *RAM* (won't OOM). This adds the
missing third axis: **host pressure** — is now a polite time to spend CPU/GPU on
LLM-bound work? On a machine that doubles as the user's daily driver, a Deep-Dive
that pins the CPU and drains the battery is exactly what makes someone disable a
24/7 background tool.

OpenHuman's gate is async (Tokio); Lighthouse's research pipeline is synchronous
(``gateway.complete`` is a blocking call), so this is a faithful *synchronous*
translation: a cooperative ``permit()`` context manager backed by a
``threading.Semaphore`` for the global concurrency slot. Callers wrap each unit of
LLM-bound work:

    gate = SchedulerGate()
    with gate.permit():
        resp = gateway.complete(...)

The permit resolves immediately under AGGRESSIVE/NORMAL, sleeps ``throttled_backoff_ms``
under THROTTLED, and re-polls every ``paused_poll_ms`` under PAUSED so the caller
resumes the moment the gate flips back on.
"""

from __future__ import annotations

import os
import threading
import time
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum

__all__ = [
    "PauseReason",
    "Policy",
    "SchedulerGate",
    "SchedulerGateConfig",
    "Signals",
    "current_policy",
    "sample_signals",
]


class PauseReason(str, Enum):
    USER_DISABLED = "user_disabled"
    ON_BATTERY = "on_battery"
    CPU_PRESSURE = "cpu_pressure"
    OFFLINE = "offline"  # Lighthouse analog of SignedOut: airplane-mode / paused
    UNKNOWN = "unknown"


class Policy(str, Enum):
    AGGRESSIVE = "aggressive"  # server/headless: bypass throttles
    NORMAL = "normal"  # desktop with headroom: run as scheduled
    THROTTLED = "throttled"  # busy or on battery: serialise + slow down
    PAUSED = "paused"  # user opted out / offline


@dataclass(frozen=True)
class Signals:
    on_ac_power: bool
    battery_charge: float | None  # 0..1, None on desktops/servers
    cpu_usage_pct: float  # 0..100
    server_mode: bool


@dataclass(frozen=True)
class SchedulerGateConfig:
    mode: str = "auto"  # auto | aggressive | off
    battery_floor_pct: float = 80.0  # below this on battery → Throttled
    cpu_idle_ceiling_pct: float = 70.0  # above this → Throttled
    sample_interval_s: float = 30.0
    throttled_backoff_ms: int = 2000  # sleep before each permit when throttled
    paused_poll_ms: int = 5000  # re-poll cadence when paused
    max_concurrent_llm: int = 1  # global slot count (raise on T3+)

    @classmethod
    def from_mapping(cls, data: dict) -> SchedulerGateConfig:
        """Build from a parsed ``[governor.scheduler_gate]`` table; unknown keys ignored."""
        fields = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in (data or {}).items() if k in fields})

    @classmethod
    def from_config_file(cls, path) -> SchedulerGateConfig:
        """Read ``[governor.scheduler_gate]`` from a config.toml; defaults if absent."""
        try:
            import tomllib  # type: ignore[import-not-found]
        except ModuleNotFoundError:  # py<3.11
            import tomli as tomllib  # type: ignore[no-redef]
        try:
            with open(path, "rb") as fh:
                data = tomllib.load(fh)
        except (FileNotFoundError, OSError):
            return cls()
        table = data.get("governor", {}).get("scheduler_gate", {})
        return cls.from_mapping(table)


# --- env overrides: explicit truthy/falsy/garbage→None (OpenHuman §7.2) ----
# CI and containers pin host conditions deterministically; garbage values must
# fall through to the real probe, never silently coerce.
_TRUTHY = {"1", "true", "yes", "on"}
_FALSY = {"0", "false", "no", "off"}


def _env_bool(name: str) -> bool | None:
    raw = os.environ.get(name)
    if raw is None:
        return None
    v = raw.strip().lower()
    if v in _TRUTHY:
        return True
    if v in _FALSY:
        return False
    return None


def _env_float(name: str) -> float | None:
    raw = os.environ.get(name)
    if raw is None:
        return None
    try:
        return float(raw.strip())
    except ValueError:
        return None


def _detect_server() -> bool:
    """Heuristic: containerised/headless hosts run flat-out."""
    if _env_bool("LIGHTHOUSE_SERVER_MODE"):
        return True
    return os.path.exists("/.dockerenv") or bool(os.environ.get("KUBERNETES_SERVICE_HOST"))


def sample_signals(cfg: SchedulerGateConfig | None = None) -> Signals:
    """Probe host signals, with env overrides winning over the real probe."""
    cfg = cfg or SchedulerGateConfig()
    on_ac = _env_bool("LIGHTHOUSE_ON_AC_POWER")
    batt = _env_float("LIGHTHOUSE_BATTERY_CHARGE")  # 0..1
    cpu = _env_float("LIGHTHOUSE_CPU_USAGE")
    server = _env_bool("LIGHTHOUSE_SERVER_MODE")

    if on_ac is None or batt is None:
        b = None
        try:
            import psutil

            b = psutil.sensors_battery()
        except Exception:
            b = None
        if b is not None:
            if on_ac is None:
                on_ac = bool(b.power_plugged)
            if batt is None:
                batt = b.percent / 100.0
        else:
            # No battery sensor → desktop/server: treat as on AC, no battery.
            if on_ac is None:
                on_ac = True

    if cpu is None:
        try:
            import psutil

            cpu = psutil.cpu_percent(interval=None)
        except Exception:
            cpu = 0.0

    if server is None:
        server = cfg.mode == "aggressive" or _detect_server()

    return Signals(
        on_ac_power=bool(on_ac if on_ac is not None else True),
        battery_charge=batt,
        cpu_usage_pct=float(cpu or 0.0),
        server_mode=bool(server),
    )


def current_policy(
    cfg: SchedulerGateConfig, sig: Signals
) -> tuple[Policy, PauseReason | None]:
    """Resolve host signals to a policy. Total function — never raises.

    Order: explicit user-off → server/aggressive → battery → cpu → normal.
    """
    if cfg.mode == "off":
        return Policy.PAUSED, PauseReason.USER_DISABLED
    if cfg.mode == "aggressive" or sig.server_mode:
        return Policy.AGGRESSIVE, None
    if (
        not sig.on_ac_power
        and sig.battery_charge is not None
        and sig.battery_charge * 100.0 < cfg.battery_floor_pct
    ):
        return Policy.THROTTLED, PauseReason.ON_BATTERY
    if sig.cpu_usage_pct > cfg.cpu_idle_ceiling_pct:
        return Policy.THROTTLED, PauseReason.CPU_PRESSURE
    return Policy.NORMAL, None


class SchedulerGate:
    """Cooperative host-courtesy gate. Hold a ``permit()`` per LLM call.

    Always pair with the Governor's budget/RAM accounting — the gate is host
    courtesy, the Governor is resource accounting; every background LLM call
    goes through both.
    """

    def __init__(
        self,
        cfg: SchedulerGateConfig | None = None,
        *,
        signals_provider: Callable[[], Signals] | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.cfg = cfg or SchedulerGateConfig()
        self._sem = threading.Semaphore(max(1, self.cfg.max_concurrent_llm))
        self._sleep = sleep
        self._cached: Signals | None = None
        self._cached_at = 0.0
        self._provider = signals_provider
        self._lock = threading.Lock()

    def _sample_cached(self) -> Signals:
        if self._provider is not None:
            return self._provider()
        now = time.monotonic()
        with self._lock:
            if self._cached is None or now - self._cached_at >= self.cfg.sample_interval_s:
                self._cached = sample_signals(self.cfg)
                self._cached_at = now
            return self._cached

    def policy(self) -> tuple[Policy, PauseReason | None]:
        return current_policy(self.cfg, self._sample_cached())

    def _block_until_capacity(self) -> None:
        while True:
            policy, _ = self.policy()
            if policy in (Policy.AGGRESSIVE, Policy.NORMAL):
                return
            if policy is Policy.THROTTLED:
                self._sleep(self.cfg.throttled_backoff_ms / 1000.0)
                return
            # PAUSED: re-poll; resumes the moment the gate flips back on.
            self._sleep(self.cfg.paused_poll_ms / 1000.0)

    @contextmanager
    def permit(self):
        """Block until the host is polite, then hold a global concurrency slot."""
        self._block_until_capacity()
        self._sem.acquire()
        try:
            yield self
        finally:
            self._sem.release()
