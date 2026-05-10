"""Tool 6: draft_sep1_documentation — Claude-backed CMS-abstractor-grade progress note.

Loads the SEP-1 abstractor rubric as a second cached system block (prompt cache win).
Stub fallback when ANTHROPIC_API_KEY is unset.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from ..audit import audit_log
from ..claude_client import CacheableBlock, ClaudeClient
from ..sharp_context import current_sharp_context

logger = logging.getLogger(__name__)

_RUBRIC_PATH = Path(__file__).parent.parent.parent.parent / "data" / "sep1_abstractor_rubric.md"

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
            "diagnosis_packet": {
                "type": "object",
                "description": "Output of confirm_sepsis_diagnosis.",
            },
            "bundle_status": {
                "type": "object",
                "description": "Output of score_bundle_compliance.",
            },
            "antibiotic_choice": {
                "type": "object",
                "description": "Output of recommend_antibiotic (optional).",
            },
            "infection_source_evidence": {
                "type": "string",
                "description": "Free-text summary of source-of-infection evidence (optional).",
            },
        },
        "required": ["diagnosis_packet", "bundle_status"],
        "additionalProperties": False,
    },
}

SYSTEM_PROMPT = """You are a clinical documentation specialist writing a structured \
progress note for CMS SEP-1 abstraction review. The note will be read by a CMS \
abstractor to score SEP-1 compliance.

Hard rules:
1. ALWAYS state Time Zero explicitly with the exact ISO timestamp.
2. Enumerate every severe-sepsis criterion that was met: infection source, SIRS \
criteria count and values, organ dysfunction sign(s).
3. For every bundle element: state status (met/in_progress/non_compliant), timestamp \
of completion (if met), and the FHIR resource reference.
4. Every non-trivial factual claim must reference a FHIR resource id (e.g., \
"Lactate 3.2 mmol/L [Observation/lactate-1]").
5. Predict abstractor_compliance_score_predicted (0.0–1.0) per the rubric.
6. List audit_concerns for anything that would likely fail abstraction.
7. Refer to "the patient" — never use name, MRN, DOB, or address.
8. Tone: terse, structured, ICU-shorthand acceptable. No preambles or apologies.

Output a single JSON object:
- note_text: prose progress note (~600-900 words, structured sections)
- structured_sections: object with keys: time_zero_documented, severe_sepsis_criteria_met, \
infection_source, bundle_3hr_status, bundle_6hr_status, clinician_assessment, plan
- cited_evidence: array of {claim, source} — source is a FHIR ref string
- abstractor_compliance_score_predicted: float 0.0-1.0
- audit_concerns: array of strings (empty if none)
"""

_RUBRIC_TEXT: str | None = None


def _load_rubric() -> str:
    global _RUBRIC_TEXT
    if _RUBRIC_TEXT is None:
        try:
            _RUBRIC_TEXT = _RUBRIC_PATH.read_text(encoding="utf-8")
        except FileNotFoundError:
            logger.warning("Abstractor rubric not found at %s; using empty string", _RUBRIC_PATH)
            _RUBRIC_TEXT = ""
    return _RUBRIC_TEXT


async def draft_sep1_documentation(
    *,
    diagnosis_packet: dict[str, Any],
    bundle_status: dict[str, Any],
    antibiotic_choice: dict[str, Any] | None = None,
    infection_source_evidence: str | None = None,
) -> dict[str, Any]:
    ctx = current_sharp_context()
    audit_log(
        "tool.draft_sep1_documentation",
        trace_id=ctx.trace_id,
        patient=f"Patient/{ctx.patient_id}",
        tool="draft_sep1_documentation",
    )

    rubric = _load_rubric()

    system_blocks = [
        CacheableBlock(text=SYSTEM_PROMPT, cache=True, ttl="1h"),
        CacheableBlock(text=rubric, cache=True, ttl="1h"),
    ]

    user_payload: dict[str, Any] = {
        "diagnosis_packet": diagnosis_packet,
        "bundle_status": bundle_status,
    }
    if antibiotic_choice is not None:
        user_payload["antibiotic_choice"] = antibiotic_choice
    if infection_source_evidence:
        user_payload["infection_source_evidence"] = infection_source_evidence

    user_blocks = [
        CacheableBlock(text=json.dumps(user_payload, indent=2), cache=False)
    ]

    client = ClaudeClient()
    try:
        result = await client.generate(
            system_blocks=system_blocks,
            user_blocks=user_blocks,
            max_tokens=6000,
        )
        parsed = _parse_json(result.text)
        parsed.setdefault("note_text", "")
        parsed.setdefault("structured_sections", {})
        parsed.setdefault("cited_evidence", [])
        parsed.setdefault("abstractor_compliance_score_predicted", 0.0)
        parsed.setdefault("audit_concerns", [])
        parsed["_telemetry"] = {
            "input_tokens": result.input_tokens,
            "cache_read_tokens": result.cache_read_input_tokens,
            "cache_hit_ratio": round(result.cache_hit_ratio, 3),
            "model": client.model,
        }
        return parsed

    except RuntimeError:
        logger.info("Claude unavailable — returning stub for draft_sep1_documentation")
        return _stub_response(diagnosis_packet, bundle_status, antibiotic_choice)


def _stub_response(
    diagnosis_packet: dict[str, Any],
    bundle_status: dict[str, Any],
    antibiotic_choice: dict[str, Any] | None,
) -> dict[str, Any]:
    classification = diagnosis_packet.get("classification", "unknown")
    time_zero = diagnosis_packet.get("time_zero", "unknown")
    time_zero_basis = diagnosis_packet.get("time_zero_basis", "")
    source = diagnosis_packet.get("infection_source_suspected", "unknown")
    overall = bundle_status.get("overall_compliance", "unknown")
    completed = bundle_status.get("completed_count", 0)
    total = bundle_status.get("total_required", 7)

    abx_line = ""
    if antibiotic_choice and antibiotic_choice.get("primary_regimen"):
        drugs = ", ".join(
            r.get("medication", "?") for r in antibiotic_choice["primary_regimen"]
        )
        abx_line = f"Antibiotics ordered: {drugs}. "

    # Build element summary lines
    elements = bundle_status.get("elements", {})
    element_lines: list[str] = []
    for name, el in elements.items():
        status = el.get("status", "unknown")
        completed_at = el.get("completed_at", "")
        fhir_ref = el.get("fhir_ref", "")
        line = f"  - {name}: {status}"
        if completed_at:
            line += f" at {completed_at}"
        if fhir_ref:
            line += f" [{fhir_ref}]"
        element_lines.append(line)

    note_text = (
        f"SEPSIS BUNDLE PROGRESS NOTE (STUB — Claude unavailable)\n\n"
        f"Classification: {classification}\n"
        f"Time Zero: {time_zero}\n"
        f"Basis: {time_zero_basis}\n"
        f"Suspected source: {source}\n\n"
        f"Bundle compliance: {overall} ({completed}/{total} elements met)\n"
        f"{abx_line}\n"
        "Bundle elements:\n" + "\n".join(element_lines)
    )

    # Collect any audit concerns from non-compliant elements
    audit_concerns = [
        f"{name} is non-compliant — deadline passed"
        for name, el in elements.items()
        if el.get("status") == "non_compliant"
    ]

    return {
        "note_text": note_text,
        "structured_sections": {
            "time_zero_documented": time_zero,
            "severe_sepsis_criteria_met": time_zero_basis,
            "infection_source": source,
            "bundle_3hr_status": overall,
            "bundle_6hr_status": overall,
            "clinician_assessment": f"{classification} — stub note",
            "plan": "Await clinician review.",
        },
        "cited_evidence": [],
        "abstractor_compliance_score_predicted": 0.7,
        "audit_concerns": audit_concerns,
        "_telemetry": {"input_tokens": 0, "cache_read_tokens": 0, "cache_hit_ratio": 0.0, "model": "stub"},
    }


def _parse_json(text: str) -> dict[str, Any]:
    """Extract the largest top-level JSON object containing documentation keys."""
    s = text.strip()
    if s.startswith("```"):
        s = s.split("```", 2)[1]
        if s.startswith("json"):
            s = s[4:]
        s = s.rsplit("```", 1)[0]

    candidates: list[dict[str, Any]] = []
    depth = 0
    start_idx = -1
    for i, ch in enumerate(s):
        if ch == "{":
            if depth == 0:
                start_idx = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start_idx != -1:
                try:
                    candidates.append(json.loads(s[start_idx : i + 1]))
                except json.JSONDecodeError:
                    pass
                start_idx = -1

    if not candidates:
        return {}
    target_keys = {
        "note_text", "structured_sections", "cited_evidence",
        "abstractor_compliance_score_predicted", "audit_concerns",
    }
    return max(candidates, key=lambda d: len(set(d.keys()) & target_keys))
