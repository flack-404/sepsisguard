"""Tool 1: screen_sepsis_signals — deterministic FHIR walk + SIRS/qSOFA scoring.

No Claude call. Pure FHIR queries + sep1_definition math.
"""

from __future__ import annotations

import base64
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from ..audit import audit_log
from ..fhir_client import FhirClient
from ..loinc import (
    GCS_TOTAL,
    HEART_RATE,
    MAP,
    RESP_RATE,
    SBP,
    SPO2_CODES,
    TEMP,
    WBC,
    BANDS_PCT,
    LACTATE_CODES,
    CREATININE,
    INR,
    PLATELETS,
    BILIRUBIN_TOTAL,
)
from ..rxnorm import BROAD_SPECTRUM_ANTIBIOTICS, INFECTION_SNOMED_CODES, INFECTION_DISPLAY_TO_SOURCE
from ..sep1_definition import evaluate_sirs, evaluate_organ_dysfunction
from ..sharp_context import current_sharp_context

logger = logging.getLogger(__name__)

SCREEN_SEPSIS_SIGNALS_SCHEMA = {
    "name": "screen_sepsis_signals",
    "description": (
        "Screen the SHARP-bound patient for potential sepsis signals over the "
        "specified lookback window. Returns SIRS criteria met, qSOFA score, "
        "organ dysfunction markers, and any free-text triggers detected in "
        "recent nursing notes / DiagnosticReports. Does NOT confirm sepsis — "
        "use confirm_sepsis_diagnosis next."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "lookback_hours": {
                "type": "integer",
                "default": 24,
                "minimum": 1,
                "maximum": 168,
            },
        },
        "additionalProperties": False,
    },
}

_FREE_TEXT_KEYWORDS = frozenset({
    "mottled", "decreased urine output", "unwell", "lethargic",
    "altered mental status", "gram-negative", "gram-positive", "septic",
    "consolidation", "cloudy urine", "sediment", "rigors", "hypotensive",
    "tachycardic", "obtunded", "confusion", "bacteremia",
})

_ALL_OBS_CODES = (
    LACTATE_CODES
    | frozenset({HEART_RATE, SBP, MAP, RESP_RATE, TEMP, WBC, BANDS_PCT,
                 GCS_TOTAL, CREATININE, INR, PLATELETS, BILIRUBIN_TOTAL})
    | SPO2_CODES
)


async def screen_sepsis_signals(*, lookback_hours: int = 24) -> dict[str, Any]:
    ctx = current_sharp_context()
    audit_log(
        "tool.screen_sepsis_signals",
        trace_id=ctx.trace_id,
        patient=f"Patient/{ctx.patient_id}",
        tool="screen_sepsis_signals",
        lookback_hours=lookback_hours,
    )

    now = datetime.now(tz=timezone.utc)
    window_start = now - timedelta(hours=lookback_hours)
    window_start_str = window_start.strftime("%Y-%m-%dT%H:%M:%SZ")

    async with FhirClient() as fhir:
        patient_id = ctx.patient_id

        # Fetch vitals + labs
        vitals_bundle = await _safe_search(fhir, "Observation", {
            "patient": patient_id,
            "category": "vital-signs",
            "date": f"ge{window_start_str}",
            "_sort": "-date",
            "_count": "100",
        })
        labs_bundle = await _safe_search(fhir, "Observation", {
            "patient": patient_id,
            "category": "laboratory",
            "date": f"ge{window_start_str}",
            "_sort": "-date",
            "_count": "100",
        })
        doc_bundle = await _safe_search(fhir, "DocumentReference", {
            "patient": patient_id,
            "date": f"ge{window_start_str}",
            "_count": "50",
        })
        diag_bundle = await _safe_search(fhir, "DiagnosticReport", {
            "patient": patient_id,
            "category": "micro-bact",
            "date": f"ge{window_start_str}",
            "_count": "50",
        })
        condition_bundle = await _safe_search(fhir, "Condition", {
            "patient": patient_id,
            "clinical-status": "active",
        })
        med_bundle = await _safe_search(fhir, "MedicationRequest", {
            "patient": patient_id,
            "status": "active",
        })

    # Extract resource lists
    vitals = _entries(vitals_bundle)
    labs = _entries(labs_bundle)
    observations = vitals + labs
    doc_refs = _entries(doc_bundle)
    diag_reports = _entries(diag_bundle)
    conditions = _entries(condition_bundle)
    med_requests = _entries(med_bundle)

    # SIRS evaluation
    sirs = evaluate_sirs(observations)

    # Organ dysfunction
    organ_markers = evaluate_organ_dysfunction(observations)

    # qSOFA (RR ≥ 22, altered mentation, SBP ≤ 100)
    qsofa_score = _compute_qsofa(observations)

    # Free-text triggers from DocumentReferences and DiagnosticReport conclusions
    free_text_triggers = _scan_free_text(doc_refs, diag_reports)

    # Infection evidence: active Conditions with infection codes OR active abx MedRequests
    infection_evidence = _extract_infection_evidence(conditions, med_requests)

    # Recommendation logic
    has_signals = sirs["count_met"] >= 2 or len(organ_markers) > 0 or len(free_text_triggers) > 0
    has_labs = len(labs) > 0
    has_infection = len(infection_evidence) > 0

    if not has_signals:
        recommendation = "no_sepsis_signal"
    elif not has_labs:
        recommendation = "needs_more_data"
    else:
        recommendation = "proceed_to_adjudication"

    # Screening score 0-4
    screening_score_4 = (
        int(sirs["count_met"] >= 2)
        + int(len(organ_markers) > 0)
        + int(len(free_text_triggers) > 0)
        + int(has_infection)
    )

    return {
        "patient_ref": f"Patient/{ctx.patient_id}",
        "screening_window": {
            "start": window_start.isoformat(),
            "end": now.isoformat(),
        },
        "sirs_criteria": sirs,
        "qsofa_score": qsofa_score,
        "organ_dysfunction_markers": organ_markers,
        "free_text_triggers": free_text_triggers,
        "infection_evidence": infection_evidence,
        "recommendation": recommendation,
        "screening_score_4": screening_score_4,
    }


# ── helpers ───────────────────────────────────────────────────────────────────

async def _safe_search(
    fhir: FhirClient, resource_type: str, params: dict[str, str]
) -> dict[str, Any]:
    try:
        return await fhir.search(resource_type, params)
    except Exception as exc:
        logger.warning("FHIR search %s failed: %s", resource_type, exc)
        return {}


def _entries(bundle: dict[str, Any]) -> list[dict[str, Any]]:
    return [e["resource"] for e in bundle.get("entry", []) if e.get("resource")]


def _compute_qsofa(observations: list[dict[str, Any]]) -> int:
    """Compute qSOFA score (0-3): RR≥22, altered mentation (GCS<15), SBP≤100."""
    from ..sep1_definition import _obs_codes, _extract_obs_value  # type: ignore[attr-defined]

    score = 0
    rr_elevated = False
    sbp_low = False
    gcs_altered = False

    for obs in observations:
        codes = _obs_codes(obs)
        val, _ = _extract_obs_value(obs)
        if val is None:
            continue
        if RESP_RATE in codes and val >= 22:
            rr_elevated = True
        if SBP in codes and val <= 100:
            sbp_low = True
        if GCS_TOTAL in codes and val < 15:
            gcs_altered = True

    score = int(rr_elevated) + int(sbp_low) + int(gcs_altered)
    return score


def _scan_free_text(
    doc_refs: list[dict[str, Any]],
    diag_reports: list[dict[str, Any]],
) -> list[dict[str, str]]:
    triggers: list[dict[str, str]] = []

    for dr in doc_refs:
        ref = f"DocumentReference/{dr.get('id', 'unknown')}"
        text_parts: list[str] = []
        for content in dr.get("content", []):
            attachment = content.get("attachment", {})
            if attachment.get("data"):
                try:
                    decoded = base64.b64decode(attachment["data"]).decode("utf-8", errors="replace")
                    text_parts.append(decoded)
                except Exception:
                    pass
            if attachment.get("title"):
                text_parts.append(attachment["title"])
        full_text = " ".join(text_parts).lower()
        snippet = _find_snippet(full_text, ref, triggers)
        if snippet:
            triggers.append({"source": ref, "snippet": snippet})

    for report in diag_reports:
        ref = f"DiagnosticReport/{report.get('id', 'unknown')}"
        conclusion = report.get("conclusion", "").lower()
        if conclusion:
            snippet = _find_snippet(conclusion, ref, triggers)
            if snippet:
                triggers.append({"source": ref, "snippet": snippet[:200]})

    return triggers


def _find_snippet(text: str, ref: str, existing: list[dict[str, str]]) -> str | None:
    """Return a ≤200 char snippet around the first matching keyword, or None."""
    already = {t["source"] for t in existing}
    if ref in already:
        return None
    for kw in _FREE_TEXT_KEYWORDS:
        idx = text.find(kw)
        if idx != -1:
            start = max(0, idx - 40)
            end = min(len(text), idx + len(kw) + 80)
            return text[start:end].strip()[:200]
    return None


def _extract_infection_evidence(
    conditions: list[dict[str, Any]],
    med_requests: list[dict[str, Any]],
) -> list[dict[str, str]]:
    evidence: list[dict[str, str]] = []

    for cond in conditions:
        for coding in cond.get("code", {}).get("coding", []):
            code = str(coding.get("code", ""))
            system = coding.get("system", "")
            display = coding.get("display", coding.get("text", "unknown condition"))
            if code in INFECTION_SNOMED_CODES or "snomed" in system.lower():
                if code in INFECTION_SNOMED_CODES:
                    evidence.append({
                        "source": f"Condition/{cond.get('id', 'unknown')}",
                        "display": display,
                    })
                    break
            # Also accept free-text condition names that indicate infection
            text = (cond.get("code", {}).get("text", "") + " " + display).lower()
            if any(w in text for w in ("pneumonia", "sepsis", "infection", "uti",
                                        "bacteremia", "cellulitis", "peritonitis")):
                evidence.append({
                    "source": f"Condition/{cond.get('id', 'unknown')}",
                    "display": display,
                })
                break

    for mr in med_requests:
        rxcodes: set[str] = set()
        mc = mr.get("medicationCodeableConcept", {})
        for c in mc.get("coding", []):
            if c.get("code"):
                rxcodes.add(str(c["code"]))
        if rxcodes & BROAD_SPECTRUM_ANTIBIOTICS:
            display = mc.get("text") or next(
                (c.get("display", "antibiotic") for c in mc.get("coding", [])), "antibiotic"
            )
            authored = mr.get("authoredOn", "")
            evidence.append({
                "source": f"MedicationRequest/{mr.get('id', 'unknown')}",
                "display": f"active order: {display}" + (f" (ordered {authored})" if authored else ""),
            })

    return evidence
