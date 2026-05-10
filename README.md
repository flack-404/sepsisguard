# SepsisGuard

> Multi-agent SEP-1 bundle co-pilot. Watches the ICU. Drives the bundle. Documents the case.

SepsisGuard is a FHIR-native multi-agent system that detects emerging sepsis early, executes the CMS SEP-1 bundle in real time, and produces CMS-abstractor-ready documentation — built on the Anthropic Claude API, MCP, and A2A v1.

**Submission:** Agents Assemble — The Healthcare AI Endgame (Prompt Opinion / Darena Health, May 2026).
**License:** Apache 2.0.

---

## Why this matters

| Metric | Value | Source |
|---|---|---|
| US sepsis deaths annually | 350,000 | CDC |
| US hospital cost (2022) | $60.0 billion | AHRQ HCUP |
| Rank among US inpatient conditions by cost | #1 most expensive | AHRQ HCUP |
| Mortality increase per hour of antibiotic delay | 4–7% | Surviving Sepsis Campaign 2021 |
| Epic Sepsis Model recall on external validation | 0.33 (missed 67%) | JAMA Internal Med 2021 |
| SEP-1 in Hospital VBP | FY2026 (active) | CMS Hospital IQR / VBP |

Generative AI is required because the earliest sepsis signals live in nursing notes, microbiology comments, and imaging impressions — exactly the data structured-only models miss.

## Architecture

Three deployable artifacts in one Python service:

1. **MCP server** — 7 tools at `/mcp`
2. **A2A v1 agent card** at `/.well-known/agent-card.json`
3. **BYO Agent on Prompt Opinion** — "SepsisGuard ICU Co-Pilot"

Five logical agents share an in-process SHARP context:

- **Sentinel** — screens FHIR observations for SIRS/qSOFA + free-text triggers
- **Adjudicator** — confirms severe sepsis vs. benign alternatives, sets Time Zero
- **Bundle Orchestrator** — drives 3-hr / 6-hr SEP-1 elements
- **Pharmacist** — drafts antibiotic regimen for clinician sign-off
- **Documentation** — drafts CMS-abstractor-grade SEP-1 progress note

### The 7 MCP tools

1. `screen_sepsis_signals`
2. `confirm_sepsis_diagnosis`
3. `score_bundle_compliance`
4. `recommend_antibiotic`
5. `drive_bundle_element`
6. `draft_sep1_documentation`
7. `notify_care_team`

See `docs/ARCHITECTURE.md` and `SEPSISGUARD_BUILD_SPEC.md` §4 for the full diagram.

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env       # add ANTHROPIC_API_KEY

# Run all three demo scenarios offline (in-process FHIR mock)
python -m sepsisguard.demo --scenario all

# Or start the server for platform integration
python -m sepsisguard.server --transport sse --port 8080
```

Endpoints:
- `GET /health` — health check
- `GET /.well-known/agent-card.json` — A2A v1 agent card
- `POST /mcp` — MCP JSON-RPC
- `POST /a2a` — A2A v1 message endpoint

## Standards

FHIR R4 · US Core 6.1 · SMART App Launch v2 · CMS SEP-1 (Hospital VBP FY2026) · Surviving Sepsis Campaign 2021 · MCP · A2A v1 · SHARP-on-MCP.

## Repository layout

See `SEPSISGUARD_BUILD_SPEC.md` §11. Agent guidance for future contributors lives in `CLAUDE.md`.

## License

Apache 2.0 — see `LICENSE`.
