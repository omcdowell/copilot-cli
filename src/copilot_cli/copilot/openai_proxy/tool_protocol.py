"""Local-tool overlay injected into Substrate user messages."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from enum import Enum
from typing import Any

TOOL_CALL_FENCE = "tool_call"
TOOL_RESPONSE_FENCE = "tool_response"
TOOLS_CATALOG_FENCE = "tools"

LOCAL_TOOLS_OVERLAY = (
    "You have access to the tools listed below. They run on the user's machine; "
    "they are not Microsoft 365 Copilot's built-in workplace tools. "
    "When (and only when) you need to call a tool, reply with ONLY one or more "
    "fenced code blocks, each tagged `tool_call` and containing a single JSON "
    "object of this exact form:\n"
    "\n"
    f"```{TOOL_CALL_FENCE}\n"
    '{"name": "<tool_name>", "arguments": { ... }}\n'
    "```\n"
    "\n"
    "To call several tools at once, emit several such blocks back to back, one JSON "
    "object each, and nothing else around them. "
    "Do not add any prose before, between, or after the blocks when calling tools. "
    "If you do not need a tool, reply normally with your answer."
)

RECENCY_FOOTER = "If you need a local tool, reply with only ```tool_call fences."

CONTINUATION_REMINDER = (
    "Continue making any necessary follow-up ```tool_call requests "
    "until you have completed the task."
)


class ToolProtocolMode(str, Enum):
    """How much protocol to re-inject on Substrate continuation turns."""

    reminder = "reminder"
    full = "full"


def format_fence(info: str, body: str) -> str:
    return f"```{info}\n{body}\n```"


def format_tools_catalog(tools: Sequence[Mapping[str, Any]]) -> str:
    normalized = [tool for tool in tools if tool.get("type") == "function"]
    return format_fence(TOOLS_CATALOG_FENCE, json.dumps(normalized, indent=2))


def build_local_tools_section(tools: Sequence[Mapping[str, Any]]) -> str:
    """Turn-1 (and full-mode) overlay plus JSON catalog."""
    return f"## Local tools\n\n{LOCAL_TOOLS_OVERLAY}\n\n{format_tools_catalog(tools)}"


def build_continuation_header(
    tools: Sequence[Mapping[str, Any]] | None,
    mode: ToolProtocolMode = ToolProtocolMode.reminder,
) -> str:
    if not tools:
        return ""
    if mode is ToolProtocolMode.full:
        return build_local_tools_section(tools)
    return CONTINUATION_REMINDER


def build_tool_protocol_prompt(tools: Sequence[Mapping[str, Any]]) -> str:
    """Full overlay + catalog. Kept as the turn-1 protocol block."""
    return build_local_tools_section(tools)
