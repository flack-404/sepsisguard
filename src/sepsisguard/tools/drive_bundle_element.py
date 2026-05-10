"""Tool 5: drive_bundle_element — create a FHIR Task for a SEP-1 bundle element.

Write tool. Requires user/Task.c scope.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from ..audit import audit_log
from ..fhir_client import FhirClient
from ..sharp_context import require_scope

logger = logging.getLogger(__name__)

DRIVE_BUNDLE_ELEMENT_SCHEMA = {
    "name": "drive_bundle_element",
    "description": (
        "Create a FHIR Task to drive a specific SEP-1 bundle element to "
        "completion. The Task is assigned to the appropriate care-team role "
        "(nurse, pharmacist, lab, RT) with a deadline matching the bundle "
        "clock. Use this to convert agent recommendations into accountable "
        "EHR-tracked work items."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "element": {
                "type": "string",
                "enum": [
                    "lactate_initial",
                    "blood_cultures",
                    "broad_spectrum_antibiotics",
                    "fluid_resuscitation",
                    "vasopressors",
                    "repeat_lactate",
                    "volume_reassessment",
                ],
            },
            "deadline": {
                "type": "string",
                "description": "ISO 8601 deadline for this element.",
            },
            "assigned_role": {
                "type": "string",
                "enum": ["nurse", "pharmacist", "rrt", "physician", "respiratory_therapist"],
            },
            "details": {
                "type": "string",
                "description": "Optional override for the task description.",
            },
        },
        "required": ["element", "deadline", "assigned_role"],
        "additionalProperties": False,
    },
}

_HIGH_PRIORITY_ELEMENTS = frozenset({
    "broad_spectrum_antibiotics",
    "fluid_resuscitation",
    "vasopressors",
})

_DEFAULT_DESCRIPTIONS: dict[str, str] = {
    "lactate_initial": "Draw serum lactate — must result within 3 hours of Time Zero.",
    "blood_cultures": "Obtain blood culture set ×2 (peripheral + central if line present) before first antibiotic dose.",
    "broad_spectrum_antibiotics": "Administer ordered broad-spectrum antibiotic IV — confirm pharmacist has verified dose.",
    "fluid_resuscitation": "Initiate 30 mL/kg crystalloid (NS or LR) IV bolus; reassess volume status at completion.",
    "vasopressors": "Initiate vasopressor (norepinephrine preferred) titrated to MAP ≥ 65 mmHg.",
    "repeat_lactate": "Repeat serum lactate — must result within 6 hours of Time Zero if initial lactate elevated.",
    "volume_reassessment": "Document focused volume status assessment (CVP, urine output trend, or passive leg raise response).",
}

_ROLE_DISPLAY: dict[str, str] = {
    "nurse": "Bedside RN",
    "pharmacist": "Pharmacist",
    "rrt": "Rapid Response Team",
    "physician": "Attending Physician",
    "respiratory_therapist": "Respiratory Therapist",
}


async def drive_bundle_element(
    *,
    element: str,
    deadline: str,
    assigned_role: str,
    details: str | None = None,
) -> dict[str, Any]:
    ctx = require_scope("user/Task.c")
    audit_log(
        "tool.drive_bundle_element",
        trace_id=ctx.trace_id,
        patient=f"Patient/{ctx.patient_id}",
        tool="drive_bundle_element",
        element=element,
    )

    now_iso = datetime.now(tz=timezone.utc).isoformat()
    priority = "urgent" if element in _HIGH_PRIORITY_ELEMENTS else "routine"
    description = details or _DEFAULT_DESCRIPTIONS.get(element, f"SEP-1 bundle element: {element}")

    task: dict[str, Any] = {
        "resourceType": "Task",
        "status": "requested",
        "intent": "order",
        "priority": priority,
        "code": {"text": f"SEP-1: {element}"},
        "description": description,
        "for": {"reference": f"Patient/{ctx.patient_id}"},
        "authoredOn": now_iso,
        "executionPeriod": {"end": deadline},
        "requester": {"display": "SepsisGuard"},
        "owner": {"display": _ROLE_DISPLAY.get(assigned_role, assigned_role)},
        "reasonCode": {"text": f"CMS SEP-1 bundle element — {element}"},
    }

    async with FhirClient() as fhir:
        response = await fhir.create(task)

    task_id = response.get("id", "unknown")
    return {
        "task_ref": f"Task/{task_id}",
        "element": element,
        "deadline": deadline,
        "assigned_role": assigned_role,
        "priority": priority,
        "description": description,
        "status": "requested",
        "authored_on": now_iso,
    }
