# Demo Scenarios

Three synthetic ICU patients designed to demonstrate the breadth of SepsisGuard's capabilities. Each scenario lives as a JSON in `data/examples/` plus a clinical-notes file in `data/clinical_notes/` (base64-loaded into FHIR `DocumentReference` attachments at runtime).

## Running them

```bash
# Offline (no API key required)
python -m sepsisguard.demo --scenario cap_severe_sepsis
python -m sepsisguard.demo --scenario uti_late_onset
python -m sepsisguard.demo --scenario intra_abdominal_septic_shock
python -m sepsisguard.demo --scenario all

# With ANTHROPIC_API_KEY set: runs the full Claude tool-use orchestrator.
# Without: runs the deterministic trajectory (same tools, no LLM reasoning).
```

For platform integration, upload the corresponding bundle from `data/fhir_bundles/` to your Prompt Opinion workspace FHIR server, then invoke SepsisGuard against the imported patient.

---

## Scenario 1 — Community-acquired pneumonia → severe sepsis

**File:** `data/examples/scenario_cap_severe_sepsis.json`
**Bundle:** `data/fhir_bundles/cap_severe_sepsis.bundle.json` (18 entries)
**Note:** `data/clinical_notes/cap_severe_sepsis_admit.txt`

**Patient:** 67-year-old female, 2-day history of cough, fever, and dyspnea. Presents to ED.

| Domain | Values |
|---|---|
| Vitals | HR 118, BP 92/56, RR 28, Temp 39.1°C, SpO2 91% RA |
| Labs | WBC 18.4K (15% bands), lactate 3.2, creatinine 1.4 (baseline 0.9), platelets 142 |
| Imaging | CXR with right lower lobe consolidation |
| eGFR | 55 mL/min/1.73m² (borderline — pharmacist review flag) |
| Allergies | Sulfa drugs (mild rash) |

**Triggers:** SIRS 4/4 + qSOFA 2 + organ dysfunction (lactate 3.2 + creatinine bump).

**What it proves:** The canonical sepsis case. SepsisGuard sails through the default trajectory: 11 tool calls, severe_sepsis with high confidence, bundle scored as `on_track` (1/6 met, 67 min into the 3-hr window), cefepime + vanc recommended (with pharmacist oversight flagged for borderline eGFR), 5 Tasks driven, advisory notification, CMS abstractor score predicted ~0.78.

---

## Scenario 2 — Hospital-onset urinary sepsis (Foley-associated)

**File:** `data/examples/scenario_uti_late_onset.json`
**Bundle:** `data/fhir_bundles/uti_late_onset.bundle.json` (17 entries)
**Note:** `data/clinical_notes/uti_late_onset_pod4.txt`

**Patient:** 78-year-old male, POD 4 from elective right total hip arthroplasty. Foley catheter still in place.

| Domain | Values |
|---|---|
| Vitals | HR 102 (was 76), BP 138/82, Temp 38.6°C, RR 22 (was 16), GCS 13 |
| Labs | WBC 13.8K (was 9.2 yesterday), lactate 2.4, creatinine stable 1.1 |
| Nursing note | "Patient confused, more lethargic than prior 24h. Urine cloudy with sediment." |
| Urinalysis | Leukocyte esterase positive, nitrites positive, many bacteria |
| Allergies | Penicillin (non-anaphylactic, mild rash) |

**Triggers:** SIRS 3/4, AMS, lactate elevated, free-text concerns. **No infection-coded Condition exists yet** — the agent must infer urinary source from the nursing note + urinalysis conclusion.

**What it proves:** The case where the LLM beats a rule engine. The Epic Sepsis Model would miss this because the structured signal is weak — vitals are borderline, lactate is just over threshold, no infection condition coded. SepsisGuard's `screen_sepsis_signals` picks up the free-text triggers ("confused", "cloudy urine", "sediment", "lethargic"); `confirm_sepsis_diagnosis` reads the nursing note + urinalysis and confirms severe sepsis with urinary source; `recommend_antibiotic` substitutes cefepime for the antibiogram's default pip-tazo because of the PCN allergy, citing the <2% cross-reactivity literature. CMS score predicted ~0.72.

---

## Scenario 3 — Intra-abdominal septic shock

**File:** `data/examples/scenario_intra_abdominal_septic_shock.json`
**Bundle:** `data/fhir_bundles/intra_abdominal_septic_shock.bundle.json` (19 entries)
**Note:** `data/clinical_notes/intra_abdominal_ed.txt`

**Patient:** 54-year-old male, 3 days of progressive abdominal pain, vomiting, fever.

| Domain | Values |
|---|---|
| Vitals | HR 132, BP 78/44 (MAP 55), RR 30, Temp 39.4°C, GCS 11 |
| Labs | WBC 24K, **lactate 5.8**, creatinine 2.1, INR 1.6, platelets 88 |
| Imaging | CT abdomen: free air under diaphragm, suspected perforated viscus |
| eGFR | 38 (renal-adjusted dosing required) |
| Allergies | None documented |

**Triggers:** All shock criteria — hypotension + lactate ≥ 4 = **septic shock**, not just severe sepsis. Multi-organ dysfunction.

**What it proves:** The aggressive bundle path. The Adjudicator classifies as `septic_shock` (not `severe_sepsis`); the orchestrator drives a 7-element bundle (vasopressors flagged as `scheduled` because hypotension is present, not `not_yet_required`); pharmacist recommends pip-tazo + vanc + metronidazole for anaerobic coverage; care team notified `stat` with surgery consult; documentation explicitly states shock criteria. CMS score predicted ~0.81 (highest of the three because shock cases have unambiguous SEP-1 documentation requirements).

---

## What the three scenarios collectively demonstrate

- **AI Factor** (judging criterion) — UTI scenario is the canonical example: free-text reading wins where the published Epic Sepsis Model (recall 0.33 in JAMA 2021) fails.
- **Impact** — CAP and shock scenarios show the bundle-driven workflow that materially affects mortality (4–7% reduction per hour of antibiotic delay closed) and reimbursement (Hospital VBP FY2026).
- **Feasibility** — All three operate on standard FHIR R4 resources, with HIPAA-grade audit logging, scope-enforced access, draft-only antibiotic recommendations, and CMS-abstractor-aligned documentation.
