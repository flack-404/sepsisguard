"""End-to-end demo runner with in-process FHIR mock.

Two execution modes:
- With ANTHROPIC_API_KEY: runs the full Claude tool-use orchestrator (run_agent).
- Without ANTHROPIC_API_KEY: runs the deterministic spec trajectory directly
  (screen → confirm → score → recommend → drive → notify → draft). Tool stubs
  return seeded outputs from the antibiogram + sep1_definition math.

The FHIR mock uses httpx.MockTransport to intercept all outbound FHIR calls.
Inbound clinical notes are base64-encoded on the fly from data/clinical_notes/
files referenced via DocumentReference.content[0].attachment._data_source_file.

Usage:
    python -m sepsisguard.demo --scenario cap_severe_sepsis
    python -m sepsisguard.demo --scenario all
    python -m sepsisguard.demo --scenario uti_late_onset --format json
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import logging
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv

# Load .env from repo root before any module reads env vars.
load_dotenv(Path(__file__).parent.parent.parent / ".env")

from .audit import audit_log
from .fhir_client import FhirClient
from .sharp_context import (
    REQUIRED_SCOPES,
    SharpContext,
    bind_sharp_context,
    reset_sharp_context,
)
from .tools import (
    confirm_sepsis_diagnosis,
    draft_sep1_documentation,
    drive_bundle_element,
    notify_care_team,
    recommend_antibiotic,
    score_bundle_compliance,
    screen_sepsis_signals,
)

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).parent.parent.parent
_SCENARIOS_DIR = _REPO_ROOT / "data" / "examples"
_CLINICAL_NOTES_DIR = _REPO_ROOT / "data" / "clinical_notes"

_SCENARIO_FILES = {
    "cap_severe_sepsis": "scenario_cap_severe_sepsis.json",
    "uti_late_onset": "scenario_uti_late_onset.json",
    "intra_abdominal_septic_shock": "scenario_intra_abdominal_septic_shock.json",
}


# ── scenario loading ─────────────────────────────────────────────────────────

def load_scenario(scenario_id: str) -> dict[str, Any]:
    fname = _SCENARIO_FILES.get(scenario_id)
    if not fname:
        raise ValueError(
            f"Unknown scenario: {scenario_id}. Available: {list(_SCENARIO_FILES)}"
        )
    path = _SCENARIOS_DIR / fname
    scenario = json.loads(path.read_text(encoding="utf-8"))
    _attach_clinical_notes(scenario)
    _rebase_scenario_times(scenario)
    return scenario


_TIME_FIELDS = (
    "effectiveDateTime", "effectiveInstant", "issued", "date",
    "authoredOn", "sent", "onsetDateTime", "recordedDate",
)


def _rebase_scenario_times(scenario: dict[str, Any]) -> None:
    """Shift every timestamp so the scenario's anchor_time = now - 90 minutes.

    Makes the demo "live" no matter when it runs: bundle scoring with default
    as_of=now() reflects "90 minutes into bundle execution" — half-way through
    the 3-hr window, giving the scoring meaningful in-flight state.
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
    """Replace `_data_source_file` placeholders with base64-encoded note bodies."""
    record = scenario.get("patient_synthetic_record", {})
    for doc in record.get("DocumentReference", []) or []:
        for content in doc.get("content", []) or []:
            attachment = content.get("attachment", {}) or {}
            file_ref = attachment.pop("_data_source_file", None)
            if file_ref and "data" not in attachment:
                note_path = _CLINICAL_NOTES_DIR / file_ref
                try:
                    raw = note_path.read_text(encoding="utf-8")
                    attachment["data"] = base64.b64encode(raw.encode("utf-8")).decode("ascii")
                except FileNotFoundError:
                    logger.warning("Clinical note file not found: %s", note_path)


# ── in-process FHIR mock ─────────────────────────────────────────────────────

def make_mock_fhir_transport(scenario: dict[str, Any]) -> httpx.MockTransport:
    """Return an httpx.MockTransport that serves FHIR R4 calls from the scenario record."""
    record = scenario.get("patient_synthetic_record", {})
    patient_id = scenario.get("patient_id", "")
    # In-memory write store keyed by resourceType
    writes: dict[str, list[dict[str, Any]]] = {}

    def _all_of_type(resource_type: str) -> list[dict[str, Any]]:
        existing = record.get(resource_type)
        if isinstance(existing, dict):
            return [existing]
        if isinstance(existing, list):
            return list(existing)
        return []

    def _searchset(resources: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "resourceType": "Bundle",
            "type": "searchset",
            "entry": [{"resource": r} for r in resources],
        }

    def _filter_by_patient(resources: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for r in resources:
            ref = (
                r.get("subject", {}).get("reference", "")
                or r.get("patient", {}).get("reference", "")
                or r.get("for", {}).get("reference", "")
            )
            if not ref or patient_id in ref:
                out.append(r)
        return out

    def _filter_by_code(resources: list[dict[str, Any]], code: str) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for r in resources:
            codes_field = r.get("code", {}) or {}
            for c in codes_field.get("coding", []) or []:
                if str(c.get("code", "")) == code:
                    out.append(r)
                    break
        return out

    def _filter_by_category(
        resources: list[dict[str, Any]], category: str
    ) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for r in resources:
            cats = r.get("category", []) or []
            if isinstance(cats, dict):
                cats = [cats]
            for cat in cats:
                for c in (cat.get("coding", []) or []) + ([] if not cat else []):
                    if str(c.get("code", "")).lower() == category.lower():
                        out.append(r)
                        break
                else:
                    continue
                break
        return out

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        method = request.method.upper()

        # Strip leading slash + base URL path components
        # We're given absolute URLs like http://mock/Observation?patient=...
        parts = [p for p in path.split("/") if p]
        if not parts:
            return httpx.Response(404, json={"resourceType": "OperationOutcome",
                "issue": [{"severity": "error", "diagnostics": "Empty path"}]})

        resource_type = parts[0]
        resource_id = parts[1] if len(parts) > 1 else None

        if method == "GET":
            existing = _all_of_type(resource_type) + writes.get(resource_type, [])
            if resource_id:
                for r in existing:
                    if r.get("id") == resource_id:
                        return httpx.Response(200, json=r)
                return httpx.Response(404, json={
                    "resourceType": "OperationOutcome",
                    "issue": [{"severity": "error",
                               "diagnostics": f"{resource_type}/{resource_id} not found"}],
                })

            # Search
            qp = dict(request.url.params)
            filtered = _filter_by_patient(existing)
            if "code" in qp:
                filtered = _filter_by_code(filtered, qp["code"])
            if "category" in qp:
                filtered = _filter_by_category(filtered, qp["category"])
            count = int(qp.get("_count", "100"))
            if qp.get("_sort", "").startswith("-date"):
                def _key(r: dict[str, Any]) -> str:
                    return (
                        r.get("effectiveDateTime")
                        or r.get("date")
                        or r.get("authoredOn")
                        or ""
                    )
                filtered = sorted(filtered, key=_key, reverse=True)
            return httpx.Response(200, json=_searchset(filtered[:count]))

        if method == "POST":
            try:
                body = json.loads(request.content.decode("utf-8") or "{}")
            except json.JSONDecodeError as exc:
                return httpx.Response(400, json={
                    "resourceType": "OperationOutcome",
                    "issue": [{"severity": "error", "diagnostics": f"Bad JSON: {exc}"}],
                })
            body.setdefault("id", str(uuid.uuid4()))
            writes.setdefault(resource_type, []).append(body)
            return httpx.Response(201, json=body)

        return httpx.Response(405, json={
            "resourceType": "OperationOutcome",
            "issue": [{"severity": "error", "diagnostics": f"Method {method} not supported"}],
        })

    return httpx.MockTransport(handler)


# ── FHIR client mock injection ───────────────────────────────────────────────

class _MockedFhirClient(FhirClient):
    """FhirClient subclass that mounts an httpx.MockTransport.

    The parent class instantiates its own AsyncClient in __aenter__; we replace
    that AsyncClient's _transport with our mock right after entry.
    """

    def __init__(self, transport: httpx.MockTransport) -> None:
        super().__init__()
        self._mock_transport = transport

    async def __aenter__(self) -> "_MockedFhirClient":  # type: ignore[override]
        await super().__aenter__()
        # Patch the AsyncClient to use the mock transport.
        assert self._client is not None
        await self._client.aclose()
        self._client = httpx.AsyncClient(
            transport=self._mock_transport,
            headers={
                "Authorization": "Bearer demo",
                "Accept": "application/fhir+json",
                "Content-Type": "application/fhir+json",
            },
            timeout=30.0,
        )
        return self


def install_mock_fhir(transport: httpx.MockTransport) -> None:
    """Monkeypatch sepsisguard.fhir_client.FhirClient to use the mock transport."""
    from . import fhir_client as fc_module

    class _Wrapped(_MockedFhirClient):
        def __init__(self) -> None:
            super().__init__(transport)

    fc_module.FhirClient = _Wrapped  # type: ignore[misc]

    # Also patch in modules that imported the name eagerly
    for modname in (
        "sepsisguard.tools.screen_signals",
        "sepsisguard.tools.score_bundle",
        "sepsisguard.tools.drive_bundle_element",
        "sepsisguard.tools.notify_care_team",
        "sepsisguard.tools.recommend_antibiotic",
    ):
        mod = sys.modules.get(modname)
        if mod is not None:
            mod.FhirClient = _Wrapped  # type: ignore[attr-defined]


# ── deterministic trajectory (offline mode) ──────────────────────────────────

async def run_deterministic_trajectory(
    scenario: dict[str, Any],
) -> dict[str, Any]:
    """Walk the default trajectory directly, without an LLM orchestrator.

    All tool implementations are the real ones — only the tool ORDER is
    hardcoded here (mirroring agent_prompt.md's default trajectory). This is
    the path used when no ANTHROPIC_API_KEY is present (the judge's smoke
    test).
    """
    trace: list[dict[str, Any]] = []

    def _record(name: str, output: dict[str, Any]) -> None:
        trace.append({"tool": name, "output": output})

    # 1. screen
    pkt = await screen_sepsis_signals(lookback_hours=72)
    _record("screen_sepsis_signals", pkt)
    if pkt.get("recommendation") == "no_sepsis_signal":
        return {"final_summary": "No sepsis signal detected. STOP.", "trace": trace}

    # 2. confirm
    diag = await confirm_sepsis_diagnosis(screening_packet=pkt)
    _record("confirm_sepsis_diagnosis", diag)
    cls = diag.get("classification", "")
    if cls in ("sepsis_likely_benign_alternative", "insufficient_data"):
        return {
            "final_summary": (
                f"Classification: {cls}. Adjudicator declined to drive the bundle. "
                "Surface to clinician."
            ),
            "trace": trace,
        }

    time_zero = diag.get("time_zero") or datetime.now(tz=timezone.utc).isoformat()
    source = diag.get("infection_source_suspected") or scenario.get(
        "expected_infection_source", "unknown"
    )

    # 3. score — use a scenario-relative "now" so bundle math is meaningful.
    # We're simulating "90 minutes after Time Zero" — half-way through the 3-hr window.
    anchor = scenario.get("anchor_time")
    if anchor:
        try:
            anchor_dt = datetime.fromisoformat(anchor.replace("Z", "+00:00"))
            scenario_now = (anchor_dt + timedelta(minutes=90)).isoformat()
        except ValueError:
            scenario_now = None
    else:
        scenario_now = None
    bundle = await score_bundle_compliance(time_zero=time_zero, as_of=scenario_now)
    _record("score_bundle_compliance", bundle)

    # 4. recommend antibiotic + drive
    abx = await recommend_antibiotic(suspected_source=source)
    _record("recommend_antibiotic", abx)

    elements = bundle.get("elements", {}) or {}
    driven: list[dict[str, Any]] = []
    for el_name, el_state in elements.items():
        status = el_state.get("status", "")
        if status not in ("scheduled", "in_progress"):
            continue
        deadline = el_state.get("deadline") or el_state.get("due_by") or ""
        if not deadline:
            continue

        # Map element key → tool element + role
        element_key = el_name.replace("_initial", "_initial").replace(
            "_before_antibiotics", ""
        ).replace("_if_persistent_hypotension", "").replace("_30ml_kg", "")
        element_key = (
            element_key.replace("blood_cultures_", "blood_cultures")
            .replace("broad_spectrum_antibiotics", "broad_spectrum_antibiotics")
            .replace("fluid_resuscitation", "fluid_resuscitation")
            .replace("vasopressors", "vasopressors")
            .replace("repeat_lactate", "repeat_lactate")
            .replace("volume_status_reassessment", "volume_reassessment")
            .replace("lactate_initial", "lactate_initial")
        )
        role = _role_for_element(element_key)

        try:
            task_result = await drive_bundle_element(
                element=element_key, deadline=deadline, assigned_role=role
            )
            driven.append(task_result)
            _record(f"drive_bundle_element[{element_key}]", task_result)
        except Exception as exc:
            logger.warning("drive_bundle_element(%s) failed: %s", element_key, exc)

    # 5. notify
    level = "urgent" if bundle.get("overall_compliance") in ("at_risk", "non_compliant") else "advisory"
    notif = await notify_care_team(
        level=level,
        audience=["bedside_nurse", "intensivist"],
        subject=f"SEP-1 bundle — {bundle.get('overall_compliance', 'in progress')}",
        body=(
            f"Sepsis classified as {cls}; "
            f"{bundle.get('completed_count', 0)}/{bundle.get('total_required', 0)} elements met. "
            f"Antibiotic plan drafted (clinician sign-off required)."
        ),
        linked_resources=[t["task_ref"] for t in driven],
    )
    _record("notify_care_team", notif)

    # 6. draft documentation
    note = await draft_sep1_documentation(
        diagnosis_packet=diag,
        bundle_status=bundle,
        antibiotic_choice=abx,
        infection_source_evidence=f"Suspected source: {source}",
    )
    _record("draft_sep1_documentation", note)

    final = (
        f"Classification: {cls}\n"
        f"Time Zero: {time_zero}\n"
        f"Source: {source}\n"
        f"Bundle: {bundle.get('overall_compliance', '?')} "
        f"({bundle.get('completed_count', 0)}/{bundle.get('total_required', 0)})\n"
        f"Antibiotics: {', '.join(r.get('medication','?') for r in abx.get('primary_regimen', []))} "
        f"[DRAFT — needs clinician sign-off]\n"
        f"Care team notified ({level}): {len(notif.get('audience', []))} recipients\n"
        f"Predicted CMS score: {note.get('abstractor_compliance_score_predicted', 0.0)}\n"
        f"Audit concerns: {len(note.get('audit_concerns', []))}"
    )

    return {"final_summary": final, "trace": trace}


_ELEMENT_ROLE: dict[str, str] = {
    "lactate_initial": "nurse",
    "blood_cultures": "nurse",
    "broad_spectrum_antibiotics": "nurse",
    "fluid_resuscitation": "nurse",
    "vasopressors": "nurse",
    "repeat_lactate": "nurse",
    "volume_reassessment": "nurse",
}


def _role_for_element(element: str) -> str:
    return _ELEMENT_ROLE.get(element, "nurse")


# ── run_scenario ─────────────────────────────────────────────────────────────

async def run_scenario(scenario_id: str) -> dict[str, Any]:
    """Run one scenario end-to-end. Returns the trace + final summary."""
    scenario = load_scenario(scenario_id)
    transport = make_mock_fhir_transport(scenario)
    install_mock_fhir(transport)

    ctx = SharpContext(
        patient_id=scenario["patient_id"],
        fhir_base_url="http://mock",
        access_token="demo",
        scopes=frozenset(s["name"] for s in REQUIRED_SCOPES),
        trace_id=f"demo-{scenario_id}-{uuid.uuid4().hex[:6]}",
    )
    token = bind_sharp_context(ctx)
    started = datetime.now(tz=timezone.utc)

    try:
        audit_log("demo.scenario.start", trace_id=ctx.trace_id, patient=f"Patient/{ctx.patient_id}")

        # Online (LLM orchestrator) when a key is present; offline fallback otherwise.
        if os.environ.get("ANTHROPIC_API_KEY"):
            from .agent_loop import run_agent
            try:
                agent_result = await run_agent(scenario["prompt"])
                outcome = {
                    "mode": "agent_loop",
                    "final_summary": agent_result.get("final_text", ""),
                    "tool_calls": agent_result.get("tool_calls", []),
                    "telemetry": agent_result.get("telemetry", {}),
                    "iterations": agent_result.get("iterations", 0),
                    "stop_reason": agent_result.get("stop_reason", ""),
                }
            except Exception as exc:
                logger.warning("Agent loop failed (%s); falling back to deterministic", exc)
                deterministic = await run_deterministic_trajectory(scenario)
                outcome = {"mode": "deterministic_fallback", **deterministic}
        else:
            deterministic = await run_deterministic_trajectory(scenario)
            outcome = {"mode": "deterministic_offline", **deterministic}

        audit_log("demo.scenario.end", trace_id=ctx.trace_id, patient=f"Patient/{ctx.patient_id}")

        elapsed = (datetime.now(tz=timezone.utc) - started).total_seconds()
        return {
            "scenario_id": scenario_id,
            "title": scenario.get("title", ""),
            "expected_classification": scenario.get("expected_classification"),
            "expected_source": scenario.get("expected_infection_source"),
            "elapsed_seconds": round(elapsed, 2),
            **outcome,
        }
    finally:
        reset_sharp_context(token)


# ── CLI ──────────────────────────────────────────────────────────────────────

def _print_human(result: dict[str, Any]) -> None:
    print(f"\n══════════════════════════════════════════════════════════════════")
    print(f" Scenario: {result['scenario_id']} — {result['title']}")
    print(f" Mode: {result.get('mode', '?')}    Elapsed: {result['elapsed_seconds']}s")
    print(f" Expected: {result['expected_classification']} ({result['expected_source']})")
    print(f"══════════════════════════════════════════════════════════════════")

    if "tool_calls" in result:
        for i, tc in enumerate(result["tool_calls"], 1):
            err = " ❌" if tc.get("error") else ""
            print(f"  {i:2d}. {tc['name']}{err}  ({tc['duration_ms']}ms)")
            print(f"      → {json.dumps(tc.get('output_summary', {}), default=str)[:120]}")
    elif "trace" in result:
        for i, step in enumerate(result["trace"], 1):
            summary = step["output"]
            # show compact 1-line summary
            keys = list(summary.keys())[:5]
            kv = ", ".join(f"{k}={str(summary.get(k))[:30]}" for k in keys)
            print(f"  {i:2d}. {step['tool']}: {kv}")

    print("\n--- final summary ---")
    print(result.get("final_summary", "(none)"))

    if "telemetry" in result:
        t = result["telemetry"]
        cache_ratio = (
            t.get("total_cache_read_tokens", 0)
            / max(1, t.get("total_input_tokens", 0) + t.get("total_cache_read_tokens", 0))
        )
        print(f"\n--- telemetry ---")
        print(f"  model: {t.get('model')}")
        print(f"  input_tokens: {t.get('total_input_tokens')}")
        print(f"  output_tokens: {t.get('total_output_tokens')}")
        print(f"  cache_read_tokens: {t.get('total_cache_read_tokens')}")
        print(f"  cache_hit_ratio: {round(cache_ratio, 3)}")
        print(f"  wall_seconds: {t.get('wall_seconds')}")


async def _amain(scenarios: list[str], output_format: str) -> int:
    results: list[dict[str, Any]] = []
    for sid in scenarios:
        try:
            r = await run_scenario(sid)
            results.append(r)
            if output_format == "human":
                _print_human(r)
        except Exception as exc:
            logger.exception("Scenario %s raised", sid)
            print(f"❌ Scenario {sid} failed: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 2

    if output_format == "json":
        print(json.dumps(results, indent=2, default=str))
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(prog="sepsisguard-demo")
    parser.add_argument(
        "--scenario",
        default="all",
        help=(
            "Scenario to run: cap_severe_sepsis | uti_late_onset | "
            "intra_abdominal_septic_shock | all"
        ),
    )
    parser.add_argument(
        "--format", choices=["human", "json"], default="human",
        help="Output format.",
    )
    parser.add_argument(
        "--log-level",
        default=os.environ.get("LOG_LEVEL", "WARNING"),
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=args.log_level.upper(),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    if args.scenario == "all":
        scenarios = list(_SCENARIO_FILES.keys())
    else:
        scenarios = [args.scenario]

    sys.exit(asyncio.run(_amain(scenarios, args.format)))


if __name__ == "__main__":
    main()
