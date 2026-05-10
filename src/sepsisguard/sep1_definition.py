"""SEP-1 bundle definition — clinical criteria, deadlines, and compliance scoring.

This is the most clinically critical file. It encodes CMS SEP-1 as pure Python
dataclasses and functions — no LLM calls, no FHIR I/O. All functions are pure
and unit-testable with synthetic FHIR dicts.

Key gotchas:
- Lactate is in mmol/L in FHIR. Do NOT auto-convert to mg/dL.
- Time Zero = latest of: SIRS-meeting vital, organ-dysfunction lab, infection doc.
- "scheduled" ≠ "in_progress": scheduled = deadline not yet hit; in_progress = order live.
- 30 mL/kg uses actual body weight (not IBW unless > 30% over — we skip IBW math).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, TypedDict

from .loinc import (
    BILIRUBIN_TOTAL,
    BANDS_PCT,
    CREATININE,
    GCS_TOTAL,
    HEART_RATE,
    INR,
    LACTATE_CODES,
    MAP,
    PLATELETS,
    RESP_RATE,
    SBP,
    SPO2_CODES,
    TEMP,
    WBC,
)

# ── SIRS thresholds (spec §5) ─────────────────────────────────────────────────
TEMP_HIGH_C = 38.0       # °C
TEMP_LOW_C = 36.0        # °C
HR_HIGH = 90             # bpm
RR_HIGH = 20             # breaths/min
WBC_HIGH = 12_000        # cells/µL
WBC_LOW = 4_000          # cells/µL
BANDS_HIGH_PCT = 10      # %

# ── Organ dysfunction thresholds ──────────────────────────────────────────────
LACTATE_HIGH = 2.0       # mmol/L
LACTATE_SHOCK = 4.0      # mmol/L (septic shock threshold)
SBP_LOW = 90             # mmHg
MAP_LOW = 65             # mmHg
CREATININE_HIGH = 2.0    # mg/dL (AKI proxy; no baseline adjustment here)
INR_HIGH = 1.5
PLATELETS_LOW = 100_000  # /µL
BILIRUBIN_HIGH = 2.0     # mg/dL


class BundleElement(str, Enum):
    LACTATE_INITIAL = "lactate_initial"
    BLOOD_CULTURES = "blood_cultures"
    BROAD_SPECTRUM_ANTIBIOTICS = "broad_spectrum_antibiotics"
    FLUID_RESUSCITATION = "fluid_resuscitation"
    VASOPRESSORS = "vasopressors"
    REPEAT_LACTATE = "repeat_lactate"
    VOLUME_REASSESSMENT = "volume_reassessment"


# 3-hr elements have 3h deadline; 6-hr elements have 6h deadline (spec §5).
BUNDLE_DEADLINES: dict[BundleElement, timedelta] = {
    BundleElement.LACTATE_INITIAL: timedelta(hours=3),
    BundleElement.BLOOD_CULTURES: timedelta(hours=3),
    BundleElement.BROAD_SPECTRUM_ANTIBIOTICS: timedelta(hours=3),
    BundleElement.FLUID_RESUSCITATION: timedelta(hours=3),
    BundleElement.VASOPRESSORS: timedelta(hours=6),
    BundleElement.REPEAT_LACTATE: timedelta(hours=6),
    BundleElement.VOLUME_REASSESSMENT: timedelta(hours=6),
}


class SirsCriteria(TypedDict):
    temp_abnormal: bool
    hr_elevated: bool
    rr_elevated: bool
    wbc_abnormal: bool
    count_met: int


class BundleStatus(TypedDict):
    time_zero: str
    as_of: str
    minutes_since_time_zero: int
    elements: dict[str, Any]
    overall_compliance: str
    completed_count: int
    total_required: int
    next_at_risk_element: str | None


# ── FHIR observation helpers ──────────────────────────────────────────────────

def _obs_codes(obs: dict[str, Any]) -> frozenset[str]:
    codes: set[str] = set()
    for c in obs.get("code", {}).get("coding", []):
        if c.get("code"):
            codes.add(str(c["code"]))
    return frozenset(codes)


def _extract_obs_value(obs: dict[str, Any]) -> tuple[float | None, str]:
    vq = obs.get("valueQuantity")
    if vq and vq.get("value") is not None:
        return float(vq["value"]), vq.get("unit", "")
    vc = obs.get("valueCodeableConcept")
    if vc:
        return None, vc.get("text", "")
    return None, ""


def _obs_time(obs: dict[str, Any]) -> datetime | None:
    ts = (
        obs.get("effectiveDateTime")
        or obs.get("effectiveInstant")
        or obs.get("issued")
        or obs.get("date")
        or obs.get("authoredOn")
        or obs.get("sent")
        or (obs.get("effectivePeriod") or {}).get("start")
        or (obs.get("collection") or {}).get("collectedDateTime")
    )
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def _to_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


# ── Core clinical functions ───────────────────────────────────────────────────

def evaluate_sirs(observations: list[dict[str, Any]]) -> SirsCriteria:
    """Tally SIRS criteria from a list of FHIR Observation dicts."""
    temp_abnormal = False
    hr_elevated = False
    rr_elevated = False
    wbc_abnormal = False

    for obs in observations:
        codes = _obs_codes(obs)
        value, unit = _extract_obs_value(obs)
        if value is None:
            continue

        if TEMP in codes:
            t = value
            if unit and ("F" in unit.upper() or "fahrenheit" in unit.lower()):
                t = (value - 32) * 5 / 9
            if t > TEMP_HIGH_C or t < TEMP_LOW_C:
                temp_abnormal = True

        if HEART_RATE in codes and value > HR_HIGH:
            hr_elevated = True

        if RESP_RATE in codes and value > RR_HIGH:
            rr_elevated = True

        if WBC in codes:
            # Normalize: values like 18.4 are in K/µL; > 1000 already in /µL
            wbc = value * 1000 if value < 500 else value
            if wbc > WBC_HIGH or wbc < WBC_LOW:
                wbc_abnormal = True

        if BANDS_PCT in codes and value > BANDS_HIGH_PCT:
            wbc_abnormal = True

    count = sum([temp_abnormal, hr_elevated, rr_elevated, wbc_abnormal])
    return SirsCriteria(
        temp_abnormal=temp_abnormal,
        hr_elevated=hr_elevated,
        rr_elevated=rr_elevated,
        wbc_abnormal=wbc_abnormal,
        count_met=count,
    )


def evaluate_organ_dysfunction(
    observations: list[dict[str, Any]],
    baselines: dict[str, float] | None = None,
) -> list[dict[str, Any]]:
    """Return list of {name, value, unit, time} for organ dysfunction markers found."""
    baselines = baselines or {}
    markers: list[dict[str, Any]] = []
    seen: set[str] = set()

    def _add(name: str, value: float, unit: str, time_str: str | None) -> None:
        if name not in seen:
            markers.append({"name": name, "value": value, "unit": unit, "time": time_str})
            seen.add(name)

    for obs in observations:
        codes = _obs_codes(obs)
        value, unit = _extract_obs_value(obs)
        if value is None:
            continue
        ts = _obs_time(obs)
        time_str = ts.isoformat() if ts else None

        if codes & LACTATE_CODES and value > LACTATE_HIGH:
            _add("elevated_lactate", value, unit or "mmol/L", time_str)

        if SBP in codes and value < SBP_LOW:
            _add("hypotension", value, unit or "mmHg SBP", time_str)

        if MAP in codes and value < MAP_LOW:
            _add("low_map", value, unit or "mmHg MAP", time_str)

        if CREATININE in codes and value > CREATININE_HIGH:
            _add("elevated_creatinine", value, unit or "mg/dL", time_str)

        if INR in codes and value > INR_HIGH:
            _add("elevated_inr", value, unit or "", time_str)

        if PLATELETS in codes:
            plt = value * 1000 if value < 1000 else value
            if plt < PLATELETS_LOW:
                _add("thrombocytopenia", plt, "/µL", time_str)

        if BILIRUBIN_TOTAL in codes and value > BILIRUBIN_HIGH:
            _add("elevated_bilirubin", value, unit or "mg/dL", time_str)

    return markers


def severe_sepsis_met(
    sirs: SirsCriteria,
    organ_dysfunction: list[dict[str, Any]],
    has_infection: bool,
) -> bool:
    """True if all three SEP-1 severe sepsis criteria are met."""
    return has_infection and sirs["count_met"] >= 2 and len(organ_dysfunction) >= 1


def septic_shock_met(
    initial_lactate: float | None,
    post_fluid_hypotension: bool,
) -> bool:
    """True if severe sepsis + (lactate ≥ 4 OR persistent hypotension after fluid)."""
    return (initial_lactate is not None and initial_lactate >= LACTATE_SHOCK) or post_fluid_hypotension


def fluid_target_ml(weight_kg: float) -> int:
    """30 mL/kg using actual body weight."""
    return int(30 * weight_kg)


# ── Bundle compliance scoring ─────────────────────────────────────────────────

def score_bundle(
    time_zero: datetime,
    as_of: datetime,
    fhir_record: dict[str, Any],
    weight_kg: float,
) -> BundleStatus:
    """Walk the FHIR record from Time Zero and classify each bundle element."""
    time_zero = _to_utc(time_zero)
    as_of = _to_utc(as_of)
    minutes_elapsed = int((as_of - time_zero).total_seconds() / 60)

    deadlines = {el: time_zero + BUNDLE_DEADLINES[el] for el in BundleElement}

    entries = fhir_record.get("entry", [])
    resources = [e["resource"] for e in entries if e.get("resource")]

    def by_type(rt: str) -> list[dict[str, Any]]:
        return [r for r in resources if r.get("resourceType") == rt]

    observations = by_type("Observation")
    med_admins = by_type("MedicationAdministration")
    med_requests = by_type("MedicationRequest")
    specimens = by_type("Specimen")
    diag_reports = by_type("DiagnosticReport")
    doc_refs = by_type("DocumentReference")

    def _el_status(deadline: datetime, completed_at: datetime | None) -> str:
        if completed_at:
            return "met" if _to_utc(completed_at) <= deadline else "non_compliant"
        return "non_compliant" if as_of > deadline else "scheduled"

    # ── 1. Lactate initial ────────────────────────────────────────────────────
    lactate_obs_all = [o for o in observations if _obs_codes(o) & LACTATE_CODES]
    lactate_post_tz = [
        o for o in lactate_obs_all
        if (t := _obs_time(o)) and _to_utc(t) >= time_zero
    ]
    initial_lactate_value: float | None = None
    first_lactate_time: datetime | None = None

    if lactate_post_tz:
        first = min(lactate_post_tz, key=lambda o: _to_utc(_obs_time(o)))  # type: ignore[arg-type]
        first_lactate_time = _to_utc(_obs_time(first))  # type: ignore[arg-type]
        val, unit = _extract_obs_value(first)
        initial_lactate_value = val
        lactate_element: dict[str, Any] = {
            "status": _el_status(deadlines[BundleElement.LACTATE_INITIAL], first_lactate_time),
            "fhir_ref": f"Observation/{first.get('id', 'unknown')}",
            "value": val,
            "unit": unit,
            "completed_at": first_lactate_time.isoformat(),
            "deadline": deadlines[BundleElement.LACTATE_INITIAL].isoformat(),
        }
    else:
        lactate_element = {
            "status": _el_status(deadlines[BundleElement.LACTATE_INITIAL], None),
            "deadline": deadlines[BundleElement.LACTATE_INITIAL].isoformat(),
        }

    # ── 2. Blood cultures before antibiotics ─────────────────────────────────
    bc_time: datetime | None = None
    bc_refs: list[str] = []

    for r in diag_reports:
        cat_str = str(r.get("category", [])).lower()
        code_str = str(r.get("code", {})).lower()
        if "micro" in cat_str or "culture" in code_str or "blood" in code_str:
            t = _obs_time(r)
            if t and _to_utc(t) >= time_zero:
                t_utc = _to_utc(t)
                if bc_time is None or t_utc < bc_time:
                    bc_time = t_utc
                bc_refs.append(f"DiagnosticReport/{r.get('id', 'unknown')}")

    for s in specimens:
        t = _obs_time(s)
        if t and _to_utc(t) >= time_zero:
            t_utc = _to_utc(t)
            if bc_time is None or t_utc < bc_time:
                bc_time = t_utc
            bc_refs.append(f"Specimen/{s.get('id', 'unknown')}")

    abx_time = _first_abx_time(med_admins, med_requests, time_zero)
    abx_after_cx = abx_time is None or bc_time is None or bc_time <= abx_time

    blood_cx_element: dict[str, Any] = {
        "deadline": deadlines[BundleElement.BLOOD_CULTURES].isoformat(),
        "antibiotic_admin_after_cx": abx_after_cx,
    }
    if bc_time:
        blood_cx_element.update({
            "status": _el_status(deadlines[BundleElement.BLOOD_CULTURES], bc_time),
            "fhir_refs": bc_refs,
            "completed_at": bc_time.isoformat(),
        })
    else:
        blood_cx_element["status"] = _el_status(
            deadlines[BundleElement.BLOOD_CULTURES], None
        )

    # ── 3. Broad-spectrum antibiotics ─────────────────────────────────────────
    abx_dl = deadlines[BundleElement.BROAD_SPECTRUM_ANTIBIOTICS]
    abx_element: dict[str, Any] = {"deadline": abx_dl.isoformat()}
    if abx_time:
        abx_element.update({
            "status": _el_status(abx_dl, abx_time),
            "completed_at": abx_time.isoformat(),
            "minutes_until_deadline": max(0, int((abx_dl - as_of).total_seconds() / 60)),
        })
    else:
        mins = int((abx_dl - as_of).total_seconds() / 60)
        abx_element.update({
            "status": _el_status(abx_dl, None),
            "minutes_until_deadline": mins,
        })

    # ── 4. Fluid resuscitation (30 mL/kg) ─────────────────────────────────────
    fluid_dl = deadlines[BundleElement.FLUID_RESUSCITATION]
    fluid_target = fluid_target_ml(weight_kg)
    fluid_given = _compute_fluid_ml(med_admins, time_zero, fluid_dl)
    fluid_element: dict[str, Any] = {
        "ml_administered": fluid_given,
        "ml_required": fluid_target,
        "deadline": fluid_dl.isoformat(),
    }
    if fluid_given >= fluid_target:
        fluid_element["status"] = "met"
    elif as_of > fluid_dl:
        fluid_element["status"] = "non_compliant"
    else:
        fluid_element["status"] = "in_progress" if fluid_given > 0 else "scheduled"

    # ── 5. Vasopressors ────────────────────────────────────────────────────────
    vasopress_dl = deadlines[BundleElement.VASOPRESSORS]
    has_hypotension = _detect_hypotension(observations, time_zero)
    vp_time = _get_vasopressor_time(med_admins, time_zero)

    if not has_hypotension:
        vasopress_element: dict[str, Any] = {
            "status": "not_yet_required",
            "rationale": "No persistent hypotension detected; vasopressors not yet indicated",
        }
    elif vp_time:
        vasopress_element = {
            "status": _el_status(vasopress_dl, vp_time),
            "completed_at": vp_time.isoformat(),
            "deadline": vasopress_dl.isoformat(),
        }
    else:
        vasopress_element = {
            "status": _el_status(vasopress_dl, None),
            "deadline": vasopress_dl.isoformat(),
            "rationale": "Hypotension present; vasopressors indicated but not yet administered",
        }

    # ── 6. Repeat lactate ─────────────────────────────────────────────────────
    repeat_dl = deadlines[BundleElement.REPEAT_LACTATE]

    if initial_lactate_value is None or initial_lactate_value <= LACTATE_HIGH:
        repeat_lactate_element: dict[str, Any] = {
            "status": "not_yet_required",
            "rationale": "Initial lactate not elevated or not yet measured",
        }
    else:
        # Repeat must be drawn after the first lactate
        repeat_obs = [
            o for o in lactate_obs_all
            if (t := _obs_time(o))
            and first_lactate_time
            and _to_utc(t) > first_lactate_time
        ]
        if repeat_obs:
            r_obs = min(repeat_obs, key=lambda o: _to_utc(_obs_time(o)))  # type: ignore[arg-type]
            r_time = _to_utc(_obs_time(r_obs))  # type: ignore[arg-type]
            repeat_lactate_element = {
                "status": _el_status(repeat_dl, r_time),
                "fhir_ref": f"Observation/{r_obs.get('id', 'unknown')}",
                "completed_at": r_time.isoformat(),
                "deadline": repeat_dl.isoformat(),
            }
        else:
            repeat_lactate_element = {
                "status": _el_status(repeat_dl, None),
                "due_by": repeat_dl.isoformat(),
            }

    # ── 7. Volume reassessment ────────────────────────────────────────────────
    vol_dl = deadlines[BundleElement.VOLUME_REASSESSMENT]
    vol_done = _check_volume_reassessment(doc_refs, observations, time_zero, vol_dl)
    if vol_done:
        vol_element: dict[str, Any] = {"status": "met"}
    else:
        vol_element = {
            "status": _el_status(vol_dl, None),
            "deadline": vol_dl.isoformat(),
        }

    elements: dict[str, Any] = {
        "lactate_initial": lactate_element,
        "blood_cultures_before_antibiotics": blood_cx_element,
        "broad_spectrum_antibiotics": abx_element,
        "fluid_resuscitation_30ml_kg": fluid_element,
        "vasopressors_if_persistent_hypotension": vasopress_element,
        "repeat_lactate": repeat_lactate_element,
        "volume_status_reassessment": vol_element,
    }

    # ── Compliance roll-up ─────────────────────────────────────────────────────
    required = [
        (name, el) for name, el in elements.items()
        if el.get("status") != "not_yet_required"
    ]
    met_count = sum(1 for _, el in required if el.get("status") == "met")
    non_compliant_any = any(el.get("status") == "non_compliant" for _, el in required)

    if non_compliant_any:
        overall = "non_compliant"
    elif met_count == len(required):
        overall = "on_track"
    else:
        # at_risk: any element with <60 min to deadline
        at_risk = any(
            el.get("minutes_until_deadline") is not None
            and 0 <= el["minutes_until_deadline"] < 60
            for _, el in required
        )
        overall = "at_risk" if at_risk else "on_track"

    # Next element to watch (soonest not-yet-met deadline)
    next_at_risk: str | None = None
    pending = [
        (name, el) for name, el in required
        if el.get("status") in ("scheduled", "in_progress")
    ]
    if pending:
        def _dl_key(item: tuple[str, dict[str, Any]]) -> datetime:
            dl = item[1].get("deadline") or item[1].get("due_by")
            if dl:
                try:
                    return _to_utc(datetime.fromisoformat(dl.replace("Z", "+00:00")))
                except (ValueError, TypeError):
                    pass
            return datetime.max.replace(tzinfo=timezone.utc)

        next_at_risk = min(pending, key=_dl_key)[0]

    return BundleStatus(
        time_zero=time_zero.isoformat(),
        as_of=as_of.isoformat(),
        minutes_since_time_zero=minutes_elapsed,
        elements=elements,
        overall_compliance=overall,
        completed_count=met_count,
        total_required=len(required),
        next_at_risk_element=next_at_risk,
    )


# ── Private helpers ───────────────────────────────────────────────────────────

def _get_med_rxnorm_codes(resource: dict[str, Any]) -> frozenset[str]:
    codes: set[str] = set()
    mc = resource.get("medicationCodeableConcept", {})
    for c in mc.get("coding", []):
        if c.get("code"):
            codes.add(str(c["code"]))
    return frozenset(codes)


def _first_abx_time(
    med_admins: list[dict[str, Any]],
    med_requests: list[dict[str, Any]],
    time_zero: datetime,
) -> datetime | None:
    from .rxnorm import BROAD_SPECTRUM_ANTIBIOTICS

    times: list[datetime] = []

    for ma in med_admins:
        if _get_med_rxnorm_codes(ma) & BROAD_SPECTRUM_ANTIBIOTICS:
            t = _obs_time(ma)
            if t and _to_utc(t) >= time_zero:
                times.append(_to_utc(t))

    # MedicationRequest authoredOn as proxy if no administrations yet
    for mr in med_requests:
        if (
            _get_med_rxnorm_codes(mr) & BROAD_SPECTRUM_ANTIBIOTICS
            and mr.get("status") in ("active", "completed")
        ):
            t = _obs_time(mr)
            if t and _to_utc(t) >= time_zero:
                times.append(_to_utc(t))

    return min(times) if times else None


def _compute_fluid_ml(
    med_admins: list[dict[str, Any]],
    time_zero: datetime,
    deadline: datetime,
) -> int:
    from .rxnorm import CRYSTALLOIDS

    total = 0
    for ma in med_admins:
        rxnorm_codes = _get_med_rxnorm_codes(ma)
        if not rxnorm_codes & CRYSTALLOIDS:
            # Fallback: text matching
            text = (
                ma.get("medicationCodeableConcept", {}).get("text", "")
                + str(ma.get("medicationReference", {}).get("display", ""))
            ).lower()
            if not any(
                w in text
                for w in ("lactated ringer", "normal saline", "0.9% nacl", "ns ", "lr ")
            ):
                continue

        t = _obs_time(ma)
        if not t:
            continue
        t_utc = _to_utc(t)
        if not (time_zero <= t_utc <= deadline):
            continue

        dos = ma.get("dosage", {})
        qty = dos.get("dose", {})
        value = qty.get("value")
        unit = qty.get("unit", "").lower()
        if value is not None:
            ml = float(value)
            if unit.startswith("l") and "ml" not in unit:
                ml *= 1000
            total += int(ml)

    return total


def _detect_hypotension(
    observations: list[dict[str, Any]],
    time_zero: datetime,
) -> bool:
    for obs in observations:
        codes = _obs_codes(obs)
        t = _obs_time(obs)
        if t and _to_utc(t) < time_zero:
            continue
        val, _ = _extract_obs_value(obs)
        if val is None:
            continue
        if SBP in codes and val < SBP_LOW:
            return True
        if MAP in codes and val < MAP_LOW:
            return True
    return False


def _get_vasopressor_time(
    med_admins: list[dict[str, Any]],
    time_zero: datetime,
) -> datetime | None:
    from .rxnorm import VASOPRESSORS

    times: list[datetime] = []
    for ma in med_admins:
        if _get_med_rxnorm_codes(ma) & VASOPRESSORS:
            t = _obs_time(ma)
            if t and _to_utc(t) >= time_zero:
                times.append(_to_utc(t))
    return min(times) if times else None


_VOLUME_REASSESSMENT_KEYWORDS = frozenset({
    "volume reassessment", "fluid status", "volume status", "cvp",
    "urine output", "response to fluid", "fluid responsiveness",
    "focused assessment", "passive leg raise",
})


def _check_volume_reassessment(
    doc_refs: list[dict[str, Any]],
    observations: list[dict[str, Any]],
    time_zero: datetime,
    deadline: datetime,
) -> bool:
    for dr in doc_refs:
        t = _obs_time(dr)
        if not t:
            continue
        t_utc = _to_utc(t)
        if not (time_zero <= t_utc <= deadline):
            continue
        # Check category / type text
        dr_text = (
            str(dr.get("category", ""))
            + str(dr.get("type", ""))
            + str(dr.get("description", ""))
        ).lower()
        for c in dr.get("content", []):
            dr_text += (c.get("attachment") or {}).get("title", "").lower() + " "
        if any(kw in dr_text for kw in _VOLUME_REASSESSMENT_KEYWORDS):
            return True
    return False
