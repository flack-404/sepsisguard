# Phase 8 — Submission & Deployment

> **Goal:** Write all submission documentation, deploy to Railway, integrate with Prompt Opinion, publish to the Marketplace, and record the demo video.
> **Effort:** ~1–2 days. Documentation drafts can start in parallel with Phases 6/7.

This is the closing phase. Everything previously built is now made visible to judges.

## Prerequisites

- Phases 1–7 all merged.
- A Railway account (free tier is enough), Anthropic API key, Prompt Opinion account.
- A logged-in `gh` CLI for the GitHub push.

## Files to create

```
docs/
├── ARCHITECTURE.md
├── DEMO_SCENARIOS.md
├── IMPACT_METRICS.md
├── HIPAA_COMPLIANCE.md
├── SEP1_BUNDLE.md
└── DEPLOY_TO_PROMPT_OPINION.md

demo/
├── demo_video_script.md
└── DEMO_RECORDING_NOTES.md
```

Plus updates to:
- `README.md` (final polish)
- `SUBMISSION.md` (final Devpost copy)
- `assets/sepsisguard_logo.png` (if not already done in Phase 6)

## Spec sections to read first

- **§17** — full deployment instructions (local, ngrok, Railway, Prompt Opinion).
- **§19** — submission materials section-by-section.
- **§20** — demo video script (3-min, three acts).
- **§21 stages 12–15** — the deploy + submit checklist.

## Task breakdown

### 8.1 Documentation files (`docs/*.md`)

#### `docs/ARCHITECTURE.md`
- [ ] Paste the diagram from spec §4.
- [ ] Section walkthrough of each layer: Prompt Opinion platform → A2A agent → 5 logical agents → 7 MCP tools → FHIR server.
- [ ] Sequence diagram for the default trajectory (`screen → confirm → score → drive → notify → draft`).
- [ ] Note the two cross-cutting concerns: SHARP context flow and prompt caching strategy.

#### `docs/DEMO_SCENARIOS.md`
- [ ] One section per scenario (CAP, UTI, intra-abdominal shock).
- [ ] For each: clinical setup, what the scenario proves about SepsisGuard's capabilities, expected agent trajectory, expected outputs.
- [ ] Specifically call out: CAP = canonical, UTI = hard adjudication requiring free-text reading, septic shock = aggressive bundle.

#### `docs/IMPACT_METRICS.md`
- [ ] Paste the table from spec §2 verbatim. Cite every source.
- [ ] Hospital-level ROI projection (300-bed hospital, 700 sepsis admissions/yr → ~$2–3M/year recovered through SEP-1 VBP compliance). See spec §19.

#### `docs/HIPAA_COMPLIANCE.md`
- [ ] §164.312(a) Access Control — SHARP user identity captured, scope enforced per tool.
- [ ] §164.312(b) Audit — JSONL audit log writes references, never PHI content.
- [ ] §164.312(c) Integrity — stateless service, FHIR is canonical.
- [ ] §164.312(d) Authentication — trusts SMART launch from the platform.
- [ ] §164.312(e) Transmission — TLS 1.2+ enforced by Railway.
- [ ] Minimum necessary — scopes per tool table.

#### `docs/SEP1_BUNDLE.md`
- [ ] CMS Time Zero abstraction guidance.
- [ ] Detailed 3-hr / 6-hr element specs with FHIR resource mapping.
- [ ] Common abstractor failure modes (lactate timing, fluid documentation, repeat lactate window).
- [ ] Documentation phrasing that scores well.
- [ ] VBP scoring impact (FY2026).
- [ ] Cite Hospital IQR specifications and Surviving Sepsis Campaign 2021.

#### `docs/DEPLOY_TO_PROMPT_OPINION.md`
- [ ] Step-by-step from §17.4: MCP server registration, scope authorization, BYO Agent setup, Marketplace publishing.
- [ ] Screenshots after live deployment.

### 8.2 README.md polish

- [ ] Update Quick Start with verified commands (after live testing).
- [ ] Add architecture diagram (paste from spec §4 or link to `docs/ARCHITECTURE.md`).
- [ ] "Why It Wins" table with AI factor + impact + feasibility (use stats from §2).
- [ ] Standards section: FHIR R4, US Core 6.1, SMART App Launch v2, AHA Sepsis Care Performance Measure, CMS SEP-1, MCP, A2A v1, SHARP-on-MCP.
- [ ] Demo links: live Railway URL, Prompt Opinion Marketplace listing.

### 8.3 SUBMISSION.md (Devpost copy)

Per spec §19. Sections:
- [ ] Tagline (~140 chars).
- [ ] Inspiration — quote AHRQ #1-most-expensive + JAMA Epic study.
- [ ] What it does — 3 paragraphs walking through the 5 agents + 7 tools.
- [ ] How we built it — Both Superpower (MCP) and Superhero (A2A) in one.
- [ ] Why this wins on judging criteria — bullet each criterion (impact / AI factor / feasibility / SHARP+A2A alignment).
- [ ] Standards we actually implement — CRD/DTR/PAS analogues for SEP-1.
- [ ] Built with — Python, Anthropic, FastAPI, FHIR R4, MCP, A2A, Railway.
- [ ] Try it yourself — 3 commands.
- [ ] What's next — production deployment, multi-hospital rollout, post-acute extension.

### 8.4 Demo video (`demo/demo_video_script.md` + recording)

Per spec §20. Three acts, 3 minutes total:

- [ ] **Act 1 — The wound (0:00–0:30)** — narrate the AHRQ #1 + Epic recall + CMS VBP stats.
- [ ] **Act 2 — The cure (0:30–2:10)** — Scene 1 setup, Scene 2 live workflow on CAP patient (all 7 tools fire), Scene 3 the hard UTI case (free-text wins), Scene 4 the safety property (post-op fever, refuses to drive bundle).
- [ ] **Act 3 — The math (2:10–2:50)** — per-case mortality reduction, per-hospital $2-3M ROI, alignment with VBP FY2026.
- [ ] Final card with license + Marketplace link.

- [ ] `demo/DEMO_RECORDING_NOTES.md` — checklist for recording (window size, mouse cursor, terminal font, scrolling speed, audio levels).
- [ ] Record in OBS or Loom. Upload to YouTube **unlisted**. Note the URL — it goes in SUBMISSION.md.

### 8.5 Railway deployment (spec §17.3)

- [ ] Push the repo to GitHub (private is fine).
- [ ] Sign in to railway.com via GitHub.
- [ ] New Project → Deploy from GitHub repo.
- [ ] Set env vars in Railway Variables panel:
  - `ANTHROPIC_API_KEY=sk-ant-...`
  - `PYTHONPATH=src`
  - `LOG_LEVEL=INFO`
  - `DEMO_MODE=true` (only if you want platform-side demos to skip Claude — usually leave false)
- [ ] Settings → Networking → **Generate Domain**.
- [ ] Verify endpoints respond:
  - `https://<url>/health` → 200
  - `https://<url>/.well-known/agent-card.json` → returns the card
  - `curl -X POST https://<url>/mcp -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}'` → returns initialize response

### 8.6 Prompt Opinion integration (spec §17.4)

- [ ] Sign up at app.promptopinion.ai (free tier with Gemini).
- [ ] Activate General Chat Agent (Po Agents → toggle Active).
- [ ] Import a synthetic patient OR upload one of `data/fhir_bundles/*.bundle.json` via the FHIR upload UI.
- [ ] **Configuration → MCP Servers → Add MCP Server**
  - Name: SepsisGuard MCP
  - Endpoint: `https://<railway-url>/mcp`
  - Transport: Streamable HTTP
  - Auth Type: None
  - Save → toggle "Enable Prompt Opinion Extension" ON
  - Selective Permissions → **Select All** (15 scopes)
- [ ] **Agents → BYO Agents → Add AI Agent**
  - Allowed Contexts: Workspace + Patient
  - Name: SepsisGuard ICU Co-Pilot
  - Description: see SUBMISSION.md tagline
  - Timeout: 300s
  - Model: gemini-3-flash-preview (default; can switch to Claude later)
  - System Prompt: paste from `agent/agent_prompt.md` (preserve `{{ PatientContextFragment }}`, `{{ PatientDataFragment }}`, `{{ McpAppsFragment }}` template vars)
  - Tools: Add SepsisGuard MCP — auto-attaches all 7
  - A2A & Skills: enable A2A + enable FHIR Context Extension + Required toggle ON
  - Skill: `bundle_execution` with description from agent card
  - Save
- [ ] **Marketplace Studio → Manage:** publisher profile (logo + about).
- [ ] **Marketplace Studio → MCP Servers:** publish SepsisGuard MCP.
- [ ] **Marketplace Studio → Agents:** publish SepsisGuard ICU Co-Pilot.

### 8.7 Live test on platform (spec §21 stage 14)

- [ ] Launchpad → Patient scope → pick the uploaded sepsis patient.
- [ ] Pick **SepsisGuard ICU Co-Pilot** agent (or General Chat Agent → consult SepsisGuard).
- [ ] Toggle "Show Tool calls" ON.
- [ ] Send: "Run sepsis bundle execution for this patient — recent vitals show concerning trends."
- [ ] Verify all 7 tools fire in sequence.
- [ ] Verify final summary text matches the agent prompt's tone (terse, ICU shorthand, no PHI).

### 8.8 Submit (spec §21 stage 15)

- [ ] Record final 3-min video. Upload unlisted to YouTube.
- [ ] Submit on Devpost using SUBMISSION.md content + video link + GitHub repo + Railway URL + Prompt Opinion Marketplace listing.

## Key patterns and gotchas

- **The FastAPI `request: Request` pitfall (spec §12 Pattern 5)** will surface as deploy-time 500s if Phase 5 was rushed. Catch it locally before pushing.
- **Health check on Railway** must return 200 within 30s (per `railway.toml`). Cold start of `claude_client` should be lazy (don't initialize Anthropic at module import).
- **`PYTHONPATH=src` is required** because the package is in `src/` (src layout). Forgetting this causes `ModuleNotFoundError: sepsisguard` on Railway. The spec calls this out explicitly.
- **HTTPS only on Railway.** Don't hardcode `http://` URLs in agent_card.json — make them absolute or relative.
- **Marketplace publish requires a logo.** Run `scripts/make_logo.py` if Phase 6 didn't.
- **YouTube video must be unlisted, not public.** Devpost requires a viewable link, but unlisted respects the synthetic-data-only nature of the demo.
- **Submission deadline:** May 12, 2026 (per spec §1). Build margin: aim to submit by May 11 evening to allow video re-recording if needed.

## Acceptance criteria

- [ ] All 6 docs in `docs/` complete and proof-read.
- [ ] README.md and SUBMISSION.md final and Devpost-ready.
- [ ] Railway deploy live, all endpoints respond.
- [ ] Prompt Opinion MCP server + BYO Agent both **Published** in the Marketplace.
- [ ] Live test on platform: agent walks through default trajectory with all 7 tool calls visible to the user.
- [ ] Demo video uploaded to YouTube (unlisted), URL captured.
- [ ] Devpost submission complete: project description, video link, GitHub repo, demo URLs all populated.
- [ ] All three scenarios runnable from the Marketplace listing by a fresh reviewer.

## Closing checklist

Before clicking "Submit" on Devpost:
- [ ] Pull the Railway URL into a fresh browser and run the demo prompt — verify it works.
- [ ] Re-watch the 3-min video. Audio level OK? Captions accurate?
- [ ] Confirm `LICENSE` is present in the repo and is Apache 2.0.
- [ ] Confirm no `.env` or `ANTHROPIC_API_KEY` in the repo (`git log -p | grep -i anthropic_api_key` should return nothing besides `.env.example`).
- [ ] Tag the release: `git tag v0.1.0 && git push --tags`.
- [ ] Submit.
