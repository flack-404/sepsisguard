# SepsisGuard — Devpost submission

> **Tagline:** Multi-agent SEP-1 bundle co-pilot. Watches the ICU. Drives the bundle. Documents the case.

**Hackathon:** Agents Assemble — The Healthcare AI Endgame (Prompt Opinion / Darena Health).
**Submission path:** Both Option 1 (MCP Server / "Superpower") and Option 2 (A2A Agent / "Superhero") in one Python service.

---

## Inspiration

Sepsis is the **#1 most expensive condition in US hospitals** — $60 billion a year, 350,000 deaths annually (AHRQ HCUP, CDC). Yet the deployed industry leader, the **Epic Sepsis Model**, was published in *JAMA Internal Medicine* (Wong et al., 2021) **missing two-thirds of cases** while alerting on 18% of all admitted patients.

The reason is simple: the earliest sepsis signals live in nursing notes, microbiology reports, and imaging conclusions. Structured-data-only models can't read them. An LLM can.

CMS just made SEP-1 a **pay-for-performance measure under Hospital Value-Based Purchasing** for fiscal year 2026. Sepsis is no longer just a clinical problem — it's revenue-cycle infrastructure. The market needs a system that actually catches the cases, drives the bundle, and produces CMS-abstractor-grade documentation. We built it.

## What it does

**SepsisGuard is a five-agent system that screens for emerging sepsis, executes the CMS SEP-1 bundle in real time, and drafts CMS-abstractor-grade documentation.** All five logical agents live in one Python service and share a SHARP context bound from inbound HTTP headers:

- **Sentinel** — `screen_sepsis_signals` walks the patient's FHIR record (Observations, Conditions, MedicationRequests, DocumentReferences, DiagnosticReports) and computes SIRS / qSOFA / organ-dysfunction markers + scans nursing notes for free-text triggers like "cloudy urine", "lethargic", "altered mental status".
- **Adjudicator** — `confirm_sepsis_diagnosis` calls Claude with the screening packet, classifies the case (severe sepsis / septic shock / benign alternative / insufficient data), and establishes Time Zero per CMS abstraction rules.
- **Bundle Orchestrator** — `score_bundle_compliance` walks the FHIR record from Time Zero and classifies each 3-hr/6-hr element; `drive_bundle_element` creates FHIR Tasks for nursing/pharmacy/lab with role-specific assignees and bundle-clock-aligned deadlines; `notify_care_team` sends FHIR Communications.
- **Pharmacist** — `recommend_antibiotic` reads AllergyIntolerance + latest eGFR + weight from FHIR, seeds a regimen from the local antibiogram, then asks Claude to refine with Surviving Sepsis Campaign 2021 + IDSA guideline citations. Output is always a draft for clinician sign-off — never auto-administered.
- **Documentation** — `draft_sep1_documentation` calls Claude with a 1-hour-cached CMS abstractor rubric and produces a structured progress note where every clinical claim cites a FHIR resource ID. Returns a predicted CMS abstractor score and a list of specific audit concerns.

The default trajectory — `screen → confirm → score → recommend → drive → notify → draft` — is enforced by the orchestrator system prompt. Hard rules: never fabricate values, never auto-administer, no PHI in conversational output, halt on `insufficient_data`.

## How we built it

**Both Superpower and Superhero in one service.**

- **MCP Server** — Python + FastAPI exposing 7 tools at `POST /mcp` (JSON-RPC 2.0). Streamable HTTP transport. SHARP context bound from `X-FHIR-*` request headers. Scope-enforced per tool.
- **A2A v1 Agent Card** at `GET /.well-known/agent-card.json` declaring 3 skills + the `ai.promptopinion/fhir-context` extension with all 15 SMART scopes.
- **Anthropic Claude** (`claude-opus-4-7`) for the 5 tools that need reasoning. Prompt caching (1-hour TTL) on system prompts and the CMS abstractor rubric — observed **cache hit ratio: 0.70–0.77** across iterations.
- **FHIR R4** for all clinical I/O. POST-only transaction Bundles with `urn:uuid:` references for upload.

## Why this wins on judging criteria

### The AI Factor

A rule engine cannot build SepsisGuard. The UTI scenario in our demo is the canonical example: a 78-year-old POD 4 ortho patient with borderline vitals, lactate 2.4, **no infection-coded Condition**. The diagnostic information lives in the nursing note's free text. An LLM reads "patient confused, more lethargic than prior 24h. Urine cloudy with sediment" and correctly classifies severe sepsis from a urinary source. Then the pharmacist sub-agent — given a PCN allergy — substitutes cefepime for piperacillin-tazobactam and cites the <2% cross-reactivity literature. Three forms of clinical reasoning, all impossible in a rule engine.

### Potential Impact

- Sepsis is the #1 most expensive condition in US hospitals: $60B/yr, 350K deaths annually.
- Every hour of antibiotic delay = 4–7% mortality increase (Surviving Sepsis Campaign 2021).
- Hospital VBP FY2026 ties SEP-1 compliance directly to Medicare reimbursement.
- Per-hospital ROI projection: **$2–3M / yr per 300-bed acute-care hospital** in recovered SEP-1 VBP compliance.

### Feasibility

- HIPAA Security Rule §164.312 mapped end-to-end (see `docs/HIPAA_COMPLIANCE.md`).
- Audit log records FHIR resource references only — never PHI content.
- Scope-enforced FHIR access (15 SMART scopes per spec §8).
- Antibiotic recommendations always require clinician sign-off — enforced server-side.
- FHIR R4 throughout, US Core 6.1-compatible, SMART App Launch v2-aligned.
- Apache 2.0 license.

## Standards we actually implement

| Standard | Role |
|---|---|
| **MCP** (Model Context Protocol) | 7 tools exposed at `POST /mcp` via JSON-RPC 2.0 |
| **A2A v1** | Agent card at `/.well-known/agent-card.json` declaring 3 skills + `fhir-context` extension; A2A message endpoint at `POST /a2a` |
| **SHARP-on-MCP** | Per-request SHARP context bound from `X-FHIR-Server-URL` / `X-FHIR-Access-Token` / `X-Patient-ID` headers |
| **FHIR R4** | Reads Patient, Encounter, Observation, Condition, MedicationRequest/Administration, AllergyIntolerance, DiagnosticReport, DocumentReference, Specimen, Procedure; writes Task, Communication, DocumentReference |
| **CMS SEP-1** (Hospital VBP FY2026) | Encoded in `sep1_definition.py` (criteria, deadlines, scoring math) — the most clinically critical file in the codebase |
| **Surviving Sepsis Campaign 2021** | Cited in antibiotic recommendations and orchestrator system prompt |
| **HIPAA 164.312** | References-only audit log; scope-enforced access; TLS in transit; minimum-necessary principle per tool |

## Built with

Python 3.12 · FastAPI · Anthropic Claude API (`claude-opus-4-7`) · FHIR R4 · MCP · A2A v1 · SHARP-on-MCP · Railway · httpx · pytest

## Try it yourself

```bash
git clone https://github.com/flack-404/sepsisguard
cd sepsisguard
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Add your ANTHROPIC_API_KEY to .env

# Run all 3 demo scenarios offline (in-process FHIR mock):
python -m sepsisguard.demo --scenario all

# Or start the server for platform integration:
python -m sepsisguard.server --transport sse --port 8080
```

Full Prompt Opinion deployment guide in `docs/DEPLOY_TO_PROMPT_OPINION.md`.

## What's next

- **Production deployment** with a real BAA-covered Anthropic account, multi-hospital pilot, Epic / Cerner SMART App Launch integration.
- **Bundle audit-mode skill** (`bundle_audit_review`) — walks discharged patients' records and predicts SEP-1 abstraction outcomes before the CMS audit, so hospitals can proactively address documentation gaps.
- **Post-acute extension** — sepsis 90-day readmission monitoring, transition-of-care documentation.
- **A2A multi-agent composition** — handoff to specialist agents (ID stewardship, palliative care, family communication) via A2A v1 messages.

## Demo video

**[YouTube link — TODO at submission time]**

3 minutes. Three scenarios. Seven tools fire visibly in the Prompt Opinion Launchpad. Per the recording notes in `demo/DEMO_RECORDING_NOTES.md`.

## License

Apache 2.0. See `LICENSE`.
