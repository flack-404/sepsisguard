# Phase 5 — Orchestration & Transport

> **Goal:** Wire the 7 tools into a Claude tool-use agent, expose them over MCP + A2A v1, and publish the agent card. After this phase, SepsisGuard runs end-to-end as an HTTP service.
> **Effort:** ~2–3 days. The largest phase.

This is the integration phase. Most bugs surface here.

## Prerequisites

- Phases 1, 2, 3, 4 all merged.
- All 7 tools registered in `TOOL_REGISTRY`.

## Files to create

```
src/sepsisguard/
├── agent_loop.py            ← Claude tool-use orchestrator
├── server.py                ← FastAPI MCP + A2A HTTP transport
└── shadow_abstractor.py     ← Claude-as-CMS-abstractor scoring simulator

agent/
├── agent_card.json          ← A2A v1 agent card (also served at /.well-known)
└── agent_prompt.md          ← system prompt for the orchestrator (spec §14)
```

## Spec sections to read first

- **§4** — architecture diagram (especially the tool/skill mapping).
- **§8** — MCP `initialize` handshake, required scopes, agent card shape.
- **§12 Pattern 5** — `server.py` route table + the FastAPI `request: Request` pitfall.
- **§12 Pattern 6** — agent loop pattern, especially the `cache_control` stripping rule.
- **§14** — orchestrator system prompt (paste into `agent/agent_prompt.md`).
- **§15** — server-specific differences (server name, scopes, tool registry).

## Task breakdown

### 5.1 `agent/agent_prompt.md`

- [ ] Paste the full orchestrator system prompt from spec §14.
- [ ] Preserve the template variables `{{ PatientContextFragment }}`, `{{ PatientDataFragment }}`, `{{ McpAppsFragment }}` — the Prompt Opinion platform substitutes these at runtime.
- [ ] Hard rules to enforce verbatim: no fabricated values, no auto-administer, no PHI in prose, halt on `insufficient_data`, `notify_care_team` urgent on missed deadlines, terse ICU shorthand.

### 5.2 `agent/agent_card.json`

- [ ] Paste from spec §8 verbatim.
- [ ] Three skills: `continuous_sepsis_monitoring`, `bundle_execution`, `bundle_audit_review`.
- [ ] Extension: `https://app.promptopinion.ai/schemas/a2a/v1/fhir-context` with `params.scopes = REQUIRED_SCOPES`.
- [ ] `supportedInterfaces: [{transport: "JSONRPC", uri: "/a2a"}]`.
- [ ] `protocolVersion: "1.0"`, `version: "0.1.0"`, `provider.name: "SepsisGuard"`.

### 5.3 `agent_loop.py`

The Anthropic tool-use loop. Iterates until `stop_reason == "end_turn"` or hits `max_iterations`.

- [ ] `async def run_agent(user_message: str, *, system_prompt: str, max_iterations: int = 12) -> dict`:
  - Builds `tools` list from `TOOL_REGISTRY`. **Remap `inputSchema` → `input_schema`** for Anthropic.
  - Initial `messages = [{"role": "user", "content": user_message}]`.
  - Loop:
    1. Call `claude.generate(system_blocks=[CacheableBlock(system_prompt, cache=True, ttl="1h")], messages=messages, tools=tools, max_tokens=4096)`.
    2. If `stop_reason == "end_turn"`, break.
    3. For each `tool_use` block in the response: dispatch `TOOL_REGISTRY[name][1](**input)` and append a `tool_result` to messages.
    4. **Strip stale `cache_control` from older `tool_result` blocks** before next iteration (spec §12 Pattern 6).
  - Return `{final_text, tool_calls: [...], iterations, telemetry: {total_input_tokens, total_cache_read_tokens, ...}}`.
- [ ] `_strip_old_cache_breakpoints(messages)` helper exactly as in spec §12.
- [ ] **Cap on iterations** — protects against runaway loops. Default 12 is enough for the full default trajectory + retries.
- [ ] Audit log per iteration: `audit_log("agent.iteration", trace_id=..., iteration=i, tool_calls=[...], stop_reason=...)`.

### 5.4 `server.py`

FastAPI app exposing MCP and A2A. **Read spec §12 Pattern 5 carefully** — the FastAPI `request: Request` pitfall is the #1 deployment bug.

- [ ] Module constants: `SERVER_NAME = "sepsisguard"`, `SERVER_VERSION = "0.1.0"`, import `REQUIRED_SCOPES` from `sharp_context`.

- [ ] **Endpoints:**

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/` | server info JSON |
| GET | `/health` | health check (Railway) |
| GET | `/.well-known/agent-card.json` | A2A v1 agent card (load `agent/agent_card.json`) |
| POST | `/mcp` | MCP JSON-RPC dispatcher |
| POST | `/a2a` | A2A v1 message endpoint |
| GET | `/mcp/sse` | optional SSE keepalive |

- [ ] **MCP JSON-RPC methods:**
  - `initialize` — return `{protocolVersion: "2024-11-05", serverInfo: {name, version}, capabilities: {tools: {}, extensions: {"ai.promptopinion/fhir-context": {scopes: REQUIRED_SCOPES}}}}`.
  - `tools/list` — return `{tools: [TOOL_REGISTRY[name][0] for name in TOOL_REGISTRY]}`.
  - `tools/call` — bind SHARP context from request headers, dispatch to the named tool, return `{content: [{type: "text", text: json.dumps(result)}], isError: false}`.
  - `agent/run` — same context bind + call `run_agent(user_message, system_prompt=AGENT_PROMPT)`.
- [ ] **Critical FastAPI quirk** (spec §12 Pattern 5): handlers must NOT take `request: Request`. Instead:
  ```python
  @app.post("/mcp")
  async def mcp_post(
      payload: dict = Body(...),
      x_fhir_server_url: str | None = Header(None, alias="X-FHIR-Server-URL"),
      x_fhir_access_token: str | None = Header(None, alias="X-FHIR-Access-Token"),
      x_patient_id: str | None = Header(None, alias="X-Patient-ID"),
      x_fhir_refresh_token: str | None = Header(None, alias="X-FHIR-Refresh-Token"),
      x_fhir_refresh_url: str | None = Header(None, alias="X-FHIR-Refresh-Url"),
  ) -> JSONResponse:
      ctx = SharpContext.from_headers({...}, granted_scopes=...)
      token = bind_sharp_context(ctx)
      try:
          ...
      finally:
          reset_sharp_context(token)
  ```
- [ ] **`/a2a` handler:** extracts user text from `params.message.parts[*].text`, calls `run_agent`, returns A2A v1 response shape `{result: {message: {parts: [{type: "text", text: <final>}]}, status: "completed"}}`.
- [ ] `def main()`:
  - Reads `PORT` env var. If set → transport = `sse`. Else → reads `SEPSISGUARD_TRANSPORT` (default `stdio`).
  - For `sse`/`http`: `uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))`.
  - For `stdio`: launch the MCP stdio loop (use `mcp` SDK if available, else implement minimal stdio JSON-RPC).
- [ ] `if __name__ == "__main__": main()`.

### 5.5 `shadow_abstractor.py`

Claude-as-CMS-abstractor — scores a drafted SEP-1 note for compliance. Mirrors AuthBridge's `shadow_payer.py`.

- [ ] `async def score_documentation(note_text: str, bundle_status: dict) -> dict`:
  - System prompt: "You are a CMS abstractor scoring a SEP-1 chart note. Score 0.0 to 1.0 against this rubric: [...]". Cache the rubric (same `data/sep1_abstractor_rubric.md` from Phase 4).
  - Returns `{score: float, passed_elements: [...], failed_elements: [...], rationale: str}`.
- [ ] Used by the demo runner (Phase 6) to display a "predicted CMS score" beside the agent's drafted note.
- [ ] Stub fallback: returns `{score: 0.85, passed_elements: ["lactate","blood_cultures","antibiotics"], failed_elements: [], rationale: "Stub score"}`.

## Key patterns and gotchas

- **The FastAPI `request: Request` pitfall (spec §12 Pattern 5)** — FastAPI 0.136 + Starlette 1.0 misclassifies `request: Request` as a query param. Use explicit `Body(...)` and `Header(..., alias=...)` parameters. This bug ate hours from the spec author; do not skip the workaround.
- **Cache breakpoint cap = 4** (spec §12 Pattern 6). Strip `cache_control` from older tool_result blocks every iteration. Otherwise breakpoint count grows and Anthropic returns an error after a few turns.
- **`inputSchema` (MCP) vs `input_schema` (Anthropic tool-use)** — different keys. The agent loop must remap when feeding `TOOL_REGISTRY` schemas to `claude.generate(tools=...)`.
- **SHARP context lifetime per request.** Bind in the FastAPI handler; reset in `finally`. Don't bind in the agent loop or tools — they read what the handler bound.
- **A2A `/a2a` requires JSON-RPC envelope** with `jsonrpc: "2.0"`, `id`, `method`, `params`. Match A2A v1 spec strictly; Prompt Opinion validates this.
- **`/.well-known/agent-card.json` is GET, no auth.** Don't accidentally protect it.
- **`/health` returns 200 with body `{"status": "ok"}`.** Railway hits this on the deploy interval; if it returns 5xx the deploy fails.
- **No PHI in `final_text`.** The agent prompt forbids names/MRN/DOB; double-check by spot-reading the demo output.

## Acceptance criteria

- [ ] `python -m sepsisguard.server --transport sse --port 8080` starts without error.
- [ ] `curl http://localhost:8080/health` returns `200 {"status":"ok"}`.
- [ ] `curl http://localhost:8080/.well-known/agent-card.json` returns the card with 3 skills.
- [ ] `curl -X POST http://localhost:8080/mcp -H 'content-type: application/json' -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}'` returns the initialize response with `extensions.ai.promptopinion/fhir-context.scopes` populated.
- [ ] `tools/list` returns 7 tools.
- [ ] `tools/call` for `screen_sepsis_signals` against the demo FHIR mock (Phase 6) succeeds end-to-end.
- [ ] `agent/run` against a sample message walks through the default trajectory (screen → confirm → score → drive → notify → draft) without erroring.
- [ ] Cache hit ratio > 0 on iteration 2+ (verify via telemetry in agent loop output).
- [ ] No iteration exceeds 4 active `cache_control` breakpoints (the spec author burned themselves on this — verify by logging breakpoint count per iteration during debugging).

## Handoff to next phase

Phase 6 (demo) calls `run_agent` directly:
```python
from sepsisguard.agent_loop import run_agent
result = await run_agent(scenario["prompt"], system_prompt=AGENT_PROMPT)
```

Phase 8 (deployment) needs the server to start cleanly with `PORT` env var to auto-select SSE.

If the agent loop or server's public API changes, update `PHASES.md` and ping the demo/deploy owners.
