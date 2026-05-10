"""Tool 7: notify_care_team — create a FHIR Communication resource.

Write tool. Requires user/Communication.c scope.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from ..audit import audit_log
from ..fhir_client import FhirClient
from ..sharp_context import require_scope

logger = logging.getLogger(__name__)

NOTIFY_CARE_TEAM_SCHEMA = {
    "name": "notify_care_team",
    "description": (
        "Send a structured A2A notification to the care team about a sepsis "
        "alert, bundle element status, or clinical concern. Creates a FHIR "
        "Communication resource and (optionally) hands off to a separate A2A "
        "agent (e.g., the hospital's nursing notification agent or pager bot)."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "level": {
                "type": "string",
                "enum": ["info", "advisory", "urgent", "stat"],
            },
            "audience": {
                "type": "array",
                "items": {
                    "type": "string",
                    "enum": [
                        "bedside_nurse",
                        "charge_nurse",
                        "intensivist",
                        "hospitalist",
                        "pharmacist",
                        "respiratory_therapist",
                        "rrt",
                        "family",
                    ],
                },
            },
            "subject": {"type": "string"},
            "body": {"type": "string"},
            "linked_resources": {
                "type": "array",
                "items": {"type": "string"},
                "description": "FHIR refs (Tasks, Conditions, Observations) this message references.",
            },
        },
        "required": ["level", "audience", "subject", "body"],
        "additionalProperties": False,
    },
}

_LEVEL_TO_PRIORITY: dict[str, str] = {
    "info": "routine",
    "advisory": "routine",
    "urgent": "urgent",
    "stat": "stat",
}

_AUDIENCE_DISPLAY: dict[str, str] = {
    "bedside_nurse": "Bedside RN",
    "charge_nurse": "Charge Nurse",
    "intensivist": "Intensivist",
    "hospitalist": "Hospitalist",
    "pharmacist": "Pharmacist",
    "respiratory_therapist": "Respiratory Therapist",
    "rrt": "Rapid Response Team",
    "family": "Patient Family",
}


async def notify_care_team(
    *,
    level: str,
    audience: list[str],
    subject: str,
    body: str,
    linked_resources: list[str] | None = None,
) -> dict[str, Any]:
    ctx = require_scope("user/Communication.c")
    audit_log(
        "tool.notify_care_team",
        trace_id=ctx.trace_id,
        patient=f"Patient/{ctx.patient_id}",
        tool="notify_care_team",
        level=level,
        audience=str(audience),
    )

    sent_at = datetime.now(tz=timezone.utc).isoformat()
    priority = _LEVEL_TO_PRIORITY.get(level, "routine")

    communication: dict[str, Any] = {
        "resourceType": "Communication",
        "status": "completed",
        "priority": priority,
        "category": [{
            "coding": [{
                "system": "http://terminology.hl7.org/CodeSystem/communication-category",
                "code": "alert",
                "display": "Alert",
            }]
        }],
        "subject": {"reference": f"Patient/{ctx.patient_id}"},
        "sent": sent_at,
        "sender": {"display": "SepsisGuard"},
        "recipient": [
            {"display": _AUDIENCE_DISPLAY.get(role, role)} for role in audience
        ],
        "topic": {"text": subject},
        "payload": [{"contentString": body}],
    }

    if linked_resources:
        communication["about"] = [{"reference": ref} for ref in linked_resources]

    async with FhirClient() as fhir:
        response = await fhir.create(communication)

    comm_id = response.get("id", "unknown")
    return {
        "communication_ref": f"Communication/{comm_id}",
        "level": level,
        "audience": audience,
        "subject": subject,
        "sent_at": sent_at,
        "priority": priority,
        "linked_resources": linked_resources or [],
    }
