"""Tool 4: recommend_antibiotic — Claude-backed antibiotic stewardship.

Fetches allergies + eGFR + weight from FHIR, seeds recommend_regimen(),
then asks Claude to refine with guideline citations.

Output is ALWAYS a draft for clinician sign-off. Never auto-administered.
Stub fallback when ANTHROPIC_API_KEY is unset.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from ..antibiogram import load_antibiogram, recommend_regimen
from ..audit import audit_log
from ..claude_client import CacheableBlock, ClaudeClient
from ..fhir_client import FhirClient
from ..loinc import EGFR, WEIGHT
from ..sharp_context import require_scope

logger = logging.getLogger(__name__)

RECOMMEND_ANTIBIOTIC_SCHEMA = {
    "name": "recommend_antibiotic",
    "description": (
        "Recommend a broad-spectrum antibiotic regimen for the suspected "
        "infection source, accounting for patient allergies, renal function "
        "(eGFR), weight, and the local antibiogram. Output is a draft only "
        "— intended for clinician sign-off, never auto-administered."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "suspected_source": {
                "type": "string",
                "enum": ["pneumonia", "urinary", "intra_abdominal",
                         "skin_soft_tissue", "central_line", "unknown"],
            },
            "include_mrsa_coverage": {"type": "boolean", "default": True},
            "include_pseudomonas_coverage": {"type": "boolean", "default": True},
        },
        "required": ["suspected_source"],
        "additionalProperties": False,
    },
}

SYSTEM_PROMPT = """You are an antibiotic stewardship agent assisting ICU clinicians \
with empiric antibiotic selection for sepsis. You receive:
- A seed regimen from the local antibiogram
- Patient allergy list (FHIR AllergyIntolerance)
- Renal function (eGFR) and weight
- Infection source
- MRSA and Pseudomonas coverage requirements

Your task: produce a refined, clinician-ready draft antibiotic regimen.

Hard rules:
1. Output is a DRAFT for clinician sign-off — never auto-administered.
2. Cite Surviving Sepsis Campaign 2021 and the relevant IDSA guideline for the source.
3. Respect all documented allergies. For non-anaphylactic penicillin allergy, \
cefepime is acceptable — explicitly state the cross-reactivity rationale.
4. If eGFR < 50, flag each renally-cleared drug with "renal_adjustment_needed" \
and state which pharmacist parameters to consider — do NOT dose-adjust yourself.
5. MRSA coverage required if include_mrsa_coverage is true.
6. Anti-pseudomonal coverage required if include_pseudomonas_coverage is true.
7. needs_clinician_signoff must always be true.

Output a single JSON object:
- primary_regimen: array of {medication, dose, frequency, route, rxnorm, renal_adjustment_note (optional)}
- rationale: prose explaining the selection (2-4 sentences)
- contraindications_checked: array of {allergen, severity, decision}
- guidelines_cited: array of guideline strings
- needs_pharmacist_review: boolean (true if eGFR < 50 or complex allergy)
- needs_clinician_signoff: true (always)
"""

_ANTIBIOGRAM: dict[str, Any] | None = None


def _get_antibiogram() -> dict[str, Any]:
    global _ANTIBIOGRAM
    if _ANTIBIOGRAM is None:
        _ANTIBIOGRAM = load_antibiogram()
    return _ANTIBIOGRAM


async def recommend_antibiotic(
    *,
    suspected_source: str,
    include_mrsa_coverage: bool = True,
    include_pseudomonas_coverage: bool = True,
) -> dict[str, Any]:
    ctx = require_scope("patient/AllergyIntolerance.rs")
    audit_log(
        "tool.recommend_antibiotic",
        trace_id=ctx.trace_id,
        patient=f"Patient/{ctx.patient_id}",
        tool="recommend_antibiotic",
        source=suspected_source,
    )

    async with FhirClient() as fhir:
        allergies = await _fetch_allergies(fhir, ctx.patient_id)
        egfr = await _fetch_latest_obs_value(fhir, ctx.patient_id, EGFR)
        weight_kg = await _fetch_latest_obs_value(fhir, ctx.patient_id, WEIGHT) or 80.0

    antibiogram = _get_antibiogram()
    seed = recommend_regimen(
        suspected_source,
        allergies=allergies,
        egfr=egfr,
        weight_kg=weight_kg,
        include_mrsa=include_mrsa_coverage,
        include_pseudomonas=include_pseudomonas_coverage,
        antibiogram=antibiogram,
    )

    user_payload = {
        "suspected_source": suspected_source,
        "include_mrsa_coverage": include_mrsa_coverage,
        "include_pseudomonas_coverage": include_pseudomonas_coverage,
        "seed_regimen": seed["primary_regimen"],
        "contraindications_from_seed": seed["contraindications_checked"],
        "renal_adjustment_needed": seed["renal_adjustment_needed"],
        "renal_flagged_drugs": seed["renal_flagged_drugs"],
        "egfr": egfr,
        "weight_kg": weight_kg,
        "antibiogram_excerpt": seed["antibiogram_excerpt"],
        "allergy_count": len(allergies),
    }

    system_blocks = [CacheableBlock(text=SYSTEM_PROMPT, cache=True, ttl="1h")]
    user_blocks = [CacheableBlock(text=json.dumps(user_payload, indent=2), cache=False)]

    client = ClaudeClient()
    try:
        result = await client.generate(
            system_blocks=system_blocks,
            user_blocks=user_blocks,
            max_tokens=2500,
        )
        parsed = _parse_json(result.text)
        parsed.setdefault("primary_regimen", [])
        parsed.setdefault("rationale", "")
        parsed.setdefault("contraindications_checked", seed["contraindications_checked"])
        parsed.setdefault("guidelines_cited", [])
        parsed.setdefault("needs_pharmacist_review", seed["renal_adjustment_needed"])
        parsed["needs_clinician_signoff"] = True  # always enforce
        parsed["_telemetry"] = {
            "input_tokens": result.input_tokens,
            "cache_read_tokens": result.cache_read_input_tokens,
            "cache_hit_ratio": round(result.cache_hit_ratio, 3),
            "model": client.model,
        }
        return parsed

    except RuntimeError:
        logger.info("Claude unavailable — returning stub for recommend_antibiotic")
        return _stub_response(seed, suspected_source)


def _stub_response(seed: dict[str, Any], source: str) -> dict[str, Any]:
    regimen = [
        {"medication": drug, "dose": "per pharmacy", "frequency": "per pharmacy",
         "route": "IV", "rxnorm": ""}
        for drug in seed["primary_regimen"]
    ]
    return {
        "primary_regimen": regimen,
        "rationale": (
            f"Stub regimen for {source} source (Claude unavailable). "
            "Seeded from local antibiogram. Awaiting clinician review."
        ),
        "contraindications_checked": seed["contraindications_checked"],
        "guidelines_cited": ["Surviving Sepsis Campaign 2021"],
        "needs_pharmacist_review": seed["renal_adjustment_needed"],
        "needs_clinician_signoff": True,
        "_telemetry": {"input_tokens": 0, "cache_read_tokens": 0, "cache_hit_ratio": 0.0, "model": "stub"},
    }


async def _fetch_allergies(fhir: FhirClient, patient_id: str) -> list[dict[str, Any]]:
    try:
        bundle = await fhir.search("AllergyIntolerance", {
            "patient": patient_id,
            "clinical-status": "active",
        })
        return [e["resource"] for e in bundle.get("entry", []) if e.get("resource")]
    except Exception as exc:
        logger.warning("Allergy fetch failed: %s", exc)
        return []


async def _fetch_latest_obs_value(
    fhir: FhirClient, patient_id: str, loinc_code: str
) -> float | None:
    try:
        bundle = await fhir.search("Observation", {
            "patient": patient_id,
            "code": loinc_code,
            "_sort": "-date",
            "_count": "1",
        })
        entries = bundle.get("entry", [])
        if entries:
            obs = entries[0].get("resource", {})
            vq = obs.get("valueQuantity", {})
            value = vq.get("value")
            if value is not None:
                return float(value)
    except Exception as exc:
        logger.warning("Observation fetch (code=%s) failed: %s", loinc_code, exc)
    return None


def _parse_json(text: str) -> dict[str, Any]:
    """Extract the first complete JSON object from text. Tolerates code fences."""
    s = text.strip()
    if s.startswith("```"):
        s = s.split("```", 2)[1]
        if s.startswith("json"):
            s = s[4:]
        s = s.rsplit("```", 1)[0]

    # Find every top-level JSON object and parse the largest one with the most keys.
    candidates: list[dict[str, Any]] = []
    depth = 0
    start_idx = -1
    for i, ch in enumerate(s):
        if ch == "{":
            if depth == 0:
                start_idx = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start_idx != -1:
                try:
                    candidates.append(json.loads(s[start_idx : i + 1]))
                except json.JSONDecodeError:
                    pass
                start_idx = -1

    if not candidates:
        return {}
    # Pick the candidate with the most relevant top-level keys.
    target_keys = {"primary_regimen", "rationale", "contraindications_checked", "guidelines_cited"}
    return max(candidates, key=lambda d: len(set(d.keys()) & target_keys))
