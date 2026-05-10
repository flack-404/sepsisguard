"""SepsisGuard MCP + A2A HTTP transport (FastAPI).

Endpoints:
    GET  /                              — server info JSON
    GET  /health                        — health check (Railway)
    GET  /.well-known/agent-card.json   — A2A v1 agent card
    POST /mcp                           — MCP JSON-RPC (initialize, tools/list, tools/call, agent/run)
    POST /a2a                           — A2A v1 message endpoint
    GET  /mcp/sse                       — optional SSE keepalive

Critical FastAPI 0.136 + Starlette 1.0 quirk (spec §12 Pattern 5): handlers
MUST NOT take `request: Request` as a parameter — FastAPI mis-classifies it as
a query param. We bind SHARP context from explicit Header(...) parameters
instead. The pattern is verbose but correct.

Transport auto-selection:
    PORT env var set         → SSE/HTTP via uvicorn (Railway)
    SEPSISGUARD_TRANSPORT    → 'sse' | 'http' | 'stdio'
    default                  → stdio (local MCP client)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import Body, FastAPI, Header
from fastapi.responses import JSONResponse, PlainTextResponse

# Load .env from repo root before any module reads env vars.
load_dotenv(Path(__file__).parent.parent.parent / ".env")

from . import __version__
from .agent_loop import run_agent
from .audit import audit_log
from .sharp_context import (
    REQUIRED_SCOPES,
    SharpContext,
    bind_sharp_context,
    reset_sharp_context,
)
from .tools import TOOL_REGISTRY

logger = logging.getLogger(__name__)

SERVER_NAME = "sepsisguard"
SERVER_VERSION = __version__

_AGENT_CARD_PATH = Path(__file__).parent.parent.parent / "agent" / "agent_card.json"
_AGENT_PROMPT_PATH = Path(__file__).parent.parent.parent / "agent" / "agent_prompt.md"

# MCP protocol version SepsisGuard implements (Anthropic MCP spec).
_MCP_PROTOCOL_VERSION = "2024-11-05"


app = FastAPI(title="SepsisGuard", version=SERVER_VERSION)


# ── helpers ──────────────────────────────────────────────────────────────────

def _all_scope_names() -> list[str]:
    """Flatten REQUIRED_SCOPES into a plain name list (used as 'granted' fallback)."""
    return [s["name"] for s in REQUIRED_SCOPES]


def _load_agent_card() -> dict[str, Any]:
    try:
        return json.loads(_AGENT_CARD_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        logger.warning("agent_card.json not found at %s", _AGENT_CARD_PATH)
        return {
            "protocolVersion": "1.0",
            "name": SERVER_NAME,
            "version": SERVER_VERSION,
            "description": "SepsisGuard A2A agent (card file missing)",
            "skills": [],
        }


def _load_agent_prompt() -> str:
    try:
        return _AGENT_PROMPT_PATH.read_text(encoding="utf-8")
    except FileNotFoundError:
        return "You are SepsisGuard. Use the available tools to assist the clinician."


def _bind_context_from_headers(
    *,
    x_fhir_server_url: str | None,
    x_fhir_access_token: str | None,
    x_patient_id: str | None,
    x_fhir_refresh_token: str | None,
    x_fhir_refresh_url: str | None,
    x_trace_id: str | None,
    granted_scopes: list[str] | None = None,
) -> Any:
    """Bind SharpContext from request headers; returns the contextvars token."""
    headers = {
        "X-FHIR-Server-URL": x_fhir_server_url or "",
        "X-FHIR-Access-Token": x_fhir_access_token or "",
        "X-Patient-ID": x_patient_id or "",
        "X-FHIR-Refresh-Token": x_fhir_refresh_token or "",
        "X-FHIR-Refresh-Url": x_fhir_refresh_url or "",
        "X-Trace-ID": x_trace_id or "",
    }
    ctx = SharpContext.from_headers(headers, granted_scopes=granted_scopes or _all_scope_names())
    return bind_sharp_context(ctx)


def _jsonrpc_response(req_id: Any, result: Any = None, error: Any = None) -> dict[str, Any]:
    out: dict[str, Any] = {"jsonrpc": "2.0", "id": req_id}
    if error is not None:
        out["error"] = error
    else:
        out["result"] = result
    return out


def _mcp_tool_list() -> list[dict[str, Any]]:
    return [schema for schema, _handler in TOOL_REGISTRY.values()]


# ── routes ───────────────────────────────────────────────────────────────────

@app.get("/")
async def root() -> JSONResponse:
    return JSONResponse({
        "name": SERVER_NAME,
        "version": SERVER_VERSION,
        "description": "SepsisGuard MCP server + A2A agent. CMS SEP-1 bundle co-pilot.",
        "endpoints": {
            "mcp": "/mcp",
            "a2a": "/a2a",
            "agent_card": "/.well-known/agent-card.json",
            "health": "/health",
        },
    })


@app.get("/health")
async def health() -> JSONResponse:
    return JSONResponse({"status": "ok", "name": SERVER_NAME, "version": SERVER_VERSION})


@app.get("/.well-known/agent-card.json")
async def agent_card() -> JSONResponse:
    return JSONResponse(_load_agent_card())


# ── /mcp ─────────────────────────────────────────────────────────────────────

@app.post("/mcp")
async def mcp_post(
    payload: dict = Body(...),
    x_fhir_server_url: str | None = Header(None, alias="X-FHIR-Server-URL"),
    x_fhir_access_token: str | None = Header(None, alias="X-FHIR-Access-Token"),
    x_patient_id: str | None = Header(None, alias="X-Patient-ID"),
    x_fhir_refresh_token: str | None = Header(None, alias="X-FHIR-Refresh-Token"),
    x_fhir_refresh_url: str | None = Header(None, alias="X-FHIR-Refresh-Url"),
    x_trace_id: str | None = Header(None, alias="X-Trace-ID"),
) -> JSONResponse:
    req_id = payload.get("id")
    method = payload.get("method", "")
    params = payload.get("params", {}) or {}

    audit_log("mcp.request", method=method, trace_id=x_trace_id or "")

    # initialize doesn't need a SHARP context.
    if method == "initialize":
        return JSONResponse(_jsonrpc_response(req_id, result={
            "protocolVersion": _MCP_PROTOCOL_VERSION,
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            "capabilities": {
                "tools": {},
                "extensions": {
                    "ai.promptopinion/fhir-context": {
                        "scopes": REQUIRED_SCOPES,
                    }
                },
            },
        }))

    if method == "tools/list":
        return JSONResponse(_jsonrpc_response(req_id, result={"tools": _mcp_tool_list()}))

    if method in ("tools/call", "agent/run"):
        token = _bind_context_from_headers(
            x_fhir_server_url=x_fhir_server_url,
            x_fhir_access_token=x_fhir_access_token,
            x_patient_id=x_patient_id,
            x_fhir_refresh_token=x_fhir_refresh_token,
            x_fhir_refresh_url=x_fhir_refresh_url,
            x_trace_id=x_trace_id,
        )
        try:
            if method == "tools/call":
                name = params.get("name", "")
                args = params.get("arguments", {}) or {}
                if name not in TOOL_REGISTRY:
                    return JSONResponse(_jsonrpc_response(
                        req_id,
                        error={"code": -32601, "message": f"Unknown tool: {name}"},
                    ))
                _schema, handler = TOOL_REGISTRY[name]
                try:
                    result = await handler(**args)
                except TypeError as exc:
                    return JSONResponse(_jsonrpc_response(
                        req_id,
                        error={"code": -32602, "message": f"Invalid arguments: {exc}"},
                    ))
                except Exception as exc:
                    logger.exception("Tool %s raised", name)
                    return JSONResponse(_jsonrpc_response(
                        req_id,
                        error={"code": -32000, "message": f"{type(exc).__name__}: {exc}"},
                    ))
                return JSONResponse(_jsonrpc_response(req_id, result={
                    "content": [{"type": "text", "text": json.dumps(result, default=str)}],
                    "isError": False,
                }))

            # agent/run
            user_text = params.get("message", "") or params.get("user_message", "")
            if not user_text:
                return JSONResponse(_jsonrpc_response(
                    req_id,
                    error={"code": -32602, "message": "agent/run requires a non-empty 'message'"},
                ))
            try:
                agent_result = await run_agent(user_text, system_prompt=_load_agent_prompt())
            except RuntimeError as exc:
                return JSONResponse(_jsonrpc_response(
                    req_id,
                    error={"code": -32000, "message": str(exc)},
                ))
            return JSONResponse(_jsonrpc_response(req_id, result=agent_result))
        finally:
            reset_sharp_context(token)

    return JSONResponse(_jsonrpc_response(
        req_id,
        error={"code": -32601, "message": f"Method not found: {method}"},
    ))


# ── /a2a ─────────────────────────────────────────────────────────────────────

@app.post("/a2a")
async def a2a_post(
    payload: dict = Body(...),
    x_fhir_server_url: str | None = Header(None, alias="X-FHIR-Server-URL"),
    x_fhir_access_token: str | None = Header(None, alias="X-FHIR-Access-Token"),
    x_patient_id: str | None = Header(None, alias="X-Patient-ID"),
    x_fhir_refresh_token: str | None = Header(None, alias="X-FHIR-Refresh-Token"),
    x_fhir_refresh_url: str | None = Header(None, alias="X-FHIR-Refresh-Url"),
    x_trace_id: str | None = Header(None, alias="X-Trace-ID"),
) -> JSONResponse:
    """A2A v1 message endpoint — JSON-RPC envelope."""
    req_id = payload.get("id")
    method = payload.get("method", "")
    params = payload.get("params", {}) or {}

    audit_log("a2a.request", method=method, trace_id=x_trace_id or "")

    if method not in ("message/send", "message/stream", "agent/run"):
        return JSONResponse(_jsonrpc_response(
            req_id,
            error={"code": -32601, "message": f"A2A method not supported: {method}"},
        ))

    # Extract user text from A2A v1 message envelope
    message = params.get("message", {}) or {}
    user_text = ""
    for part in message.get("parts", []) or []:
        if part.get("type") in ("text", "text/plain") or "text" in part:
            user_text += part.get("text", "")
    if not user_text:
        user_text = params.get("user_message", "") or params.get("text", "")

    if not user_text:
        return JSONResponse(_jsonrpc_response(
            req_id,
            error={"code": -32602, "message": "A2A message has no text content"},
        ))

    token = _bind_context_from_headers(
        x_fhir_server_url=x_fhir_server_url,
        x_fhir_access_token=x_fhir_access_token,
        x_patient_id=x_patient_id,
        x_fhir_refresh_token=x_fhir_refresh_token,
        x_fhir_refresh_url=x_fhir_refresh_url,
        x_trace_id=x_trace_id,
    )
    try:
        try:
            agent_result = await run_agent(user_text, system_prompt=_load_agent_prompt())
        except RuntimeError as exc:
            return JSONResponse(_jsonrpc_response(
                req_id,
                error={"code": -32000, "message": str(exc)},
            ))

        return JSONResponse(_jsonrpc_response(req_id, result={
            "message": {
                "role": "assistant",
                "parts": [
                    {"type": "text", "text": agent_result.get("final_text", "")},
                    {
                        "type": "data",
                        "data": {
                            "tool_calls": agent_result.get("tool_calls", []),
                            "iterations": agent_result.get("iterations", 0),
                            "telemetry": agent_result.get("telemetry", {}),
                        },
                    },
                ],
            },
            "status": "completed",
        }))
    finally:
        reset_sharp_context(token)


@app.get("/mcp/sse")
async def mcp_sse() -> PlainTextResponse:
    """Optional SSE keepalive — Prompt Opinion polls this on Streamable HTTP."""
    return PlainTextResponse("event: ping\ndata: {}\n\n", media_type="text/event-stream")


# ── entrypoint ───────────────────────────────────────────────────────────────

def _resolve_transport() -> str:
    if os.environ.get("PORT"):
        return os.environ.get("SEPSISGUARD_TRANSPORT", "sse")
    return os.environ.get("SEPSISGUARD_TRANSPORT", "stdio")


async def _stdio_loop() -> None:
    """Minimal MCP stdio loop — reads JSON-RPC lines from stdin, writes to stdout.

    This is a best-effort implementation for local MCP clients (e.g. Claude
    Desktop). Production deploys use the HTTP transport via Prompt Opinion.
    """
    loop = asyncio.get_event_loop()
    reader = asyncio.StreamReader()
    protocol = asyncio.StreamReaderProtocol(reader)
    await loop.connect_read_pipe(lambda: protocol, sys.stdin)
    writer = sys.stdout

    while True:
        line = await reader.readline()
        if not line:
            break
        try:
            payload = json.loads(line.decode("utf-8"))
        except json.JSONDecodeError as exc:
            writer.write(json.dumps({
                "jsonrpc": "2.0", "id": None,
                "error": {"code": -32700, "message": f"Parse error: {exc}"},
            }) + "\n")
            writer.flush()
            continue

        # Re-use the FastAPI handler logic via a synthetic invocation.
        # Build a SharpContext from any embedded headers in params, if present.
        method = payload.get("method", "")
        req_id = payload.get("id")
        if method == "initialize":
            resp = _jsonrpc_response(req_id, result={
                "protocolVersion": _MCP_PROTOCOL_VERSION,
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
                "capabilities": {
                    "tools": {},
                    "extensions": {
                        "ai.promptopinion/fhir-context": {"scopes": REQUIRED_SCOPES}
                    },
                },
            })
        elif method == "tools/list":
            resp = _jsonrpc_response(req_id, result={"tools": _mcp_tool_list()})
        else:
            resp = _jsonrpc_response(
                req_id,
                error={
                    "code": -32601,
                    "message": (
                        f"Method '{method}' not supported over stdio. "
                        "Use HTTP transport for tools/call (FHIR context required)."
                    ),
                },
            )
        writer.write(json.dumps(resp) + "\n")
        writer.flush()


def main() -> None:
    parser = argparse.ArgumentParser(prog="sepsisguard-server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse", "http"],
        default=_resolve_transport(),
        help="Transport: stdio (default local), sse/http (cloud).",
    )
    parser.add_argument(
        "--host", default="0.0.0.0",
        help="HTTP bind host (used when transport != stdio).",
    )
    parser.add_argument(
        "--port", type=int,
        default=int(os.environ.get("PORT", "8080")),
        help="HTTP port (used when transport != stdio).",
    )
    parser.add_argument(
        "--log-level",
        default=os.environ.get("LOG_LEVEL", "INFO"),
        help="Logging level.",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=args.log_level.upper(),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    if args.transport == "stdio":
        asyncio.run(_stdio_loop())
        return

    # HTTP / SSE — both served by FastAPI/uvicorn (Streamable HTTP transport
    # accepts plain POST /mcp; SSE keepalive is exposed at /mcp/sse).
    import uvicorn
    uvicorn.run(app, host=args.host, port=args.port, log_level=args.log_level.lower())


if __name__ == "__main__":
    main()
