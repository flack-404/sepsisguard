"""Antibiogram loader and regimen selection logic.

This module provides structured antibiotic regimen suggestions seeded from
a local antibiogram JSON. The output feeds tool 4 (recommend_antibiotic),
where Claude refines the selection and cites guidelines.

The antibiogram is DATA, not policy — this module returns structured
suggestions; the LLM produces the human-readable rationale.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_DEFAULT_PATH = Path(__file__).parent.parent.parent / "data" / "antibiogram" / "default_antibiogram.json"


def load_antibiogram(path: str | Path | None = None) -> dict[str, Any]:
    """Load and return the antibiogram JSON from *path* (default: data/antibiogram/default_antibiogram.json)."""
    target = Path(path) if path else _DEFAULT_PATH
    with target.open(encoding="utf-8") as fh:
        return json.load(fh)


def recommend_regimen(
    suspected_source: str,
    *,
    allergies: list[dict[str, Any]],
    egfr: float | None,
    weight_kg: float,
    include_mrsa: bool = True,
    include_pseudomonas: bool = True,
    antibiogram: dict[str, Any],
) -> dict[str, Any]:
    """Return a structured regimen seed for Claude to refine.

    Args:
        suspected_source: One of the source keys in antibiogram["first_line_by_source"].
        allergies: List of FHIR AllergyIntolerance resource dicts.
        egfr: Estimated glomerular filtration rate (mL/min/1.73m²), or None if unavailable.
        weight_kg: Actual body weight in kg.
        include_mrsa: Whether MRSA coverage is clinically indicated.
        include_pseudomonas: Whether anti-pseudomonal coverage is indicated.
        antibiogram: The loaded antibiogram dict from load_antibiogram().

    Returns:
        {primary_regimen, rationale, contraindications_checked, renal_adjustment_needed}
    """
    allergy_flags = _parse_allergy_flags(allergies)
    source = suspected_source.lower().replace("-", "_")
    source_map = antibiogram.get("first_line_by_source", {})

    if source not in source_map:
        source = "unknown"

    source_entry = source_map.get(source, {})

    # Select regimen based on penicillin allergy status
    if allergy_flags["penicillin_anaphylaxis"]:
        drugs = source_entry.get("alt_pcn_allergy", source_entry.get("primary", []))
        pcn_note = "Penicillin anaphylaxis — avoided all penicillins and cephalosporins."
    elif allergy_flags["penicillin_non_anaphylaxis"]:
        # Modern literature accepts cefepime for non-anaphylactic penicillin allergy
        drugs = source_entry.get("primary", [])
        pcn_note = (
            "Non-anaphylactic penicillin allergy — cefepime accepted per cross-reactivity "
            "literature (≤2% structural cross-reactivity with 4th-gen cephalosporins)."
        )
    else:
        drugs = source_entry.get("primary", [])
        pcn_note = None

    # Ensure MRSA coverage
    if include_mrsa and "vancomycin" not in drugs and "linezolid" not in drugs:
        if allergy_flags["vancomycin"]:
            drugs = list(drugs) + ["linezolid"]
        else:
            drugs = list(drugs) + ["vancomycin"]

    # Ensure anti-pseudomonal coverage
    if include_pseudomonas and not any(
        d in drugs for d in ("cefepime", "piperacillin_tazobactam", "meropenem")
    ):
        if not allergy_flags["penicillin_anaphylaxis"]:
            drugs = list(drugs) + ["cefepime"]
        else:
            drugs = list(drugs) + ["meropenem"]

    # Build contraindications list
    contraindications_checked: list[dict[str, str]] = []
    if pcn_note:
        contraindications_checked.append({
            "allergen": "penicillin",
            "severity": "anaphylaxis" if allergy_flags["penicillin_anaphylaxis"] else "non_anaphylactic",
            "decision": pcn_note,
        })
    if allergy_flags["vancomycin"]:
        contraindications_checked.append({
            "allergen": "vancomycin",
            "severity": "documented",
            "decision": "Switched to linezolid for MRSA coverage.",
        })

    # Renal adjustment flag
    renal_adjustment_needed = False
    renal_flagged_drugs: list[str] = []
    if egfr is not None and egfr < 50:
        candidates = {"cefepime", "vancomycin", "piperacillin_tazobactam"}
        renal_flagged_drugs = [d for d in drugs if d in candidates]
        if renal_flagged_drugs:
            renal_adjustment_needed = True

    # Antibiogram susceptibility excerpt for context
    organisms = antibiogram.get("organisms", {})
    relevant_organisms = _relevant_organisms(source)
    antibiogram_excerpt = {
        org: {drug: pct for drug, pct in data.items() if drug in drugs}
        for org, data in organisms.items()
        if org in relevant_organisms
    }

    return {
        "primary_regimen": drugs,
        "rationale": f"Structured seed for {source} source; pending Claude refinement.",
        "contraindications_checked": contraindications_checked,
        "renal_adjustment_needed": renal_adjustment_needed,
        "renal_flagged_drugs": renal_flagged_drugs,
        "egfr": egfr,
        "weight_kg": weight_kg,
        "antibiogram_excerpt": antibiogram_excerpt,
    }


# ── Private helpers ───────────────────────────────────────────────────────────

def _parse_allergy_flags(allergies: list[dict[str, Any]]) -> dict[str, bool]:
    """Extract clinically relevant allergy flags from FHIR AllergyIntolerance resources."""
    flags = {
        "penicillin_anaphylaxis": False,
        "penicillin_non_anaphylaxis": False,
        "vancomycin": False,
        "cephalosporin": False,
    }
    for a in allergies:
        if a.get("clinicalStatus", {}).get("coding", [{}])[0].get("code") not in ("active", None, ""):
            # Skip inactive allergies (some EHRs include "resolved" entries)
            coding = a.get("clinicalStatus", {}).get("coding", [{}])
            if coding and coding[0].get("code") == "inactive":
                continue

        substance = _allergy_substance_text(a).lower()
        criticality = a.get("criticality", "").lower()  # high = anaphylaxis
        reaction_severity = _max_reaction_severity(a)

        is_anaphylaxis = criticality == "high" or reaction_severity == "severe"

        if any(w in substance for w in ("penicillin", "amoxicillin", "ampicillin",
                                         "piperacillin", "nafcillin", "oxacillin")):
            if is_anaphylaxis:
                flags["penicillin_anaphylaxis"] = True
            else:
                flags["penicillin_non_anaphylaxis"] = True

        if "vancomycin" in substance:
            flags["vancomycin"] = True

        if any(w in substance for w in ("cephalosporin", "cefazolin", "ceftriaxone",
                                         "cefepime", "cephalexin")):
            flags["cephalosporin"] = True

    return flags


def _allergy_substance_text(allergy: dict[str, Any]) -> str:
    """Extract the substance name string from an AllergyIntolerance resource."""
    code = allergy.get("code", {})
    for c in code.get("coding", []):
        if c.get("display"):
            return c["display"]
    return code.get("text", "")


def _max_reaction_severity(allergy: dict[str, Any]) -> str:
    """Return the most severe reaction severity string, or empty string."""
    severities = {"mild": 1, "moderate": 2, "severe": 3}
    max_sev = ""
    max_val = 0
    for reaction in allergy.get("reaction", []):
        sev = reaction.get("severity", "").lower()
        if severities.get(sev, 0) > max_val:
            max_val = severities.get(sev, 0)
            max_sev = sev
    return max_sev


def _relevant_organisms(source: str) -> frozenset[str]:
    """Map infection source to likely pathogens for antibiogram excerpt."""
    mapping: dict[str, frozenset[str]] = {
        "pneumonia": frozenset({"Pseudomonas_aeruginosa", "S_aureus_MRSA", "S_aureus_MSSA",
                                 "Klebsiella_pneumoniae"}),
        "urinary": frozenset({"E_coli", "Klebsiella_pneumoniae"}),
        "intra_abdominal": frozenset({"E_coli", "Klebsiella_pneumoniae",
                                       "Pseudomonas_aeruginosa", "S_aureus_MRSA"}),
        "skin_soft_tissue": frozenset({"S_aureus_MRSA", "S_aureus_MSSA"}),
        "central_line": frozenset({"S_aureus_MRSA", "S_aureus_MSSA", "Klebsiella_pneumoniae"}),
        "unknown": frozenset({"E_coli", "Klebsiella_pneumoniae", "Pseudomonas_aeruginosa",
                               "S_aureus_MRSA"}),
    }
    return mapping.get(source, frozenset())
