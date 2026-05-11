# SepsisGuard

> **Multi-agent SEP-1 bundle co-pilot.** Watches the ICU. Drives the bundle. Documents the case.

[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)](pyproject.toml)
[![FHIR R4](https://img.shields.io/badge/FHIR-R4-orange)](https://hl7.org/fhir/R4/)
[![MCP](https://img.shields.io/badge/MCP-2024--11--05-purple)](https://spec.modelcontextprotocol.io/)
[![A2A v1](https://img.shields.io/badge/A2A-v1.0-green)](https://promptopinion.ai)

SepsisGuard is a **FHIR-native multi-agent system** that detects emerging sepsis from structured AND free-text signals, executes the **CMS SEP-1 bundle** in real time, drafts antibiotic regimens for clinician sign-off, and produces **CMS-abstractor-grade documentation** — all in a single Python service that doubles as an MCP server and an A2A v1 agent on the Prompt Opinion platform.

> 🏆 **Built for:** [Agents Assemble — The Healthcare AI Endgame](https://devpost.com/) (Prompt Opinion / Darena Health, May 2026)
> 🩺 **Live MCP endpoint:** `https://sepsisguard-production.up.railway.app/mcp`
> 🎥 **Demo video:** *[TBD]*

---

## ⚡ TL;DR

Sepsis is the **#1 most expensive condition in US hospitals** — **$60B/yr, 350,000 deaths annually**. The deployed industry leader, the Epic Sepsis Model, was published in *JAMA Internal Medicine* missing **two-thirds of cases**. CMS just made SEP-1 a **pay-for-performance measure** under Hospital Value-Based Purchasing for FY2026.

A rule engine cannot catch the misses. **An LLM, reading nursing notes and microbiology reports as comfortably as it reads lab values, can.** SepsisGuard is the proof.

```text
┌────────────────────────────────────────────────────────────────┐
│   screen_sepsis_signals  → confirm_sepsis_diagnosis            │
│         ↓                          ↓                            │
│   SIRS/qSOFA + free text   severe_sepsis | septic_shock        │
│   + organ markers          Time Zero established               │
│         ↓                          ↓                            │
│   score_bundle_compliance ← drive_bundle_element (×N)          │
│         ↓                          ↓                            │
│   FHIR Tasks created      notify_care_team (FHIR Communication)│
│         ↓                          ↓                            │
│   recommend_antibiotic    draft_sep1_documentation             │
│   (clinician sign-off)    (CMS-abstractor grade note)          │
└────────────────────────────────────────────────────────────────┘
```

---

## 🩻 Why this matters

| Metric | Value | Source |
|---|---|---|
| US sepsis deaths annually | **350,000** | CDC |
| US adult sepsis hospitalizations | 1.7 million | CDC |
| US hospital cost (2022) | **$60.0 billion** | AHRQ HCUP |
| Rank among US inpatient conditions by cost | **#1 most expensive** | AHRQ HCUP 2022 |
| Two-year cost growth | +$3.4B | Sepsis Alliance / AHRQ |
| Mortality increase per hour of antibiotic delay | **4–7%** | Surviving Sepsis Campaign 2021 |
| Epic Sepsis Model recall on external validation | **0.33** (missed 67% of cases) | Wong et al., *JAMA Internal Med* 2021 |
| Epic Sepsis Model alert burden | 18% of all admitted patients | Wong et al., 2021 |
| SEP-1 in Hospital Value-Based Purchasing | **FY2026** (active) | CMS Hospital IQR / VBP rules |

**Per-hospital ROI projection:** A 300-bed hospital recovers approximately **$2–3M / yr** through SEP-1 VBP compliance once SepsisGuard captures the cases the structured-only models miss.

---

## 🧠 Why Generative AI

Five reasons a rule engine cannot do this work:

1. **Free-text signals.** The earliest sepsis indicators live in nursing notes ("patient appears unwell, mottled skin, decreased urine output"), microbiology stubs ("gram-negative rods on initial Gram stain"), and radiology conclusions ("findings consistent with pneumonia"). The Epic model fails because it cannot read them. An LLM does.
2. **Trajectory reasoning.** "Is this patient getting worse?" requires comparing serial labs and vitals against baseline and weighing the trend — not a rule, judgment.
3. **Bundle adjudication.** SEP-1 has dozens of failure modes ("hypotension was not persistent — only one reading"; "lactate drawn at 4hr but bundle clock started at 0hr"). Each requires reading multiple FHIR resources together with timestamps and clinical context.
4. **CMS-abstractor narrative.** The abstractor reads chart prose, not structured data. The note must explicitly say "Bundle initiated at 14:32 in response to lactate 4.1 and SBP 86 mmHg consistent with septic shock; antibiotics ordered as cefepime + vancomycin per institutional antibiogram; 30 mL/kg LR initiated; repeat lactate ordered at 16:32."
5. **Step-down judgment.** When does the agent stop driving? Patient improves? Transferred? De-escalated? Not a flowchart.

---

## 🏛 Architecture

**Three deployable artifacts in one Python service:**

1. **MCP Server** — Python + FastAPI exposing 7 tools at `POST /mcp` over JSON-RPC 2.0. Streamable HTTP transport. SHARP context bound from `X-FHIR-*` request headers. Scope-enforced per tool.
2. **A2A v1 Agent Card** at `GET /.well-known/agent-card.json` declaring 3 skills + the `ai.promptopinion/fhir-context` extension with all 15 SMART scopes.
3. **BYO Agent on Prompt Opinion** ("SepsisGuard ICU Co-Pilot") — orchestrates the 7 tools via Gemini (platform default) or Claude.

**Five logical agents** all share an in-process per-request SHARP context:

| Agent | Tool(s) | Role |
|---|---|---|
| **Sentinel** | `screen_sepsis_signals` | FHIR walk: SIRS + qSOFA + free-text triggers + infection evidence |
| **Adjudicator** | `confirm_sepsis_diagnosis` | Claude reasoning over the screening packet; sets Time Zero |
| **Bundle Orchestrator** | `score_bundle_compliance`, `drive_bundle_element`, `notify_care_team` | Drives 3-hr / 6-hr elements; creates FHIR Tasks + Communications |
| **Pharmacist** | `recommend_antibiotic` | Antibiogram + AllergyIntolerance + eGFR → draft regimen with guideline citations |
| **Documentation** | `draft_sep1_documentation` | Cached CMS abstractor rubric → progress note with FHIR-ref citations |

### The 7 MCP tools

1. **`screen_sepsis_signals`** — deterministic FHIR walk, computes SIRS / qSOFA / organ markers, scans nursing notes for free-text triggers.
2. **`confirm_sepsis_diagnosis`** — Claude adjudicates `severe_sepsis | septic_shock | benign_alternative | insufficient_data`; sets Time Zero.
3. **`score_bundle_compliance`** — pure SEP-1 math: walks FHIR record from Time Zero forward, classifies every element.
4. **`recommend_antibiotic`** — Claude + antibiogram + patient AllergyIntolerance/eGFR → draft regimen (always requires clinician sign-off).
5. **`drive_bundle_element`** — creates a FHIR Task for one bundle element with role-specific assignee and bundle-clock-aligned deadline.
6. **`draft_sep1_documentation`** — Claude with the CMS abstractor rubric → structured progress note with predicted compliance score.
7. **`notify_care_team`** — creates a FHIR Communication with priority and audience.

Full architecture diagram in [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md). Tool schemas in [`SEPSISGUARD_BUILD_SPEC.md`](SEPSISGUARD_BUILD_SPEC.md) §7.

---

## 🚀 Quick start

### Run locally (offline demo, no API key required)

```bash
git clone https://github.com/flack-404/sepsisguard
cd sepsisguard
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Run all three demo scenarios with the in-process FHIR mock
python -m sepsisguard.demo --scenario all
```

### Run with real Claude orchestrator

```bash
cp .env.example .env       # paste your ANTHROPIC_API_KEY
python -m sepsisguard.demo --scenario cap_severe_sepsis
```

### Start the MCP server (for platform integration)

```bash
python -m sepsisguard.server --transport sse --port 8080

# Verify
curl http://localhost:8080/health
# → {"status":"ok","name":"sepsisguard","version":"0.1.0"}
```

### Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/` | Server info |
| GET | `/health` | Health check |
| GET | `/.well-known/agent-card.json` | A2A v1 agent card |
| POST | `/mcp` | MCP JSON-RPC (initialize, tools/list, tools/call, agent/run) |
| POST | `/a2a` | A2A v1 message endpoint |
| GET | `/mcp/sse` | Optional SSE keepalive |

---

## 🎬 Three demo scenarios

Three synthetic ICU patients (`data/examples/*.json`). Each exercises a different SepsisGuard capability:

| # | Scenario | Patient | Demonstrates |
|---|---|---|---|
| 1 | **CAP severe sepsis** | Eleanor Martinez, 67F | Canonical path — SIRS 4/4, organ dysfunction, pneumonia, cefepime + vanc |
| 2 | **Hospital UTI (Foley-associated)** | Harold Thompson, 78M POD 4 | **Free-text adjudication wins** — borderline vitals, no infection-coded Condition, agent infers CAUTI from nursing note + urinalysis. Substitutes cefepime for pip-tazo with cross-reactivity rationale for PCN allergy. |
| 3 | **Intra-abdominal septic shock** | Marcus Chen, 54M | **Shock pathway** — lactate 5.8 + MAP 55, classification flips to `septic_shock`, vasopressors scheduled, anaerobic coverage |

Generate FHIR transaction bundles (POST-only, `urn:uuid:` refs) for upload to a Prompt Opinion workspace:

```bash
python scripts/scenarios_to_fhir_bundles.py
# → data/fhir_bundles/{cap,uti,intra_abdominal}*.bundle.json
```

Full clinical detail and expected outcomes in [`docs/DEMO_SCENARIOS.md`](docs/DEMO_SCENARIOS.md).

---

## 🧪 Tests

```bash
PYTHONPATH=src pytest tests/ -v
```

**20 tests, ~60 seconds, no API key required.** Covers infrastructure (SHARP context scope checks, audit log), domain (SEP-1 truth tables, bundle scoring math, antibiogram + PCN allergy substitution), tools (deterministic FHIR walks + Claude stub fallbacks), FastAPI endpoints, and the end-to-end demo path.

---

## 🛡 Safety properties

Hard-coded into the orchestrator prompt and enforced server-side:

- **No fabricated values.** Every clinical claim traces to a tool result; the agent halts on `insufficient_data` rather than guess.
- **No auto-administration.** Every antibiotic recommendation is returned with `needs_clinician_signoff: true`. The platform shows this prominently in the UI.
- **No PHI in conversational output.** The agent refers to "the patient" — never name, MRN, DOB, or address (even though Patient.name is populated for the platform UI).
- **HIPAA-grade audit log.** JSONL append-only at `logs/audit.jsonl`. Records references (`Patient/abc-123`), event names, durations — **never PHI content**. Free-text values >200 chars are truncated as a best-effort guard. See [`docs/HIPAA_COMPLIANCE.md`](docs/HIPAA_COMPLIANCE.md) for the full §164.312 mapping.
- **Scope-enforced FHIR access.** 15 SMART scopes declared in the agent card; `require_scope()` checked before every FHIR I/O.

---

## 📚 Documentation

| Doc | What it covers |
|---|---|
| [`SEPSISGUARD_BUILD_SPEC.md`](SEPSISGUARD_BUILD_SPEC.md) | Full 1,536-line build specification (the source of truth) |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | System diagram, five agents, two cross-cutting concerns |
| [`docs/DEMO_SCENARIOS.md`](docs/DEMO_SCENARIOS.md) | Three scenarios with expected outcomes |
| [`docs/IMPACT_METRICS.md`](docs/IMPACT_METRICS.md) | All stats with citations, per-hospital ROI math |
| [`docs/HIPAA_COMPLIANCE.md`](docs/HIPAA_COMPLIANCE.md) | §164.312 access/audit/integrity/auth/transmission mapping |
| [`docs/SEP1_BUNDLE.md`](docs/SEP1_BUNDLE.md) | CMS abstraction rules + common failure modes + scoring template |
| [`docs/DEPLOY_TO_PROMPT_OPINION.md`](docs/DEPLOY_TO_PROMPT_OPINION.md) | 7-step deploy checklist (Railway + Marketplace) |
| [`PHASES.md`](PHASES.md) | 8-phase development plan (for future contributors) |
| [`CLAUDE.md`](CLAUDE.md) | Agent guidance for Claude Code instances working on this repo |

---

## 📐 Standards implemented

**FHIR R4** · US Core 6.1 · SMART App Launch v2 · **CMS SEP-1** (Hospital VBP FY2026) · **Surviving Sepsis Campaign 2021** · IDSA HAP/UTI/Intra-Abdominal guidelines · **MCP** (Model Context Protocol 2024-11-05) · **A2A v1.0** · **SHARP-on-MCP** · **HIPAA 164.312**

---

## 🗂 Repository layout

```
sepsisguard/
├── src/sepsisguard/
│   ├── server.py             # FastAPI MCP + A2A endpoints
│   ├── agent_loop.py         # Claude tool-use orchestrator
│   ├── sharp_context.py      # Per-request SHARP context (ContextVar)
│   ├── fhir_client.py        # Async FHIR R4 client + scope enforcement
│   ├── claude_client.py      # Anthropic SDK wrapper with prompt caching
│   ├── audit.py              # JSONL audit log (references only, no PHI)
│   ├── sep1_definition.py    # SEP-1 criteria + bundle scoring math
│   ├── antibiogram.py        # Antibiotic regimen selection + allergy logic
│   ├── shadow_abstractor.py  # Claude-as-CMS-abstractor scoring simulator
│   ├── demo.py               # In-process FHIR mock + scenario runner
│   ├── tools/                # The 7 MCP tools
│   ├── loinc.py | rxnorm.py | alert_store.py
├── agent/
│   ├── agent_card.json       # A2A v1 agent card
│   └── agent_prompt.md       # Orchestrator system prompt
├── data/
│   ├── examples/             # 3 scenario JSONs
│   ├── clinical_notes/       # 3 nursing/admit notes (base64-loaded into FHIR DocumentReferences)
│   ├── fhir_bundles/         # 3 uploadable FHIR transaction bundles
│   ├── antibiogram/          # Local antibiogram (organism × drug × susceptibility %)
│   └── sep1_abstractor_rubric.md
├── docs/                     # 6 deep-dive docs
├── demo/                     # Demo UI + video script + recording notes
├── scripts/                  # Bundle generator
├── tests/                    # Pytest suite (20 tests, no API key required)
└── ...                       # LICENSE, README, requirements, Procfile, etc.
```

---

## 🤝 Contributing

This project shipped for the Agents Assemble hackathon (May 2026). Issues and PRs welcome.

**For Claude Code instances working on this repo:** see [`CLAUDE.md`](CLAUDE.md) for the project's load-bearing details and gotchas.

---

## 📜 License

[Apache 2.0](LICENSE) — open source, commercial use permitted.
