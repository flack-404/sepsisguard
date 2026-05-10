"""SHARP context — per-request FHIR credentials carried via contextvars.

Tools call current_sharp_context() to read patient_id / FHIR endpoint / scopes
without needing threading args. The MCP server binds one SharpContext per
inbound request, resets it when the request completes.
"""

from __future__ import annotations

import uuid
from contextvars import ContextVar, Token
from dataclasses import dataclass, field

# Full list of SMART scopes required by SepsisGuard (spec §8).
REQUIRED_SCOPES = [
    {"name": "patient/Patient.rs", "required": True},
    {"name": "patient/Encounter.rs", "required": True},
    {"name": "patient/Observation.rs", "required": True},
    {"name": "patient/Condition.rs", "required": True},
    {"name": "patient/MedicationRequest.rs", "required": True},
    {"name": "patient/MedicationAdministration.rs", "required": True},
    {"name": "patient/AllergyIntolerance.rs", "required": True},
    {"name": "patient/DiagnosticReport.rs", "required": True},
    {"name": "patient/DocumentReference.rs", "required": True},
    {"name": "patient/Specimen.rs"},
    {"name": "patient/Procedure.rs"},
    {"name": "user/Task.c", "required": True},
    {"name": "user/Communication.c", "required": True},
    {"name": "user/DocumentReference.c", "required": True},
    {"name": "user/MedicationRequest.c"},
]


@dataclass
class SharpContext:
    patient_id: str
    fhir_base_url: str
    access_token: str
    scopes: frozenset[str]
    user: str | None = None
    intent: str | None = None
    trace_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    refresh_token: str | None = None
    refresh_url: str | None = None

    @classmethod
    def from_headers(
        cls,
        headers: dict[str, str],
        granted_scopes: list[str] | None = None,
    ) -> SharpContext:
        def h(key: str) -> str | None:
            return headers.get(key) or headers.get(key.lower())

        patient_id = h("X-Patient-ID") or ""
        fhir_base_url = h("X-FHIR-Server-URL") or ""
        access_token = h("X-FHIR-Access-Token") or ""
        refresh_token = h("X-FHIR-Refresh-Token")
        refresh_url = h("X-FHIR-Refresh-Url")
        trace_id = h("X-Trace-ID") or str(uuid.uuid4())
        scopes = frozenset(granted_scopes or [])

        return cls(
            patient_id=patient_id,
            fhir_base_url=fhir_base_url,
            access_token=access_token,
            scopes=scopes,
            trace_id=trace_id,
            refresh_token=refresh_token,
            refresh_url=refresh_url,
        )


_current: ContextVar[SharpContext | None] = ContextVar(
    "_current_sharp_context", default=None
)


def current_sharp_context() -> SharpContext:
    ctx = _current.get()
    if ctx is None:
        raise RuntimeError(
            "No SHARP context bound. Call bind_sharp_context() before invoking tools."
        )
    return ctx


def bind_sharp_context(ctx: SharpContext) -> Token[SharpContext | None]:
    return _current.set(ctx)


def reset_sharp_context(token: Token[SharpContext | None]) -> None:
    _current.reset(token)


def require_scope(scope: str) -> SharpContext:
    """Return the current context if *scope* is granted; raise PermissionError otherwise."""
    ctx = current_sharp_context()
    if scope not in ctx.scopes:
        raise PermissionError(f"Scope not granted: {scope}")
    return ctx
