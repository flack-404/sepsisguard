# Phase 6 — Demo Suite

> **Goal:** Build the three end-to-end demo scenarios, an offline FHIR mock, the demo runner, and the single-file animated workflow UI. This is what the Devpost video showcases.
> **Effort:** ~1–2 days.

## Prerequisites

- Phase 5 (orchestration) merged. The agent loop runs end-to-end against a FHIR backend.

## Files to create

```
data/examples/
├── scenario_cap_severe_sepsis.json
├── scenario_uti_late_onset.json
└── scenario_intra_abdominal_septic_shock.json

data/clinical_notes/
├── cap_severe_sepsis_admit.txt
├── uti_late_onset_pod4.txt
└── intra_abdominal_ed.txt

data/fhir_bundles/
├── cap_severe_sepsis.bundle.json          (generated)
├── uti_late_onset.bundle.json             (generated)
└── intra_abdominal_septic_shock.bundle.json   (generated)

src/sepsisguard/
└── demo.py                                ← end-to-end demo runner with in-process FHIR mock

scripts/
├── scenarios_to_fhir_bundles.py           ← scenario JSON → uploadable FHIR transaction Bundle
└── make_logo.py                           ← logo PNG generator

demo/
└── ui/
    └── index.html                         ← single-file animated workflow demo

assets/
└── sepsisguard_logo.png                   (generated)
```

## Spec sections to read first

- **§5** — SEP-1 bundle definition (drives what each scenario must contain).
- **§9** — FHIR resources and LOINC codes used in scenarios.
- **§10** — three demo scenarios (CAP, UTI, intra-abdominal shock) with required vitals/labs/notes.
- **§12 Pattern 7** — `httpx.MockTransport` pattern for the in-process FHIR mock.
- **§16** — demo runner CLI shape.

## Task breakdown

### 6.1 Scenario JSONs (`data/examples/scenario_*.json`)

Each scenario file contains everything needed to seed the FHIR mock:

```json
{
  "scenario_id": "cap_severe_sepsis",
  "title": "Community-acquired pneumonia → severe sepsis",
  "patient_synthetic_record": {
    "Patient": {...},
    "Encounter": {...},
    "Observation": [...],          // vitals + labs with timestamps
    "Condition": [...],
    "AllergyIntolerance": [...],
    "DocumentReference": [...],    // nursing notes (link to clinical_notes/*.txt)
    "DiagnosticReport": [...],     // imaging, micro
    "MedicationRequest": [...],
    "MedicationAdministration": []
  },
  "prompt": "Run sepsis bundle execution for this patient — recent vitals show concerning trends.",
  "expected_classification": "severe_sepsis",
  "expected_time_zero_anchor": "ed_arrival_plus_45min",
  "expected_bundle_status": {
    "lactate_initial": "met",
    "blood_cultures_before_antibiotics": "met",
    "broad_spectrum_antibiotics": "in_progress"
  }
}
```

- [ ] **Scenario 1: CAP severe sepsis** — 67yo F. Vitals: HR 118, BP 92/56, RR 28, Temp 39.1°C, SpO2 91%. Labs: WBC 18.4 K (15% bands), lactate 3.2, creatinine 1.4 (baseline 0.9), platelets 142. CXR with RLL consolidation. **Canonical case** — agent should sail through.
- [ ] **Scenario 2: UTI late-onset (Foley-associated)** — 78yo M, POD 4. Vitals: HR 102, BP 138/82, Temp 38.6°C, RR 22. Labs: WBC 13.8 K (was 9.2), lactate 2.4. Nursing note: "Patient confused, more lethargic than prior 24h. Urine cloudy with sediment." **Hard case** — relies on free-text reading.
- [ ] **Scenario 3: Intra-abdominal septic shock** — 54yo M. Vitals: HR 132, BP 78/44 (MAP 55), RR 30, Temp 39.4°C. Labs: WBC 24 K, lactate 5.8, creatinine 2.1, INR 1.6, platelets 88. CT: free air, suspected perforated viscus. **Shock case** — drives aggressively.

### 6.2 Clinical notes (`data/clinical_notes/*.txt`)

Plain-text nursing/admit notes referenced by `DocumentReference` resources in each scenario.

- [ ] `cap_severe_sepsis_admit.txt` — admit note from ED. ~200 words. Must contain "pneumonia", "consolidation", "WBC 18.4", "lactate 3.2".
- [ ] `uti_late_onset_pod4.txt` — POD 4 nursing note. Must contain "confused", "lethargic", "cloudy urine", "sediment", "Foley". This is the trigger that tool 1's free-text scan must catch and tool 2's adjudicator confirms.
- [ ] `intra_abdominal_ed.txt` — ED triage note. Must contain "abdominal pain", "free air", "suspected perforation", "lactate 5.8", "MAP 55".

When loaded into FHIR, the notes go in `DocumentReference.content[0].attachment.data` as base64 of the UTF-8 plain text.

### 6.3 `scripts/scenarios_to_fhir_bundles.py`

CLI tool to convert scenario JSON → uploadable FHIR transaction Bundle.

- [ ] Reads `data/examples/scenario_*.json`.
- [ ] Emits a transaction Bundle to `data/fhir_bundles/<scenario_id>.bundle.json`.
- [ ] **POST-only entries — no client-supplied `id`.** Use `urn:uuid:<uuid4>` for `fullUrl` and references between resources.
- [ ] One `Patient` entry, one `Encounter` referencing it, all observations/conditions/etc. referencing the Patient by `urn:uuid:`.
- [ ] DocumentReference content: base64-encode the matching text file from `data/clinical_notes/`.
- [ ] CLI: `python scripts/scenarios_to_fhir_bundles.py [--scenario <id>|all]`.

### 6.4 `src/sepsisguard/demo.py`

Demo runner. Two modes:

1. **Standalone:** `python -m sepsisguard.demo --scenario cap_severe_sepsis` — uses in-process FHIR mock + binds SHARP context manually + runs `run_agent` end-to-end.
2. **All:** `--scenario all` — runs the three scenarios sequentially, prints per-scenario summary table.

- [ ] `_make_mock_transport(scenario)` — returns `httpx.MockTransport` whose handler dispatches FHIR queries against the in-memory `patient_synthetic_record` dict. Supports `read`, `search` (by patient + code), `create` (in-memory write).
- [ ] Bind SharpContext with synthetic `fhir_base_url="http://mock"`, `access_token="demo"`, all 15 scopes granted.
- [ ] `async def run_scenario(scenario_id) -> dict` — loads scenario, mounts mock, runs `run_agent`, returns `{scenario_id, final_text, tool_calls, telemetry, predicted_abstractor_score}`.
- [ ] **Patches `FhirClient` to use the mock transport** — either via dependency injection or via env var that the client reads. Keep this clean; same hook will be reused by tests.
- [ ] CLI argparse: `--scenario`, `--verbose`, `--format json|text`.
- [ ] On success, prints:
  - Scenario title
  - Time Zero (anchored)
  - Tool call sequence (1-line each)
  - Bundle status table
  - Final agent message
  - Predicted CMS abstractor score (from `shadow_abstractor`)
  - Cache hit ratio across the run

### 6.5 `demo/ui/index.html`

Single-file animated workflow demo. No build step, no dependencies. Pure HTML + CSS + vanilla JS.

- [ ] Header: SepsisGuard logo + tagline.
- [ ] Three tabs (one per scenario). Each tab plays back a pre-recorded tool-call sequence with timing.
- [ ] Agent thought-bubble animation walking through `screen → confirm → score → drive → notify → draft`.
- [ ] Final screen: drafted SEP-1 note + predicted CMS score.
- [ ] Use one of the scenarios' actual `run_agent` output as the data source — embed it as a `const SCENARIO_DATA = {...}` JSON literal.
- [ ] Style: dark theme, monospace for technical content, clean medical aesthetic. No frameworks.
- [ ] Mobile-responsive (judges may watch on a phone).

### 6.6 `scripts/make_logo.py`

- [ ] Generate `assets/sepsisguard_logo.png` programmatically — uses Pillow or matplotlib.
- [ ] Keep simple: shield motif + "SepsisGuard" wordmark. 512×512 PNG.
- [ ] Document the colors (e.g., `#dc2626` red shield, `#0f172a` text) so the UI and submission match.

## Key patterns and gotchas

- **`httpx.MockTransport`** is per-client. Patch the `FhirClient.__aenter__` to use a mock-equipped `AsyncClient` when `DEMO_MODE=true` OR when the demo runner injects it. Same hook will be reused by Phase 7 tests.
- **Time Zero in scenarios needs absolute ISO 8601 timestamps.** The bundle scoring math doesn't accept relative offsets. Pick a canonical "now" per scenario (e.g., `2026-05-10T14:32:00Z` for CAP) and write all observations relative to it.
- **Base64 encoding for note attachments** uses standard base64, not url-safe. Newlines in the encoded string are fine.
- **The free-text trigger keywords (Phase 3)** must be present verbatim in your clinical notes — otherwise the screening fails. Spot-check by searching each note for the keyword set.
- **Demo must run without an `ANTHROPIC_API_KEY`** — Phase 4's stub fallback handles it, but verify end-to-end. The Devpost reviewer may run the demo without setting the key.
- **Don't put real PHI in scenarios.** All names/addresses/MRNs synthetic. Add a "SYNTHETIC DATA" header to each scenario JSON.

## Acceptance criteria

- [ ] `python -m sepsisguard.demo --scenario cap_severe_sepsis` runs to completion offline (no network) in <60 seconds with stub Claude, <120 seconds with real Claude.
- [ ] All three scenarios produce `expected_classification` correctly.
- [ ] UTI scenario specifically: tool 1's screening packet contains the "confused", "cloudy urine" snippets. Tool 2 confirms `severe_sepsis` despite the borderline vitals.
- [ ] Septic shock scenario: tool 2 returns `septic_shock` (not `severe_sepsis`).
- [ ] `demo/ui/index.html` opens directly in a browser (file://) and plays through all three scenarios without errors.
- [ ] `scripts/scenarios_to_fhir_bundles.py --scenario all` produces three valid transaction Bundles. Validate by uploading one to the live Prompt Opinion FHIR server (Phase 8).
- [ ] FHIR bundles use `urn:uuid:` references — `grep '"id":' data/fhir_bundles/*.json` returns no client-supplied IDs at the resource level.
- [ ] `assets/sepsisguard_logo.png` exists and is <100 KB.

## Handoff to next phase

Phase 7 (tests) reuses your FHIR mock infrastructure. Export it cleanly:
```python
# src/sepsisguard/demo.py
def make_mock_fhir_transport(scenario: dict) -> httpx.MockTransport: ...
def load_scenario(scenario_id: str) -> dict: ...
```

Phase 8 (deployment) uploads `data/fhir_bundles/*.json` into the Prompt Opinion FHIR server as the demo patient seed. The bundles must round-trip through their POST endpoint without errors.
