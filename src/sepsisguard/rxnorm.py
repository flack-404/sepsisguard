"""RxNorm codes for antibiotics, vasopressors, and fluids.

SNOMED condition codes are included here for hackathon scope; they would
move to snomed.py in a production codebase.

All codes sourced from spec §9.
"""

from __future__ import annotations

# ── Antibiotics ───────────────────────────────────────────────────────────────
CEFEPIME_2G_IV = "309027"
VANCOMYCIN_IV = "11124"
PIPERACILLIN_TAZOBACTAM = "31700"
MEROPENEM = "6753"
LINEZOLID = "190376"
LEVOFLOXACIN = "82122"
METRONIDAZOLE = "41493"
CEFAZOLIN = "20489"
NAFCILLIN = "7454"
CEFTRIAXONE = "309362"

# ── Vasopressors ──────────────────────────────────────────────────────────────
NOREPINEPHRINE = "7512"
EPINEPHRINE = "3992"
VASOPRESSIN = "11149"
DOPAMINE = "3628"

# ── IV Fluids (crystalloids) ──────────────────────────────────────────────────
LACTATED_RINGERS = "142436"
NORMAL_SALINE = "27303"

# ── Category sets ─────────────────────────────────────────────────────────────
BROAD_SPECTRUM_ANTIBIOTICS: frozenset[str] = frozenset({
    CEFEPIME_2G_IV, VANCOMYCIN_IV, PIPERACILLIN_TAZOBACTAM, MEROPENEM,
    LINEZOLID, LEVOFLOXACIN, METRONIDAZOLE, CEFTRIAXONE,
})

CRYSTALLOIDS: frozenset[str] = frozenset({LACTATED_RINGERS, NORMAL_SALINE})

VASOPRESSORS: frozenset[str] = frozenset({
    NOREPINEPHRINE, EPINEPHRINE, VASOPRESSIN, DOPAMINE,
})

# ── SNOMED codes for conditions ───────────────────────────────────────────────
# (Tucked here for hackathon scope; these would live in snomed.py in production.)
SNOMED_SEVERE_SEPSIS = "449868000"
SNOMED_SEPTIC_SHOCK = "76571007"
SNOMED_PNEUMONIA = "233604007"
SNOMED_UTI = "68566005"
SNOMED_BACTEREMIA = "5758002"
SNOMED_INTRA_ABDOMINAL = "74474003"   # Peritonitis / intra-abdominal infection
SNOMED_CELLULITIS = "128045006"

INFECTION_SNOMED_CODES: frozenset[str] = frozenset({
    SNOMED_PNEUMONIA, SNOMED_UTI, SNOMED_BACTEREMIA,
    SNOMED_INTRA_ABDOMINAL, SNOMED_CELLULITIS,
    "40733004",   # infectious disease
    "87628006",   # bacterial infectious disease (general)
    "281390002",  # healthcare-associated infection
})

# Display names for common infection sources (used in antibiogram lookup keys)
INFECTION_DISPLAY_TO_SOURCE = {
    "pneumonia": "pneumonia",
    "community acquired pneumonia": "pneumonia",
    "cap": "pneumonia",
    "hospital acquired pneumonia": "pneumonia",
    "hap": "pneumonia",
    "urinary tract infection": "urinary",
    "uti": "urinary",
    "foley": "urinary",
    "cauti": "urinary",
    "intra-abdominal": "intra_abdominal",
    "intra_abdominal": "intra_abdominal",
    "abdominal": "intra_abdominal",
    "peritonitis": "intra_abdominal",
    "perforated": "intra_abdominal",
    "cellulitis": "skin_soft_tissue",
    "skin": "skin_soft_tissue",
    "soft tissue": "skin_soft_tissue",
    "central line": "central_line",
    "clabsi": "central_line",
    "line": "central_line",
    "bacteremia": "unknown",
}
