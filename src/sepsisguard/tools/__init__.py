"""SepsisGuard MCP tools.

Each tool module exports a SCHEMA dict and an async handler. The TOOL_REGISTRY
maps tool name -> (schema, handler) and is consumed by the MCP server's
tools/list and tools/call dispatchers.
"""

TOOL_REGISTRY: dict = {}
