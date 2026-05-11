# CMS SEP-1 Bundle — Implementation Notes

This document captures the SEP-1 abstraction rules SepsisGuard encodes, with the references CMS abstractors use when scoring.

## Time Zero

Time Zero is the earliest time the patient simultaneously met all three:
- **Suspected or confirmed infection** — active Condition with infection code, positive culture, or clinician documentation containing the word "infection," "sepsis," "pneumonia," "UTI," "bacteremia," etc.
- **≥ 2 SIRS criteria** — temp > 38°C or < 36°C; HR > 90; RR > 20 or PaCO₂ < 32; WBC > 12K, < 4K, or > 10% bands.
- **≥ 1 organ dysfunction sign** — lactate > 2.0 mmol/L; SBP < 90; MAP < 65; creatinine > 2.0; INR > 1.5; platelets < 100K; bilirubin > 2.0; acute altered mentation.

Abstractors use the **latest** of:
- The SIRS-meeting vital sign time
- The organ-dysfunction lab result time
- The infection documentation time

Generic phrases like "patient appeared septic overnight" are insufficient. The note must state a specific ISO timestamp.

## 3-hour bundle elements (must complete within 3 hours of Time Zero)

| Element | What | FHIR resource(s) | SepsisGuard tracking |
|---|---|---|---|
| 3a. **Initial lactate** | Serum lactate measured | Observation (LOINC 32693-4 preferred, 2524-7 legacy) | `lactate_initial` |
| 3b. **Blood cultures before antibiotics** | At least one set collected before first abx admin | Specimen + DiagnosticReport (category=micro-bact) | `blood_cultures_before_antibiotics` |
| 3c. **Broad-spectrum antibiotics** | At least one IV broad-spectrum antibiotic administered | MedicationAdministration with RxNorm in BROAD_SPECTRUM_ANTIBIOTICS set | `broad_spectrum_antibiotics` |
| 3d. **30 mL/kg crystalloid** | If hypotensive or lactate ≥ 4 — administer 30 mL/kg of IV crystalloid within 3 hours | MedicationAdministration (LR/NS) summed over the window | `fluid_resuscitation_30ml_kg` |

## 6-hour bundle elements (must complete within 6 hours of Time Zero)

| Element | What | FHIR resource(s) | SepsisGuard tracking |
|---|---|---|---|
| 6a. **Vasopressors** | If hypotension persists after fluid resuscitation — initiate vasopressors to MAP ≥ 65 | MedicationAdministration (norepinephrine, etc.) | `vasopressors_if_persistent_hypotension` |
| 6b. **Repeat lactate** | If initial lactate > 2.0 — remeasure within 6 hours | Observation | `repeat_lactate` |
| 6c. **Volume status reassessment** | Documented physical exam or focused assessment after fluids | DocumentReference / Observation with modality keyword | `volume_status_reassessment` |

## Common abstractor failure modes

These are the audit concerns SepsisGuard's `draft_sep1_documentation` is trained to flag:

1. **Time Zero not stated as a specific timestamp.** The note must say `Time Zero: 2026-05-10T14:32:00Z`, not "this morning".
2. **SIRS criteria not enumerated.** The note must list the values (temp 39.1°C, HR 118, RR 28, WBC 18.4K), not just say "SIRS criteria met".
3. **Lactate drawn at 4h but bundle clock at 0h.** Fails the 3-hr element even though within 6h.
4. **Blood cultures drawn after antibiotic administration.** Fails 3b — must precede first abx admin timestamp.
5. **Fluid given but not crystalloid.** Colloid (albumin, blood products) doesn't count toward 30 mL/kg.
6. **Repeat lactate drawn outside the 6h window.** Fails 6b.
7. **Volume reassessment documented as "patient appears euvolemic"** without specifying modality (PLR, UOP response, CVP, echo, etc.).
8. **MedicationRequest.authoredOn used instead of MedicationAdministration.effectiveDateTime.** Order time is not administration time.
9. **30 mL/kg math missing.** Note must show actual mL infused vs. weight-based target.
10. **Note signed before bundle completion.** Some EHRs auto-sign on save — abstractors look for explicit completion timestamps per element.

## SepsisGuard's documentation phrasing template

The drafted note follows a pattern that scores well on the abstractor rubric:

```
SEP-1 BUNDLE PROGRESS NOTE
Time Zero: <ISO timestamp>
Basis: <SIRS criteria with values+times> + <organ dysfunction with values+times> + <infection documentation source>

Bundle 3-hr status (deadline <ISO>):
  - Lactate: <value> mmol/L @ <time> [Observation/<id>]
  - Blood cultures: collected @ <time> [Specimen/<id>], abx administered @ <time> [MedicationAdministration/<id>] — cx precedes abx
  - Broad-spectrum antibiotics: <drug> <dose> <route> @ <time> [MedicationAdministration/<id>]
  - 30 mL/kg crystalloid: <ml> mL infused / <target> mL required [MedicationAdministration refs]

Bundle 6-hr status (deadline <ISO>):
  - Vasopressors: <status — drug/time or "not indicated, no persistent hypotension after fluid">
  - Repeat lactate: <value> mmol/L @ <time> [Observation/<id>]
  - Volume reassessment: <modality — PLR response, UOP trend, CVP, echo> documented @ <time> [DocumentReference/<id>]

Clinician assessment: <severe sepsis | septic shock> per CMS SEP-1 criteria. Alternative diagnoses considered and ruled out: <list>.

Plan: <next steps>
```

Every clinical claim is annotated with a FHIR resource reference. The CMS abstractor can trace each statement back to a record.

## Hospital VBP scoring impact (FY2026)

SEP-1 is one of several measures in the Hospital VBP "Safety" domain. Per CMS Hospital IQR specifications:
- Hospitals are scored on the percentage of eligible cases that pass abstraction.
- The score is risk-adjusted and benchmarked against national performance.
- A hospital's VBP score modulates a portion of its Medicare reimbursement (typically 2% of base DRG payments).

Math: for a 300-bed acute-care hospital with $200M annual Medicare revenue, a 1-percentage-point improvement in SEP-1 compliance is worth roughly **$200K/yr** in VBP reimbursement.

## References

- CMS Hospital IQR / VBP Program Manuals
- Surviving Sepsis Campaign Guidelines 2021 (Evans et al., Crit Care Med)
- The Joint Commission SEP-1 Specifications (current version)
- IDSA / ATS Hospital-Acquired Pneumonia Guideline (2016, ongoing updates)
- AHRQ HCUP Statistical Brief 316 — Sepsis cost
- Wong et al., External Validation of a Widely Implemented Proprietary Sepsis Prediction Model in Hospitalized Patients (JAMA Internal Med 2021)
