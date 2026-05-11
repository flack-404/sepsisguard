"""Smoke tests + clinical-logic spot checks.

Runs without ANTHROPIC_API_KEY (uses stub fallbacks for Claude-backed tools).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

# ── infrastructure ───────────────────────────────────────────────────────────

def test_sharp_context_scope_check():
    from sepsisguard.sharp_context import (
        SharpContext,
        bind_sharp_context,
        require_scope,
        reset_sharp_context,
    )

    ctx = SharpContext(
        patient_id="x", fhir_base_url="http://mock", access_token="t",
        scopes=frozenset({"patient/Patient.rs"}),
    )
    token = bind_sharp_context(ctx)
    try:
        # Granted scope passes
        require_scope("patient/Patient.rs")
        # Denied scope raises
        with pytest.raises(PermissionError):
            require_scope("user/Task.c")
    finally:
        reset_sharp_context(token)


def test_audit_log_writes_records(isolated_audit_log):
    from sepsisguard.audit import audit_log

    audit_log("test.event", trace_id="t1", patient="Patient/abc")
    contents = isolated_audit_log.read_text(encoding="utf-8").strip().splitlines()
    assert len(contents) == 1
    rec = json.loads(contents[0])
    assert rec["event"] == "test.event"
    assert rec["trace_id"] == "t1"
    assert rec["patient"] == "Patient/abc"


# ── domain layer ─────────────────────────────────────────────────────────────

def test_loinc_constants_resolve():
    from sepsisguard import loinc

    assert loinc.LACTATE == "32693-4"
    assert loinc.WBC == "6690-2"
    assert loinc.HEART_RATE == "8867-4"
    assert loinc.LACTATE_LEGACY in loinc.LACTATE_CODES


def test_evaluate_sirs_cap_scenario():
    from sepsisguard.sep1_definition import evaluate_sirs

    obs = [
        # Temp 39.1°C
        {"code": {"coding": [{"code": "8310-5"}]}, "valueQuantity": {"value": 39.1, "unit": "Cel"}},
        # HR 118
        {"code": {"coding": [{"code": "8867-4"}]}, "valueQuantity": {"value": 118}},
        # RR 28
        {"code": {"coding": [{"code": "9279-1"}]}, "valueQuantity": {"value": 28}},
        # WBC 18.4 K/uL
        {"code": {"coding": [{"code": "6690-2"}]}, "valueQuantity": {"value": 18.4, "unit": "10*3/uL"}},
    ]
    sirs = evaluate_sirs(obs)
    assert sirs["count_met"] == 4


def test_severe_sepsis_truth_table():
    from sepsisguard.sep1_definition import severe_sepsis_met

    sirs_high = {"temp_abnormal": True, "hr_elevated": True, "rr_elevated": True,
                 "wbc_abnormal": True, "count_met": 4}
    sirs_low = {"temp_abnormal": False, "hr_elevated": True, "rr_elevated": False,
                "wbc_abnormal": False, "count_met": 1}
    organ = [{"name": "elevated_lactate", "value": 3.2}]

    assert severe_sepsis_met(sirs_high, organ, has_infection=True) is True
    assert severe_sepsis_met(sirs_high, organ, has_infection=False) is False
    assert severe_sepsis_met(sirs_low, organ, has_infection=True) is False
    assert severe_sepsis_met(sirs_high, [], has_infection=True) is False


def test_septic_shock_lactate_threshold():
    from sepsisguard.sep1_definition import septic_shock_met

    assert septic_shock_met(initial_lactate=5.8, post_fluid_hypotension=False) is True
    assert septic_shock_met(initial_lactate=3.5, post_fluid_hypotension=False) is False
    assert septic_shock_met(initial_lactate=3.5, post_fluid_hypotension=True) is True
    assert septic_shock_met(initial_lactate=None, post_fluid_hypotension=False) is False


def test_score_bundle_with_synthetic_data():
    from sepsisguard.sep1_definition import score_bundle

    tz = datetime(2026, 5, 10, 14, 32, tzinfo=timezone.utc)
    record = {
        "entry": [
            # Initial lactate at T+25
            {"resource": {
                "resourceType": "Observation", "id": "lac-1",
                "code": {"coding": [{"code": "32693-4"}]},
                "effectiveDateTime": (tz + timedelta(minutes=25)).isoformat(),
                "valueQuantity": {"value": 3.2, "unit": "mmol/L"},
            }},
            # Blood cx at T+15
            {"resource": {
                "resourceType": "DiagnosticReport", "id": "cx-1",
                "category": [{"coding": [{"code": "micro-bact"}]}],
                "code": {"coding": [{"display": "blood culture"}]},
                "effectiveDateTime": (tz + timedelta(minutes=15)).isoformat(),
            }},
            # Cefepime admin at T+90
            {"resource": {
                "resourceType": "MedicationAdministration", "id": "ma-1",
                "medicationCodeableConcept": {"coding": [{"code": "309027"}]},
                "effectiveDateTime": (tz + timedelta(minutes=90)).isoformat(),
            }},
        ]
    }
    as_of = tz + timedelta(hours=2)
    result = score_bundle(tz, as_of, record, weight_kg=70)

    assert result["elements"]["lactate_initial"]["status"] == "met"
    assert result["elements"]["blood_cultures_before_antibiotics"]["status"] == "met"
    assert result["elements"]["blood_cultures_before_antibiotics"]["antibiotic_admin_after_cx"] is True
    assert result["elements"]["broad_spectrum_antibiotics"]["status"] == "met"


def test_antibiogram_lookup_pneumonia():
    from sepsisguard.antibiogram import load_antibiogram, recommend_regimen

    ab = load_antibiogram()
    out = recommend_regimen(
        "pneumonia",
        allergies=[],
        egfr=80, weight_kg=70,
        include_mrsa=True, include_pseudomonas=True,
        antibiogram=ab,
    )
    assert "cefepime" in out["primary_regimen"]
    assert "vancomycin" in out["primary_regimen"]


def test_antibiogram_pcn_allergy_substitutes_cefepime():
    from sepsisguard.antibiogram import load_antibiogram, recommend_regimen

    ab = load_antibiogram()
    allergy = [{
        "clinicalStatus": {"coding": [{"code": "active"}]},
        "criticality": "low",
        "code": {"coding": [{"display": "Penicillin"}]},
        "reaction": [{"severity": "mild", "manifestation": [{"text": "rash"}]}],
    }]
    out = recommend_regimen(
        "urinary",
        allergies=allergy,
        egfr=80, weight_kg=70,
        include_mrsa=True, include_pseudomonas=True,
        antibiogram=ab,
    )
    # For urinary + non-anaphylactic PCN allergy, cefepime is acceptable
    pcn_decision = next(
        (c for c in out["contraindications_checked"] if c["allergen"] == "penicillin"),
        None,
    )
    assert pcn_decision is not None
    assert pcn_decision["severity"] == "non_anaphylactic"
    assert "cross-reactivity" in pcn_decision["decision"].lower()


# ── tools (deterministic) ────────────────────────────────────────────────────

async def test_screen_sepsis_signals_cap(bound_demo_context):
    from sepsisguard.tools.screen_signals import screen_sepsis_signals

    result = await screen_sepsis_signals(lookback_hours=72)
    assert result["recommendation"] == "proceed_to_adjudication"
    assert result["sirs_criteria"]["count_met"] >= 2
    assert len(result["organ_dysfunction_markers"]) >= 1


async def test_drive_bundle_element_creates_task(bound_demo_context):
    from sepsisguard.tools.drive_bundle_element import drive_bundle_element

    deadline = (datetime.now(tz=timezone.utc) + timedelta(hours=3)).isoformat()
    result = await drive_bundle_element(
        element="broad_spectrum_antibiotics",
        deadline=deadline,
        assigned_role="nurse",
    )
    assert result["task_ref"].startswith("Task/")
    assert result["priority"] == "urgent"


async def test_notify_care_team_creates_communication(bound_demo_context):
    from sepsisguard.tools.notify_care_team import notify_care_team

    result = await notify_care_team(
        level="urgent",
        audience=["bedside_nurse", "intensivist"],
        subject="Test",
        body="Test body",
    )
    assert result["communication_ref"].startswith("Communication/")
    assert result["priority"] == "urgent"


# ── tools (Claude stubs) ─────────────────────────────────────────────────────

async def test_confirm_diagnosis_stub_handles_empty_evidence(bound_demo_context):
    """Regression: stub must not crash when infection_evidence is empty."""
    from sepsisguard.tools.confirm_diagnosis import confirm_sepsis_diagnosis

    packet = {
        "recommendation": "needs_more_data",
        "sirs_criteria": {"count_met": 2},
        "organ_dysfunction_markers": [],
        "infection_evidence": [],  # empty list
        "free_text_triggers": [],
    }
    result = await confirm_sepsis_diagnosis(screening_packet=packet)
    assert result["classification"] in (
        "insufficient_data", "sepsis_likely_benign_alternative", "severe_sepsis"
    )


async def test_recommend_antibiotic_stub_returns_regimen(bound_demo_context):
    from sepsisguard.tools.recommend_antibiotic import recommend_antibiotic

    result = await recommend_antibiotic(suspected_source="pneumonia")
    assert result["needs_clinician_signoff"] is True
    assert isinstance(result["primary_regimen"], list)


async def test_draft_documentation_stub(bound_demo_context):
    from sepsisguard.tools.draft_documentation import draft_sep1_documentation

    diag = {"classification": "severe_sepsis", "time_zero": "2026-05-10T14:55:00Z"}
    bundle = {"overall_compliance": "on_track", "completed_count": 1,
              "total_required": 6, "elements": {}}
    result = await draft_sep1_documentation(
        diagnosis_packet=diag, bundle_status=bundle,
    )
    assert "note_text" in result
    assert "Time Zero" in result["note_text"]


# ── server / FastAPI ─────────────────────────────────────────────────────────

def test_health_endpoint():
    from fastapi.testclient import TestClient

    from sepsisguard.server import app
    c = TestClient(app)
    r = c.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_agent_card_lists_three_skills():
    from fastapi.testclient import TestClient

    from sepsisguard.server import app
    c = TestClient(app)
    r = c.get("/.well-known/agent-card.json")
    assert r.status_code == 200
    assert len(r.json()["skills"]) == 3


def test_mcp_initialize_declares_extension():
    from fastapi.testclient import TestClient

    from sepsisguard.server import app
    c = TestClient(app)
    r = c.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    assert r.status_code == 200
    ext = r.json()["result"]["capabilities"]["extensions"]["ai.promptopinion/fhir-context"]
    assert len(ext["scopes"]) == 15


def test_mcp_tools_list_returns_seven():
    from fastapi.testclient import TestClient

    from sepsisguard.server import app
    c = TestClient(app)
    r = c.post("/mcp", json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
    assert r.status_code == 200
    tools = r.json()["result"]["tools"]
    assert len(tools) == 7
    names = {t["name"] for t in tools}
    assert names == {
        "screen_sepsis_signals", "confirm_sepsis_diagnosis", "score_bundle_compliance",
        "recommend_antibiotic", "drive_bundle_element", "draft_sep1_documentation",
        "notify_care_team",
    }


# ── end-to-end ───────────────────────────────────────────────────────────────

async def test_demo_runs_cap_scenario_without_anthropic_key(monkeypatch):
    """Critical: demo must run with no API key (judges may try this).

    Set the key to empty string — load_dotenv won't override an existing var,
    and `if os.environ.get("ANTHROPIC_API_KEY"):` is falsy for empty strings.
    """
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")

    from sepsisguard.demo import run_scenario

    result = await run_scenario("cap_severe_sepsis")
    assert result["mode"] in ("deterministic_offline", "deterministic_fallback")
    assert "severe_sepsis" in result.get("final_summary", "").lower()
