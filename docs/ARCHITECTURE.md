# SepsisGuard Architecture

> One Python service. Three deployable artifacts. Five logical agents. Seven MCP tools.

## High level

```
                        ┌──────────────────────────┐
                        │  EHR (SMART on FHIR)     │
                        │  Subscription resource   │
                        └────────────┬─────────────┘
                                     │ streams Observations
                                     ▼
                ┌─────────────────────────────────────┐
                │     Prompt Opinion Platform          │
                │   - SHARP context bridge             │
                │   - A2A v1 message routing           │
                │   - Workspace FHIR server            │
                │   - General Chat Agent (Gemini)      │
                └─────────────────────┬───────────────┘
                                      │ X-FHIR-* headers
                                      │ MCP / A2A v1 JSON-RPC
                                      ▼
   ┌─────────────────────────────────────────────────────────────┐
   │             SepsisGuard A2A Agent (Sentinel)                │
   │                                                             │
   │   Skill: continuous_sepsis_monitoring                       │
   │   Skill: bundle_execution                                   │
   │   Skill: bundle_audit_review                                │
   │                                                             │
   │   Internal coordination (in-process subagents):             │
   │   ┌───────────────┐  ┌──────────────┐  ┌────────────────┐   │
   │   │   Sentinel    │  │  Adjudicator │  │    Bundle      │   │
   │   │  (detector)   │→ │  (confirmer) │→ │  Orchestrator  │   │
   │   └───────────────┘  └──────────────┘  └───┬────────────┘   │
   │                                            │                │
   │                    ┌───────────────────────┼─────────┐      │
   │                    ▼                       ▼         ▼      │
   │            ┌───────────────┐  ┌────────────────┐  ┌──────┐  │
   │            │  Pharmacist   │  │ Documentation  │  │Family│  │
   │            │  (abx pick)   │  │  (chart note)  │  │ A2A  │  │
   │            └───────────────┘  └────────────────┘  └──────┘  │
   │                                                             │
   │  SepsisGuard MCP Server (7 tools at /mcp)                   │
   │     1. screen_sepsis_signals                                │
   │     2. confirm_sepsis_diagnosis                             │
   │     3. score_bundle_compliance                              │
   │     4. recommend_antibiotic                                 │
   │     5. drive_bundle_element                                 │
   │     6. draft_sep1_documentation                             │
   │     7. notify_care_team                                     │
   └─────────────────────────────────────────────────────────────┘
                                      │
                                      ▼ POST/GET FHIR R4
                ┌──────────────────────────┐
                │  Prompt Opinion FHIR     │
                │  (workspace FHIR server) │
                └──────────────────────────┘
```

## Three deployable artifacts

1. **MCP Server** — Python + FastAPI exposing 7 tools at `POST /mcp`. Speaks JSON-RPC 2.0 with `tools/list`, `tools/call`, and `agent/run`. Auto-binds SHARP context from `X-FHIR-*` request headers.
2. **A2A v1 Agent Card** served at `GET /.well-known/agent-card.json`. Declares 3 skills + the `ai.promptopinion/fhir-context` extension with all 15 SMART scopes.
3. **BYO Agent on Prompt Opinion** ("SepsisGuard ICU Co-Pilot") configured against the MCP endpoint, with Gemini (platform default) or Claude as the orchestrator.

## Five logical agents

All five run in the same Python process and share the per-request SHARP context. They are *logical* roles — each is the focus of a different system prompt or tool — not separate services.

| # | Agent | Tool(s) | Role |
|---|---|---|---|
| 1 | **Sentinel** | `screen_sepsis_signals` | FHIR walk: SIRS / qSOFA / free-text triggers / infection evidence |
| 2 | **Adjudicator** | `confirm_sepsis_diagnosis` | Claude reasoning over screening packet; sets Time Zero; rules out benign alternatives |
| 3 | **Bundle Orchestrator** | `score_bundle_compliance`, `drive_bundle_element`, `notify_care_team` | Drives 3-hr / 6-hr elements to completion; creates FHIR Tasks; pages care team |
| 4 | **Pharmacist** | `recommend_antibiotic` | Claude + antibiogram + AllergyIntolerance/eGFR → draft regimen with guideline citations |
| 5 | **Documentation** | `draft_sep1_documentation` | Claude + cached CMS abstractor rubric → CMS-abstractor-grade progress note |

## Default trajectory

```
screen_sepsis_signals
    │
    ├── recommendation == "no_sepsis_signal" → STOP
    │
    ▼
confirm_sepsis_diagnosis(screening_packet)
    │
    ├── classification in (sepsis_likely_benign_alternative, insufficient_data) → STOP
    │
    ▼
score_bundle_compliance(time_zero)
    │
    ▼
recommend_antibiotic(suspected_source)
    │
    ▼
For each scheduled element:
    drive_bundle_element(element, deadline, role)
    │
    ▼
notify_care_team(level, audience, subject, body, linked_resources)
    │
    ▼
draft_sep1_documentation(diagnosis, bundle, antibiotic_choice)
```

Hard rules enforced in the orchestrator prompt (`agent/agent_prompt.md`):

- Never fabricate vitals, labs, or timestamps — every claim must trace to a tool result.
- Never auto-administer medications — antibiotic recommendations are drafts requiring clinician sign-off.
- No PHI in conversational output — refer to "the patient".
- Halt on `insufficient_data` — never speculate.
- `notify_care_team` urgent on missed deadlines; continue driving remaining elements.

## Two cross-cutting concerns

### SHARP context propagation

Per-request `ContextVar` carries `patient_id`, `fhir_base_url`, `access_token`, and granted scopes through every async hop. Tools read it via `current_sharp_context()` — no threading args. Bound in the FastAPI handler from `X-FHIR-Server-URL` / `X-FHIR-Access-Token` / `X-Patient-ID` headers; reset on response.

### Prompt caching strategy

All 3 Claude-backed tools and the agent loop use Anthropic prompt caching with `ttl="1h"` for stable content (system prompts + the CMS abstractor rubric). The agent loop strips `cache_control` from older `tool_result` blocks each turn — Anthropic enforces a max of 4 cache breakpoints per request. Observed cache hit ratio in production runs: **0.70–0.77**.

## Standards implemented

- **MCP** (Model Context Protocol) — JSON-RPC 2.0 with `initialize`, `tools/list`, `tools/call`, `agent/run`.
- **A2A v1** — JSON-RPC 2.0 message envelope, agent card, skill declaration, `fhir-context` extension.
- **SHARP-on-MCP** — `X-FHIR-*` header transport for FHIR session credentials.
- **FHIR R4** — reads Patient, Encounter, Observation, Condition, MedicationRequest/Administration, AllergyIntolerance, DiagnosticReport, DocumentReference, Specimen, Procedure; writes Task, Communication, DocumentReference.
- **CMS SEP-1** (Hospital VBP FY2026) — encoded in `sep1_definition.py` (criteria, deadlines, scoring math).
- **Surviving Sepsis Campaign 2021** — cited in antibiotic recommendations.
- **HIPAA 164.312** — references-only audit log, scope-enforced access, TLS in transit.
