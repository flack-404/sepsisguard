"""Tool 2: confirm_sepsis_diagnosis — Claude-backed SEP-1 adjudication.

Reads the screening packet from tool 1 and determines:
- severe_sepsis / septic_shock / sepsis_likely_benign_alternative / insufficient_data
- Time Zero (when severe sepsis criteria were first simultaneously met)

Stub fallback: deterministic result when ANTHROPIC_API_KEY is unset + DEMO_MODE=true.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from ..audit import audit_log
from ..claude_client import CacheableBlock, ClaudeClient
from ..sharp_context import current_sharp_context

logger = logging.getLogger(__name__)

CONFIRM_SEPSIS_DIAGNOSIS_SCHEMA = {
    "name": "confirm_sepsis_diagnosis",
    "description": (
        "Adjudicate whether the screened signals constitute severe sepsis or "
        "septic shock per CMS SEP-1 definitions, OR are explained by an "
        "alternative cause. Returns diagnosis classification and Time Zero "
        "(the timestamp severe sepsis criteria were first met). Time Zero "
        "starts the 3-hour and 6-hour bundle clocks."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "screening_packet": {
                "type": "object",
                "description": "Full output of tool 1 (screen_sepsis_signals).",
            },
        },
        "required": ["screening_packet"],
        "additionalProperties": False,
    },
}

SYSTEM_PROMPT = """You are a sepsis adjudication agent embedded in an ICU workflow. \
You read a screening packet built from FHIR data and decide whether the patient meets \
CMS SEP-1 criteria for severe sepsis or septic shock, OR whether the signals are \
explained by a benign alternative.

Hard rules:
1. Severe sepsis requires ALL THREE: (a) suspected/documented infection, \
(b) ≥ 2 SIRS criteria, (c) ≥ 1 organ dysfunction sign.
2. Septic shock requires severe sepsis PLUS persistent hypotension after \
30 mL/kg fluid OR initial lactate ≥ 4.0 mmol/L.
3. Time Zero is the FIRST documented timestamp at which all severe sepsis \
criteria were simultaneously met. Use the LATEST of: SIRS-meeting vital, \
organ-dysfunction lab, or infection documentation.
4. Consider and EXPLICITLY rule out alternatives: post-op fever, alcohol \
withdrawal, neuroleptic malignant syndrome, pancreatitis, anaphylaxis.
5. NEVER invent timestamps or values not present in the screening packet.
6. If the case is ambiguous, return "insufficient_data" and name what you'd \
need — do not guess.

Output a single JSON object with exactly these keys:
- classification: "severe_sepsis" | "septic_shock" | "sepsis_likely_benign_alternative" | "insufficient_data"
- time_zero: ISO 8601 string (or null if not yet established)
- time_zero_basis: short prose explaining which signals established Time Zero
- infection_source_suspected: "pneumonia" | "urinary" | "intra_abdominal" | "skin_soft_tissue" | "central_line" | "unknown"
- alternative_explanations_considered: array of strings
- alternative_explanations_ruled_out: boolean
- confidence: "high" | "medium" | "low"
- next_action: "drive_bundle" | "monitor_recheck_in_2h" | "escalate_to_clinician"
"""


async def confirm_sepsis_diagnosis(
    *, screening_packet: dict[str, Any]
) -> dict[str, Any]:
    ctx = current_sharp_context()
    audit_log(
        "tool.confirm_sepsis_diagnosis",
        trace_id=ctx.trace_id,
        patient=f"Patient/{ctx.patient_id}",
        tool="confirm_sepsis_diagnosis",
    )

    system_blocks = [CacheableBlock(text=SYSTEM_PROMPT, cache=True, ttl="1h")]
    user_blocks = [
        CacheableBlock(
            text=(
                "<screening_packet>\n"
                + json.dumps(screening_packet, indent=2)
                + "\n</screening_packet>\n\nReturn the JSON described in the system prompt."
            ),
            cache=False,
        )
    ]

    client = ClaudeClient()
    try:
        result = await client.generate(
            system_blocks=system_blocks,
            user_blocks=user_blocks,
            max_tokens=1500,
        )
        parsed = _parse_json(result.text)
        parsed.setdefault("classification", "insufficient_data")
        parsed.setdefault("time_zero", None)
        parsed.setdefault("time_zero_basis", "")
        parsed.setdefault("infection_source_suspected", "unknown")
        parsed.setdefault("alternative_explanations_considered", [])
        parsed.setdefault("alternative_explanations_ruled_out", False)
        parsed.setdefault("confidence", "low")
        parsed.setdefault("next_action", "escalate_to_clinician")
        parsed["_telemetry"] = {
            "input_tokens": result.input_tokens,
            "cache_read_tokens": result.cache_read_input_tokens,
            "cache_hit_ratio": round(result.cache_hit_ratio, 3),
            "model": client.model,
        }
        return parsed

    except RuntimeError:
        logger.info("Claude unavailable — returning stub for confirm_sepsis_diagnosis")
        return _stub_response(screening_packet)


def _stub_response(screening_packet: dict[str, Any]) -> dict[str, Any]:
    """Deterministic stub when Claude is unavailable (DEMO_MODE or no API key)."""
    sirs = screening_packet.get("sirs_criteria", {})
    organ = screening_packet.get("organ_dysfunction_markers", [])
    infection = screening_packet.get("infection_evidence", [])
    recommendation = screening_packet.get("recommendation", "")

    has_sirs = sirs.get("count_met", 0) >= 2
    has_organ = len(organ) > 0
    has_infection = len(infection) > 0

    # Determine time_zero candidate from organ dysfunction timestamps
    time_zero = None
    time_zero_basis = ""
    if organ:
        times = [m.get("time") for m in organ if m.get("time")]
        if times:
            time_zero = max(times)  # latest of organ dysfunction markers
            time_zero_basis = (
                f"Stub: latest organ-dysfunction marker time ({organ[0].get('name', 'unknown')})."
            )

    if recommendation == "proceed_to_adjudication" and has_sirs and has_organ and has_infection:
        classification = "severe_sepsis"
        confidence = "medium"
        next_action = "drive_bundle"
    elif recommendation == "no_sepsis_signal":
        classification = "sepsis_likely_benign_alternative"
        confidence = "medium"
        next_action = "monitor_recheck_in_2h"
    else:
        classification = "insufficient_data"
        confidence = "low"
        next_action = "escalate_to_clinician"
        time_zero = None
        time_zero_basis = "Insufficient data to establish Time Zero."

    source = screening_packet.get("infection_evidence", [{}])[0].get("display", "unknown")
    from ..rxnorm import INFECTION_DISPLAY_TO_SOURCE  # type: ignore[attr-defined]
    source_key = "unknown"
    for kw, mapped in INFECTION_DISPLAY_TO_SOURCE.items():
        if kw in source.lower():
            source_key = mapped
            break

    return {
        "classification": classification,
        "time_zero": time_zero,
        "time_zero_basis": time_zero_basis,
        "infection_source_suspected": source_key,
        "alternative_explanations_considered": [
            "post-op fever", "alcohol withdrawal", "pancreatitis"
        ],
        "alternative_explanations_ruled_out": classification != "insufficient_data",
        "confidence": confidence,
        "next_action": next_action,
        "_telemetry": {"input_tokens": 0, "cache_read_tokens": 0, "cache_hit_ratio": 0.0, "model": "stub"},
    }


def _parse_json(text: str) -> dict[str, Any]:
    """Extract the largest top-level JSON object containing classification keys."""
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
    target_keys = {"classification", "time_zero", "infection_source_suspected", "confidence"}
    return max(candidates, key=lambda d: len(set(d.keys()) & target_keys))
