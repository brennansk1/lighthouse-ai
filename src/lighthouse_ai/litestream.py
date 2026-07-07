"""Litestream integration: config rendering, install hints, lag reporting.

Litestream itself is a Go binary installed out-of-band. We render its YAML
config from a template, then expose helpers for the doctor command.
"""

from __future__ import annotations

import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from .paths import Paths
from .templates import render


def render_litestream_config(paths: Paths) -> str:
    return render(
        "litestream.yml",
        state_db=paths.state_db,
        audit_db=paths.audit_db,
        intents_db=paths.intents_db,
        positions_db=paths.positions_db,
        hypotheses_db=paths.hypotheses_db,
        replicas_dir=paths.replicas_dir,
    )


def write_litestream_config(paths: Paths) -> Path:
    paths.litestream_config.parent.mkdir(parents=True, exist_ok=True)
    paths.litestream_config.write_text(render_litestream_config(paths))
    return paths.litestream_config


def litestream_installed() -> bool:
    return shutil.which("litestream") is not None


def litestream_version() -> str | None:
    if not litestream_installed():
        return None
    try:
        out = subprocess.run(
            ["litestream", "version"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        return (out.stdout or out.stderr).strip() or None
    except Exception:
        return None


@dataclass(frozen=True)
class ReplicaLag:
    name: str
    youngest_mtime: float | None
    lag_seconds: float | None


def replica_lags(paths: Paths) -> list[ReplicaLag]:
    out: list[ReplicaLag] = []
    if not paths.replicas_dir.exists():
        return out
    now = time.time()
    for sub in sorted(paths.replicas_dir.iterdir()):
        if not sub.is_dir():
            continue
        youngest = 0.0
        for f in sub.rglob("*"):
            if f.is_file():
                youngest = max(youngest, f.stat().st_mtime)
        if youngest:
            out.append(ReplicaLag(sub.name, youngest, round(now - youngest, 2)))
        else:
            out.append(ReplicaLag(sub.name, None, None))
    return out


def install_hint() -> str:
    return (
        "Install Litestream:\n"
        "  macOS:  brew install benbjohnson/litestream/litestream\n"
        "  Linux:  https://litestream.io/install/\n"
        "Then run: litestream replicate -config ~/.lighthouse/litestream.yml"
    )
