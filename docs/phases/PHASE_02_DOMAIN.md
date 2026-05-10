# Phase 2 — Domain Layer

> **Goal:** Encode all SEP-1 clinical knowledge as data — LOINC/RxNorm constants, bundle definitions and scoring, antibiogram, and the in-memory alert store.
> **Effort:** ~1–2 days. This phase has no external dependencies, so it can run in parallel with Phase 1.

This is **the most important phase for clinical correctness.** The spec author flags `sep1_definition.py` and the bundle-scoring math as where most of the project's correctness lives.

## Prerequisites

- Phase 0 (scaffold) merged.
- Spec sections §5 (SEP-1 definition), §9 (FHIR/LOINC/RxNorm), §13 (`score_bundle` math).

## Files to create

```
src/sepsisguard/
├── loinc.py                ← LOINC code constants for vitals + labs
├── rxnorm.py               ← RxNorm constants for antibiotics + fluids + pressors
├── sep1_definition.py      ← bundle elements, deadlines, severe-sepsis/shock criteria
├── antibiogram.py          ← regimen selection logic + JSON loader
└── alert_store.py          ← in-memory store of SepsisAlert + Time Zero per patient

data/antibiogram/
└── default_antibiogram.json   ← sample local antibiogram (organism × drug × susceptibility %)
```

## Spec sections to read first

- **§5** — full SEP-1 bundle definition (3-hr and 6-hr elements, severe sepsis criteria, shock criteria).
- **§7 Tool 3 (`score_bundle_compliance`)** — return shape your `sep1_definition` must serve.
- **§9** — exact LOINC and RxNorm code values to encode.

## Task breakdown

### 2.1 `loinc.py`

- [ ] Module-level constants (uppercase) for every LOINC in spec §9. Examples:
  ```python
  LACTATE = "32693-4"
  LACTATE_LEGACY = "2524-7"
  WBC = "6690-2"
  BANDS_PCT = "26511-6"
  CREATININE = "2160-0"
  INR = "6301-6"
  PLATELETS = "777-3"
  BILIRUBIN_TOTAL = "1975-2"
  HEART_RATE = "8867-4"
  SBP = "8480-6"
  DBP = "8462-4"
  MAP = "8478-0"
  RESP_RATE = "9279-1"
  TEMP = "8310-5"
  SPO2 = ("2708-6", "59408-5")
  GCS_TOTAL = "9269-2"
  QSOFA_SCORE = "91348-6"
  ```
- [ ] Helper sets: `LACTATE_CODES = {LACTATE, LACTATE_LEGACY}`, `VITAL_CODES = {...}`, `ORGAN_DYSFUNCTION_LAB_CODES = {...}`.

### 2.2 `rxnorm.py`

- [ ] Constants for every RxNorm in spec §9: `CEFEPIME_2G_IV`, `VANCOMYCIN_IV`, `PIPERACILLIN_TAZOBACTAM`, `MEROPENEM`, `NOREPINEPHRINE`, `LACTATED_RINGERS`.
- [ ] Sets: `BROAD_SPECTRUM_ANTIBIOTICS`, `CRYSTALLOIDS`, `VASOPRESSORS`.
- [ ] Optional: SNOMED constants for conditions (`SEVERE_SEPSIS = "449868000"`, `SEPTIC_SHOCK = "76571007"`, etc.) — could live in a separate `snomed.py`, but tucking them at the bottom of `rxnorm.py` is fine for hackathon scope. Document the choice.

### 2.3 `sep1_definition.py`

This is the core data file. Encode SEP-1 as Python dataclasses, not free text.

- [ ] `class BundleElement(Enum)` with members: `LACTATE_INITIAL`, `BLOOD_CULTURES`, `BROAD_SPECTRUM_ANTIBIOTICS`, `FLUID_RESUSCITATION`, `VASOPRESSORS`, `REPEAT_LACTATE`, `VOLUME_REASSESSMENT`.
- [ ] `BUNDLE_DEADLINES: dict[BundleElement, timedelta]` — `LACTATE_INITIAL → 3h`, `BLOOD_CULTURES → 3h`, `BROAD_SPECTRUM_ANTIBIOTICS → 3h`, `FLUID_RESUSCITATION → 3h` (within 3 of Time Zero), `VASOPRESSORS → 6h`, `REPEAT_LACTATE → 6h`, `VOLUME_REASSESSMENT → 6h`.
- [ ] `class SirsCriteria` (TypedDict): `temp_abnormal`, `hr_elevated`, `rr_elevated`, `wbc_abnormal`, `count_met`. Encode thresholds as module constants:
  ```python
  TEMP_HIGH_C = 38.0
  TEMP_LOW_C = 36.0
  HR_HIGH = 90
  RR_HIGH = 20
  WBC_HIGH = 12_000   # cells/µL
  WBC_LOW  = 4_000
  BANDS_HIGH_PCT = 10
  ```
- [ ] `class OrganDysfunctionThresholds` constants: `LACTATE_HIGH = 2.0`, `LACTATE_SHOCK = 4.0`, `SBP_LOW = 90`, `MAP_LOW = 65`.
- [ ] `def evaluate_sirs(observations: list[dict]) -> SirsCriteria` — given Observation dicts (FHIR JSON), tally SIRS criteria.
- [ ] `def evaluate_organ_dysfunction(observations, baselines) -> list[dict]` — return list of `{name, value, unit, time}`.
- [ ] `def severe_sepsis_met(sirs, organ_dysfunction, has_infection: bool) -> bool` — implements the AND of three conditions.
- [ ] `def septic_shock_met(initial_lactate: float | None, post_fluid_hypotension: bool) -> bool`.
- [ ] `def fluid_target_ml(weight_kg: float) -> int` — returns `int(30 * weight_kg)` (rounded down).
- [ ] `class BundleStatus` (TypedDict) — mirrors the return shape from spec §7 Tool 3.
- [ ] `def score_bundle(time_zero: datetime, as_of: datetime, fhir_record: dict, weight_kg: float) -> BundleStatus` — walks the FHIR record, classifies each element as `met` / `in_progress` / `scheduled` / `not_yet_required` / `non_compliant`, computes deadlines.
  - **The `score_bundle` function is consumed by tool 3.** Tool 3 should be a thin FHIR-fetch + `score_bundle` call.
- [ ] All functions are pure and unit-testable with synthetic FHIR dicts.

### 2.4 `antibiogram.py`

- [ ] `def load_antibiogram(path: str | Path | None = None) -> dict` — loads `data/antibiogram/default_antibiogram.json` if path is None.
- [ ] `def recommend_regimen(suspected_source: str, *, allergies: list[dict], egfr: float | None, weight_kg: float, include_mrsa: bool, include_pseudomonas: bool, antibiogram: dict) -> dict` — returns `{primary_regimen: [...], rationale: ..., contraindications_checked: [...]}`. Use it from tool 4 to *seed* the Claude prompt; Claude refines + cites guidelines.
- [ ] Allergy logic: penicillin allergy → avoid penicillins, accept cefepime per cross-reactivity literature. Vanc-allergy → switch to linezolid for MRSA coverage.
- [ ] Renal logic: `eGFR < 50` flags `renal_adjustment_needed` for cefepime/vanc/zosyn (don't auto-dose; that's pharmacist territory).

### 2.5 `data/antibiogram/default_antibiogram.json`

Sample structure:
```json
{
  "facility": "Default ICU Antibiogram (synthetic)",
  "year": 2025,
  "organisms": {
    "E_coli": {"cefepime": 92, "ceftriaxone": 78, "piperacillin_tazobactam": 95, "meropenem": 100},
    "Klebsiella_pneumoniae": {"cefepime": 88, "ceftriaxone": 70, "piperacillin_tazobactam": 90, "meropenem": 99},
    "Pseudomonas_aeruginosa": {"cefepime": 85, "piperacillin_tazobactam": 80, "meropenem": 88, "ceftriaxone": 0},
    "S_aureus_MSSA": {"cefazolin": 100, "vancomycin": 100, "nafcillin": 100},
    "S_aureus_MRSA": {"vancomycin": 100, "linezolid": 100, "ceftriaxone": 0}
  },
  "first_line_by_source": {
    "pneumonia":      {"primary": ["cefepime", "vancomycin"], "alt_pcn_allergy": ["levofloxacin", "vancomycin"]},
    "urinary":        {"primary": ["piperacillin_tazobactam"], "alt_pcn_allergy": ["cefepime"]},
    "intra_abdominal":{"primary": ["piperacillin_tazobactam", "vancomycin"], "alt_pcn_allergy": ["cefepime", "metronidazole", "vancomycin"]},
    "skin_soft_tissue":{"primary": ["vancomycin", "piperacillin_tazobactam"]},
    "central_line":   {"primary": ["vancomycin", "cefepime"]},
    "unknown":        {"primary": ["vancomycin", "piperacillin_tazobactam"]}
  }
}
```

### 2.6 `alert_store.py`

- [ ] `@dataclass class SepsisAlert`: `patient_id`, `trigger_criteria: list[str]`, `time_zero_candidate: datetime | None`, `screening_packet: dict`, `created_at: datetime`.
- [ ] In-process dict keyed by `patient_id`. Methods: `record_alert(alert)`, `get(patient_id) -> SepsisAlert | None`, `set_time_zero(patient_id, ts)`, `clear(patient_id)`.
- [ ] Thread-safe with an `asyncio.Lock`. Process-local only (no persistence) — same shape as AuthBridge's `submission_store`. The note at top of the file should say so.

## Key patterns and gotchas

- **Time Zero is the latest of:** the SIRS-meeting vital, the organ-dysfunction lab, and infection documentation. Get this wrong and bundle scoring is wrong. Spec §13 confirm-diagnosis system prompt repeats this rule.
- **Lactate is reported in mmol/L** in FHIR — not mg/dL. Don't auto-convert. If you see a unit you don't recognize, surface it as "unit_unknown" and skip — never guess.
- **`scheduled` ≠ `in_progress`.** `scheduled` means "deadline known but not yet hit"; `in_progress` means "the order is live but not yet completed". `not_yet_required` is for elements that depend on a clinical condition (e.g., vasopressors only if hypotension persists).
- **Cefepime cross-reactivity:** modern literature accepts cefepime in patients with non-anaphylactic penicillin allergy. Encode this; tool 4 will cite it.
- **30 mL/kg uses *actual* body weight** unless > 30% over IBW (spec doesn't require IBW math; just use actual weight from FHIR).
- **The antibiogram is data, not policy.** `recommend_regimen` returns a structured suggestion; the LLM in tool 4 produces the human-readable rationale. Don't try to write the rationale here.

## Acceptance criteria

- [ ] All modules import without error.
- [ ] `evaluate_sirs` correctly identifies 4/4 SIRS for the CAP scenario vitals (HR 118, RR 28, Temp 39.1, WBC 18.4K).
- [ ] `severe_sepsis_met` returns `True` when given (4/4 SIRS, 2 organ dysfunction signs, has_infection=True).
- [ ] `septic_shock_met(initial_lactate=5.8, post_fluid_hypotension=True)` returns `True`.
- [ ] `score_bundle` against a synthetic FHIR dict with: lactate at T+25min, blood cx at T+15min, antibiotics at T+90min — returns `lactate_initial.status == "met"`, `blood_cultures_before_antibiotics.status == "met"` (with `antibiotic_admin_after_cx == True`), `broad_spectrum_antibiotics.status == "met"`.
- [ ] `recommend_regimen("pneumonia", ...)` returns cefepime + vancomycin as primary regimen.
- [ ] `alert_store` round-trip works under `asyncio` (record → get → clear).

## Handoff to next phase

Phase 3 will call:
```python
from sepsisguard.sep1_definition import score_bundle, evaluate_sirs, evaluate_organ_dysfunction, severe_sepsis_met
from sepsisguard.loinc import LACTATE_CODES, WBC, ...
from sepsisguard.alert_store import alert_store, SepsisAlert
```

Phase 4 will call:
```python
from sepsisguard.antibiogram import load_antibiogram, recommend_regimen
```

Lock these names down before Phase 3/4 starts.
