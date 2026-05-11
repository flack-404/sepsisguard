# Deploy to Prompt Opinion

End-to-end checklist for getting SepsisGuard live on the Prompt Opinion Marketplace.

## Prerequisites

- A Prompt Opinion account at https://app.promptopinion.ai
- A Google AI Studio account (for the platform's General Chat Agent model — Gemini 3.1 Flash Lite is free)
- An Anthropic API key (for SepsisGuard's Claude tools)
- A Railway account (free tier OK for the hackathon submission)
- This repo cloned, tests passing locally (`PYTHONPATH=src pytest tests/`)

## Step 1 — Deploy the MCP server to Railway

Files already in the repo: `Procfile`, `railway.toml`, `runtime.txt`, `pyproject.toml`.

```bash
# Push to GitHub (private repo is fine)
git push origin main

# Then in Railway dashboard:
# 1. New Project → Deploy from GitHub repo (select flack-404/sepsisguard)
# 2. Variables → add:
ANTHROPIC_API_KEY=sk-ant-...
PYTHONPATH=src
LOG_LEVEL=INFO
ANTHROPIC_MODEL=claude-opus-4-7
# 3. Settings → Networking → Generate Domain
```

Once deployed, verify:
```bash
curl https://<your-railway-domain>/health
# → {"status": "ok", "name": "sepsisguard", "version": "0.1.0"}

curl https://<your-railway-domain>/.well-known/agent-card.json
# → returns the agent card with 3 skills

curl -X POST https://<your-railway-domain>/mcp \
  -H 'content-type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}'
# → returns initialize response with extensions.ai.promptopinion/fhir-context.scopes
```

## Step 2 — Seed a sepsis patient into your Prompt Opinion workspace

1. Generate the FHIR bundles locally:
   ```bash
   python scripts/scenarios_to_fhir_bundles.py
   # Produces 3 bundles in data/fhir_bundles/
   ```
2. In Prompt Opinion: Configuration → Patients → Import → upload `data/fhir_bundles/cap_severe_sepsis.bundle.json`.
3. The workspace will POST every resource into its FHIR server with new server-assigned IDs.

## Step 3 — Register SepsisGuard as an MCP server

In Prompt Opinion: **Configuration → MCP Servers → Add MCP Server**

- **Name:** SepsisGuard MCP
- **Endpoint:** `https://<your-railway-domain>/mcp`
- **Transport:** Streamable HTTP
- **Auth Type:** None
- Save.
- Toggle **"Enable Prompt Opinion Extension"** ON.
- **Selective Permissions:** "Select All" (15 scopes).
- Save.

## Step 4 — Create the SepsisGuard ICU Co-Pilot agent

In Prompt Opinion: **Agents → Build Your Own Agents → Add AI Agent**

- **Name:** SepsisGuard ICU Co-Pilot
- **Description:** "Multi-agent SEP-1 bundle co-pilot. Watches for sepsis, drives the bundle, drafts the documentation note."
- **Allowed Contexts:** Workspace + Patient
- **Timeout Seconds:** 300
- **Model:** gemini-3.1-flash-lite (platform default — free)
- **System Prompt:** paste from `agent/agent_prompt.md`. **Preserve** the template variables `{{ PatientContextFragment }}`, `{{ PatientDataFragment }}`, `{{ McpAppsFragment }}` — the platform substitutes them at runtime.
- **Tools:** Click "Add Tool" → select the SepsisGuard MCP server → all 7 tools auto-attach.
- **A2A & Skills:**
  - Enable A2A toggle.
  - Enable FHIR Context Extension + Required toggle ON.
  - Add Skill: `bundle_execution` (description from `agent/agent_card.json`).
- Save.

## Step 5 — Smoke test on the platform

In Prompt Opinion: **Launchpad**

1. Patient scope → select the imported sepsis patient.
2. Pick agent: **SepsisGuard ICU Co-Pilot** (or use the General Chat Agent and ask it to consult SepsisGuard).
3. Toggle **"Show Tool Calls"** ON.
4. Send prompt: *"Run sepsis bundle execution for this patient — vitals show concerning trends and the labs just resulted."*

Expected:
- All 7 tools fire in default-trajectory order.
- Time Zero is set.
- 5 FHIR Tasks are created in the workspace (visible in the Patient view's Task tab).
- 1 FHIR Communication is sent.
- 1 FHIR DocumentReference (the SEP-1 progress note) is added.
- The agent's final summary appears with a predicted CMS abstractor score.

## Step 6 — Publish to the Marketplace

In Prompt Opinion: **Marketplace Studio**

1. **Manage:** complete publisher profile (logo + bio).
2. **MCP Servers:** Publish SepsisGuard MCP.
3. **Agents:** Publish SepsisGuard ICU Co-Pilot.

After publishing, the agent + tools are discoverable in the Marketplace and invokable by any workspace that adopts them.

## Step 7 — Record the demo video

3-minute structure (per `demo/demo_video_script.md`):
- **0:00–0:30** — The problem (AHRQ #1 cost, JAMA Epic-Sepsis recall 0.33, CMS VBP FY2026).
- **0:30–2:10** — Live workflow on the platform:
  - Scene 1: SepsisGuard MCP server registered in Configuration.
  - Scene 2: CAP patient → "Run bundle execution" → all 7 tools fire visibly → final note drafted.
  - Scene 3: UTI patient → free-text adjudication wins.
  - Scene 4: Post-op fever patient (negative case) → Adjudicator refuses.
- **2:10–2:50** — The math (4–7% mortality per hour, $2–3M / 300-bed hospital, FY2026 VBP).

Upload **unlisted** to YouTube. Drop the URL into your Devpost submission.

## Common deployment pitfalls

- **`ModuleNotFoundError: sepsisguard`** on Railway — you forgot `PYTHONPATH=src`. Set it in Variables.
- **`/mcp` returns 500 with "request" query param error** — you wrote `request: Request` in a FastAPI handler. Don't (see spec §12 Pattern 5). Use explicit `Body(...)` and `Header(..., alias=...)`.
- **Cache breakpoint count exceeded 4** — you forgot to strip `cache_control` from older tool_result blocks. The pattern is in `agent_loop.py` (`_strip_old_cache_breakpoints`).
- **`temperature` parameter not allowed** — `claude-opus-4-7` deprecated it. Omit the kwarg entirely.
- **FHIR uploads fail with "ID already exists"** — your transaction bundle has client-supplied `id`s. Use `urn:uuid:` references and let the server assign IDs. The `scripts/scenarios_to_fhir_bundles.py` does this correctly.
