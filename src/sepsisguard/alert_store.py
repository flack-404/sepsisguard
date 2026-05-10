"""In-memory SepsisAlert store — process-local, no persistence.

One dict keyed by patient_id. Protected by asyncio.Lock for coroutine safety.
This is intentionally process-local (same shape as AuthBridge's submission_store).
On process restart all alerts are lost; the FHIR record is the system of record.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class SepsisAlert:
    patient_id: str
    trigger_criteria: list[str]
    time_zero_candidate: datetime | None
    screening_packet: dict[str, Any]
    created_at: datetime = field(default_factory=lambda: datetime.now(tz=timezone.utc))


class _AlertStore:
    def __init__(self) -> None:
        self._store: dict[str, SepsisAlert] = {}
        self._lock = asyncio.Lock()

    async def record_alert(self, alert: SepsisAlert) -> None:
        """Insert or replace the alert for the given patient."""
        async with self._lock:
            self._store[alert.patient_id] = alert

    async def get(self, patient_id: str) -> SepsisAlert | None:
        """Return the current alert for *patient_id*, or None."""
        async with self._lock:
            return self._store.get(patient_id)

    async def set_time_zero(self, patient_id: str, ts: datetime) -> None:
        """Update time_zero_candidate for an existing alert.

        Silently no-ops if no alert exists for the patient.
        """
        async with self._lock:
            alert = self._store.get(patient_id)
            if alert is not None:
                alert.time_zero_candidate = ts

    async def clear(self, patient_id: str) -> None:
        """Remove the alert for *patient_id* (e.g., after bundle completion)."""
        async with self._lock:
            self._store.pop(patient_id, None)

    async def all_patient_ids(self) -> list[str]:
        """Return a snapshot of all patient IDs with active alerts."""
        async with self._lock:
            return list(self._store.keys())


# Module-level singleton — import and use directly.
alert_store = _AlertStore()
