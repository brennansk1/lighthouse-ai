"""SandboxStore tests (SB1) — two-zone, broker-gated, quota-bounded store."""

from __future__ import annotations

from pathlib import Path

import pytest

from lighthouse_ai.sandbox.broker import build_default_broker
from lighthouse_ai.sandbox.scanners import EICAR_SIGNATURE
from lighthouse_ai.sandbox.store import (
    DEFAULT_MAX_BYTES,
    SandboxStore,
)

# Fixed, deterministic timestamps — no datetime.now() anywhere.
T0 = "2026-05-29T00:00:00Z"
T1 = "2026-05-29T00:00:01Z"
T2 = "2026-05-29T00:00:02Z"
T3 = "2026-05-29T00:00:03Z"


def _store(tmp_path: Path, max_bytes: int | None = DEFAULT_MAX_BYTES) -> SandboxStore:
    return SandboxStore(tmp_path / "data", max_bytes=max_bytes)


def _broker(tmp_path: Path):
    return build_default_broker(tmp_path / "broker")


def test_add_user_upload_stored_with_verdict(tmp_path):
    store = _store(tmp_path)
    broker = _broker(tmp_path)
    item = store.add(b"<p>hello world</p>", zone="uploads",
                     filename="notes.html", content_type="text/html",
                     source="user", broker=broker, now=T0)
    assert item is not None
    assert item.zone == "uploads"
    assert item.source == "user"
    assert item.scan_verdict == "admit"
    assert item.filename == "notes.html"
    # On-disk under the uploads zone, sha-derived name.
    saved = Path(item.saved_path)  # type: ignore[arg-type]
    assert saved.exists()
    assert saved.parent == (tmp_path / "data" / "sandbox" / "uploads").resolve()
    assert saved.name.startswith(item.sha256)
    # Listed in its zone.
    assert [i.id for i in store.list(zone="uploads")] == [item.id]


def test_reject_payload_not_stored(tmp_path):
    store = _store(tmp_path)
    broker = _broker(tmp_path)
    item = store.add(EICAR_SIGNATURE, zone="uploads", filename="virus.txt",
                     content_type="text/plain", source="user",
                     broker=broker, now=T0)
    assert item is None
    assert store.list() == []
    # Nothing written to the uploads zone.
    uploads = tmp_path / "data" / "sandbox" / "uploads"
    assert not any(p.is_file() for p in uploads.iterdir())


def test_quarantined_readable_only_with_flag(tmp_path):
    store = _store(tmp_path)
    broker = _broker(tmp_path)
    item = store.add(b"<script>evil()</script>", zone="uploads",
                     filename="x.html", content_type="text/html",
                     source="user", broker=broker, now=T0)
    assert item is not None
    assert item.scan_verdict == "quarantine"
    with pytest.raises(PermissionError):
        store.read(item.id)
    assert store.read(item.id, allow_quarantined=True) == b"<script>evil()</script>"


def test_read_returns_bytes_for_admitted_item(tmp_path):
    store = _store(tmp_path)
    broker = _broker(tmp_path)
    payload = b"plain text body"
    item = store.add(payload, zone="uploads", filename="a.txt",
                     content_type="text/plain", source="user",
                     broker=broker, now=T0)
    assert item is not None
    assert store.read(item.id) == payload


def test_quota_lru_evicts_oldest_pinned_survives(tmp_path):
    # Cap fits exactly two 100-byte items; a third forces one eviction.
    store = _store(tmp_path, max_bytes=250)
    broker = _broker(tmp_path)
    blob = b"A" * 100

    a = store.add(blob + b"a", zone="workspace", filename="a.txt",
                  content_type="text/plain", source="run:1",
                  broker=broker, now=T0, pinned=True)  # pinned, oldest
    b = store.add(blob + b"b", zone="workspace", filename="b.txt",
                  content_type="text/plain", source="run:1",
                  broker=broker, now=T1)               # oldest non-pinned
    c = store.add(blob + b"c", zone="workspace", filename="c.txt",
                  content_type="text/plain", source="run:1",
                  broker=broker, now=T2)
    assert a is not None and b is not None and c is not None

    # Adding a fourth pushes well over cap → LRU evicts oldest non-pinned (b).
    d = store.add(blob + b"d", zone="workspace", filename="d.txt",
                  content_type="text/plain", source="run:1",
                  broker=broker, now=T3)
    assert d is not None

    a_now = store.stat(a.id)
    b_now = store.stat(b.id)
    assert a_now is not None and b_now is not None
    # Pinned item survives.
    assert not a_now.evicted
    assert a_now.saved_path is not None
    # Oldest non-pinned was evicted: payload gone, row marked evicted.
    assert b_now.evicted
    assert b_now.saved_path is None
    with pytest.raises(FileNotFoundError):
        store.read(b.id)
    # Pinned still readable.
    assert store.read(a.id).startswith(b"A" * 100)


def test_usage_shape(tmp_path):
    store = _store(tmp_path, max_bytes=1_000_000)
    broker = _broker(tmp_path)
    store.add(b"hello", zone="uploads", filename="u.txt",
              content_type="text/plain", source="user", broker=broker, now=T0)
    store.add(b"world!", zone="workspace", filename="w.txt",
              content_type="text/plain", source="run:1", broker=broker, now=T1)
    usage = store.usage()
    assert set(usage.keys()) == {"used_bytes", "max_bytes", "by_zone"}
    assert usage["used_bytes"] == len(b"hello") + len(b"world!")
    assert usage["max_bytes"] == 1_000_000
    assert usage["by_zone"] == {"uploads": 5, "workspace": 6}


def test_breakdown_shape(tmp_path):
    store = _store(tmp_path)
    broker = _broker(tmp_path)
    store.add(b"hello", zone="uploads", filename="u.txt",
              content_type="text/plain", source="user", broker=broker, now=T0)
    store.add(b"\x00\x01\x02\x03", zone="workspace", filename="b.bin",
              content_type="application/octet-stream", source="skill:viz",
              broker=broker, now=T1)
    bd = store.breakdown()
    assert set(bd.keys()) == {"by_zone", "by_type", "by_source"}
    for section in bd.values():
        for row in section:
            assert set(row.keys()) == {"key", "count", "bytes"}
    zones = {r["key"]: r for r in bd["by_zone"]}
    assert zones["uploads"]["count"] == 1
    assert zones["workspace"]["count"] == 1
    sources = {r["key"] for r in bd["by_source"]}
    assert sources == {"user", "skill:viz"}


def test_path_traversal_filename_neutralized(tmp_path):
    store = _store(tmp_path)
    broker = _broker(tmp_path)
    item = store.add(b"safe content", zone="uploads",
                     filename="../../etc/passwd", content_type="text/plain",
                     source="user", broker=broker, now=T0)
    assert item is not None
    saved = Path(item.saved_path)  # type: ignore[arg-type]
    uploads_root = (tmp_path / "data" / "sandbox" / "uploads").resolve()
    # Stored strictly under the uploads zone root — no escape.
    assert saved.parent == uploads_root
    assert uploads_root in saved.resolve().parents or saved.resolve().parent == uploads_root
    # The hostile path never materialized outside the sandbox.
    assert not (tmp_path / "etc" / "passwd").exists()
    assert not Path("/etc/passwd_lighthouse_test").exists()
    # Round-trips fine.
    assert store.read(item.id) == b"safe content"


def test_write_artifact_targets_workspace_only(tmp_path):
    store = _store(tmp_path)
    broker = _broker(tmp_path)
    item = store.write_artifact(b"chart,data\n1,2\n", filename="chart.csv",
                                content_type="text/csv", source="skill:viz",
                                broker=broker, now=T0)
    assert item is not None
    assert item.zone == "workspace"


def test_safe_path_rejects_absolute_and_dotdot(tmp_path):
    store = _store(tmp_path)
    # Absolute path collapses to its leaf, contained under the zone.
    p = store._safe_path("uploads", "/etc/passwd")
    assert p.parent == (tmp_path / "data" / "sandbox" / "uploads").resolve()
    # Pure traversal leaves no valid leaf → rejected.
    with pytest.raises(ValueError):
        store._safe_path("uploads", "../..")
    with pytest.raises(ValueError):
        store._safe_path("nope", "x")  # type: ignore[arg-type]


def test_pin_and_remove(tmp_path):
    store = _store(tmp_path)
    broker = _broker(tmp_path)
    item = store.add(b"data", zone="workspace", filename="a.txt",
                     content_type="text/plain", source="run:1",
                     broker=broker, now=T0)
    assert item is not None
    store.pin(item.id)
    assert store.stat(item.id).pinned is True  # type: ignore[union-attr]
    store.pin(item.id, pinned=False)
    assert store.stat(item.id).pinned is False  # type: ignore[union-attr]
    assert store.remove(item.id) is True
    assert store.stat(item.id) is None
    assert store.remove("does-not-exist") is False
