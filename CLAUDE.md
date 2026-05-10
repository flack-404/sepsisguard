# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository state

This repo currently contains **only a build specification** — `SEPSISGUARD_BUILD_SPEC.md` (1,536 lines). No source code, tests, or build files exist yet. Future Claude instances are expected to implement SepsisGuard from this spec.

`SEPSISGUARD_BUILD_SPEC.md` is the source of truth. Read the relevant section before implementing anything; do not paraphrase from this CLAUDE.md.

The spec frequently says "copy from AuthBridge" — AuthBridge is a sibling reference codebase that is **not present** in this repo. If shared-infrastructure files (sharp_context, fhir_client, claude_client, audit, server, agent_loop) need to be written and AuthBridge isn't accessible, ask the user how to proceed rather than inventing patterns.

## What's being built

SepsisGuard: a multi-agent FHIR-native system for ICU sepsis bundle execution (CMS SEP-1). Three deployable artifacts in one Python service:
- **MCP server** exposing 7 tools at `/mcp`
- **A2A v1 agent card** at `/.well-known/agent-card.json` declaring 3 skills + the `ai.promptopinion/fhir-context` extension
- **BYO Agent** configured on the Prompt Opinion platform that consumes the 7 tools

Stack: Python 3.12, FastAPI, Anthropic Claude (`claude-opus-4-7`), FHIR R4, MCP, A2A v1.

## Architecture: the load-bearing shape

Five logical agents live in **one Python process** and share a SHARP context bound from inbound HTTP headers:

1. **Sentinel** — screens FHIR observations for SIRS/qSOFA + free-text triggers (tool 1)
2. **Adjudicator** — confirms severe sepsis vs. benign alternatives, sets Time Zero (tool 2)
3. **Bundle Orchestrator** — drives 3hr/6hr SEP-1 elements (tools 3, 5, 7)
4. **Pharmacist** — drafts antibiotic regimen for clinician sign-off (tool 4)
5. **Documentation** — drafts CMS-abstractor-grade SEP-1 progress note (tool 6)

The default agent trajectory is fixed: `screen → confirm → score → (recommend → drive)* → notify → draft`. See spec §14 for the orchestrator system prompt with hard rules (no fabricated values, no auto-administration, no PHI in conversational output, halt on `insufficient_data`).

The 7 tools are: `screen_sepsis_signals`, `confirm_sepsis_diagnosis`, `score_bundle_compliance`, `recommend_antibiotic`, `drive_bundle_element`, `draft_sep1_documentation`, `notify_care_team`. Tools 1 and 3 are deterministic FHIR walks; the other 5 call Claude. Schemas in spec §7; full code template for one tool in §13.

Most clinical correctness lives in `sep1_definition.py` (bundle elements, deadlines, scoring math) and `tools/score_bundle.py`. The spec author flags these as the hard part — code is mechanical.

## Code conventions

- `from __future__ import annotations` at the top of every module (Python 3.10+ compat).
- Type hints required on all public APIs.
- `asyncio_mode = "auto"` is set in `pyproject.toml` — async tests do **not** need `@pytest.mark.asyncio`.
- If you rename or change the signature of any public API used across phases (especially the four infra modules: `sharp_context`, `fhir_client`, `claude_client`, `audit`), document the change at the top of `PHASES.md` so downstream phase authors don't have to chase it.

## Conventions and gotchas the spec is emphatic about

These are the easy-to-miss details that have already burned the spec author:

- **Omit `temperature`** in Claude calls — deprecated for `claude-opus-4-7`.
- **Strip old `cache_control` from tool_result blocks** before each new agent-loop iteration. Anthropic enforces a max of 4 cache breakpoints per request; otherwise breakpoints accumulate across turns. Pattern in spec §12, Pattern 6.
- **Don't use `request: Request` as a FastAPI param** in the `/mcp` and `/a2a` handlers. FastAPI 0.136 + Starlette 1.0 misclassifies it as a query param. Use explicit `Body(...)` and `Header(..., alias=...)` parameters instead. Pattern in spec §12, Pattern 5.
- **SHARP context flows via `contextvars.ContextVar`** — tools read it via `current_sharp_context()`, no threading args. Headers `X-FHIR-Server-URL`, `X-FHIR-Access-Token`, `X-Patient-ID` are bound per request.
- **Audit log records references, never PHI content.** JSONL append-only.
- **FHIR Bundles for upload are POST-only with `urn:uuid:` references** (no client-supplied IDs).
- **Antibiotic recommendations are always drafts.** Never auto-administer.
- **Demo runner uses `httpx.MockTransport`** to intercept FHIR calls — keeps demos offline-runnable without `ANTHROPIC_API_KEY` (gate Claude calls in tools 2/4/6 behind a stub fallback).

## Required SMART scopes

15 scopes total (9 reads + 4 writes + 2 optional). Full list in spec §8. Writes: `user/Task.c`, `user/Communication.c`, `user/DocumentReference.c`, optional `user/MedicationRequest.c`. The Prompt Opinion integration step requires "Select All" on these scopes.

## Project layout (target)

`src/sepsisguard/` package with `tools/` subdirectory for the 7 tool modules; `agent/`, `data/`, `demo/`, `docs/`, `scripts/`, `tests/`, `assets/`, `logs/` siblings. Full tree in spec §11. Cloud entrypoint is `python -m sepsisguard.server`; transport auto-selects to `sse` when `$PORT` is set (Railway), else `stdio`.

## Setup

```bash
# Install package in editable mode with dev deps
pip install -e ".[dev]"

# Copy env template and fill in values
cp .env.example .env
```

## Common commands

```bash
# Lint and format
ruff check src/ tests/
ruff format src/ tests/

# Run all tests
PYTHONPATH=src pytest tests/ -v

# Run a single test
PYTHONPATH=src pytest tests/path/to/test_file.py::test_name -v

# Local server (two equivalent forms after pip install -e)
PYTHONPATH=src python -m sepsisguard.server --transport sse --port 8080
sepsisguard-server --transport sse --port 8080

# Demo (offline, no API key required if stubs are wired — two equivalent forms)
PYTHONPATH=src python -m sepsisguard.demo --scenario cap_severe_sepsis
sepsisguard-demo --scenario uti_late_onset
sepsisguard-demo --scenario intra_abdominal_septic_shock
sepsisguard-demo --scenario all
```

Required env vars: `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL` (default `claude-opus-4-7`), `SEPSISGUARD_TRANSPORT` (auto-selects `sse` when `$PORT` is set), `LOG_LEVEL`, `DEMO_MODE`. `PYTHONPATH=src` is always required (src layout).

## Phase implementation guide

Each phase has a self-contained doc in `docs/phases/` with file lists, spec section pointers, task checklists, and acceptance criteria. Start there before writing any code. The dependency order is: Phase 1 (Infrastructure) → Phase 2 (Domain) → Phases 3 & 4 in parallel → Phase 5 (Orchestration) → Phases 6 & 7 in parallel → Phase 8 (Submission). See `PHASES.md` for the full dependency graph.

## Spec navigation cheatsheet

When implementing, jump directly:
- Tool schemas + return shapes → §7
- SHARP/MCP integration (handshake, scopes, headers, agent card) → §8
- LOINC / RxNorm / SNOMED constants → §9
- Three demo scenarios (CAP, UTI, intra-abdominal shock) → §10
- File tree → §11
- Reusable code patterns (SHARP context, FHIR client, Claude client, audit, server, agent loop, demo mock) → §12
- Full tool implementation template → §13
- Orchestrator system prompt + hard rules → §14
- Step-by-step build checklist (15 stages) → §21
