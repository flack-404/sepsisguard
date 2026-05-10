"""Claude tool-use orchestrator for SepsisGuard.

Iterates the Anthropic Messages API with `tools=[...]` until stop_reason is
"end_turn" or max_iterations is exhausted. Dispatches tool_use blocks to
TOOL_REGISTRY[name][1](**input) and appends tool_result blocks back into the
conversation.

Critical detail (spec §12 Pattern 6): Anthropic enforces a max of 4
`cache_control` breakpoints per request. Before each new turn we strip
`cache_control` from older tool_result blocks (see _strip_old_cache_breakpoints).
Without this, breakpoint count grows unboundedly across iterations and the API
errors out.

Note on Claude unavailability: when ANTHROPIC_API_KEY is unset (DEMO_MODE),
this module raises RuntimeError — the demo runner has its own deterministic
fallback path that calls tools in spec order without an LLM orchestrator.
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any

import anthropic

from .audit import audit_log
from .sharp_context import current_sharp_context
from .tools import TOOL_REGISTRY

logger = logging.getLogger(__name__)

_PROMPT_PATH = Path(__file__).parent.parent.parent / "agent" / "agent_prompt.md"

_DEFAULT_MAX_ITERATIONS = 12


def _load_default_prompt() -> str:
    try:
        return _PROMPT_PATH.read_text(encoding="utf-8")
    except FileNotFoundError:
        logger.warning("agent_prompt.md not found at %s", _PROMPT_PATH)
        return "You are SepsisGuard. Use the available tools to assist the clinician."


def _build_anthropic_tools() -> list[dict[str, Any]]:
    """Remap MCP-style 'inputSchema' to Anthropic-style 'input_schema'."""
    tools: list[dict[str, Any]] = []
    for schema, _handler in TOOL_REGISTRY.values():
        tools.append({
            "name": schema["name"],
            "description": schema["description"],
            "input_schema": schema["inputSchema"],
        })
    return tools


def _strip_old_cache_breakpoints(messages: list[dict[str, Any]]) -> None:
    """Remove cache_control from older tool_result blocks (spec §12 Pattern 6)."""
    for msg in messages:
        if msg.get("role") != "user":
            continue
        content = msg.get("content", [])
        if not isinstance(content, list):
            continue
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_result":
                block.pop("cache_control", None)


def _content_blocks_to_serializable(content: Any) -> list[dict[str, Any]]:
    """Turn Anthropic SDK response content into JSON-safe dicts for the next turn."""
    out: list[dict[str, Any]] = []
    for block in content:
        btype = getattr(block, "type", None)
        if btype == "text":
            out.append({"type": "text", "text": getattr(block, "text", "")})
        elif btype == "tool_use":
            out.append({
                "type": "tool_use",
                "id": getattr(block, "id", ""),
                "name": getattr(block, "name", ""),
                "input": getattr(block, "input", {}) or {},
            })
        else:
            data = getattr(block, "model_dump", None)
            out.append(data() if callable(data) else {"type": btype or "unknown"})
    return out


async def _dispatch_tool(name: str, args: dict[str, Any]) -> dict[str, Any]:
    """Run a registered tool handler and return its result dict."""
    if name not in TOOL_REGISTRY:
        return {"error": f"Unknown tool: {name}"}
    _schema, handler = TOOL_REGISTRY[name]
    try:
        result = await handler(**(args or {}))
        return result if isinstance(result, dict) else {"value": result}
    except TypeError as exc:
        return {"error": f"Tool {name} called with bad arguments: {exc}"}
    except Exception as exc:
        logger.exception("Tool %s raised", name)
        return {"error": f"Tool {name} raised {type(exc).__name__}: {exc}"}


def _summarize_result(result: dict[str, Any]) -> dict[str, Any]:
    """Compact view of a tool result for the trace (drops large nested fields)."""
    if "error" in result:
        return {"error": result["error"]}
    summary: dict[str, Any] = {}
    for k in (
        "recommendation", "classification", "time_zero", "overall_compliance",
        "completed_count", "total_required", "next_at_risk_element",
        "task_ref", "communication_ref", "abstractor_compliance_score_predicted",
        "primary_regimen", "screening_score_4",
    ):
        if k in result:
            v = result[k]
            if isinstance(v, list) and v and isinstance(v[0], dict):
                summary[k] = [
                    d.get("medication") or d.get("name") or d.get("source") or "..."
                    for d in v
                ]
            else:
                summary[k] = v
    return summary or {"keys": list(result.keys())[:8]}


async def run_agent(
    user_message: str,
    *,
    system_prompt: str | None = None,
    max_iterations: int = _DEFAULT_MAX_ITERATIONS,
    max_tokens_per_turn: int = 4096,
) -> dict[str, Any]:
    """Run the agent tool-use loop. Returns trace + final summary.

    Raises RuntimeError if ANTHROPIC_API_KEY is unset.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set — cannot run agent loop")

    ctx = current_sharp_context()
    system_prompt = system_prompt or _load_default_prompt()
    model = os.environ.get("ANTHROPIC_MODEL", "claude-opus-4-7")

    audit_log(
        "agent.start",
        trace_id=ctx.trace_id,
        patient=f"Patient/{ctx.patient_id}",
        max_iterations=max_iterations,
        model=model,
    )

    client = anthropic.AsyncAnthropic(api_key=api_key)
    tools = _build_anthropic_tools()

    # System prompt cached for 1h (we expect repeated turns within a session
    # AND multi-patient invocations against the same model deployment).
    system = [
        {
            "type": "text",
            "text": system_prompt,
            "cache_control": {"type": "ephemeral", "ttl": "1h"},
        }
    ]

    messages: list[dict[str, Any]] = [
        {"role": "user", "content": user_message}
    ]

    tool_calls: list[dict[str, Any]] = []
    total_input_tokens = 0
    total_output_tokens = 0
    total_cache_read = 0
    total_cache_creation = 0
    final_text = ""
    stop_reason = "max_iterations"

    started = time.monotonic()

    for iteration in range(max_iterations):
        _strip_old_cache_breakpoints(messages)

        # NOTE: temperature intentionally omitted — deprecated for claude-opus-4-7.
        response = await client.messages.create(
            model=model,
            max_tokens=max_tokens_per_turn,
            system=system,
            messages=messages,
            tools=tools,
        )

        usage = response.usage
        total_input_tokens += getattr(usage, "input_tokens", 0)
        total_output_tokens += getattr(usage, "output_tokens", 0)
        total_cache_read += getattr(usage, "cache_read_input_tokens", 0)
        total_cache_creation += getattr(usage, "cache_creation_input_tokens", 0)
        stop_reason = response.stop_reason or stop_reason

        content_blocks = _content_blocks_to_serializable(response.content)
        messages.append({"role": "assistant", "content": content_blocks})

        tool_uses = [b for b in content_blocks if b.get("type") == "tool_use"]
        text_blocks = [b for b in content_blocks if b.get("type") == "text"]

        if not tool_uses:
            # Final assistant message — model is done.
            final_text = "\n".join(b.get("text", "") for b in text_blocks).strip()
            break

        # Run each requested tool and assemble all tool_results into one user msg.
        tool_results: list[dict[str, Any]] = []
        for tu in tool_uses:
            tname = tu.get("name", "")
            targs = tu.get("input", {}) or {}
            t_started = time.monotonic()
            result = await _dispatch_tool(tname, targs)
            duration_ms = int((time.monotonic() - t_started) * 1000)

            tool_calls.append({
                "iteration": iteration,
                "name": tname,
                "input": targs,
                "output_summary": _summarize_result(result),
                "duration_ms": duration_ms,
                "error": "error" in result,
            })
            audit_log(
                "agent.tool_call",
                trace_id=ctx.trace_id,
                patient=f"Patient/{ctx.patient_id}",
                tool=tname,
                iteration=iteration,
                duration_ms=duration_ms,
                status="error" if "error" in result else "ok",
            )

            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tu.get("id", ""),
                "content": json.dumps(result, default=str),
                "cache_control": {"type": "ephemeral", "ttl": "5m"},
            })

        messages.append({"role": "user", "content": tool_results})

    audit_log(
        "agent.end",
        trace_id=ctx.trace_id,
        patient=f"Patient/{ctx.patient_id}",
        iterations=len(tool_calls),
        stop_reason=stop_reason,
    )

    return {
        "final_text": final_text,
        "tool_calls": tool_calls,
        "iterations": len(tool_calls),
        "stop_reason": stop_reason,
        "telemetry": {
            "total_input_tokens": total_input_tokens,
            "total_output_tokens": total_output_tokens,
            "total_cache_read_tokens": total_cache_read,
            "total_cache_creation_tokens": total_cache_creation,
            "wall_seconds": round(time.monotonic() - started, 2),
            "model": model,
        },
    }
