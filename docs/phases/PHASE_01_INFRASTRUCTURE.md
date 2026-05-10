# Phase 1 — Shared Infrastructure

> **Goal:** Build the four cross-cutting modules every tool depends on: SHARP context, FHIR client, Claude client, and audit log.
> **Effort:** ~1–2 days for one engineer.

## Prerequisites

- Phase 0 (scaffold) merged. The `src/sepsisguard/` package directory exists.
- `requirements.txt` installed in a venv. `ANTHROPIC_API_KEY` available for ad-hoc smoke tests.

## Files to create

```
src/sepsisguard/
├── sharp_context.py     ← contextvar-based SHARP context (patient_id, FHIR creds, scopes)
├── fhir_client.py       ← async httpx FHIR R4 client bound to the SHARP context
├── claude_client.py     ← Anthropic AsyncAnthropic wrapper with prompt caching
└── audit.py             ← JSON-Lines audit logger (no PHI in log content)
```

## Spec sections to read first

- **§8** — SHARP-on-MCP integration: required HTTP headers, scopes, agent card.
- **§12 Pattern 1** — `sharp_context.py` API surface.
- **§12 Pattern 2** — `fhir_client.py` API surface.
- **§12 Pattern 3** — `claude_client.py` and the `temperature` deprecation rule.
- **§12 Pattern 4** — `audit.py` JSONL pattern.

## Task breakdown

### 1.1 `sharp_context.py`

- [ ] Define `SharpContext` dataclass with: `patient_id`, `fhir_base_url`, `access_token`, `scopes: frozenset[str]`, `user: str | None`, `intent: str | None`, `trace_id: str`, optional `refresh_token`, `refresh_url`.
- [ ] `SharpContext.from_headers(headers, granted_scopes=...)` constructor — reads `X-FHIR-Server-URL`, `X-FHIR-Access-Token`, `X-Patient-ID`, `X-FHIR-Refresh-Token`, `X-FHIR-Refresh-Url`. Generates `trace_id` if absent.
- [ ] Module-level `ContextVar[SharpContext | None]` named `_current`.
- [ ] `current_sharp_context() -> SharpContext` — raises `RuntimeError` if unset.
- [ ] `bind_sharp_context(ctx) -> Token` and `reset_sharp_context(token) -> None`.
- [ ] `require_scope(scope: str) -> SharpContext` — raises `PermissionError("Scope not granted: ...")` if not in `ctx.scopes`. Returns the context for chaining.
- [ ] `REQUIRED_SCOPES` list (15 entries from spec §8).

### 1.2 `fhir_client.py`

- [ ] `class FhirClient` — async context manager (`__aenter__`/`__aexit__`).
- [ ] On enter, reads `current_sharp_context()` to get `fhir_base_url` + `access_token`. Constructs an `httpx.AsyncClient` with `Authorization: Bearer <token>` and `Accept: application/fhir+json` headers.
- [ ] Methods:
  - `read(resource_type, id) -> dict`
  - `search(resource_type, params: dict) -> dict` (returns the searchset Bundle)
  - `create(resource: dict) -> dict` (POSTs to `/<resourceType>`, returns the response with assigned id)
  - `transaction(bundle: dict) -> dict` (POST to root with a transaction Bundle)
  - `patient_record(include: tuple[str, ...]) -> dict` (use `Patient/<id>/$everything` or fan-out searches; pick simplest that works for demo)
- [ ] Retry on `429` and `5xx` with exponential backoff (max 3 attempts).
- [ ] Parse `OperationOutcome` errors and raise a typed exception with the issue text.
- [ ] Audit-log every request with `audit_log("fhir.<verb>", trace_id=..., resource=..., status=...)`.
- [ ] **Scope check before each call:** read uses `require_scope("patient/<Type>.rs")`, write uses `require_scope("user/<Type>.c")`.

### 1.3 `claude_client.py`

- [ ] `class CacheableBlock` (dataclass): `text: str`, `cache: bool = False`, `ttl: Literal["5m", "1h"] = "5m"`.
- [ ] `class ClaudeResult` (dataclass): `text: str`, `input_tokens: int`, `output_tokens: int`, `cache_read_input_tokens: int`, `cache_creation_input_tokens: int`, `stop_reason: str`. Add a `cache_hit_ratio` property.
- [ ] `class ClaudeClient`:
  - Reads `ANTHROPIC_API_KEY` and `ANTHROPIC_MODEL` (default `claude-opus-4-7`) from env.
  - Holds an `AsyncAnthropic` client.
  - `async def generate(*, system_blocks, user_blocks, max_tokens, tools=None, messages=None) -> ClaudeResult`
    - Builds the `system=[{"type":"text","text":..., "cache_control": {"type":"ephemeral","ttl":"1h"}}]` array honoring the `cache` flag.
    - Builds `messages=[{"role":"user","content":[...]}]` from `user_blocks` unless `messages` is passed (used by agent loop).
    - **Does NOT pass `temperature`.** Spec §12 Pattern 3.
    - Returns `ClaudeResult` populated from `response.usage`.
- [ ] If `ANTHROPIC_API_KEY` is unset and `DEMO_MODE=true`, the client should be importable but `generate()` raises a clear `RuntimeError("ANTHROPIC_API_KEY not set; tool stub fallback should run instead")`. Tools handle the fallback (Phase 4).

### 1.4 `audit.py`

- [ ] `audit_log(event: str, **fields)` — appends one JSON line to `logs/audit.jsonl` with: `ts` (ISO 8601 UTC), `event`, all kwargs.
- [ ] `LOG_PATH` resolves from `SEPSISGUARD_AUDIT_LOG` env var, default `logs/audit.jsonl`.
- [ ] **Never log PHI.** Whitelist permissible fields in module-level documentation: `trace_id`, `patient` (FHIR ref like `Patient/abc`, NOT a name), `resource` (FHIR ref), `tool`, `event`, `status`, `error_class`, durations, scope names, model names. Reject if a kwarg looks like free text > 200 chars (best-effort guard).
- [ ] Append-only, line-buffered. No reads.

## Key patterns and gotchas

- **`temperature` is deprecated for `claude-opus-4-7`** — omit it from the Anthropic call. (CLAUDE.md, spec §12 Pattern 3.)
- **`from __future__ import annotations`** at the top of every file.
- **The 4-cache-breakpoint cap** is an agent-loop concern (Phase 5). Phase 1 just needs `cache: bool` on `CacheableBlock` and to set `cache_control` correctly when `cache=True`.
- **Audit log holds references, not values** — `audit_log(..., patient=ctx.patient_id)` is the form. Never log lab values, vitals, or note text.
- **FHIR auth header is exactly `Bearer <token>`.** The token comes from the SHARP context, never from env.
- **Don't write a refresh-token flow yet.** The spec lists it as optional; defer until Phase 5 if a tool actually 401s.

## Acceptance criteria

- [ ] `python -c "from sepsisguard.sharp_context import current_sharp_context, bind_sharp_context, SharpContext"` succeeds.
- [ ] `python -c "from sepsisguard.fhir_client import FhirClient"` succeeds.
- [ ] `python -c "from sepsisguard.claude_client import ClaudeClient, CacheableBlock"` succeeds.
- [ ] A unit test (write it as part of Phase 7, but smoke-check now): bind a fake context with one scope, call `require_scope` for that scope (should pass) and a different scope (should raise).
- [ ] `audit_log("test.event", trace_id="t1", patient="Patient/x")` writes a single JSON line to `logs/audit.jsonl`.

## Handoff to next phase

Phases 3 and 4 import these four modules everywhere. Make sure your public API matches what the spec's tool template (§13) calls — specifically:

```python
from ..sharp_context import current_sharp_context, require_scope
from ..fhir_client import FhirClient
from ..claude_client import CacheableBlock, ClaudeClient
from ..audit import audit_log
```

If you change an API name or signature, document it at the top of `PHASES.md` so the tool authors don't have to chase it.
