# CMS SEP-1 Abstractor Rubric — SepsisGuard Prompt Cache

This document is loaded once per process and cached on Anthropic's side (ttl=1h).
It encodes the CMS Hospital IQR SEP-1 abstraction rules as understood by experienced abstractors.

## 1. Time Zero Definition (CMS)

Time Zero is the earliest time the patient met ALL of the following simultaneously:
- Suspected or confirmed infection (Condition code, positive culture, or clinician documentation)
- Two or more SIRS criteria met (temp > 38°C or < 36°C; HR > 90; RR > 20 or PaCO₂ < 32 mmHg; WBC > 12K, < 4K, or > 10% bands)
- At least one organ dysfunction sign (lactate > 2 mmol/L, SBP < 90, MAP < 65, creatinine > 2 mg/dL, INR > 1.5, platelets < 100K, bilirubin > 2 mg/dL, acute altered mentation)

Abstractors use the LATEST of:
- The time of the SIRS-meeting vital sign
- The time of the organ-dysfunction lab result
- The time infection was first documented

Time Zero must be documented explicitly in the progress note. Generic phrases like "patient appeared septic overnight" are insufficient. The note must state the specific time.

## 2. What Counts as "Documented Infection"

Acceptable evidence for infection (in order of strength):
1. Active Condition resource with an infection SNOMED code (pneumonia 233604007, UTI 68566005, bacteremia 5758002, peritonitis 74474003, cellulitis 128045006)
2. Positive blood culture result in a DiagnosticReport
3. Clinician progress note containing explicit language: "sepsis," "infection," "pneumonia," "UTI," "bacteremia," "peritonitis," "cellulitis," or "septic"
4. Active antibiotic MedicationRequest (supportive only — cannot be the sole basis)

Not acceptable alone: fever without documented source, elevated WBC without documented source, nursing concern without physician co-signature.

## 3. Three-Hour Bundle Elements

All three elements must be completed within 3 hours of Time Zero.

### 3a. Serum Lactate
- Must be a serum or arterial lactate (LOINC 32693-4 or 2524-7)
- Unit must be mmol/L (FHIR standard) — do not convert to mg/dL
- Capillary lactate does NOT count
- Collection time (Specimen.collection.collectedDateTime) is the timestamp; resulted time is acceptable if collection time is missing
- If initial lactate ≥ 2 mmol/L, a repeat lactate is required within 6 hours

### 3b. Blood Cultures Before Antibiotics
- Must be drawn BEFORE the first antibiotic dose
- Two separate draw sites required (peripheral or central acceptable)
- Timing evidence: DiagnosticReport.effectiveDateTime or Specimen.collection.collectedDateTime
- If antibiotics were given first, this element fails even if cultures drawn within 3 hours
- Common abstractor trap: antibiotic order time ≠ administration time — use MedicationAdministration, not MedicationRequest

### 3c. Broad-Spectrum Antibiotics
- Must be administered (MedicationAdministration, not just ordered) within 3 hours
- Must cover the suspected source (pneumonia → gram-negative + MRSA; urinary → gram-negative; intra-abdominal → gram-negative + anaerobes)
- Single-agent carbapenems (meropenem, imipenem) count as broad-spectrum alone
- Narrow-spectrum antibiotics (ceftriaxone alone for pneumonia) may fail if Pseudomonas coverage was indicated

## 4. Six-Hour Bundle Elements

### 4a. 30 mL/kg Crystalloid Resuscitation
- Crystalloid only: normal saline (0.9% NaCl) or lactated Ringer's solution
- Colloid (albumin, hetastarch) does NOT count
- Must be administered within 3 hours (CMS changed this from 6h to 3h in 2021 update — verify with current spec)
- Use actual body weight (not IBW) unless > 30% above IBW
- If volume is documented in liters, multiply by 1000 for mL
- Dose spread across multiple administrations counts cumulatively within the window

### 4b. Vasopressors (if indicated)
- Indicated when MAP < 65 after 30 mL/kg fluid OR when initial lactate ≥ 4 mmol/L
- Must be initiated within 6 hours of Time Zero
- Norepinephrine is first-line; dopamine, epinephrine, vasopressin acceptable
- Document the specific MAP target (≥ 65 mmHg) in the note

### 4c. Repeat Lactate (if initial elevated)
- Required only if initial lactate > 2 mmol/L
- Must be drawn within 6 hours of Time Zero (not 6 hours of initial lactate)
- If initial lactate was normal (≤ 2), this element is not required

### 4d. Volume Status Reassessment
- Required after fluid resuscitation
- Acceptable documentation: focused physical exam with fluid tolerance assessment, CVP measurement, passive leg raise result, urine output response, bedside echo
- Must be documented in a progress note or nursing note — verbal communication is insufficient
- Timing: within 6 hours of Time Zero

## 5. Documentation Phrasing That Scores Well

Abstractors look for explicit, timestamped, structured language. Examples that score well:

"Sepsis bundle initiated at 14:32 in response to: HR 118, temp 39.1°C, WBC 18.4 K/µL, and lactate 3.2 mmol/L (Time Zero 14:32). Blood cultures drawn at 14:35 from two peripheral sites. Cefepime 2g IV and vancomycin 1.5g IV administered at 15:05. 30 mL/kg (2400 mL) NS bolus initiated 14:40, completed 15:55. Lactate repeat pending at 20:32."

Avoid: vague timelines, passive voice without timestamps, referring to "the sepsis workup" without specifics.

## 6. What Abstractors Do NOT Count

- Colloid resuscitation for the fluid element
- Oral antibiotics for the antibiotic element
- Antibiotic orders without documented administration
- Blood cultures drawn after antibiotic administration
- Capillary lactate
- Generic "sepsis protocol started" without element-level timestamps
- Vitals charted before the documented Time Zero (cannot retroactively move Time Zero)

## 7. Common Abstractor Failure Modes

- "Lactate at T+4h with bundle clock at T=0" — fails the 3-hr lactate element even if within 6 hours
- Blood culture order time used instead of collection time — often makes cultures appear later than they were
- Fluid documented in nursing notes but not reconciled to the 30 mL/kg math
- Volume reassessment documented in verbal report only — not in the chart
- Time Zero placed at ED triage rather than when sepsis criteria were simultaneously met

## 8. Predicted Compliance Score Guidance

When predicting abstractor_compliance_score_predicted (0.0–1.0):
- 1.0: All elements met within windows, explicit timestamped documentation, Time Zero unambiguous
- 0.8–0.99: All elements met but minor documentation gaps (e.g., volume reassessment lacks explicit CVP)
- 0.6–0.79: Most elements met; one element borderline or documentation unclear
- 0.4–0.59: One element definitively missed or Time Zero ambiguous
- < 0.4: Two or more elements missed or major documentation failure

Flag audit_concerns for any element that will likely fail abstraction review.
