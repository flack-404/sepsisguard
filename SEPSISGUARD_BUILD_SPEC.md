# SepsisGuard — Complete Build Specification

> **Purpose of this document:** An exhaustive engineering spec sufficient for a fresh AI agent (or developer) to build SepsisGuard end-to-end with zero prior context. Every architectural decision, file path, code pattern, FHIR resource, demo scenario, and deployment step is documented here. Intended audience: an LLM agent like Claude Code, given full filesystem write access, asked to build the project from scratch.

**Project name:** SepsisGuard
**Purpose:** Multi-agent FHIR-native system that detects emerging sepsis early, executes the CMS SEP-1 bundle, and produces CMS-abstractor-ready documentation in real time.
**Hackathon target:** Agents Assemble — The Healthcare AI Endgame, Prompt Opinion / Darena Health, deadline May 12, 2026.
**License:** Apache 2.0
**Stack:** Python 3.10+, FastAPI, Anthropic Claude API (claude-opus-4-7), FHIR R4, MCP (Model Context Protocol), A2A v1.0 (Agent-to-Agent Protocol)

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Problem and Impact](#2-problem-and-impact)
3. [Why Generative AI](#3-why-generative-ai)
4. [Architecture Overview](#4-architecture-overview)
5. [SEP-1 Bundle Definition](#5-sep-1-bundle-definition)
6. [Multi-Agent Decomposition](#6-multi-agent-decomposition)
7. [The 7 MCP Tools](#7-the-7-mcp-tools)
8. [SHARP-on-MCP Integration](#8-sharp-on-mcp-integration)
9. [FHIR Resources](#9-fhir-resources)
10. [Demo Scenarios](#10-demo-scenarios)
11. [Project File Structure](#11-project-file-structure)
12. [Code Templates and Patterns](#12-code-templates-and-patterns)
13. [Implementation: Tool-by-Tool](#13-implementation-tool-by-tool)
14. [Agent Loop](#14-agent-loop)
15. [Server / Transport Layer](#15-server-transport-layer)
16. [Demo Runner](#16-demo-runner)
17. [Deployment](#17-deployment)
18. [Testing Strategy](#18-testing-strategy)
19. [Submission Materials](#19-submission-materials)
20. [Demo Video Script](#20-demo-video-script)
21. [Step-by-Step Build Checklist](#21-step-by-step-build-checklist)

---

## 1. Executive Summary

SepsisGuard is the **Sepsis Bundle Co-Pilot for the ICU**. It is a multi-agent system that:

1. **Detects sepsis early** by reading both structured FHIR data (vitals, labs) and unstructured nursing notes / DiagnosticReports — closing the gap that has caused deployed sepsis-prediction models like the Epic Sepsis Model to miss two-thirds of cases (JAMA Internal Medicine, 2021).

2. **Executes the CMS SEP-1 bundle** in real time — driving lactate measurement, blood cultures before antibiotics, broad-spectrum antibiotics within 3 hours, 30 mL/kg crystalloid for hypotension, repeat lactate, and vasopressor titration. Each element gets a Task in the FHIR record.

3. **Drafts the CMS-abstractor documentation** — the chart note that determines whether the bundle "counts" for Hospital Value-Based Purchasing reimbursement.

4. **Drives clinical safety, not just alerting** — refuses to act on insufficient evidence, provides peer-to-peer-ready justification, hands off to the clinical team with structured A2A messages.

**The product** combines: a SHARP-on-MCP server (the **Superpower**, 7 tools) with an A2A v1 orchestrator agent (the **Superhero**) that the Prompt Opinion platform's General Chat Agent can consult for any patient in the workspace.

**Differentiation from AuthBridge:** AuthBridge solves administrative prior-authorization (cost, delays). SepsisGuard solves clinical bedside care (mortality, real-time). Different FHIR resources, different audience, zero overlap.

---

## 2. Problem and Impact

Use these numbers verbatim in pitch material — every one is sourced.

| Metric | Value | Source |
|--------|-------|--------|
| US sepsis deaths annually | **350,000** | CDC |
| US adult sepsis hospitalizations | 1.7 million | CDC |
| Total US hospital cost | **$60.0 billion (2022)** | AHRQ HCUP Statistical Brief 316 |
| Rank among US inpatient conditions by cost | **#1 most expensive** | AHRQ HCUP 2022 |
| Cost growth over two prior years | +$3.4B | Sepsis Alliance / AHRQ |
| Mortality increase per hour of antibiotic delay | **4–7%** | Surviving Sepsis Campaign 2021 |
| Epic Sepsis Model recall on external validation | **0.33** (missed 67% of cases) | Wong et al., JAMA Internal Med 2021 |
| Epic alert burden in same study | 18% of all admitted patients | Wong et al., JAMA Internal Med 2021 |
| SEP-1 inclusion in Hospital VBP | **FY2026** (active) | CMS Hospital IQR / VBP rules |

**Regulatory tailwind:** SEP-1 is now a **pay-for-performance** measure under Hospital Value-Based Purchasing. A hospital's compliance directly affects Medicare reimbursement. This makes SepsisGuard not just clinical software but **revenue-cycle infrastructure** — the strongest commercial story on the table.

---

## 3. Why Generative AI

A rule engine cannot build SepsisGuard. Specifically:

1. **Free-text signals.** The earliest sepsis signals live in nursing notes ("patient looks unwell, mottled skin, decreased urine output"), microbiology comments ("gram-negative rods on initial Gram stain"), and imaging impressions ("findings consistent with pneumonia, septic emboli not excluded"). The Epic Sepsis Model failed because it ignored these. An LLM reads them.

2. **Trajectory reasoning.** Whether a patient is *getting worse* requires comparing serial labs and vitals over hours, weighting the trend against baseline severity. This isn't an obvious rule — it's clinical reasoning.

3. **Bundle adjudication.** SEP-1 has dozens of failure modes ("hypotension was not persistent — only one reading", "lactate was drawn at 4hr but bundle clock started at 0hr"). Each requires reading multiple FHIR resources together with the timestamps and clinical context to decide "did this element count?"

4. **CMS-abstractor narrative.** The CMS abstractor scoring SEP-1 reads chart notes, not data fields. A note has to *say* "Bundle initiated at 14:32 in response to lactate of 4.1 and SBP 86 mmHg consistent with septic shock; antibiotics ordered as cefepime + vancomycin per institutional antibiogram; 30 mL/kg LR initiated, repeat lactate ordered at 16:32." Generating that prose from structured data is exactly what LLMs do.

5. **Step-down reasoning on improvement.** When does the agent stop driving the bundle? When the patient improves? Got transferred? Was de-escalated? These judgment calls don't reduce to a flowchart.

---

## 4. Architecture Overview

```
                        ┌──────────────────────────┐
                        │  EHR (SMART on FHIR)     │
                        │  Subscription resource   │
                        └────────────┬─────────────┘
                                     │ continuously streams
                                     │ Observation events
                                     ▼
                ┌─────────────────────────────────────┐
                │     Prompt Opinion Platform          │
                │   - SHARP context bridge             │
                │   - A2A v1 message routing           │
                │   - 5T deliverables surfacing        │
                └─────────────────────┬───────────────┘
                                      │ X-FHIR-* headers
                                      │ A2A message + metadata
                                      ▼
   ┌─────────────────────────────────────────────────────────────┐
   │             SepsisGuard A2A Agent (Sentinel)                │
   │                                                             │
   │   Skill: continuous_sepsis_monitoring                       │
   │   Skill: bundle_execution                                   │
   │   Skill: bundle_audit_review                                │
   │                                                             │
   │   Internal coordination (in-process A2A subagents):         │
   │   ┌───────────────┐  ┌──────────────┐  ┌────────────────┐  │
   │   │   Sentinel    │  │  Adjudicator │  │    Bundle      │  │
   │   │  (detector)   │→ │  (confirmer) │→ │  Orchestrator  │  │
   │   └───────────────┘  └──────────────┘  └───┬────────────┘  │
   │                                            │                │
   │                    ┌───────────────────────┼─────────┐      │
   │                    │                       │         │      │
   │                    ▼                       ▼         ▼      │
   │            ┌───────────────┐  ┌────────────────┐  ┌──────┐  │
   │            │  Pharmacist   │  │ Documentation  │  │Family│  │
   │            │   (abx pick)  │  │  (chart note)  │  │ A2A  │  │
   │            └───────────────┘  └────────────────┘  └──────┘  │
   │                                                             │
   │   uses ↓                                                    │
   │                                                             │
   │  SepsisGuard MCP Server (7 tools)                           │
   │     1. screen_sepsis_signals                                │
   │     2. confirm_sepsis_diagnosis                             │
   │     3. score_bundle_compliance                              │
   │     4. recommend_antibiotic                                 │
   │     5. drive_bundle_element                                 │
   │     6. draft_sep1_documentation                             │
   │     7. notify_care_team                                     │
   └─────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
                ┌──────────────────────────┐
                │  FHIR R4 server          │
                │   (Prompt Opinion        │
                │    workspace FHIR)       │
                └──────────────────────────┘
```

**Three deployable artifacts, same as AuthBridge:**

1. **MCP Server** (Python, FastAPI) — exposes 7 tools at `/mcp` and an A2A v1 endpoint at `/a2a`.
2. **A2A Agent Card** at `/.well-known/agent-card.json` — declares 3 skills + the `ai.promptopinion/fhir-context` extension.
3. **BYO Agent on Prompt Opinion** ("SepsisGuard ICU Co-Pilot") — uses our 7 MCP tools.

---

## 5. SEP-1 Bundle Definition

SEP-1 (CMS Severe Sepsis and Septic Shock Management Bundle) is the contract our agent has to satisfy. The bundle has **3-hour** and **6-hour** elements measured from "Time Zero" (the time severe sepsis was first identified, per CMS abstraction rules).

### 3-Hour Bundle Elements (must complete within 3 hours of Time Zero)

| Element | What | FHIR resource(s) |
|---------|------|---|
| **3a. Initial lactate** | Serum lactate level measured | Observation (LOINC 2524-7 or 32693-4) |
| **3b. Blood cultures before antibiotics** | At least one set of blood cultures collected before antibiotic administration | Specimen + DiagnosticReport |
| **3c. Broad-spectrum antibiotics** | At least one IV broad-spectrum antibiotic administered | MedicationAdministration |

### 6-Hour Bundle Elements (must complete within 6 hours of Time Zero)

| Element | What | FHIR resource(s) |
|---------|------|---|
| **6a. 30 mL/kg crystalloid** | If hypotension (SBP < 90 mmHg, MAP < 65, or lactate ≥ 4) — administer 30 mL/kg of IV crystalloid within 3 hours | MedicationAdministration (LR/NS) |
| **6b. Vasopressors** | If hypotension persists after fluid resuscitation — initiate vasopressors to maintain MAP ≥ 65 | MedicationAdministration (norepinephrine, etc.) |
| **6c. Repeat lactate** | If initial lactate > 2.0 mmol/L — remeasure within 6 hours | Observation |
| **6d. Volume status reassessment** | Documented physical exam or focused assessment after fluids | DocumentReference / Observation |

**Severe sepsis criteria (Time Zero triggers):**
- Suspected/documented infection
- ≥ 2 SIRS criteria (WBC, temp, HR, RR)
- ≥ 1 organ dysfunction sign (lactate > 2, SBP < 90, MAP < 65, creatinine ↑, INR ↑, bilirubin ↑, platelets ↓, AMS)

**Septic shock criteria:**
- Severe sepsis + persistent hypotension after 30 mL/kg fluid OR initial lactate ≥ 4

The **`policy_store` equivalent** (call it `sep1_definition.py`) encodes these criteria as data, exactly as `policy_store.py` did for AuthBridge's payer policies.

---

## 6. Multi-Agent Decomposition

Five logical agents, all coordinated by the top-level A2A skill. Each is a Claude tool-use loop with a focused system prompt, but they all live in the same Python process and share the SHARP context. Some implementations would split them into separate A2A external agents — for our hackathon scope, in-process is sufficient.

### Agent 1: Sentinel
- **Role:** Watches the cohort; flags potential sepsis triggers.
- **Input:** Stream of FHIR Observation events (vitals, labs).
- **Output:** A `SepsisAlert` object (patient_id, trigger_criteria, time_zero_candidate).
- **Tools used:** `screen_sepsis_signals`.
- **Termination:** Returns a list of patient_ids flagged for adjudication.

### Agent 2: Adjudicator
- **Role:** For each flagged patient, decides "Real sepsis or noise?"
- **Input:** patient_id + `SepsisAlert`.
- **Output:** Diagnosis confirmation (`severe_sepsis` | `septic_shock` | `not_sepsis` | `requires_clinician_review`) with a Time Zero timestamp.
- **Tools used:** `confirm_sepsis_diagnosis`.
- **Critical reasoning:** Must read DocumentReference (nursing notes), DiagnosticReport (microbiology, imaging), and Condition (existing infections). Must distinguish sepsis from non-sepsis SIRS (e.g., post-op fever).

### Agent 3: Bundle Orchestrator
- **Role:** Drives each SEP-1 bundle element to completion. Coordinates Pharmacist + Documentation subagents.
- **Input:** Confirmed sepsis + Time Zero.
- **Output:** Bundle compliance status for each element, structured as a Task per element.
- **Tools used:** `score_bundle_compliance`, `drive_bundle_element`, `notify_care_team`.

### Agent 4: Pharmacist
- **Role:** Recommends antibiotic regimen.
- **Input:** Suspected source (CAP, CAUTI, intra-abdominal, skin/soft tissue, unknown), patient allergies, renal function, local antibiogram.
- **Output:** Specific antibiotic + dose + route.
- **Tools used:** `recommend_antibiotic`.
- **Constraint:** ALWAYS draft for clinician sign-off. Never auto-administer.

### Agent 5: Documentation
- **Role:** Drafts the SEP-1 progress note that the CMS abstractor will read.
- **Input:** Confirmed sepsis + bundle compliance status + clinical narrative.
- **Output:** A FHIR DocumentReference (or Communication) with the prose note.
- **Tools used:** `draft_sep1_documentation`.

---

## 7. The 7 MCP Tools

Each tool follows the same pattern as AuthBridge: schema-validated input, SHARP-context-bound, audit-logged, single-purpose.

### Tool 1: `screen_sepsis_signals`

```python
SCREEN_SEPSIS_SIGNALS_SCHEMA = {
    "name": "screen_sepsis_signals",
    "description": (
        "Screen the SHARP-bound patient for potential sepsis signals over the "
        "specified lookback window. Returns SIRS criteria met, qSOFA score, "
        "organ dysfunction markers, and any free-text triggers detected in "
        "recent nursing notes / DiagnosticReports. Does NOT confirm sepsis — "
        "use confirm_sepsis_diagnosis next."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "lookback_hours": {
                "type": "integer",
                "default": 24,
                "minimum": 1,
                "maximum": 168,
            },
        },
        "additionalProperties": False,
    },
}
```

**Behavior:** Pulls from FHIR:
- Recent vitals (HR, BP, RR, temp, SpO2)
- Recent labs (WBC with diff, lactate, creatinine, INR, platelets, bilirubin)
- Mental status assessments
- Recent nursing notes (DocumentReference where category=nursing-note)
- Microbiology reports (DiagnosticReport where category=micro)

**Returns:**
```python
{
    "patient_ref": "Patient/...",
    "screening_window": {"start": "...", "end": "..."},
    "sirs_criteria": {
        "temp_abnormal": True,        # > 38°C or < 36°C
        "hr_elevated": True,          # > 90 bpm
        "rr_elevated": False,         # > 20 or PaCO2 < 32
        "wbc_abnormal": True,         # > 12K, < 4K, or > 10% bands
        "count_met": 3,
    },
    "qsofa_score": 2,                  # 0-3
    "organ_dysfunction_markers": [
        {"name": "elevated_lactate", "value": 3.2, "unit": "mmol/L", "time": "..."},
        {"name": "hypotension", "value": 86, "unit": "mmHg SBP", "time": "..."},
    ],
    "free_text_triggers": [
        {"source": "DocumentReference/nursing-note-1234",
         "snippet": "patient appears unwell, decreased urine output overnight..."}
    ],
    "infection_evidence": [
        {"source": "Condition/...", "display": "pneumonia, suspected"},
        {"source": "MedicationRequest/...", "display": "started cefepime 6h ago"},
    ],
    "recommendation": "proceed_to_adjudication" | "no_sepsis_signal" | "needs_more_data",
    "screening_score_4": 3,            # rough completeness score 0-4
}
```

### Tool 2: `confirm_sepsis_diagnosis`

```python
CONFIRM_SEPSIS_DIAGNOSIS_SCHEMA = {
    "name": "confirm_sepsis_diagnosis",
    "description": (
        "Adjudicate whether the screened signals constitute severe sepsis or "
        "septic shock per CMS SEP-1 definitions, OR are explained by an "
        "alternative cause. Returns diagnosis classification and Time Zero "
        "(the timestamp severe sepsis criteria were first met). Time Zero "
        "starts the 3-hour and 6-hour bundle clocks."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "screening_packet": {
                "type": "object",
                "description": "Full output of tool 1 (screen_sepsis_signals).",
            },
        },
        "required": ["screening_packet"],
        "additionalProperties": False,
    },
}
```

**Behavior:** Calls Claude with a strict adjudicator system prompt. Inputs: the screening packet + a cached ICU adjudication policy + recent imaging/micro reports.

**Returns:**
```python
{
    "classification": "severe_sepsis" | "septic_shock" | "sepsis_likely_benign_alternative" | "insufficient_data",
    "time_zero": "2026-05-10T14:32:00Z",   # ISO 8601, when severe sepsis criteria first met
    "time_zero_basis": "Lactate 3.2 + SBP 86 + WBC 18.4K + clinical concern documented in nursing note...",
    "infection_source_suspected": "pneumonia",  # or 'urinary' | 'intra_abdominal' | 'skin_soft_tissue' | 'unknown'
    "alternative_explanations_considered": ["post-op fever", "alcohol withdrawal", "..."],
    "alternative_explanations_ruled_out": True,
    "confidence": "high" | "medium" | "low",
    "next_action": "drive_bundle" | "monitor_recheck_in_2h" | "escalate_to_clinician",
    "telemetry": {"input_tokens": ..., "cache_hit_ratio": ...},
}
```

### Tool 3: `score_bundle_compliance`

```python
SCORE_BUNDLE_COMPLIANCE_SCHEMA = {
    "name": "score_bundle_compliance",
    "description": (
        "Compute the current SEP-1 bundle compliance status for a patient with "
        "a confirmed sepsis diagnosis. Walks the FHIR record from Time Zero "
        "forward and identifies which of the 3-hour and 6-hour bundle elements "
        "are met, in progress, or overdue."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "time_zero": {"type": "string", "description": "ISO 8601 timestamp"},
            "as_of": {"type": "string", "description": "ISO 8601; defaults to now"},
        },
        "required": ["time_zero"],
        "additionalProperties": False,
    },
}
```

**Returns:**
```python
{
    "time_zero": "2026-05-10T14:32:00Z",
    "as_of": "2026-05-10T16:15:00Z",
    "minutes_since_time_zero": 103,
    "elements": {
        "lactate_initial": {
            "status": "met",
            "fhir_ref": "Observation/lactate-1",
            "value": 3.2, "unit": "mmol/L",
            "completed_at": "2026-05-10T14:55:00Z",
            "deadline": "2026-05-10T17:32:00Z",
        },
        "blood_cultures_before_antibiotics": {
            "status": "met",
            "fhir_refs": ["DiagnosticReport/blood-cx-1"],
            "completed_at": "2026-05-10T14:48:00Z",
            "antibiotic_admin_after_cx": True,
        },
        "broad_spectrum_antibiotics": {
            "status": "in_progress",
            "fhir_ref": "MedicationRequest/cefepime-1",
            "ordered_at": "2026-05-10T15:10:00Z",
            "deadline": "2026-05-10T17:32:00Z",
            "minutes_until_deadline": 77,
        },
        "fluid_resuscitation_30ml_kg": {
            "status": "in_progress",
            "ml_administered": 1500,
            "ml_required": 2400,             # 30 mL/kg × 80 kg
            "deadline": "2026-05-10T17:32:00Z",
        },
        "vasopressors_if_persistent_hypotension": {
            "status": "not_yet_required",
            "rationale": "Patient not yet hypotensive after 1.5L fluid; reassess at 6hr mark",
        },
        "repeat_lactate": {
            "status": "scheduled",
            "due_by": "2026-05-10T20:32:00Z",
        },
        "volume_status_reassessment": {
            "status": "in_progress",
        },
    },
    "overall_compliance": "on_track" | "at_risk" | "non_compliant",
    "completed_count": 2,
    "total_required": 7,
    "next_at_risk_element": "broad_spectrum_antibiotics",
}
```

### Tool 4: `recommend_antibiotic`

```python
RECOMMEND_ANTIBIOTIC_SCHEMA = {
    "name": "recommend_antibiotic",
    "description": (
        "Recommend a broad-spectrum antibiotic regimen for the suspected "
        "infection source, accounting for patient allergies, renal function "
        "(eGFR), weight, and the local antibiogram. Output is a draft only "
        "— intended for clinician sign-off, never auto-administered."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "suspected_source": {
                "type": "string",
                "enum": ["pneumonia", "urinary", "intra_abdominal",
                         "skin_soft_tissue", "central_line", "unknown"],
            },
            "include_mrsa_coverage": {"type": "boolean", "default": True},
            "include_pseudomonas_coverage": {"type": "boolean", "default": True},
        },
        "required": ["suspected_source"],
        "additionalProperties": False,
    },
}
```

**Behavior:** Calls Claude with a stewardship system prompt. Reads patient AllergyIntolerance + recent eGFR + recent weight from FHIR. Cross-references a local antibiogram (cached JSON in `data/antibiogram/`).

**Returns:**
```python
{
    "primary_regimen": [
        {"medication": "cefepime", "dose": "2 g", "frequency": "q8h",
         "route": "IV", "rxnorm": "203843",
         "renal_adjustment_note": "Patient eGFR 65 — standard dosing; reassess if eGFR < 50"},
        {"medication": "vancomycin", "dose": "loading 25 mg/kg, then per pharmacy",
         "route": "IV", "rxnorm": "11124"},
    ],
    "rationale": "Broad gram-negative coverage including Pseudomonas plus MRSA coverage; suspected pneumonia source.",
    "contraindications_checked": [
        {"allergen": "penicillin", "severity": "anaphylaxis", "decision": "Avoid penicillins; cefepime acceptable per cross-reactivity literature"},
    ],
    "guidelines_cited": [
        "Surviving Sepsis Campaign 2021",
        "IDSA Hospital-Acquired Pneumonia Guideline 2016 (current)",
    ],
    "needs_pharmacist_review": False,
    "needs_clinician_signoff": True,
}
```

### Tool 5: `drive_bundle_element`

```python
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
                "enum": ["lactate_initial", "blood_cultures",
                         "broad_spectrum_antibiotics", "fluid_resuscitation",
                         "vasopressors", "repeat_lactate", "volume_reassessment"],
            },
            "deadline": {"type": "string"},
            "assigned_role": {
                "type": "string",
                "enum": ["nurse", "pharmacist", "rrt", "physician", "respiratory_therapist"],
            },
            "details": {"type": "string"},
        },
        "required": ["element", "deadline", "assigned_role"],
        "additionalProperties": False,
    },
}
```

**Behavior:** Constructs a FHIR Task resource and POSTs to the FHIR server. Task references the SHARP-bound Patient and includes a structured "what to do" + "why" + "by when".

### Tool 6: `draft_sep1_documentation`

```python
DRAFT_SEP1_DOCUMENTATION_SCHEMA = {
    "name": "draft_sep1_documentation",
    "description": (
        "Draft the CMS-abstractor-ready progress note documenting the SEP-1 "
        "bundle execution. The note must explicitly state Time Zero, the "
        "criteria that established severe sepsis or septic shock, and each "
        "bundle element with its timestamp and FHIR resource reference. This "
        "is the documentation CMS abstractors review for compliance scoring."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "diagnosis_packet": {"type": "object",
                "description": "Output of confirm_sepsis_diagnosis"},
            "bundle_status": {"type": "object",
                "description": "Output of score_bundle_compliance"},
            "antibiotic_choice": {"type": "object",
                "description": "Output of recommend_antibiotic, optional"},
            "infection_source_evidence": {"type": "string",
                "description": "Free-text summary of source-of-infection evidence"},
        },
        "required": ["diagnosis_packet", "bundle_status"],
        "additionalProperties": False,
    },
}
```

**Behavior:** Real Claude call with prompt-cached system prompt + cached SEP-1 abstractor scoring rubric. Returns a structured JSON containing the prose note + citation map.

**Returns:**
```python
{
    "note_text": "(prose, ~600-900 words, formatted as a structured progress note)",
    "structured_sections": {
        "time_zero_documented": "...",
        "severe_sepsis_criteria_met": "...",
        "infection_source": "...",
        "bundle_3hr_status": "...",
        "bundle_6hr_status": "...",
        "clinician_assessment": "...",
        "plan": "...",
    },
    "cited_evidence": [
        {"claim": "Patient met SIRS with HR 118, temp 39.1", "source": "Observation/vitals-1234"},
        {"claim": "Lactate 3.2 mmol/L documented within 1hr of Time Zero", "source": "Observation/lactate-1"},
    ],
    "abstractor_compliance_score_predicted": 0.92,
    "audit_concerns": [],
}
```

### Tool 7: `notify_care_team`

```python
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
                    "enum": ["bedside_nurse", "charge_nurse", "intensivist",
                            "hospitalist", "pharmacist", "respiratory_therapist",
                            "rrt", "family"],
                },
            },
            "subject": {"type": "string"},
            "body": {"type": "string"},
            "linked_resources": {
                "type": "array",
                "items": {"type": "string"},
                "description": "FHIR refs (Tasks, Conditions, Observations) the message references",
            },
        },
        "required": ["level", "audience", "subject", "body"],
        "additionalProperties": False,
    },
}
```

---

## 8. SHARP-on-MCP Integration

This section documents the platform integration patterns. They are **identical to AuthBridge** and you should reuse the code patterns wholesale.

### MCP `initialize` handshake

When the platform calls `POST /mcp` with `{"method":"initialize"}`, return:

```python
{
    "protocolVersion": "2024-11-05",
    "serverInfo": {"name": "sepsisguard", "version": "0.1.0"},
    "capabilities": {
        "tools": {},
        "extensions": {
            "ai.promptopinion/fhir-context": {
                "scopes": REQUIRED_SCOPES,
            }
        },
    },
}
```

### Required SMART scopes (`REQUIRED_SCOPES`)

```python
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
```

The first 9 are reads. The last 4 are writes (Task creation for bundle elements, Communication for notifications, DocumentReference for the SEP-1 note, optional MedicationRequest for antibiotic order drafts).

### HTTP headers received per `tools/call`

```
X-FHIR-Server-URL: https://app.promptopinion.ai/api/workspaces/.../fhir
X-FHIR-Access-Token: <JWT>
X-Patient-ID: <UUID>
X-FHIR-Refresh-Token: <optional, only if offline_access scope granted>
X-FHIR-Refresh-Url: <optional>
```

### Agent card at `/.well-known/agent-card.json`

```python
{
    "protocolVersion": "1.0",
    "name": "SepsisGuard",
    "description": "Multi-agent SEP-1 bundle co-pilot ...",
    "version": "0.1.0",
    "provider": {"name": "SepsisGuard", "url": "https://github.com/.../sepsisguard"},
    "capabilities": {
        "streaming": False,
        "extensions": [
            {
                "uri": "https://app.promptopinion.ai/schemas/a2a/v1/fhir-context",
                "description": "FHIR context for sepsis bundle execution",
                "required": True,
                "params": {"scopes": REQUIRED_SCOPES},
            }
        ],
    },
    "skills": [
        {
            "id": "continuous_sepsis_monitoring",
            "name": "Watch a patient for emerging sepsis",
            "description": "Continuously screen for SIRS/qSOFA + free-text signals; "
                "surface a SepsisAlert if criteria are met.",
            "tags": ["sepsis", "early-warning", "icu"],
        },
        {
            "id": "bundle_execution",
            "name": "Execute the CMS SEP-1 bundle for a confirmed sepsis case",
            "description": "Drive each 3-hr and 6-hr bundle element to completion; "
                "assign Tasks; draft the abstractor-grade documentation note.",
            "tags": ["sepsis", "sep-1", "bundle"],
        },
        {
            "id": "bundle_audit_review",
            "name": "Audit a completed sepsis encounter for SEP-1 compliance",
            "description": "Walk a discharged patient's record and predict whether "
                "the encounter passes CMS SEP-1 abstractor review.",
            "tags": ["sepsis", "audit", "vbp"],
        },
    ],
    "supportedInterfaces": [
        {"transport": "JSONRPC", "uri": "/a2a"},
    ],
    "defaultInputModes": ["text/plain"],
    "defaultOutputModes": ["text/plain", "application/json"],
}
```

---

## 9. FHIR Resources

The full list of FHIR resources SepsisGuard reads and writes. Used by both the FHIR client and the test data generator.

| Resource | Read | Write | Notes |
|----------|------|-------|-------|
| **Patient** | ✅ | — | demographics |
| **Encounter** | ✅ | — | hospitalization context |
| **Observation** | ✅ | — | vitals, labs (LOINC-coded) |
| **Condition** | ✅ | — | known infections, comorbidities |
| **MedicationRequest** | ✅ | optional | antibiotic recommendations |
| **MedicationAdministration** | ✅ | — | what was actually given |
| **AllergyIntolerance** | ✅ | — | drug allergies |
| **DiagnosticReport** | ✅ | — | imaging, microbiology |
| **DocumentReference** | ✅ | ✅ | nursing notes (read), SEP-1 note (write) |
| **Specimen** | ✅ | — | blood culture specimens |
| **Procedure** | ✅ | — | central line, intubation |
| **Task** | — | ✅ | bundle element drivers |
| **Communication** | — | ✅ | care team notifications |

### Key LOINC codes

- **Lactate (mmol/L):** 32693-4 (preferred), 2524-7 (older)
- **WBC count:** 6690-2
- **Bands %:** 26511-6
- **Creatinine:** 2160-0
- **INR:** 6301-6
- **Platelets:** 777-3
- **Bilirubin total:** 1975-2
- **Heart rate:** 8867-4
- **Systolic BP:** 8480-6
- **Diastolic BP:** 8462-4
- **Mean arterial pressure:** 8478-0
- **Respiratory rate:** 9279-1
- **Body temperature:** 8310-5
- **SpO2:** 2708-6, 59408-5
- **GCS total:** 9269-2
- **qSOFA score:** 91348-6

### Key RxNorm codes for antibiotics

- **Cefepime 2 g IV:** 309027
- **Vancomycin IV:** 11124
- **Piperacillin/tazobactam:** 31700
- **Meropenem:** 6753
- **Norepinephrine:** 7512
- **Lactated Ringer's:** 142436

### Key SNOMED for conditions

- **Severe sepsis:** 449868000
- **Septic shock:** 76571007
- **Pneumonia:** 233604007
- **Urinary tract infection:** 68566005

---

## 10. Demo Scenarios

Three patients, mirroring the AuthBridge pattern (3 scenarios across 3 specialties).

### Scenario 1: Community-acquired pneumonia → severe sepsis

- **Patient:** 67-year-old female, 2-day history of cough, fever, and dyspnea. Presents to ED.
- **Vitals at presentation:** HR 118, BP 92/56, RR 28, Temp 39.1°C, SpO2 91% RA
- **Labs:** WBC 18.4 K (15% bands), lactate 3.2 mmol/L, creatinine 1.4 (baseline 0.9), platelets 142
- **Imaging:** CXR with right lower lobe consolidation
- **Trigger:** SIRS (4/4) + qSOFA 2 + organ dysfunction (lactate 3.2, creatinine bump)
- **Expected SepsisGuard outcome:** Severe sepsis confirmed. Time Zero = ED arrival + 45 min. Bundle 3-hr elements completed within window. Recommended cefepime + vancomycin. Note drafted citing bundle compliance.

### Scenario 2: Hospital-onset urinary sepsis (Foley-associated)

- **Patient:** 78-year-old male, post-op day 4 from elective ortho. Foley placed intraop, still in.
- **Vitals on POD 4 morning:** HR 102, BP 138/82, Temp 38.6°C, RR 22 (was 16 yesterday)
- **Labs:** WBC 13.8 K (was 9.2 yesterday), lactate 2.4 mmol/L, creatinine stable
- **Nursing note:** "Patient confused, more lethargic than prior 24h. Urine cloudy with sediment."
- **Trigger:** SIRS (3/4) + AMS + free-text concern + lactate elevated
- **Expected outcome:** Severe sepsis confirmed (despite less obvious vitals). Time Zero = nursing assessment time. Source: urinary. Recommended: pip/tazo. Foley removal Task created. **This is the hard case** — the Adjudicator must read free-text to confirm.

### Scenario 3: Septic shock (intra-abdominal)

- **Patient:** 54-year-old male, 3 days of progressive abdominal pain, vomiting, fever.
- **Vitals:** HR 132, BP 78/44 (MAP 55), RR 30, Temp 39.4°C
- **Labs:** WBC 24 K, **lactate 5.8 mmol/L**, creatinine 2.1, INR 1.6, platelets 88
- **CT abdomen:** Free air, suspected perforated viscus
- **Trigger:** All shock criteria — hypotension + lactate ≥ 4 = septic shock
- **Expected outcome:** **Septic shock confirmed.** Bundle drives more aggressively: 30 mL/kg fluid bolus immediate, vasopressors flagged as likely needed, surgical consult Communication, broader antibiotic regimen (vanc + zosyn or cefepime + flagyl). Repeat lactate scheduled at 4hr. Time-stamped documentation.

---

## 11. Project File Structure

Mirror the AuthBridge layout exactly. Drop the directory below into a fresh repo.

```
sepsisguard/
├── README.md                           ← project overview
├── SUBMISSION.md                        ← Devpost submission text
├── LICENSE                              ← Apache 2.0
├── requirements.txt                     ← pip dependencies
├── pyproject.toml                       ← package metadata
├── .env.example                         ← template — copy to .env
├── .gitignore
├── Procfile                             ← Railway: web: python -m sepsisguard.server
├── runtime.txt                          ← python-3.12
├── railway.toml                         ← Railway deploy config
│
├── src/sepsisguard/
│   ├── __init__.py
│   ├── server.py                        ← MCP + A2A HTTP transport (FastAPI)
│   ├── agent_loop.py                    ← Claude tool-use orchestrator
│   ├── shadow_abstractor.py             ← Claude-based CMS abstractor simulator
│   ├── alert_store.py                   ← in-memory alert/Time Zero store
│   ├── sharp_context.py                 ← SHARP context (HTTP headers + contextvar)
│   ├── fhir_client.py                   ← async FHIR R4 client
│   ├── claude_client.py                 ← Anthropic API w/ prompt caching
│   ├── audit.py                         ← HIPAA audit log (JSONL)
│   ├── sep1_definition.py               ← bundle elements, deadlines, scoring
│   ├── antibiogram.py                   ← local antibiogram + selection logic
│   ├── loinc.py                         ← LOINC code constants
│   ├── rxnorm.py                        ← RxNorm code constants
│   ├── demo.py                          ← end-to-end demo runner
│   └── tools/
│       ├── __init__.py                  ← TOOL_REGISTRY
│       ├── screen_signals.py            ← tool 1
│       ├── confirm_diagnosis.py         ← tool 2
│       ├── score_bundle.py              ← tool 3
│       ├── recommend_antibiotic.py      ← tool 4
│       ├── drive_bundle_element.py      ← tool 5
│       ├── draft_documentation.py       ← tool 6
│       └── notify_care_team.py          ← tool 7
│
├── agent/
│   ├── agent_card.json                  ← A2A v1 agent card (also served at /.well-known)
│   └── agent_prompt.md                  ← system prompt for the orchestrator
│
├── data/
│   ├── examples/
│   │   ├── scenario_cap_severe_sepsis.json
│   │   ├── scenario_uti_late_onset.json
│   │   └── scenario_intra_abdominal_septic_shock.json
│   ├── fhir_bundles/                    ← uploadable FHIR transaction bundles
│   │   ├── cap_severe_sepsis.bundle.json
│   │   ├── uti_late_onset.bundle.json
│   │   └── intra_abdominal_septic_shock.bundle.json
│   ├── clinical_notes/                  ← uploadable as DocumentReferences
│   │   ├── cap_severe_sepsis_admit.txt
│   │   ├── uti_late_onset_pod4.txt
│   │   └── intra_abdominal_ed.txt
│   ├── antibiogram/
│   │   └── default_antibiogram.json
│   └── sep1_abstractor_rubric.md        ← cached prompt content
│
├── demo/
│   ├── demo_video_script.md
│   ├── workflow_diagram.md
│   ├── DEMO_RECORDING_NOTES.md
│   ├── ui/
│   │   └── index.html                   ← visual workflow demo (single file)
│   └── screenshots/
│
├── docs/
│   ├── ARCHITECTURE.md
│   ├── DEMO_SCENARIOS.md
│   ├── IMPACT_METRICS.md
│   ├── HIPAA_COMPLIANCE.md
│   ├── SEP1_BUNDLE.md                   ← detailed CMS rules, abstractor logic
│   └── DEPLOY_TO_PROMPT_OPINION.md
│
├── scripts/
│   ├── scenarios_to_fhir_bundles.py    ← convert scenario JSON → uploadable Bundle
│   └── make_logo.py                    ← generate logo PNG
│
├── assets/
│   └── sepsisguard_logo.png
│
├── tests/
│   └── test_tools.py                    ← smoke tests
│
└── logs/                                ← runtime artifacts (gitignored)
    ├── audit.jsonl
    ├── mcp-server.log
    └── ngrok.log
```

---

## 12. Code Templates and Patterns

These patterns are direct copies from AuthBridge. **Reuse them — don't reinvent.**

### Pattern 1: SHARP context (`sharp_context.py`)

A `contextvars.ContextVar` carries the SHARP context through every async hop. Tools call `current_sharp_context()` to access patient ID + FHIR endpoint without threading args.

```python
# Key API:
current_sharp_context() -> SharpContext   # raises if missing
require_scope(scope: str) -> SharpContext # asserts scope granted
SharpContext.from_headers(headers, granted_scopes=...) -> SharpContext
bind_sharp_context(ctx) -> token
reset_sharp_context(token) -> None
```

`SharpContext` carries: `patient_id`, `fhir_base_url`, `access_token`, `scopes`, `user`, `intent`, `trace_id`.

### Pattern 2: FHIR client (`fhir_client.py`)

Async `httpx`-based client. Reads OAuth token + FHIR base URL from the bound SHARP context.

```python
# Key API:
async with FhirClient() as fhir:
    patient = await fhir.read("Patient", "...")
    obs = await fhir.search("Observation",
        {"patient": patient_id, "code": "32693-4", "_sort": "-date"})
    record = await fhir.patient_record(include=("Condition", "Observation", ...))
    response = await fhir.create({"resourceType": "Task", ...})
    response = await fhir.transaction(bundle)
```

Implements: scope checking, retry on 429/5xx, audit logging, OperationOutcome parsing.

### Pattern 3: Claude client (`claude_client.py`)

Anthropic `AsyncAnthropic` wrapper with explicit prompt caching. Critical detail: **`temperature` is deprecated for `claude-opus-4-7`** — omit it.

```python
class CacheableBlock:
    text: str
    cache: bool = False
    ttl: str = "5m"  # or "1h"

await claude.generate(
    system_blocks=[CacheableBlock(text=SYSTEM_PROMPT, cache=True, ttl="1h"),
                   CacheableBlock(text=SEP1_RUBRIC, cache=True, ttl="1h")],
    user_blocks=[CacheableBlock(text=PATIENT_PACKET, cache=False)],
    max_tokens=2048,
)
```

### Pattern 4: Audit log (`audit.py`)

JSON-Lines append. NEVER log PHI — only resource references.

```python
audit_log("tool.confirm_sepsis_diagnosis",
    trace_id=ctx.trace_id, patient=ctx.patient_id, tool="confirm_sepsis_diagnosis")
```

### Pattern 5: Server transport (`server.py`)

FastAPI app with these endpoints:

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/` | server info |
| GET | `/health` | health check (Railway) |
| GET | `/.well-known/agent-card.json` | A2A v1 agent card |
| POST | `/mcp` | MCP JSON-RPC (initialize, tools/list, tools/call, agent/run) |
| POST | `/a2a` | A2A v1 message endpoint |
| GET | `/mcp/sse` | SSE keepalive (optional) |

**Critical FastAPI 0.136 + Starlette 1.0 quirk:** Don't use `request: Request` parameter — FastAPI mis-classifies it as a query param. Instead use:
```python
@app.post("/mcp")
async def mcp_post(
    payload: dict = Body(...),
    x_fhir_server_url: str | None = Header(None, alias="X-FHIR-Server-URL"),
    x_fhir_access_token: str | None = Header(None, alias="X-FHIR-Access-Token"),
    x_patient_id: str | None = Header(None, alias="X-Patient-ID"),
    ...
) -> JSONResponse:
    ...
```

### Pattern 6: Agent loop (`agent_loop.py`)

Anthropic Messages API with `tools=` parameter. Iterates until `stop_reason == "end_turn"`.

**Critical detail:** Anthropic enforces a max of 4 `cache_control` breakpoints per request. The agent loop must strip `cache_control` from older `tool_result` blocks before sending the next request — otherwise the breakpoint count grows unboundedly across iterations.

```python
def _strip_old_cache_breakpoints(messages):
    for msg in messages:
        if msg.get("role") != "user": continue
        for block in msg.get("content", []):
            if isinstance(block, dict) and block.get("type") == "tool_result":
                block.pop("cache_control", None)
```

### Pattern 7: Demo runner with in-process FHIR mock (`demo.py`)

Use `httpx.MockTransport` to intercept FHIR calls and serve scenario data without a live server. Keeps the demo offline-runnable.

---

## 13. Implementation: Tool-by-Tool

This section is the actual code template for each tool. Pattern is identical across all 7. I'll show one in full; the others mirror.

### `tools/confirm_diagnosis.py` — full template

```python
"""Tool 2: confirm_sepsis_diagnosis."""

from __future__ import annotations
import json
import logging
from typing import Any

from ..audit import audit_log
from ..claude_client import CacheableBlock, ClaudeClient
from ..sharp_context import current_sharp_context

logger = logging.getLogger(__name__)

CONFIRM_SEPSIS_DIAGNOSIS_SCHEMA = {
    "name": "confirm_sepsis_diagnosis",
    "description": (
        "Adjudicate whether the screened signals constitute severe sepsis or "
        "septic shock per CMS SEP-1 definitions. Returns diagnosis "
        "classification and Time Zero (the timestamp severe sepsis criteria "
        "were first met). Time Zero starts the 3-hour and 6-hour bundle clocks."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "screening_packet": {
                "type": "object",
                "description": "Output of screen_sepsis_signals.",
            },
        },
        "required": ["screening_packet"],
        "additionalProperties": False,
    },
}

SYSTEM_PROMPT = """You are a sepsis adjudication agent embedded in an ICU
workflow. You read a screening packet built from FHIR data and decide whether
the patient meets CMS SEP-1 criteria for severe sepsis or septic shock, OR
whether the signals are explained by a benign alternative.

Hard rules:
1. Severe sepsis requires ALL THREE: (a) suspected/documented infection,
   (b) ≥ 2 SIRS criteria, (c) ≥ 1 organ dysfunction sign.
2. Septic shock requires severe sepsis PLUS persistent hypotension after
   30 mL/kg fluid OR initial lactate ≥ 4.0 mmol/L.
3. Time Zero is the FIRST documented timestamp at which all severe sepsis
   criteria were simultaneously met. Use the latest of: SIRS-meeting vital,
   organ-dysfunction lab, or infection documentation.
4. Consider and EXPLICITLY rule out alternatives: post-op fever, alcohol
   withdrawal, neuroleptic malignant syndrome, pancreatitis, anaphylaxis.
5. NEVER invent timestamps or values not present in the screening packet.
6. If the case is ambiguous, return "insufficient_data" and name what you'd
   need — do not guess.

Output a single JSON object with these fields:
- classification: "severe_sepsis" | "septic_shock" | "sepsis_likely_benign_alternative" | "insufficient_data"
- time_zero: ISO 8601 string (or null if not yet established)
- time_zero_basis: short prose explaining which signals established Time Zero
- infection_source_suspected: "pneumonia" | "urinary" | "intra_abdominal" | "skin_soft_tissue" | "central_line" | "unknown"
- alternative_explanations_considered: array of strings
- alternative_explanations_ruled_out: boolean
- confidence: "high" | "medium" | "low"
- next_action: "drive_bundle" | "monitor_recheck_in_2h" | "escalate_to_clinician"
"""

async def confirm_sepsis_diagnosis(
    *, screening_packet: dict[str, Any]
) -> dict[str, Any]:
    ctx = current_sharp_context()
    audit_log("tool.confirm_sepsis_diagnosis",
              trace_id=ctx.trace_id, patient=ctx.patient_id)

    system_blocks = [CacheableBlock(text=SYSTEM_PROMPT, cache=True, ttl="1h")]
    user_blocks = [
        CacheableBlock(
            text=("<screening_packet>\n" + json.dumps(screening_packet, indent=2)
                  + "\n</screening_packet>\n\nReturn the JSON described in the system prompt."),
            cache=False,
        ),
    ]

    client = ClaudeClient()
    result = await client.generate(
        system_blocks=system_blocks, user_blocks=user_blocks, max_tokens=1500
    )
    parsed = _parse_json(result.text)
    parsed.setdefault("classification", "insufficient_data")
    parsed.setdefault("alternative_explanations_considered", [])
    parsed.setdefault("alternative_explanations_ruled_out", False)
    parsed.setdefault("confidence", "low")
    parsed.setdefault("next_action", "escalate_to_clinician")
    parsed["_telemetry"] = {
        "input_tokens": result.input_tokens,
        "cache_read_tokens": result.cache_read_input_tokens,
        "cache_hit_ratio": round(result.cache_hit_ratio, 3),
        "model": client.model,
    }
    return parsed


def _parse_json(text: str) -> dict[str, Any]:
    s = text.strip()
    if s.startswith("```"):
        s = s.split("```", 2)[1]
        if s.startswith("json"): s = s[4:]
        s = s.rsplit("```", 1)[0]
    start, end = s.find("{"), s.rfind("}")
    if start == -1 or end == -1: return {}
    try:
        return json.loads(s[start:end+1])
    except json.JSONDecodeError:
        return {}
```

The other 6 tools follow this exact pattern. The two that don't call Claude are `screen_sepsis_signals` (deterministic FHIR queries + scoring) and `score_bundle_compliance` (deterministic FHIR walk + bundle math).

---

## 14. Agent Loop

Identical pattern to AuthBridge's `agent_loop.py`. The orchestrator system prompt should look like this:

```
You are SepsisGuard, an ICU sepsis bundle co-pilot embedded in the Prompt
Opinion platform. You are invoked when a clinician asks you to monitor a
patient for sepsis OR drive bundle compliance for a confirmed sepsis case.

You have seven tools (above in McpAppsFragment). Default trajectory:

  1. screen_sepsis_signals
     -> if recommendation = "no_sepsis_signal", stop and report
     -> else continue
  2. confirm_sepsis_diagnosis (with the screening packet)
     -> if classification = "sepsis_likely_benign_alternative" or
        "insufficient_data", stop and surface to clinician
     -> else continue
  3. score_bundle_compliance (with time_zero from step 2)
  4. For any element that is "in_progress" or "scheduled":
     - if antibiotic-related: recommend_antibiotic, then drive_bundle_element
     - else: drive_bundle_element directly
  5. notify_care_team with bundle status (urgent if any element at risk)
  6. draft_sep1_documentation

Hard rules:
- NEVER fabricate vitals, labs, or timestamps. Every claim must trace to
  a tool result.
- NEVER auto-administer medications — every antibiotic recommendation is a
  draft for clinician sign-off.
- NEVER include patient name, MRN, DOB, or address in conversational output.
  Refer to "the patient".
- If confirm_sepsis_diagnosis returns "insufficient_data", report the gap
  to the clinician and STOP. Do not run subsequent tools speculatively.
- If at any point a bundle element becomes "non_compliant" (deadline passed),
  notify_care_team with level=urgent and continue driving the remaining
  elements — but flag the missed element in the documentation.
- Tone: terse, factual, ICU-shorthand acceptable ("3.2 lactate", "30/kg in").
  No preambles. No apologies.
```

---

## 15. Server / Transport Layer

The `server.py` file is structurally identical to AuthBridge's. Required differences:

1. `SERVER_NAME = "sepsisguard"` (not `"authbridge"`).
2. `REQUIRED_SCOPES` updated to the SepsisGuard list (see §8).
3. Tool registry imports SepsisGuard tools.
4. `_build_agent_card()` returns the SepsisGuard skills, not AuthBridge's.
5. `handle_a2a` extracts the user's text from `params.message.parts[].text` and passes it to `run_agent` — same pattern.

---

## 16. Demo Runner

`demo.py` mirrors AuthBridge's pattern: an in-process FHIR mock served via `httpx.MockTransport`. Key differences:

- Three scenario JSONs in `data/examples/`
- Scenarios contain `patient_synthetic_record` with the same shape as AuthBridge but with sepsis-relevant FHIR resources (Observations for vitals, labs, mental status; DocumentReferences for nursing notes; DiagnosticReports for micro/imaging)
- The demo runner runs the full agent loop against the bound SHARP context; should output the trace and final summary

```bash
python -m sepsisguard.demo --scenario cap_severe_sepsis
python -m sepsisguard.demo --scenario uti_late_onset
python -m sepsisguard.demo --scenario intra_abdominal_septic_shock
python -m sepsisguard.demo --scenario all
```

---

## 17. Deployment

### 17.1 Local development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# edit .env: ANTHROPIC_API_KEY=sk-ant-...
python -m sepsisguard.server --transport sse --port 8080
```

### 17.2 ngrok for first-pass platform integration

```bash
# install
curl -sSL "https://bin.equinox.io/c/bNyj1mQVY4c/ngrok-v3-stable-linux-amd64.tgz" \
  | tar xz -C ~/.local/bin/
~/.local/bin/ngrok config add-authtoken <YOUR_NGROK_TOKEN>
~/.local/bin/ngrok http 8080
# copy the https://...ngrok-free.dev URL
```

### 17.3 Railway permanent deployment

Files needed at repo root:

**`Procfile`**
```
web: python -m sepsisguard.server
```

**`railway.toml`**
```toml
[build]
builder = "NIXPACKS"

[deploy]
startCommand = "python -m sepsisguard.server"
healthcheckPath = "/health"
healthcheckTimeout = 30
restartPolicyType = "ON_FAILURE"
restartPolicyMaxRetries = 5
```

**`runtime.txt`**
```
python-3.12
```

Server's `main()` must auto-detect cloud mode via `$PORT`:
```python
default=(
    "sse"
    if os.environ.get("PORT")
    else os.environ.get("AUTHBRIDGE_TRANSPORT", "stdio")  # rename to SEPSISGUARD_TRANSPORT
),
```

Required Railway env vars:
- `ANTHROPIC_API_KEY` (required)
- `PYTHONPATH=src` (required — package is in `src/sepsisguard/`)
- `LOG_LEVEL=INFO`
- `DEMO_MODE=true`

After deploy: Settings → Networking → **Generate Domain**.

### 17.4 Prompt Opinion platform integration

1. **Configuration → MCP Servers → Add MCP Server**
   - Name: SepsisGuard MCP
   - Endpoint: `https://<railway-url>/mcp`
   - Transport: Streamable HTTP
   - Auth Type: None
   - Save → toggle "Enable Prompt Opinion Extension" ON
   - Authorize all 15 SMART scopes (Selective Permissions → Select All)

2. **Agents → BYO Agents → Add AI Agent**
   - Allowed Contexts: Workspace + Patient
   - Name: SepsisGuard ICU Co-Pilot
   - Description: see §19 below
   - Timeout Seconds: 300
   - Model: gemini-3-flash-preview (default)
   - System Prompt: paste from §14 above (preserve `{{ PatientContextFragment }}`, `{{ PatientDataFragment }}`, `{{ McpAppsFragment }}` template variables)
   - Tools: Add SepsisGuard MCP (auto-attaches all 7 tools)
   - A2A & Skills: enable A2A + enable FHIR Context Extension + Required toggle ON
   - Skill: `bundle_execution` with description from agent card
   - Save

3. **Marketplace Studio → Manage**: fill publisher profile, enable publishing
4. **Marketplace Studio → MCP Servers**: publish SepsisGuard MCP
5. **Marketplace Studio → Agents**: publish SepsisGuard ICU Co-Pilot

---

## 18. Testing Strategy

`tests/test_tools.py` should include:

```python
def test_sharp_context_scope_check(): ...
def test_sep1_definition_loads(): ...
def test_sep1_score_bundle_with_synthetic_data(): ...
def test_demo_runs_cap_scenario_without_anthropic_key(): ...
def test_audit_log_writes_records(tmp_path, monkeypatch): ...
def test_antibiogram_lookup(): ...
def test_loinc_constants_resolve(): ...
```

The demo-runs test should work even without `ANTHROPIC_API_KEY` set — gate the Claude calls in tools 2, 4, 6 behind a stub fallback (same pattern as AuthBridge's `_stub_justification`).

---

## 19. Submission Materials

### `README.md`

Mirror AuthBridge's README structure with these adaptations:

- Tagline: "Multi-agent SEP-1 bundle co-pilot. Watches the ICU. Drives the bundle. Documents the case."
- Why It Wins table: AI Factor + Potential Impact + Feasibility (use stats from §2)
- Architecture section: paste the diagram from §4
- Quick Start section: same shape as AuthBridge's (but `sepsisguard.demo --scenario cap_severe_sepsis`)
- Standards section: FHIR R4, US Core 6.1, SMART App Launch v2, AHA Sepsis Care Performance Measure, CMS SEP-1, SHARP-on-MCP

### `SUBMISSION.md` (Devpost text)

Sections:
1. **Tagline** (one line, ~140 chars)
2. **Inspiration** — quote the AHRQ #1-most-expensive stat + JAMA Epic study
3. **What it does** — 3 paragraphs walking through the 5 agents + 7 tools
4. **How we built it** — Both Superpower (MCP) and Superhero (A2A) in one
5. **Why this wins on judging criteria** — bullet each criterion
6. **Standards we actually implement** — CRD/DTR/PAS analogues for SEP-1
7. **Built with** — Python, Anthropic, FastAPI, FHIR R4, etc.
8. **Try it yourself** — 3 commands
9. **What's next** — production deployment, multi-hospital rollout, post-acute extension

### `docs/IMPACT_METRICS.md`

Use the table from §2 verbatim. Add hospital-level ROI projection:
- 300-bed hospital with 700 sepsis admissions/year
- ~70% need bundle execution (severe sepsis or septic shock)
- ~30% currently fail SEP-1 documentation (CMS national avg)
- Each failed SEP-1 case costs ~$3K in HVBP impact + $15K in suboptimal care
- SepsisGuard captures 80% of currently-failed cases → recovers ~12-18% of total
- ROI: ~$2-3M/year per 300-bed hospital

### `docs/HIPAA_COMPLIANCE.md`

Same template as AuthBridge:
- §164.312(a) Access Control: SHARP user identity captured, scope enforced per tool
- §164.312(b) Audit: JSONL audit log, references not content
- §164.312(c) Integrity: stateless, FHIR is canonical
- §164.312(d) Authentication: trusts SMART launch
- §164.312(e) Transmission: TLS 1.2+
- Minimum necessary: scopes per tool

### `docs/SEP1_BUNDLE.md`

Detailed walkthrough of CMS SEP-1 abstraction rules. Cover:
- Time Zero definition (CMS abstraction guidance)
- 3-hour and 6-hour element specs
- Common abstractor failure modes
- Documentation requirements
- VBP scoring impact (FY2026)

### `docs/ARCHITECTURE.md`

Paste the diagram from §4 + section walkthrough of each layer. Mirror AuthBridge.

### `docs/DEMO_SCENARIOS.md`

Walk through each of the 3 scenarios, what they prove (CAP = canonical, UTI = hard adjudication case requiring free-text reading, septic shock = aggressive bundle).

### `docs/DEPLOY_TO_PROMPT_OPINION.md`

Copy the AuthBridge guide and adapt names. The deployment shape is identical.

---

## 20. Demo Video Script

3-minute structure:

**Act 1 — The wound (0:00 - 0:30)**
> "Sepsis kills 350,000 Americans every year and costs $60 billion annually — the most expensive condition in any US hospital. The deployed industry leader, the Epic Sepsis Model, was published in JAMA Internal Medicine missing two-thirds of cases while flooding clinicians with false alerts on 18% of all hospital patients. CMS just made SEP-1 a pay-for-performance measure under Hospital Value-Based Purchasing. The market needs a new approach."

**Act 2 — The cure (0:30 - 2:10)**

Scene 1 — Setup: the SepsisGuard MCP server registered on Prompt Opinion with FHIR Context Extension enabled.

Scene 2 — Live workflow: in the Launchpad, with patient context bound, send the prompt:
> "Run sepsis bundle execution for this patient — they were just flagged with rising lactate and SIRS criteria."

Watch all 7 tools fire. Show the final summary: confirmed severe sepsis, Time Zero established, bundle elements driven, SEP-1 note drafted citing every required element.

Scene 3 — The hard case: switch to the UTI patient. Same agent. The tools find the AMS in the nursing note, the elevated WBC trend, the cloudy urine — confirm sepsis from FREE TEXT signals that Epic's structured-only model would miss.

Scene 4 — The safety property: run on a patient with post-op fever (looks like sepsis but isn't). The Adjudicator returns "sepsis_likely_benign_alternative" and refuses to drive the bundle.

**Act 3 — The math (2:10 - 2:50)**
> "Per case: 4-7% mortality reduction per hour of antibiotic delay closed. Per 300-bed hospital: $2-3M/year recovered through SEP-1 VBP compliance. Per CMS rule: aligned with Hospital VBP FY2026, deployable today. Per patient: a chemotherapy infusion that starts on Monday — except this time the patient is alive to receive it."

**Final card:**
> SepsisGuard. Open source. Apache 2.0. Live on the Prompt Opinion Marketplace.

---

## 21. Step-by-Step Build Checklist

Execute in this order. Each step is independently verifiable.

### Stage 1: Scaffold
- [ ] Create directory structure per §11
- [ ] Write `README.md`, `SUBMISSION.md`, `LICENSE`, `.gitignore`, `Procfile`, `railway.toml`, `runtime.txt`, `pyproject.toml`, `requirements.txt`, `.env.example`

### Stage 2: Shared infrastructure (copy from AuthBridge)
- [ ] `src/sepsisguard/__init__.py`
- [ ] `src/sepsisguard/sharp_context.py` (copy AuthBridge's, rename)
- [ ] `src/sepsisguard/fhir_client.py` (copy)
- [ ] `src/sepsisguard/claude_client.py` (copy — IMPORTANT: omit `temperature`)
- [ ] `src/sepsisguard/audit.py` (copy)

### Stage 3: SepsisGuard-specific data
- [ ] `src/sepsisguard/loinc.py` (LOINC constants from §9)
- [ ] `src/sepsisguard/rxnorm.py` (RxNorm constants from §9)
- [ ] `src/sepsisguard/sep1_definition.py` (bundle elements + scoring math)
- [ ] `src/sepsisguard/antibiogram.py` (selection logic + JSON loader)
- [ ] `data/antibiogram/default_antibiogram.json` (sample antibiogram)
- [ ] `src/sepsisguard/alert_store.py` (in-memory alert/Time Zero store, mirrors AuthBridge's submission_store)

### Stage 4: The 7 tools
- [ ] `src/sepsisguard/tools/__init__.py` (TOOL_REGISTRY)
- [ ] `src/sepsisguard/tools/screen_signals.py` (deterministic — FHIR queries + scoring)
- [ ] `src/sepsisguard/tools/confirm_diagnosis.py` (Claude call — see §13 for full template)
- [ ] `src/sepsisguard/tools/score_bundle.py` (deterministic — FHIR walk + sep1_definition math)
- [ ] `src/sepsisguard/tools/recommend_antibiotic.py` (Claude call + antibiogram)
- [ ] `src/sepsisguard/tools/drive_bundle_element.py` (FHIR Task creation)
- [ ] `src/sepsisguard/tools/draft_documentation.py` (Claude call — abstractor-grade prose)
- [ ] `src/sepsisguard/tools/notify_care_team.py` (FHIR Communication creation)

### Stage 5: Shadow abstractor
- [ ] `src/sepsisguard/shadow_abstractor.py` (Claude-as-CMS-abstractor that scores the documentation note for compliance — mirrors AuthBridge's `shadow_payer.py`)

### Stage 6: Agent loop and server
- [ ] `src/sepsisguard/agent_loop.py` (copy AuthBridge's pattern, swap system prompt)
- [ ] `src/sepsisguard/server.py` (copy AuthBridge's, swap REQUIRED_SCOPES, agent card, server name)
- [ ] `agent/agent_card.json` (A2A v1 spec — copy AuthBridge's, swap details)
- [ ] `agent/agent_prompt.md` (system prompt from §14)

### Stage 7: Demo data
- [ ] `data/examples/scenario_cap_severe_sepsis.json`
- [ ] `data/examples/scenario_uti_late_onset.json`
- [ ] `data/examples/scenario_intra_abdominal_septic_shock.json`
- [ ] `data/clinical_notes/cap_severe_sepsis_admit.txt`
- [ ] `data/clinical_notes/uti_late_onset_pod4.txt`
- [ ] `data/clinical_notes/intra_abdominal_ed.txt`
- [ ] `scripts/scenarios_to_fhir_bundles.py` (copy AuthBridge's, adapt for sepsis resources)
- [ ] Generate `data/fhir_bundles/*.bundle.json` (POST-only Bundles, no client-supplied IDs, urn:uuid references)

### Stage 8: Demo runner
- [ ] `src/sepsisguard/demo.py` (in-process FHIR mock + scenario runner, mirrors AuthBridge)

### Stage 9: Tests
- [ ] `tests/test_tools.py` with 7 tests per §18

### Stage 10: Submission docs
- [ ] `docs/ARCHITECTURE.md`
- [ ] `docs/DEMO_SCENARIOS.md`
- [ ] `docs/IMPACT_METRICS.md`
- [ ] `docs/HIPAA_COMPLIANCE.md`
- [ ] `docs/SEP1_BUNDLE.md`
- [ ] `docs/DEPLOY_TO_PROMPT_OPINION.md`
- [ ] `demo/demo_video_script.md`
- [ ] `demo/DEMO_RECORDING_NOTES.md`
- [ ] `demo/ui/index.html` (single-file animated workflow demo, copy AuthBridge's pattern)
- [ ] `assets/sepsisguard_logo.png` (run `scripts/make_logo.py`)

### Stage 11: Smoke test locally
- [ ] `pytest tests/ -v` — all green
- [ ] `python -m sepsisguard.demo --scenario cap_severe_sepsis` — runs end-to-end with stub Claude
- [ ] `python -m sepsisguard.server --transport sse --port 8080` — starts; `/health` returns 200; `/.well-known/agent-card.json` returns the card; `/mcp` initialize returns the extension declaration

### Stage 12: Deploy
- [ ] Push to GitHub (private repo)
- [ ] Sign in to railway.com via GitHub
- [ ] New Project → Deploy from GitHub repo
- [ ] Set env vars: `ANTHROPIC_API_KEY`, `PYTHONPATH=src`, `LOG_LEVEL=INFO`, `DEMO_MODE=true`
- [ ] Settings → Networking → Generate Domain
- [ ] Verify `https://<url>/health` returns 200

### Stage 13: Prompt Opinion integration
- [ ] Sign up at app.promptopinion.ai (free tier with Gemini)
- [ ] Activate General Chat Agent (Po Agents → toggle Active)
- [ ] Import a synthetic patient OR upload one of the FHIR bundles
- [ ] Configuration → MCP Servers → Add MCP Server (Railway URL + /mcp)
- [ ] Toggle FHIR Context Extension ON; Select All scopes; Save
- [ ] Agents → BYO Agents → Add AI Agent (config per §17.4 step 2)
- [ ] Marketplace Studio → Manage → Publisher Profile (logo + about)
- [ ] Marketplace Studio → MCP Servers → Publish
- [ ] Marketplace Studio → Agents → Publish

### Stage 14: Live test
- [ ] Launchpad → Patient scope → pick uploaded sepsis patient
- [ ] Pick SepsisGuard ICU Co-Pilot agent (or General Chat Agent → consult SepsisGuard)
- [ ] Toggle "Show Tool calls" ON
- [ ] Send: "Run sepsis bundle execution for this patient — recent vitals show concerning trends."
- [ ] Verify all 7 tools fire in sequence
- [ ] Verify final summary from agent

### Stage 15: Record + submit
- [ ] Record 3-min video per script in §20
- [ ] Upload video to YouTube (unlisted)
- [ ] Submit on Devpost using SUBMISSION.md content + video link

---

## Closing notes for the implementer

This document plus the AuthBridge reference codebase is sufficient to build SepsisGuard. The architectural patterns are identical — only the domain logic changes. **The hard part is not writing code; it is encoding SEP-1 abstraction rules correctly.** The `sep1_definition.py` and `tools/score_bundle.py` files are where most of the project's clinical correctness lives.

Three things will save the implementer time:

1. **Copy AuthBridge files first, mass-rename, then edit domain logic.** Don't try to write any of the shared infrastructure from scratch.
2. **Build from `screen_sepsis_signals` outward.** That tool is the cheapest to verify (no LLM call), so you can iterate FHIR queries fast.
3. **Test the SHARP context contract early.** Before writing any tool, stand up the server, register it on Prompt Opinion, and verify a single trivial tool (`screen_sepsis_signals` with no FHIR calls) receives the correct `X-FHIR-*` headers. Everything else assumes that contract works.

Good luck. Build the thing.
