# HIPAA Compliance

SepsisGuard is designed to operate as a HIPAA Business Associate within a covered entity's clinical workflow. This document maps the service's design to the HIPAA Security Rule (45 CFR §164.312).

## §164.312(a) Access Control

- **SHARP context propagation.** Every tool call binds a `SharpContext` from the `X-FHIR-Server-URL`, `X-FHIR-Access-Token`, `X-Patient-ID` headers issued by the Prompt Opinion platform's SMART-launched session. The patient ID and access token are scoped to the launching clinician's session; SepsisGuard does not maintain its own user database or credential store.
- **Scope enforcement per tool.** Each FHIR read uses `require_scope(f"patient/{Type}.rs")`; each write uses `require_scope(f"user/{Type}.c")`. Missing scopes raise `PermissionError`, which the MCP server converts to a JSON-RPC error.
- **Required SMART scopes** (15 total, declared in `/.well-known/agent-card.json`):
  - 9 read scopes: `patient/Patient.rs`, `patient/Encounter.rs`, `patient/Observation.rs`, `patient/Condition.rs`, `patient/MedicationRequest.rs`, `patient/MedicationAdministration.rs`, `patient/AllergyIntolerance.rs`, `patient/DiagnosticReport.rs`, `patient/DocumentReference.rs`
  - 2 optional reads: `patient/Specimen.rs`, `patient/Procedure.rs`
  - 4 write scopes: `user/Task.c`, `user/Communication.c`, `user/DocumentReference.c`, `user/MedicationRequest.c` (optional)

## §164.312(b) Audit Controls

- **Append-only JSON-Lines audit log** at `logs/audit.jsonl` (configurable via `SEPSISGUARD_AUDIT_LOG`).
- **PHI is never logged.** Each entry contains references (`Patient/abc-123`), event names, trace IDs, durations, status codes, and resource type names — never patient names, MRNs, DOBs, addresses, or clinical values.
- **Best-effort PHI guard.** Free-text values longer than 200 chars are truncated as a defensive measure.
- **Per-event records** for every FHIR I/O (`fhir.read`, `fhir.search`, `fhir.create`), tool invocation (`tool.<name>`), agent iteration (`agent.tool_call`, `agent.start`, `agent.end`), and MCP/A2A request (`mcp.request`, `a2a.request`).

## §164.312(c) Integrity

- **Stateless service.** SepsisGuard does not persist patient state. The in-memory `alert_store` is process-local and used only to coordinate within a single agent run; it is not durable across requests or restarts.
- **FHIR is the system of record.** All writes go to the customer's FHIR server (FHIR Tasks, Communications, DocumentReferences). Reads always re-fetch from FHIR — there is no caching layer that could go stale.
- **Hashes implicit in FHIR `versionId`.** Subsequent reads include the FHIR-server-assigned version, allowing optimistic concurrency at the customer's discretion.

## §164.312(d) Person or Entity Authentication

- **Trusts the SMART launch.** Authentication is performed by the EHR's SMART-on-FHIR authorization server; SepsisGuard receives a `Bearer` access token already scoped to the clinician's identity and the patient context.
- **Token validation deferred to the FHIR server.** The token is passed through to the customer's FHIR server, which validates it on every call. SepsisGuard never decodes the token claims itself.
- **No long-lived secrets in the service.** The only persistent credential is the Anthropic API key used for Claude inference — that key has no PHI access and is not bound to any patient.

## §164.312(e) Transmission Security

- **TLS 1.2+ on all transports.** Railway-issued HTTPS certificates protect the public `/mcp`, `/a2a`, and `/.well-known/agent-card.json` endpoints.
- **All FHIR calls use HTTPS.** The `FhirClient` connects to the customer's FHIR endpoint at the URL passed in `X-FHIR-Server-URL`; HTTP is rejected by httpx with default settings.
- **No PHI in URLs.** All PHI is in the request body, not the URL path or query string.

## Minimum Necessary

Each tool requests only the scopes it needs. For example:
- `screen_sepsis_signals` reads Observation, Condition, MedicationRequest, DocumentReference, DiagnosticReport — no writes.
- `drive_bundle_element` requires only `user/Task.c` — does not request `user/MedicationRequest.c` even when driving the antibiotic element (the antibiotic order itself is a separate clinician action).
- `recommend_antibiotic` requires `patient/AllergyIntolerance.rs` plus latest Observation reads — does not request Conditions or DocumentReferences.

## Business Associate / Subprocessor

SepsisGuard's reliance on the Anthropic API for Claude inference makes Anthropic a subprocessor. Customers deploying SepsisGuard should:

1. Sign a BAA directly with Anthropic (offered for enterprise plans).
2. Verify that PHI sent to Claude is minimal — SepsisGuard tools send FHIR resource refs + extracted clinical values (e.g., "lactate 3.2 mmol/L @ 2026-05-10T14:55Z [Observation/lab-lactate-initial]"), never patient names or other direct identifiers.
3. Configure `ANTHROPIC_API_KEY` to point at the BAA-covered Anthropic account.

## What SepsisGuard does NOT do

- It does not store PHI. The in-memory alert store is intentionally process-local.
- It does not log PHI. The audit log holds references, not values.
- It does not auto-administer medications. All antibiotic recommendations are drafts requiring clinician sign-off (enforced by always returning `needs_clinician_signoff: true`).
- It does not bypass the FHIR server. Every read and write is RESTful FHIR R4.
- It does not invent FHIR resources. All claims in the drafted progress note cite a FHIR resource ID.
