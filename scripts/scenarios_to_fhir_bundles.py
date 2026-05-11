"""Convert scenario JSONs → uploadable FHIR R4 transaction Bundles.

Per spec §17.4 and the hackathon video transcript: the judge uploads our FHIR
Bundle into the Prompt Opinion workspace's FHIR server. The bundle must be
POST-only with urn:uuid: references — no client-supplied resource IDs.

Usage:
    python scripts/scenarios_to_fhir_bundles.py                    # all scenarios
    python scripts/scenarios_to_fhir_bundles.py --scenario cap_severe_sepsis
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

# Time fields to rebase when shifting scenario timestamps to "near now".
_TIME_FIELDS = (
    "effectiveDateTime", "effectiveInstant", "issued", "date",
    "authoredOn", "sent", "onsetDateTime", "recordedDate",
)

_REPO_ROOT = Path(__file__).parent.parent
_SCENARIOS_DIR = _REPO_ROOT / "data" / "examples"
_CLINICAL_NOTES_DIR = _REPO_ROOT / "data" / "clinical_notes"
_OUTPUT_DIR = _REPO_ROOT / "data" / "fhir_bundles"

_SCENARIO_FILES = {
    "cap_severe_sepsis": "scenario_cap_severe_sepsis.json",
    "uti_late_onset": "scenario_uti_late_onset.json",
    "intra_abdominal_septic_shock": "scenario_intra_abdominal_septic_shock.json",
}


def _load_scenario(scenario_id: str) -> dict[str, Any]:
    path = _SCENARIOS_DIR / _SCENARIO_FILES[scenario_id]
    return json.loads(path.read_text(encoding="utf-8"))


def _rebase_scenario_times(scenario: dict[str, Any]) -> None:
    """Shift every timestamp so anchor_time = now - 90 minutes.

    This is critical for platform uploads: without it, the FHIR resources
    are stamped at the scenario's original anchor (2026-05-10) but the
    agent runs against wall-clock "now", so all bundle deadlines have
    already passed and every element scores NON-COMPLIANT.
    """
    anchor_str = scenario.get("anchor_time")
    if not anchor_str:
        return
    try:
        anchor = datetime.fromisoformat(anchor_str.replace("Z", "+00:00"))
    except ValueError:
        return

    target_anchor = datetime.now(tz=timezone.utc) - timedelta(minutes=90)
    offset = target_anchor - anchor

    def _shift(ts: str) -> str:
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            return ts
        return (dt + offset).isoformat()

    def _walk(obj: Any) -> None:
        if isinstance(obj, dict):
            for k, v in list(obj.items()):
                if k in _TIME_FIELDS and isinstance(v, str):
                    obj[k] = _shift(v)
                elif k == "period" and isinstance(v, dict):
                    for pk in ("start", "end"):
                        if isinstance(v.get(pk), str):
                            v[pk] = _shift(v[pk])
                else:
                    _walk(v)
        elif isinstance(obj, list):
            for item in obj:
                _walk(item)

    _walk(scenario.get("patient_synthetic_record", {}))
    scenario["anchor_time"] = target_anchor.isoformat()


def _attach_clinical_notes(scenario: dict[str, Any]) -> None:
    record = scenario.get("patient_synthetic_record", {})
    for doc in record.get("DocumentReference", []) or []:
        for content in doc.get("content", []) or []:
            attachment = content.get("attachment", {}) or {}
            file_ref = attachment.pop("_data_source_file", None)
            if file_ref and "data" not in attachment:
                note_path = _CLINICAL_NOTES_DIR / file_ref
                raw = note_path.read_text(encoding="utf-8")
                attachment["data"] = base64.b64encode(raw.encode("utf-8")).decode("ascii")


def _strip_ids_and_remap(record: dict[str, Any]) -> tuple[dict[str, list[dict[str, Any]]], dict[str, str]]:
    """Strip client-supplied ids; build resource_type → resources + id→urn:uuid map."""
    resources: dict[str, list[dict[str, Any]]] = {}
    id_to_urn: dict[str, str] = {}

    def _process(resource: dict[str, Any]) -> None:
        rt = resource.get("resourceType")
        if not rt:
            return
        old_id = resource.pop("id", None)
        urn = f"urn:uuid:{uuid.uuid4()}"
        if old_id:
            id_to_urn[f"{rt}/{old_id}"] = urn
        resources.setdefault(rt, []).append({"_urn": urn, "resource": resource})

    for rt, val in record.items():
        if isinstance(val, dict):
            _process(val)
        elif isinstance(val, list):
            for item in val:
                if isinstance(item, dict):
                    _process(item)

    return resources, id_to_urn


def _remap_references(obj: Any, id_to_urn: dict[str, str]) -> None:
    """Recursively rewrite 'reference' fields like 'Patient/abc' → 'urn:uuid:...'."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == "reference" and isinstance(v, str) and v in id_to_urn:
                obj[k] = id_to_urn[v]
            else:
                _remap_references(v, id_to_urn)
    elif isinstance(obj, list):
        for item in obj:
            _remap_references(item, id_to_urn)


def build_bundle(scenario: dict[str, Any]) -> dict[str, Any]:
    record = scenario.get("patient_synthetic_record", {})
    resources, id_to_urn = _strip_ids_and_remap(record)

    entries: list[dict[str, Any]] = []
    for rt, items in resources.items():
        for item in items:
            res = item["resource"]
            urn = item["_urn"]
            _remap_references(res, id_to_urn)
            entries.append({
                "fullUrl": urn,
                "resource": {"resourceType": rt, **res},
                "request": {"method": "POST", "url": rt},
            })

    return {
        "resourceType": "Bundle",
        "type": "transaction",
        "entry": entries,
    }


def main() -> int:
    parser = argparse.ArgumentParser(prog="scenarios_to_fhir_bundles")
    parser.add_argument(
        "--scenario",
        default="all",
        help="Scenario to convert: <id> | all (default).",
    )
    parser.add_argument(
        "--output-dir", default=str(_OUTPUT_DIR),
        help=f"Output directory (default {_OUTPUT_DIR}).",
    )
    args = parser.parse_args()

    targets = (
        list(_SCENARIO_FILES) if args.scenario == "all" else [args.scenario]
    )
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    for sid in targets:
        if sid not in _SCENARIO_FILES:
            print(f"❌ Unknown scenario: {sid}", file=sys.stderr)
            return 2
        scenario = _load_scenario(sid)
        _attach_clinical_notes(scenario)
        _rebase_scenario_times(scenario)
        bundle = build_bundle(scenario)
        out_path = out_dir / f"{sid}.bundle.json"
        out_path.write_text(json.dumps(bundle, indent=2), encoding="utf-8")
        anchor = scenario.get("anchor_time", "?")[:19]
        print(f"✅ {sid}: {len(bundle['entry'])} entries → {out_path} (anchor: {anchor}Z)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
