"""Shared pytest fixtures for SepsisGuard tests."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

# Ensure tests run without contacting the real Anthropic API by default.
# Tests that need a key set it explicitly.
os.environ.setdefault("DEMO_MODE", "true")
os.environ.pop("ANTHROPIC_API_KEY", None)


@pytest.fixture
def repo_root() -> Path:
    return Path(__file__).parent.parent


@pytest.fixture(autouse=True)
def isolated_audit_log(tmp_path, monkeypatch):
    """Point audit log at a tmp path so tests don't accumulate writes."""
    log_path = tmp_path / "audit.jsonl"
    monkeypatch.setenv("SEPSISGUARD_AUDIT_LOG", str(log_path))
    # Re-import audit so the new env var is picked up.
    import importlib

    from sepsisguard import audit
    importlib.reload(audit)
    yield log_path


@pytest.fixture
def cap_scenario():
    from sepsisguard.demo import load_scenario
    return load_scenario("cap_severe_sepsis")


@pytest.fixture
def uti_scenario():
    from sepsisguard.demo import load_scenario
    return load_scenario("uti_late_onset")


@pytest.fixture
def shock_scenario():
    from sepsisguard.demo import load_scenario
    return load_scenario("intra_abdominal_septic_shock")


@pytest.fixture
def bound_demo_context(cap_scenario):
    """Bind a SHARP context with all scopes for testing tool calls."""
    from sepsisguard.demo import install_mock_fhir, make_mock_fhir_transport
    from sepsisguard.sharp_context import (
        REQUIRED_SCOPES,
        SharpContext,
        bind_sharp_context,
        reset_sharp_context,
    )

    transport = make_mock_fhir_transport(cap_scenario)
    install_mock_fhir(transport)

    ctx = SharpContext(
        patient_id=cap_scenario["patient_id"],
        fhir_base_url="http://mock",
        access_token="test",
        scopes=frozenset(s["name"] for s in REQUIRED_SCOPES),
        trace_id="test-trace",
    )
    token = bind_sharp_context(ctx)
    yield ctx
    reset_sharp_context(token)
