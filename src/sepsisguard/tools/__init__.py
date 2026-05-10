"""SepsisGuard MCP tools.

Each tool module exports a SCHEMA dict and an async handler. TOOL_REGISTRY maps
tool name -> (schema, handler) and is consumed by the MCP server's tools/list
and tools/call dispatchers.

Note for Phase 5 (agent loop): schemas use "inputSchema" (MCP convention).
When sending to Anthropic's tool-use API, remap to "input_schema":
    anthropic_tools = [
        {"name": s["name"], "description": s["description"],
         "input_schema": s["inputSchema"]}
        for s, _ in TOOL_REGISTRY.values()
    ]
"""

from __future__ import annotations

# Phase 3 — deterministic tools
from .screen_signals import SCREEN_SEPSIS_SIGNALS_SCHEMA, screen_sepsis_signals
from .score_bundle import SCORE_BUNDLE_COMPLIANCE_SCHEMA, score_bundle_compliance
from .drive_bundle_element import DRIVE_BUNDLE_ELEMENT_SCHEMA, drive_bundle_element
from .notify_care_team import NOTIFY_CARE_TEAM_SCHEMA, notify_care_team

# Phase 4 — Claude-backed tools
from .confirm_diagnosis import CONFIRM_SEPSIS_DIAGNOSIS_SCHEMA, confirm_sepsis_diagnosis
from .recommend_antibiotic import RECOMMEND_ANTIBIOTIC_SCHEMA, recommend_antibiotic
from .draft_documentation import DRAFT_SEP1_DOCUMENTATION_SCHEMA, draft_sep1_documentation

TOOL_REGISTRY: dict = {
    "screen_sepsis_signals":    (SCREEN_SEPSIS_SIGNALS_SCHEMA,    screen_sepsis_signals),
    "confirm_sepsis_diagnosis": (CONFIRM_SEPSIS_DIAGNOSIS_SCHEMA, confirm_sepsis_diagnosis),
    "score_bundle_compliance":  (SCORE_BUNDLE_COMPLIANCE_SCHEMA,  score_bundle_compliance),
    "recommend_antibiotic":     (RECOMMEND_ANTIBIOTIC_SCHEMA,     recommend_antibiotic),
    "drive_bundle_element":     (DRIVE_BUNDLE_ELEMENT_SCHEMA,     drive_bundle_element),
    "draft_sep1_documentation": (DRAFT_SEP1_DOCUMENTATION_SCHEMA, draft_sep1_documentation),
    "notify_care_team":         (NOTIFY_CARE_TEAM_SCHEMA,         notify_care_team),
}
