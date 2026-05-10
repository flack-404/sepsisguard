"""LOINC code constants for SepsisGuard.

All codes sourced from spec §9 and CMS SEP-1 bundle definition.
"""

from __future__ import annotations

# ── Labs ──────────────────────────────────────────────────────────────────────
LACTATE = "32693-4"          # Lactate [Moles/volume] in Blood (preferred)
LACTATE_LEGACY = "2524-7"    # Lactate [Mass/volume] in Blood (older)
WBC = "6690-2"               # Leukocytes [#/volume] in Blood
BANDS_PCT = "26511-6"        # Band form neutrophils/100 leukocytes in Blood
CREATININE = "2160-0"        # Creatinine [Mass/volume] in Serum or Plasma
INR = "6301-6"               # INR in Platelet poor plasma
PLATELETS = "777-3"          # Platelets [#/volume] in Blood
BILIRUBIN_TOTAL = "1975-2"   # Bilirubin.total [Mass/volume] in Serum or Plasma

# ── Vitals ────────────────────────────────────────────────────────────────────
HEART_RATE = "8867-4"        # Heart rate
SBP = "8480-6"               # Systolic blood pressure
DBP = "8462-4"               # Diastolic blood pressure
MAP = "8478-0"               # Mean blood pressure
RESP_RATE = "9279-1"         # Respiratory rate
TEMP = "8310-5"              # Body temperature
SPO2_1 = "2708-6"            # Oxygen saturation in Arterial blood
SPO2_2 = "59408-5"           # Oxygen saturation by Pulse oximetry
GCS_TOTAL = "9269-2"         # Glasgow coma score total
QSOFA_SCORE = "91348-6"      # qSOFA score

# ── Anthropometrics ───────────────────────────────────────────────────────────
WEIGHT = "29463-7"           # Body weight
EGFR = "33914-3"             # Glomerular filtration rate/1.73 sq M.predicted

# ── Convenience sets ──────────────────────────────────────────────────────────
SPO2 = (SPO2_1, SPO2_2)
SPO2_CODES: frozenset[str] = frozenset(SPO2)

LACTATE_CODES: frozenset[str] = frozenset({LACTATE, LACTATE_LEGACY})

VITAL_CODES: frozenset[str] = frozenset({
    HEART_RATE, SBP, DBP, MAP, RESP_RATE, TEMP, GCS_TOTAL, *SPO2_CODES,
})

ORGAN_DYSFUNCTION_LAB_CODES: frozenset[str] = frozenset({
    *LACTATE_CODES, CREATININE, INR, PLATELETS, BILIRUBIN_TOTAL,
})

ALL_OBSERVED_CODES: frozenset[str] = VITAL_CODES | ORGAN_DYSFUNCTION_LAB_CODES | {WBC, BANDS_PCT}
