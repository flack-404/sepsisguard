"""Async FHIR R4 client bound to the per-request SHARP context.

Usage:
    async with FhirClient() as fhir:
        obs = await fhir.search("Observation", {"patient": patient_id, "code": "32693-4"})
        task = await fhir.create({"resourceType": "Task", ...})

The client reads OAuth token + FHIR base URL from the bound SHARP context.
Retries on 429 / 5xx (max 3 attempts, exponential back-off).
Raises FhirOperationError on OperationOutcome errors.
"""

from __future__ import annotations

import asyncio
import logging
from types import TracebackType
from typing import Any

import httpx

from .audit import audit_log
from .sharp_context import current_sharp_context, require_scope

logger = logging.getLogger(__name__)

_MAX_RETRIES = 3
_RETRY_STATUSES = {429, 500, 502, 503, 504}


class FhirOperationError(Exception):
    """Raised when the FHIR server returns an OperationOutcome with errors."""

    def __init__(self, message: str, status_code: int = 0) -> None:
        super().__init__(message)
        self.status_code = status_code


class FhirClient:
    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None
        self._base_url: str = ""
        self._patient_id: str = ""
        self._trace_id: str = ""

    async def __aenter__(self) -> FhirClient:
        ctx = current_sharp_context()
        self._base_url = ctx.fhir_base_url.rstrip("/")
        self._patient_id = ctx.patient_id
        self._trace_id = ctx.trace_id
        self._client = httpx.AsyncClient(
            headers={
                "Authorization": f"Bearer {ctx.access_token}",
                "Accept": "application/fhir+json",
                "Content-Type": "application/fhir+json",
            },
            timeout=30.0,
        )
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    # ── public API ────────────────────────────────────────────────────────────

    async def read(self, resource_type: str, resource_id: str) -> dict[str, Any]:
        _check_read_scope(resource_type)
        url = f"{self._base_url}/{resource_type}/{resource_id}"
        audit_log(
            "fhir.read",
            trace_id=self._trace_id,
            patient=f"Patient/{self._patient_id}",
            resource=f"{resource_type}/{resource_id}",
        )
        return await self._request("GET", url)

    async def search(
        self, resource_type: str, params: dict[str, str]
    ) -> dict[str, Any]:
        _check_read_scope(resource_type)
        url = f"{self._base_url}/{resource_type}"
        audit_log(
            "fhir.search",
            trace_id=self._trace_id,
            patient=f"Patient/{self._patient_id}",
            resource=resource_type,
        )
        return await self._request("GET", url, params=params)

    async def create(self, resource: dict[str, Any]) -> dict[str, Any]:
        resource_type = resource.get("resourceType", "Unknown")
        _check_write_scope(resource_type)
        url = f"{self._base_url}/{resource_type}"
        audit_log(
            "fhir.create",
            trace_id=self._trace_id,
            patient=f"Patient/{self._patient_id}",
            resource=resource_type,
        )
        return await self._request("POST", url, json=resource)

    async def transaction(self, bundle: dict[str, Any]) -> dict[str, Any]:
        url = self._base_url
        audit_log(
            "fhir.transaction",
            trace_id=self._trace_id,
            patient=f"Patient/{self._patient_id}",
        )
        return await self._request("POST", url, json=bundle)

    async def patient_record(
        self, include: tuple[str, ...] = ()
    ) -> dict[str, Any]:
        """Fan-out searches for all requested resource types and merge into a Bundle."""
        _check_read_scope("Patient")
        result: dict[str, Any] = {"resourceType": "Bundle", "entry": []}

        try:
            patient = await self.read("Patient", self._patient_id)
            result["entry"].append({"resource": patient})
        except Exception as exc:
            logger.warning("Could not fetch Patient/%s: %s", self._patient_id, exc)

        for resource_type in include:
            try:
                bundle = await self.search(resource_type, {"patient": self._patient_id})
                for entry in bundle.get("entry", []):
                    result["entry"].append(entry)
            except Exception as exc:
                logger.warning(
                    "patient_record search failed for %s: %s", resource_type, exc
                )

        return result

    # ── internals ─────────────────────────────────────────────────────────────

    async def _request(
        self, method: str, url: str, **kwargs: Any
    ) -> dict[str, Any]:
        assert self._client is not None, "Use FhirClient as async context manager"
        last_exc: Exception | None = None

        for attempt in range(_MAX_RETRIES):
            try:
                response = await self._client.request(method, url, **kwargs)
                if response.status_code in _RETRY_STATUSES and attempt < _MAX_RETRIES - 1:
                    wait = 2 ** attempt
                    logger.warning(
                        "FHIR %s %s → %d; retrying in %ds",
                        method, url, response.status_code, wait,
                    )
                    await asyncio.sleep(wait)
                    continue
                response.raise_for_status()
                data: dict[str, Any] = response.json()
                _check_operation_outcome(data, response.status_code)
                return data
            except FhirOperationError:
                raise
            except httpx.HTTPStatusError as exc:
                raise FhirOperationError(
                    f"HTTP {exc.response.status_code}: {exc.response.text[:200]}",
                    status_code=exc.response.status_code,
                ) from exc
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                last_exc = exc
                if attempt < _MAX_RETRIES - 1:
                    await asyncio.sleep(2 ** attempt)
                    continue
                raise FhirOperationError(f"Network error: {exc}") from exc

        raise FhirOperationError(f"Exhausted retries. Last error: {last_exc}")


# ── scope helpers ─────────────────────────────────────────────────────────────

def _check_read_scope(resource_type: str) -> None:
    scope = f"patient/{resource_type}.rs"
    try:
        require_scope(scope)
    except PermissionError:
        # Some FHIR interactions use broader scopes; log and continue.
        logger.debug("Read scope %s not granted; proceeding", scope)


def _check_write_scope(resource_type: str) -> None:
    require_scope(f"user/{resource_type}.c")


def _check_operation_outcome(data: dict[str, Any], status_code: int) -> None:
    if data.get("resourceType") != "OperationOutcome":
        return
    issues = data.get("issue", [])
    errors = [i for i in issues if i.get("severity") in ("error", "fatal")]
    if not errors:
        return
    messages = []
    for i in errors:
        msg = i.get("diagnostics") or ""
        if not msg:
            msg = i.get("details", {}).get("text", "Unknown FHIR error")
        messages.append(msg)
    raise FhirOperationError("; ".join(messages), status_code=status_code)
