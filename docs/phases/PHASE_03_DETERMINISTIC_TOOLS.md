# Phase 3 — Deterministic MCP Tools

> **Goal:** Implement the four MCP tools that don't call Claude — pure FHIR queries, scoring math, and FHIR resource creation.
> **Effort:** ~1–2 days. Can be split with Phase 4 if two people are working in parallel.

These tools are the cheapest to verify (no LLM cost, deterministic outputs). The spec author specifically recommends building from `screen_sepsis_signals` outward — get the FHIR plumbing right before tackling Claude-backed tools.

## Prerequisites

- Phase 1 (infrastructure) merged.
- Phase 2 (domain layer) merged.

## Files to create

```
src/sepsisguard/tools/
├── screen_signals.py            ← tool 1: screen_sepsis_signals
├── score_bundle.py              ← tool 3: score_bundle_compliance
├── drive_bundle_element.py      ← tool 5: drive_bundle_element
└── notify_care_team.py          ← tool 7: notify_care_team
```

Also update `src/sepsisguard/tools/__init__.py` to register these in `TOOL_REGISTRY`.

## Spec sections to read first

- **§7** — schemas + return shapes for tools 1, 3, 5, 7.
- **§13** — full code template (the one tool shown is `confirm_diagnosis`, but the file structure applies).
- **§9** — FHIR resource columns (Read vs Write).

## Task breakdown

### 3.1 `screen_signals.py` — tool 1

Pure FHIR walk + deterministic scoring. **No Claude call.**

- [ ] Export `SCREEN_SEPSIS_SIGNALS_SCHEMA` (paste from spec §7 Tool 1).
- [ ] `async def screen_sepsis_signals(*, lookback_hours: int = 24) -> dict`:
  1. `ctx = current_sharp_context()`; `audit_log("tool.screen_sepsis_signals", ...)`.
  2. With `FhirClient()`, search:
     - `Observation?patient=<id>&category=vital-signs&date=ge<window_start>&_sort=-date`
     - `Observation?patient=<id>&category=laboratory&date=ge<window_start>&_sort=-date`
     - `DocumentReference?patient=<id>&category=clinical-note&date=ge<window_start>` (filter to nursing notes by `type` if available)
     - `DiagnosticReport?patient=<id>&category=micro-bact&date=ge<window_start>`
     - `Condition?patient=<id>&clinical-status=active`
     - `MedicationRequest?patient=<id>&status=active`
  3. Pass observations into `evaluate_sirs` and `evaluate_organ_dysfunction` from `sep1_definition`.
  4. **Free-text triggers:** scan `DocumentReference` content (decoded base64 if needed) and `DiagnosticReport.conclusion` for keywords: `mottled`, `decreased urine output`, `unwell`, `lethargic`, `altered mental status`, `gram-negative`, `gram-positive`, `septic`, `consolidation`, `cloudy urine`, `sediment`. Return matched snippets (≤200 chars each) as `{source: "DocumentReference/abc", snippet: "..."}`.
  5. **Infection evidence:** active Conditions whose code is in a known infection set (pneumonia, UTI, cellulitis, intra-abdominal infection, bacteremia) OR active antibiotic MedicationRequests.
  6. Compute `recommendation`:
     - `no_sepsis_signal` if SIRS count_met < 2 AND no organ dysfunction AND no free-text trigger.
     - `needs_more_data` if signals exist but data is sparse (e.g., no recent labs).
     - `proceed_to_adjudication` otherwise.
  7. `screening_score_4`: `int(sirs_count_met >= 2) + int(any_organ_dysfunction) + int(any_free_text_trigger) + int(any_infection_evidence)`.
  8. Return the dict shape from spec §7 Tool 1.

- [ ] **Do not include patient name, MRN, or DOB in the return value.** Snippets must reference FHIR resources, not patient identifiers.

### 3.2 `score_bundle.py` — tool 3

Thin wrapper around `sep1_definition.score_bundle`.

- [ ] Export `SCORE_BUNDLE_COMPLIANCE_SCHEMA` from spec §7 Tool 3.
- [ ] `async def score_bundle_compliance(*, time_zero: str, as_of: str | None = None) -> dict`:
  1. Parse `time_zero` (ISO 8601). Default `as_of = datetime.now(tz=UTC)`.
  2. Use `FhirClient.patient_record(include=("Observation","MedicationRequest","MedicationAdministration","DiagnosticReport","Specimen","DocumentReference"))` to fetch the relevant slice from Time Zero - 6h forward.
  3. Get patient weight: search `Observation?patient=<id>&code=29463-7&_sort=-date&_count=1`. Default to 80 kg if missing.
  4. Call `score_bundle(time_zero, as_of, fhir_record, weight_kg)`.
  5. Add a top-level `next_at_risk_element` field (scan elements for the soonest deadline that's not yet `met`).
  6. Return.

### 3.3 `drive_bundle_element.py` — tool 5

Creates a FHIR Task. **Write tool — requires `user/Task.c` scope.**

- [ ] Export `DRIVE_BUNDLE_ELEMENT_SCHEMA` from spec §7 Tool 5.
- [ ] `async def drive_bundle_element(*, element: str, deadline: str, assigned_role: str, details: str | None = None) -> dict`:
  1. `ctx = require_scope("user/Task.c")`; audit log.
  2. Build a Task resource:
     ```python
     {
       "resourceType": "Task",
       "status": "requested",
       "intent": "order",
       "priority": "urgent" if element in {"broad_spectrum_antibiotics","fluid_resuscitation","vasopressors"} else "routine",
       "code": {"text": f"SEP-1: {element}"},
       "description": details or _default_description(element),
       "for": {"reference": f"Patient/{ctx.patient_id}"},
       "authoredOn": now_iso(),
       "executionPeriod": {"end": deadline},
       "requester": {"display": "SepsisGuard"},
       "owner": {"display": _role_display(assigned_role)},
       "reasonCode": {"text": f"CMS SEP-1 bundle element {element}"},
     }
     ```
  3. POST via `FhirClient().create(task)`.
  4. Return `{task_ref: f"Task/{response['id']}", element, deadline, assigned_role, status: "requested"}`.
- [ ] `_default_description` map: lactate_initial → "Draw serum lactate", blood_cultures → "Obtain blood culture set ×2", broad_spectrum_antibiotics → "Administer ordered broad-spectrum antibiotic", fluid_resuscitation → "Initiate 30 mL/kg crystalloid bolus", vasopressors → "Initiate vasopressor titration to MAP ≥ 65", repeat_lactate → "Repeat serum lactate", volume_reassessment → "Document focused volume status assessment".
- [ ] `_role_display` map: nurse → "Bedside RN", pharmacist → "Pharmacist", rrt → "Rapid Response Team", physician → "Attending physician", respiratory_therapist → "Respiratory Therapist".

### 3.4 `notify_care_team.py` — tool 7

Creates a FHIR Communication. **Write tool — requires `user/Communication.c` scope.**

- [ ] Export `NOTIFY_CARE_TEAM_SCHEMA` from spec §7 Tool 7.
- [ ] `async def notify_care_team(*, level: str, audience: list[str], subject: str, body: str, linked_resources: list[str] | None = None) -> dict`:
  1. `ctx = require_scope("user/Communication.c")`; audit log.
  2. Build a Communication resource:
     ```python
     {
       "resourceType": "Communication",
       "status": "completed",
       "priority": _level_to_priority(level),  # info/advisory→routine, urgent→urgent, stat→stat
       "category": [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/communication-category", "code": "alert"}]}],
       "subject": {"reference": f"Patient/{ctx.patient_id}"},
       "sent": now_iso(),
       "sender": {"display": "SepsisGuard"},
       "recipient": [{"display": role} for role in audience],
       "topic": {"text": subject},
       "payload": [{"contentString": body}],
       "about": [{"reference": ref} for ref in (linked_resources or [])],
     }
     ```
  3. POST via `FhirClient().create(comm)`.
  4. Return `{communication_ref: f"Communication/{response['id']}", level, audience, sent_at: ...}`.

### 3.5 Update `tools/__init__.py`

```python
from .screen_signals import SCREEN_SEPSIS_SIGNALS_SCHEMA, screen_sepsis_signals
from .score_bundle import SCORE_BUNDLE_COMPLIANCE_SCHEMA, score_bundle_compliance
from .drive_bundle_element import DRIVE_BUNDLE_ELEMENT_SCHEMA, drive_bundle_element
from .notify_care_team import NOTIFY_CARE_TEAM_SCHEMA, notify_care_team

TOOL_REGISTRY = {
    "screen_sepsis_signals":     (SCREEN_SEPSIS_SIGNALS_SCHEMA, screen_sepsis_signals),
    "score_bundle_compliance":   (SCORE_BUNDLE_COMPLIANCE_SCHEMA, score_bundle_compliance),
    "drive_bundle_element":      (DRIVE_BUNDLE_ELEMENT_SCHEMA, drive_bundle_element),
    "notify_care_team":          (NOTIFY_CARE_TEAM_SCHEMA, notify_care_team),
}
```

Phase 4 will add three more entries.

## Key patterns and gotchas

- **Scope-check before every FHIR call.** `FhirClient` should already do this (Phase 1), but double-check the writes here.
- **No client-supplied `id`** on FHIR creates. POST-only. Spec §17 calls this out for upload bundles; same rule applies at runtime.
- **DocumentReference content is base64-encoded.** When scanning notes for free-text triggers, decode `content[0].attachment.data`. Some FHIR servers serve `contentString` directly under `content[0].attachment.url` — handle both.
- **`patient` search param:** some FHIR servers require `patient=Patient/<id>`, others accept `patient=<id>`. Try `subject=Patient/<id>` as a fallback. Pick what the demo FHIR mock returns and document it.
- **Don't add a Claude call here.** If you find yourself wanting to "ask Claude to summarize the snippets," stop — that's tool 2 (`confirm_sepsis_diagnosis`) territory.
- **Free-text trigger detection is intentionally simple keyword matching.** It's a heuristic, not the source of truth — tool 2 reads the actual text and decides.
- **Time math always in UTC.** Convert `time_zero` to UTC on entry; emit ISO 8601 with `Z` suffix.

## Acceptance criteria

- [ ] All four tools importable from `sepsisguard.tools`.
- [ ] `TOOL_REGISTRY` has 4 entries (3 more come in Phase 4).
- [ ] Hand-call each tool from a Python REPL with a stubbed `FhirClient` (use Phase 6's mock if Phase 6 is partway done — otherwise mock manually) and validate the return matches the spec §7 shape.
- [ ] Audit log shows one entry per tool call with `trace_id` and `patient` ref.
- [ ] No LLM calls anywhere in this phase. `grep -r "ClaudeClient\|claude_client" src/sepsisguard/tools/screen_signals.py src/sepsisguard/tools/score_bundle.py src/sepsisguard/tools/drive_bundle_element.py src/sepsisguard/tools/notify_care_team.py` returns nothing.

## Handoff to next phase

Phases 4 and 5 read `TOOL_REGISTRY` directly. Don't change its name or shape. The agent loop (Phase 5) does:

```python
from sepsisguard.tools import TOOL_REGISTRY
schemas = [s for s, _ in TOOL_REGISTRY.values()]
result = await TOOL_REGISTRY[name][1](**args)
```

If you add helper modules under `tools/`, prefix them with `_` so the registry import stays clean.
