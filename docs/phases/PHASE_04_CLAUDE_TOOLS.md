# Phase 4 — Claude-Backed MCP Tools

> **Goal:** Implement the three MCP tools that call Claude — adjudication, antibiotic recommendation, and CMS-abstractor-grade documentation drafting.
> **Effort:** ~1–2 days. Can run in parallel with Phase 3.

This phase is where SepsisGuard's clinical reasoning lives. Each tool wraps Claude with a strict system prompt and prompt-cached context.

## Prerequisites

- Phase 1 (infrastructure) merged — `ClaudeClient`, `CacheableBlock`, `audit_log`.
- Phase 2 (domain layer) merged — `antibiogram`, `sep1_definition`.

## Files to create

```
src/sepsisguard/tools/
├── confirm_diagnosis.py         ← tool 2: confirm_sepsis_diagnosis
├── recommend_antibiotic.py      ← tool 4: recommend_antibiotic
└── draft_documentation.py       ← tool 6: draft_sep1_documentation

data/
└── sep1_abstractor_rubric.md    ← cached prompt content for tool 6
```

Update `tools/__init__.py` to register these in `TOOL_REGISTRY` (alongside Phase 3's four entries).

## Spec sections to read first

- **§7 Tools 2, 4, 6** — schemas and return shapes.
- **§13** — full implementation template for tool 2 (`confirm_diagnosis.py`). Tools 4 and 6 follow the same pattern.
- **§12 Pattern 3** — Claude client usage. **Reminder: omit `temperature`.**
- **CLAUDE.md** — gotchas (cache breakpoints, no `temperature`, stub fallback in DEMO_MODE).

## Task breakdown

### 4.1 `confirm_diagnosis.py` — tool 2

Spec §13 has the **full template**. Copy verbatim, then verify these details.

- [ ] Export `CONFIRM_SEPSIS_DIAGNOSIS_SCHEMA`.
- [ ] `SYSTEM_PROMPT` per spec §13. Hard rules:
  - Severe sepsis = (infection AND ≥2 SIRS AND ≥1 organ dysfunction).
  - Septic shock = severe sepsis + (post-fluid hypotension OR initial lactate ≥ 4.0).
  - Time Zero = latest of SIRS-meeting vital, organ-dysfunction lab, infection documentation.
  - Must consider AND rule out alternatives: post-op fever, alcohol withdrawal, NMS, pancreatitis, anaphylaxis.
  - Never invent timestamps or values.
  - On ambiguity, return `insufficient_data` and name the gap.
- [ ] `async def confirm_sepsis_diagnosis(*, screening_packet: dict) -> dict`:
  - System block cached with `ttl="1h"`.
  - User block contains the screening packet inside `<screening_packet>...</screening_packet>` tags.
  - `max_tokens=1500`.
  - Parse JSON from response (template's `_parse_json` handles `\`\`\`json` fences).
  - Default missing fields per spec §13.
  - Attach `_telemetry: {input_tokens, cache_read_tokens, cache_hit_ratio, model}`.
- [ ] **Stub fallback:** if `ClaudeClient.generate()` raises (no API key + DEMO_MODE), return a deterministic stub based on the screening packet's `recommendation`:
  - `"proceed_to_adjudication"` + ≥2 organ dysfunction signs → stub `severe_sepsis` with Time Zero = latest organ_dysfunction_markers[*].time.
  - else → stub `insufficient_data`.
  - Same shape as a real return; mark `_telemetry: {model: "stub"}`.

### 4.2 `recommend_antibiotic.py` — tool 4

- [ ] Export `RECOMMEND_ANTIBIOTIC_SCHEMA`.
- [ ] System prompt: stewardship-focused. Rules:
  - Output is a **draft for clinician sign-off**, never auto-administered.
  - Cite Surviving Sepsis Campaign 2021 + IDSA guideline relevant to the source.
  - Respect allergies; explain reasoning when accepting cefepime in a non-anaphylactic penicillin allergy.
  - Renal: if eGFR < 50, flag the regimen for renal dose adjustment but don't dose.
  - MRSA + Pseudomonas coverage flags from the schema must be honored.
- [ ] `async def recommend_antibiotic(*, suspected_source: str, include_mrsa_coverage: bool = True, include_pseudomonas_coverage: bool = True) -> dict`:
  1. `ctx = require_scope("patient/AllergyIntolerance.rs")`; audit log.
  2. With `FhirClient()`, fetch:
     - Allergies: `AllergyIntolerance?patient=<id>&clinical-status=active`.
     - Latest eGFR: `Observation?patient=<id>&code=33914-3&_sort=-date&_count=1` (LOINC 33914-3 for eGFR).
     - Latest weight: `Observation?patient=<id>&code=29463-7&_sort=-date&_count=1`.
  3. Call `antibiogram.recommend_regimen(...)` to seed structured suggestion.
  4. Pass `{seed_regimen, allergies, egfr, weight, source, antibiogram_excerpt}` into Claude as the user block. System prompt is cached with `ttl="1h"`.
  5. Parse JSON. Ensure `needs_clinician_signoff: True` is always set.
  6. Stub fallback: return the `recommend_regimen` output verbatim with rationale = "Stub regimen (Claude unavailable)".

### 4.3 `draft_documentation.py` — tool 6

The most demanding prompt — the output is what CMS abstractors read.

- [ ] Export `DRAFT_SEP1_DOCUMENTATION_SCHEMA`.
- [ ] System prompt: write-like-a-physician progress note. Rules:
  - Must explicitly state **Time Zero**.
  - Must enumerate every severe-sepsis criterion that was met.
  - For every bundle element: state status + timestamp + FHIR ref.
  - Cite evidence: each non-trivial claim references a FHIR resource id.
  - Predict an `abstractor_compliance_score_predicted` (0.0 to 1.0).
  - Flag `audit_concerns` for anything that would fail abstraction (e.g., bundle element completed past deadline, missing volume reassessment doc).
- [ ] **Cache the SEP-1 abstractor rubric:** load `data/sep1_abstractor_rubric.md` and pass as a *second cached system block* with `ttl="1h"`. This is the prompt-cache win — the rubric is large and stable.
- [ ] `async def draft_sep1_documentation(*, diagnosis_packet: dict, bundle_status: dict, antibiotic_choice: dict | None = None, infection_source_evidence: str | None = None) -> dict`:
  - System: `[SYSTEM_PROMPT, ABSTRACTOR_RUBRIC]` (both cached, 1h).
  - User: serialized JSON of inputs.
  - `max_tokens=2500` (longer prose).
  - Parse JSON; default missing fields.
  - Stub fallback: assemble a templated note from the inputs (string interpolation, no Claude). Mark `abstractor_compliance_score_predicted: 0.7` and `_telemetry.model: "stub"`.

### 4.4 `data/sep1_abstractor_rubric.md`

Author this file as the cached prompt content. ~600–1,200 words. Cover:

- [ ] CMS Time Zero abstraction rules verbatim from CMS Hospital IQR specifications.
- [ ] What counts as "documented infection" (active Condition with infection code, OR positive culture, OR clinician note that uses the word "infection"/"sepsis"/"pneumonia"/etc.).
- [ ] What counts as the 30 mL/kg fluid bolus (must use crystalloid; colloid doesn't count).
- [ ] What counts as a repeat lactate (must be drawn within 6h of Time Zero).
- [ ] Common abstractor failure modes (e.g., "lactate drawn at 4h with bundle clock at 0h" — fails 3hr element even though within 6hr).
- [ ] Documentation phrasing that scores well ("Bundle initiated at HH:MM in response to..." pattern).
- [ ] What the abstractor explicitly *does not* count (e.g., generic "patient septic" without supporting criteria).

This file is loaded once per process and cached on Anthropic's side. Make it information-dense, no formatting fluff.

### 4.5 Update `tools/__init__.py`

```python
from .confirm_diagnosis import CONFIRM_SEPSIS_DIAGNOSIS_SCHEMA, confirm_sepsis_diagnosis
from .recommend_antibiotic import RECOMMEND_ANTIBIOTIC_SCHEMA, recommend_antibiotic
from .draft_documentation import DRAFT_SEP1_DOCUMENTATION_SCHEMA, draft_sep1_documentation

TOOL_REGISTRY.update({
    "confirm_sepsis_diagnosis":  (CONFIRM_SEPSIS_DIAGNOSIS_SCHEMA, confirm_sepsis_diagnosis),
    "recommend_antibiotic":      (RECOMMEND_ANTIBIOTIC_SCHEMA, recommend_antibiotic),
    "draft_sep1_documentation":  (DRAFT_SEP1_DOCUMENTATION_SCHEMA, draft_sep1_documentation),
})
```

Final `TOOL_REGISTRY` should have 7 entries.

## Key patterns and gotchas

- **No `temperature` in any Claude call.** `claude-opus-4-7` deprecated it — passing it errors.
- **Cache `ttl="1h"`** for system prompts and the rubric. Use `ttl="5m"` (default) for user content that varies per request.
- **JSON parsing must be robust** — Claude sometimes wraps JSON in `\`\`\`json ... \`\`\``. The `_parse_json` helper from spec §13 handles this; copy it.
- **Stub fallback is required** for every Claude-backed tool. Tests run without an API key; demos with `DEMO_MODE=true` skip the API. Gate the fallback on `RuntimeError` from `ClaudeClient.generate()` OR an env check (`os.environ.get("ANTHROPIC_API_KEY")` falsy).
- **Telemetry on every return:** `{input_tokens, cache_read_tokens, cache_hit_ratio, model}`. The agent loop will surface these to demonstrate prompt caching is working.
- **PHI rule still holds.** The diagnosis packet contains FHIR refs and clinical values, not patient names. The drafted note refers to "the patient" — never use the actual name even if the FHIR Patient resource has it.
- **Don't validate the JSON schema in Python.** Claude is told the shape; defaulting missing fields is enough. Strict schema validation slows iteration without catching real bugs.

## Acceptance criteria

- [ ] All three tools importable. `TOOL_REGISTRY` has 7 entries total.
- [ ] With `DEMO_MODE=true` and no `ANTHROPIC_API_KEY`, each tool returns a sensible stub (no crash).
- [ ] With a real key, `confirm_sepsis_diagnosis` against the CAP scenario screening packet returns `classification: "severe_sepsis"` and a Time Zero within the screening window.
- [ ] `recommend_antibiotic("pneumonia", include_mrsa_coverage=True, include_pseudomonas_coverage=True)` returns cefepime + vancomycin with cited guidelines.
- [ ] `draft_sep1_documentation` produces a `note_text` that mentions "Time Zero", lists at least 3 bundle elements with timestamps, and `cited_evidence` references valid FHIR refs.
- [ ] Telemetry shows non-zero `cache_read_tokens` on the second call (prompt caching is working).

## Handoff to next phase

Phase 5's agent loop iterates Claude with `tools=[s for s, _ in TOOL_REGISTRY.values()]` and dispatches via `TOOL_REGISTRY[name][1](**args)`. Verify that every schema's `name`, `description`, `inputSchema` is well-formed Anthropic tool-use shape (top-level keys: `name`, `description`, `input_schema` — but spec uses `inputSchema`; the agent loop must remap to `input_schema` when sending to Anthropic). **Document this remap explicitly in your `__init__.py` or spec the renaming in PHASES.md.**
