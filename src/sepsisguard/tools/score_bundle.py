"""Tool 3: score_bundle_compliance — thin FHIR fetch + sep1_definition.score_bundle.

No Claude call. Deterministic math only.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from ..audit import audit_log
from ..fhir_client import FhirClient
from ..loinc import WEIGHT
from ..sep1_definition import score_bundle
from ..sharp_context import current_sharp_context

logger = logging.getLogger(__name__)

SCORE_BUNDLE_COMPLIANCE_SCHEMA = {
    "name": "score_bundle_compliance",
    "description": (
        "Compute the current SEP-1 bundle compliance status for a patient with "
        "a confirmed sepsis diagnosis. Walks the FHIR record from Time Zero "
        "forward and identifies which of the 3-hour and 6-hour bundle elements "
        "are met, in progress, or overdue."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "time_zero": {
                "type": "string",
                "description": "ISO 8601 timestamp when severe sepsis criteria were first met.",
            },
            "as_of": {
                "type": "string",
                "description": "ISO 8601 timestamp to score against; defaults to now.",
            },
        },
        "required": ["time_zero"],
        "additionalProperties": False,
    },
}

_DEFAULT_WEIGHT_KG = 80.0

_PATIENT_RECORD_INCLUDES = (
    "Observation",
    "MedicationRequest",
    "MedicationAdministration",
    "DiagnosticReport",
    "Specimen",
    "DocumentReference",
)


async def score_bundle_compliance(
    *, time_zero: str, as_of: str | None = None
) -> dict[str, Any]:
    ctx = current_sharp_context()
    audit_log(
        "tool.score_bundle_compliance",
        trace_id=ctx.trace_id,
        patient=f"Patient/{ctx.patient_id}",
        tool="score_bundle_compliance",
    )

    # Parse time_zero
    tz_dt = _parse_iso(time_zero)
    as_of_dt = _parse_iso(as_of) if as_of else datetime.now(tz=timezone.utc)

    async with FhirClient() as fhir:
        fhir_record = await fhir.patient_record(include=_PATIENT_RECORD_INCLUDES)
        weight_kg = await _fetch_weight(fhir, ctx.patient_id)

    result = score_bundle(tz_dt, as_of_dt, fhir_record, weight_kg)
    return dict(result)


# ── helpers ───────────────────────────────────────────────────────────────────

def _parse_iso(ts: str) -> datetime:
    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


async def _fetch_weight(fhir: FhirClient, patient_id: str) -> float:
    """Fetch most recent body weight observation. Returns default 80 kg if unavailable."""
    try:
        bundle = await fhir.search("Observation", {
            "patient": patient_id,
            "code": WEIGHT,
            "_sort": "-date",
            "_count": "1",
        })
        entries = bundle.get("entry", [])
        if entries:
            obs = entries[0].get("resource", {})
            vq = obs.get("valueQuantity", {})
            value = vq.get("value")
            unit = vq.get("unit", "").lower()
            if value is not None:
                kg = float(value)
                if "lb" in unit or "pound" in unit:
                    kg = kg * 0.453592
                return round(kg, 1)
    except Exception as exc:
        logger.warning("Weight fetch failed: %s; using default %s kg", exc, _DEFAULT_WEIGHT_KG)
    return _DEFAULT_WEIGHT_KG
