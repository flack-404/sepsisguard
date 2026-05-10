"""Shadow CMS abstractor — Claude scores a drafted SEP-1 note for compliance.

Mirrors AuthBridge's shadow_payer.py pattern. The drafted progress note from
tool 6 is scored against the same rubric the real CMS abstractor uses.

Used by the demo runner to display a "predicted CMS abstractor score" beside
the agent's drafted note. Has a stub fallback when no API key is set.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from .claude_client import CacheableBlock, ClaudeClient

logger = logging.getLogger(__name__)

_RUBRIC_PATH = Path(__file__).parent.parent.parent / "data" / "sep1_abstractor_rubric.md"

SYSTEM_PROMPT = """You are a CMS abstractor reviewing a SEP-1 progress note for \
Hospital Value-Based Purchasing compliance scoring. You score the note STRICTLY \
against the rubric — you do NOT defer to the writing physician.

Your task: given a drafted progress note + the structured bundle status, predict \
whether the encounter passes SEP-1 abstraction.

Hard rules:
1. Score in [0.0, 1.0]. 0.85+ = passes; 0.70-0.85 = at risk; <0.70 = fails.
2. List each bundle element that you would mark "passed" or "failed".
3. Identify rationale failures: missing Time Zero, vague infection documentation, \
fluid bolus not crystalloid, lactate redrawn outside window, etc.
4. Be terse. No preambles.

Output a single JSON object:
- score: float 0.0-1.0
- passed_elements: array of bundle-element name strings
- failed_elements: array of bundle-element name strings
- rationale: 2-4 sentence prose explaining the score
- specific_concerns: array of strings — concrete abstraction failures
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


async def score_documentation(
    note_text: str,
    bundle_status: dict[str, Any],
) -> dict[str, Any]:
    """Score a drafted progress note against the SEP-1 abstractor rubric."""
    rubric = _load_rubric()

    system_blocks = [
        CacheableBlock(text=SYSTEM_PROMPT, cache=True, ttl="1h"),
        CacheableBlock(text=rubric, cache=True, ttl="1h"),
    ]

    user_payload = {
        "note_text": note_text,
        "bundle_status_summary": {
            "overall_compliance": bundle_status.get("overall_compliance"),
            "completed_count": bundle_status.get("completed_count"),
            "total_required": bundle_status.get("total_required"),
            "elements": {
                name: el.get("status")
                for name, el in (bundle_status.get("elements") or {}).items()
            },
        },
    }
    user_blocks = [CacheableBlock(text=json.dumps(user_payload, indent=2), cache=False)]

    client = ClaudeClient()
    try:
        result = await client.generate(
            system_blocks=system_blocks,
            user_blocks=user_blocks,
            max_tokens=900,
        )
        parsed = _parse_json(result.text)
        parsed.setdefault("score", 0.0)
        parsed.setdefault("passed_elements", [])
        parsed.setdefault("failed_elements", [])
        parsed.setdefault("rationale", "")
        parsed.setdefault("specific_concerns", [])
        parsed["_telemetry"] = {
            "input_tokens": result.input_tokens,
            "cache_read_tokens": result.cache_read_input_tokens,
            "cache_hit_ratio": round(result.cache_hit_ratio, 3),
            "model": client.model,
        }
        return parsed
    except RuntimeError:
        logger.info("Claude unavailable — returning stub score")
        return _stub_score(bundle_status)


def _stub_score(bundle_status: dict[str, Any]) -> dict[str, Any]:
    """Deterministic score derived from structural bundle status when Claude is unavailable."""
    elements = bundle_status.get("elements", {}) or {}
    completed = bundle_status.get("completed_count", 0)
    total = bundle_status.get("total_required", 0) or 1
    base_ratio = completed / total

    passed = [name for name, el in elements.items() if el.get("status") == "met"]
    failed = [
        name for name, el in elements.items()
        if el.get("status") == "non_compliant"
    ]

    # Penalty for any non-compliance
    penalty = 0.15 * len(failed)
    score = max(0.0, min(1.0, base_ratio - penalty))

    if score >= 0.85:
        rationale = "Stub score: bundle elements substantially complete and on-time."
    elif score >= 0.7:
        rationale = "Stub score: bundle on track but at least one element at risk."
    else:
        rationale = "Stub score: bundle has non-compliant elements likely to fail abstraction."

    return {
        "score": round(score, 2),
        "passed_elements": passed,
        "failed_elements": failed,
        "rationale": rationale,
        "specific_concerns": [
            f"{name} deadline passed" for name in failed
        ],
        "_telemetry": {
            "input_tokens": 0, "cache_read_tokens": 0,
            "cache_hit_ratio": 0.0, "model": "stub",
        },
    }


def _parse_json(text: str) -> dict[str, Any]:
    s = text.strip()
    if s.startswith("```"):
        s = s.split("```", 2)[1]
        if s.startswith("json"):
            s = s[4:]
        s = s.rsplit("```", 1)[0]
    start, end = s.find("{"), s.rfind("}")
    if start == -1 or end == -1:
        return {}
    try:
        return json.loads(s[start : end + 1])
    except json.JSONDecodeError:
        return {}
