# Phase 7 — Testing & Quality

> **Goal:** Smoke-test every layer with `pytest`. Catch import errors, broken signatures, and obvious clinical-logic regressions before submission.
> **Effort:** ~half a day to a day.

This phase is intentionally lightweight — it's a hackathon, not a production rollout. The goal is "the demo doesn't crash" and "the bundle scoring is sane." Don't aim for high coverage.

## Prerequisites

- Phases 1–5 merged (modules exist to test).
- Phase 6 partially done is OK — the FHIR mock from `demo.py` is reused here.

## Files to create

```
tests/
├── test_tools.py             ← smoke tests + clinical-logic spot checks
└── conftest.py               ← shared fixtures (SHARP context, FHIR mock)
```

## Spec sections to read first

- **§18** — required test list.
- **§12 Pattern 7** — how to mount the FHIR mock.

## Task breakdown

### 7.1 `tests/conftest.py`

- [ ] Pytest fixtures:
  - `bound_sharp_context` — yields a SharpContext with all 15 scopes granted, mock FHIR URL, dummy token. Resets after the test.
  - `cap_scenario` — loads `data/examples/scenario_cap_severe_sepsis.json`.
  - `mock_fhir_transport(cap_scenario)` — returns the `httpx.MockTransport` from `demo.make_mock_fhir_transport`.
  - `monkeypatch_audit_log(tmp_path, monkeypatch)` — sets `SEPSISGUARD_AUDIT_LOG` to a tmp file.
- [ ] `pytest_plugins = ["pytest_asyncio"]` if not picked up from `pyproject.toml`.

### 7.2 `tests/test_tools.py`

Cover spec §18's required tests, plus a few clinical-logic spot-checks.

- [ ] **Infrastructure**
  - `test_sharp_context_scope_check` — bind context with `["patient/Patient.rs"]`, `require_scope("patient/Patient.rs")` passes, `require_scope("user/Task.c")` raises `PermissionError`.
  - `test_audit_log_writes_records(tmp_path, monkeypatch)` — `audit_log("test.evt", trace_id="t1", patient="Patient/x")` produces one valid JSON line at the expected path.

- [ ] **Domain layer**
  - `test_loinc_constants_resolve` — `import sepsisguard.loinc; assert loinc.LACTATE == "32693-4"`.
  - `test_sep1_definition_loads` — `evaluate_sirs` against CAP scenario observations returns `count_met == 4`.
  - `test_severe_sepsis_criteria` — covers severe sepsis truth table (3 positive cases + 2 negatives).
  - `test_septic_shock_lactate_threshold` — `septic_shock_met(initial_lactate=5.8, post_fluid_hypotension=False)` returns `True`. With `initial_lactate=3.5, post_fluid_hypotension=False` returns `False`.
  - `test_score_bundle_with_synthetic_data` — given a synthetic FHIR record with lactate@T+25min, blood cx@T+15min, antibiotics@T+90min: `score_bundle` returns `lactate_initial.status == "met"`, `blood_cultures_before_antibiotics.status == "met"`, `antibiotic_admin_after_cx == True`.
  - `test_antibiogram_lookup_pneumonia` — `recommend_regimen("pneumonia", allergies=[], egfr=80, weight_kg=70, include_mrsa=True, include_pseudomonas=True, antibiogram=load_antibiogram())` returns regimen with cefepime + vancomycin.
  - `test_antibiogram_pcn_allergy` — same call but with anaphylactic penicillin allergy still produces an acceptable regimen (cefepime per cross-reactivity literature).

- [ ] **Tools (deterministic)**
  - `test_screen_sepsis_signals_cap_scenario(bound_sharp_context, mock_fhir_transport)` — returns `recommendation == "proceed_to_adjudication"`, `sirs_criteria.count_met >= 2`, at least one organ_dysfunction_marker, free-text trigger from the admit note.
  - `test_drive_bundle_element_creates_task(bound_sharp_context, mock_fhir_transport)` — call returns `task_ref` starting with `Task/`. Mock transport recorded one POST to `/Task`.
  - `test_notify_care_team_creates_communication(bound_sharp_context, mock_fhir_transport)` — `level="urgent"` is mapped to `priority: "urgent"` on the FHIR Communication.

- [ ] **Tools (Claude-backed, stub mode)**
  - Set `monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)` and `monkeypatch.setenv("DEMO_MODE", "true")`.
  - `test_confirm_diagnosis_stub_severe_sepsis` — given the CAP screening packet, stub returns `classification == "severe_sepsis"` with a Time Zero string.
  - `test_recommend_antibiotic_stub_pneumonia` — stub returns regimen including cefepime.
  - `test_draft_documentation_stub_assembles_note` — stub returns `note_text` that mentions Time Zero.

- [ ] **End-to-end**
  - `test_demo_runs_cap_scenario_without_anthropic_key(monkeypatch, tmp_path)` — `demo.run_scenario("cap_severe_sepsis")` returns successfully with `expected_classification == "severe_sepsis"`. **This is the smoke test that the Devpost reviewer effectively runs.** It must pass with no API key.

- [ ] **Server**
  - `test_health_endpoint_returns_ok` — TestClient `GET /health` → 200, `{"status": "ok"}`.
  - `test_agent_card_lists_three_skills` — `GET /.well-known/agent-card.json` → 3 skills.
  - `test_mcp_initialize_declares_extension` — `POST /mcp` with initialize method → response includes `extensions["ai.promptopinion/fhir-context"]` with non-empty `scopes`.
  - `test_mcp_tools_list_returns_seven_tools` — `tools/list` returns 7 schemas.

### 7.3 Type checking and linting (optional, recommended)

- [ ] `ruff check src/ tests/` clean.
- [ ] `ruff format --check src/ tests/` clean.
- [ ] If using mypy: `mypy src/sepsisguard --ignore-missing-imports` clean. (Not blocking; hackathon scope.)

## Key patterns and gotchas

- **`pytest_asyncio` mode is `auto`** (set in `pyproject.toml`). Tests with `async def` work without a decorator.
- **Tests must run with no API key.** If a single test calls Anthropic without a stub gate, CI breaks — and the Devpost reviewer's smoke test breaks.
- **The FHIR mock is per-test.** Don't share state across tests. The `mock_fhir_transport` fixture should rebuild the in-memory record fresh each time.
- **Audit log writes accumulate across tests** unless you point them to `tmp_path`. The `monkeypatch_audit_log` fixture handles this; use it everywhere a tool is called.
- **Clinical truth tables matter more than coverage percent.** A passing test for `severe_sepsis_met(SIRS=1, organ=2, infection=True)` returning `False` is more valuable than 100 trivial assertions.
- **Don't assert against Claude output strings** — they vary. Assert on structural fields (`classification`, `time_zero` parses as ISO 8601, `note_text` contains "Time Zero").

## Acceptance criteria

- [ ] `pytest tests/ -v` — all green with no `ANTHROPIC_API_KEY` set.
- [ ] `pytest tests/ -v` — all green with `ANTHROPIC_API_KEY` set (the same tests, just exercising real Claude in tool 2/4/6 if you choose to enable that path).
- [ ] Test count ≥ 15 distinct cases.
- [ ] Total runtime < 30 seconds without API key (stub fallbacks are fast).
- [ ] No test depends on network access except the optional Claude-key path.

## Handoff to next phase

Phase 8 will run `pytest tests/ -v` as a Railway pre-deploy step. If you add a new test file, add it to `[tool.pytest.ini_options].testpaths` in `pyproject.toml` (currently `["tests"]` — already correct).
