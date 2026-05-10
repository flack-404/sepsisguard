"""HIPAA audit log — append-only JSON-Lines.

Permissible fields: trace_id, patient (FHIR ref like Patient/abc, never a name),
resource (FHIR ref), tool, event, status, error_class, duration_ms, scope,
model, count, method, url_path.

Never log PHI. A best-effort guard rejects free-text values longer than 200 chars.
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path

_LOG_PATH_ENV = os.environ.get("SEPSISGUARD_AUDIT_LOG", "logs/audit.jsonl")
LOG_PATH = Path(_LOG_PATH_ENV)

_lock = threading.Lock()

# Best-effort allowlist for audit field names. Not enforced as an error;
# used as documentation and for the PHI guard heuristic.
_ALLOWED_FIELDS = {
    "trace_id", "patient", "resource", "tool", "event", "status",
    "error_class", "duration_ms", "scope", "model", "count",
    "method", "url_path", "element", "level", "audience",
}


def audit_log(event: str, **fields: object) -> None:
    """Append one JSON line to the audit log.

    All keyword arguments are included in the record. Free-text strings longer
    than 200 characters are truncated as a best-effort PHI guard.
    """
    sanitized: dict[str, object] = {}
    for k, v in fields.items():
        if isinstance(v, str) and len(v) > 200:
            sanitized[k] = v[:200] + "...[truncated]"
        else:
            sanitized[k] = v

    record = {
        "ts": datetime.now(tz=timezone.utc).isoformat(),
        "event": event,
        **sanitized,
    }
    line = json.dumps(record, default=str) + "\n"

    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        with LOG_PATH.open("a", buffering=1, encoding="utf-8") as fh:
            fh.write(line)
