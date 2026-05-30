"""Sprint 21.2 — Gateway dispatch table tests.

These focus on the new backend-routing logic added on top of the existing
gateway suite. The injectable ``ollama=`` constructor arg lets us swap in a
fake backend without touching real HTTP.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import pytest

from lighthouse_ai.backends.ollama import ChatResponse, OllamaUnavailable
from lighthouse_ai.gateway import Gateway
from lighthouse_ai.governor import BUDGET_DEFAULTS, Governor
from lighthouse_ai.hardware import HardwareProfile
from lighthouse_ai.persistence import open_db


@dataclass
class _FakeOllama:
    """Stub backend matching the OllamaBackend chat() signature."""
    fixed_text: str = "ollama-says-hi"
    prompt_tokens: int = 7
    completion_tokens: int = 4
    raise_on_chat: bool = False
    available_flag: bool = True
    calls: list[dict] | None = None

    def __post_init__(self) -> None:
        self.calls = []

    def available(self) -> bool:
        return self.available_flag

    def loaded_models(self):
        # These tests exercise *routing*, not the RAM guard — report every
        # model as already resident so enough-RAM never blocks the fake.
        class _All:
            def __contains__(self, _x): return True
        return _All()

    def chat(self, model: str, prompt: str, *, sampling=None, system=None) -> ChatResponse:
        assert self.calls is not None
        self.calls.append({"model": model, "prompt": prompt, "sampling": sampling})
        if self.raise_on_chat:
            raise OllamaUnavailable("simulated")
        return ChatResponse(
            text=self.fixed_text, prompt_tokens=self.prompt_tokens,
            completion_tokens=self.completion_tokens, model=model,
        )


@pytest.fixture
def stub_profile() -> HardwareProfile:
    """T1 (Mac mini / 16 GB) — binds every role to Ollama per catalog/models.yaml.

    T3+ tiers use ``mlx`` or ``vllm`` as the inference backend; the Sprint 21
    dispatcher only knows ``ollama`` so far. The MLX/vLLM adapters land in
    Sprint 22.
    """
    return HardwareProfile(
        platform="macos", arch="arm64", apple_silicon=True,
        total_ram_gb=16.0, free_ram_gb=8.0,
        cpu_cores_physical=8, cpu_cores_logical=8,
        gpu=[], unified_memory=True,
        available_backends=["cpu", "ollama"],
        suggested_tier="T1",
    )


def _gateway_with_fake(migrated_paths, stub_profile, fake: _FakeOllama | None) -> Gateway:
    g = Governor(migrated_paths.state_db, BUDGET_DEFAULTS)
    return Gateway(g, migrated_paths.audit_db, profile=stub_profile,
                   ollama=fake, prefer_real_backends=fake is not None)


def test_dispatch_routes_ollama_when_available(migrated_paths, stub_profile):
    fake = _FakeOllama()
    gw = _gateway_with_fake(migrated_paths, stub_profile, fake)
    resp = gw.complete("planner", "hello", job_id="j1")
    assert resp.text == "ollama-says-hi"
    assert resp.prompt_tokens == 7
    assert resp.completion_tokens == 4
    assert len(fake.calls) == 1
    assert fake.calls[0]["model"]  # whatever T3 planner is


def test_dispatch_runs_real_moe_tag_under_tight_ram(migrated_paths, stub_profile):
    """A fine-grained MoE bound to a real tag (``qwen3:30b-a3b``) pages from SSD,
    so even under near-zero free RAM it must run on real Ollama — never silently
    degrade to the low-mem mock. Regression for the runtime-tag MoE recognition
    bug (catalog ``PAGEABLE_MOE`` only held capability-class names)."""

    @dataclass
    class _NotResident(_FakeOllama):
        def loaded_models(self):
            return []  # model is NOT hot → admission must rely on is_pageable_moe

    fake = _NotResident(fixed_text="real-moe")
    gw = _gateway_with_fake(migrated_paths, stub_profile, fake)
    gw = Gateway(Governor(migrated_paths.state_db, BUDGET_DEFAULTS),
                 migrated_paths.audit_db, profile=stub_profile, ollama=fake,
                 overrides={"planner": "qwen3:30b-a3b"})
    from lighthouse_ai.governor.ollama_queue import AdmissionConfig
    # Refuse-now config + essentially no free RAM: a dense model would be denied,
    # but the paging MoE reserves nothing (need=0) and runs.
    gw._admission = AdmissionConfig(wait_timeout_s=0.0)
    resp = gw.complete("planner", "hello")
    assert resp.text == "real-moe"
    assert resp.model == "qwen3:30b-a3b"
    assert gw.drain_backends().get("ollama") == 1


def test_dispatch_falls_back_to_mock_when_ollama_unavailable(migrated_paths, stub_profile):
    fake = _FakeOllama(available_flag=False)
    gw = _gateway_with_fake(migrated_paths, stub_profile, fake)
    resp = gw.complete("planner", "hello")
    assert "[mock" in resp.text


def test_dispatch_falls_back_to_mock_on_backend_error(migrated_paths, stub_profile):
    fake = _FakeOllama(raise_on_chat=True)
    gw = _gateway_with_fake(migrated_paths, stub_profile, fake)
    resp = gw.complete("planner", "hello")
    # Backend raised → mock fallback used.
    assert "[mock" in resp.text


def test_dispatch_records_backend_used_in_audit(migrated_paths, stub_profile):
    fake = _FakeOllama()
    gw = _gateway_with_fake(migrated_paths, stub_profile, fake)
    gw.complete("planner", "hello", job_id="trace-1")
    conn = open_db(migrated_paths.audit_db)
    try:
        row = conn.execute(
            "SELECT payload_json FROM audit_events "
            "WHERE event_type='model_call' ORDER BY seq DESC LIMIT 1"
        ).fetchone()
    finally:
        conn.close()
    payload = json.loads(row[0])
    assert payload["backend_used"] == "ollama"
    assert payload["job_id"] == "trace-1"


def test_dispatch_records_mock_fallback_in_audit(migrated_paths, stub_profile):
    fake = _FakeOllama(raise_on_chat=True)
    gw = _gateway_with_fake(migrated_paths, stub_profile, fake)
    gw.complete("planner", "hello")
    conn = open_db(migrated_paths.audit_db)
    try:
        row = conn.execute(
            "SELECT payload_json FROM audit_events "
            "WHERE event_type='model_call' ORDER BY seq DESC LIMIT 1"
        ).fetchone()
    finally:
        conn.close()
    assert json.loads(row[0])["backend_used"] == "mock"


def test_dispatch_no_real_backends_when_disabled(migrated_paths, stub_profile):
    """``prefer_real_backends=False`` keeps the old mock-only behavior."""
    g = Governor(migrated_paths.state_db, BUDGET_DEFAULTS)
    gw = Gateway(g, migrated_paths.audit_db, profile=stub_profile,
                 ollama=None, prefer_real_backends=False)
    resp = gw.complete("planner", "hello")
    assert "[mock" in resp.text


def test_dispatch_passes_sampling_to_backend(migrated_paths, stub_profile):
    fake = _FakeOllama()
    gw = _gateway_with_fake(migrated_paths, stub_profile, fake)
    gw.complete("planner", "hello")
    # The catalog's planner role has a sampling dict.
    samp = fake.calls[0]["sampling"]
    assert "temperature" in samp


def test_dispatch_existing_mock_tests_still_pass(migrated_paths, stub_profile):
    """When no ollama is injected and prefer_real defaults to True, but no real
    daemon is reachable, the Gateway must still complete via mock fallback."""
    g = Governor(migrated_paths.state_db, BUDGET_DEFAULTS)
    # No ollama= passed: the gateway will try OllamaBackend(), which will fail
    # available() if no daemon is up. We just confirm completion still works.
    gw = Gateway(g, migrated_paths.audit_db, profile=stub_profile,
                 prefer_real_backends=True)
    resp = gw.complete("planner", "hello")
    assert resp.text
    # Either real (ollama-says-hi or actual Qwen output) or mock; both are valid.
