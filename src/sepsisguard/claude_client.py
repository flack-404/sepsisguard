"""Anthropic API wrapper with explicit prompt caching.

Critical: do NOT pass `temperature` — deprecated for claude-opus-4-7.
Cache breakpoint management (stripping old tool_result cache_control) is the
responsibility of agent_loop.py, not this module.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Literal

import anthropic


@dataclass
class CacheableBlock:
    text: str
    cache: bool = False
    ttl: Literal["5m", "1h"] = "5m"


@dataclass
class ClaudeResult:
    text: str
    input_tokens: int
    output_tokens: int
    cache_read_input_tokens: int
    cache_creation_input_tokens: int
    stop_reason: str

    @property
    def cache_hit_ratio(self) -> float:
        total = self.input_tokens + self.cache_read_input_tokens
        if total == 0:
            return 0.0
        return self.cache_read_input_tokens / total


class ClaudeClient:
    def __init__(self) -> None:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        self.model: str = os.environ.get("ANTHROPIC_MODEL", "claude-opus-4-7")
        self._demo_mode: bool = (
            os.environ.get("DEMO_MODE", "false").lower() == "true"
        )
        if api_key:
            self._client: anthropic.AsyncAnthropic | None = anthropic.AsyncAnthropic(
                api_key=api_key
            )
        else:
            self._client = None

    async def generate(
        self,
        *,
        system_blocks: list[CacheableBlock],
        user_blocks: list[CacheableBlock],
        max_tokens: int,
        tools: list[dict[str, Any]] | None = None,
        messages: list[dict[str, Any]] | None = None,
    ) -> ClaudeResult:
        """Call Claude with prompt caching. Never passes temperature."""
        if self._client is None:
            raise RuntimeError(
                "ANTHROPIC_API_KEY not set; tool stub fallback should run instead"
            )

        system: list[dict[str, Any]] = []
        for block in system_blocks:
            entry: dict[str, Any] = {"type": "text", "text": block.text}
            if block.cache:
                entry["cache_control"] = {"type": "ephemeral", "ttl": block.ttl}
            system.append(entry)

        if messages is None:
            content: list[dict[str, Any]] = []
            for block in user_blocks:
                item: dict[str, Any] = {"type": "text", "text": block.text}
                if block.cache:
                    item["cache_control"] = {"type": "ephemeral", "ttl": block.ttl}
                content.append(item)
            messages = [{"role": "user", "content": content}]

        # NOTE: temperature intentionally omitted — deprecated for claude-opus-4-7.
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": messages,
        }
        if tools:
            kwargs["tools"] = tools

        response = await self._client.messages.create(**kwargs)

        text = ""
        for block in response.content:
            if hasattr(block, "text"):
                text += block.text

        usage = response.usage
        return ClaudeResult(
            text=text,
            input_tokens=getattr(usage, "input_tokens", 0),
            output_tokens=getattr(usage, "output_tokens", 0),
            cache_read_input_tokens=getattr(usage, "cache_read_input_tokens", 0),
            cache_creation_input_tokens=getattr(
                usage, "cache_creation_input_tokens", 0
            ),
            stop_reason=response.stop_reason or "end_turn",
        )
