"""Local-tool overlay injected into Substrate user messages."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from enum import Enum
from typing import Any

from copilot_cli.copilot.openai_proxy.prompt_config import DEFAULT_PROMPTS, get_prompts

TOOL_CALL_FENCE = "tool_call"
TOOL_RESPONSE_FENCE = "tool_response"
TOOLS_CATALOG_FENCE = "tools"

LOCAL_TOOLS_OVERLAY = DEFAULT_PROMPTS.local_tools_overlay
RECENCY_FOOTER = DEFAULT_PROMPTS.recency_footer
CONTINUATION_REMINDER = DEFAULT_PROMPTS.continuation_reminder


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
    prompts = get_prompts()
    return (
        f"{prompts.local_tools_heading}\n\n{prompts.local_tools_overlay}\n\n"
        f"{format_tools_catalog(tools)}"
    )


def build_continuation_header(
    tools: Sequence[Mapping[str, Any]] | None,
    mode: ToolProtocolMode = ToolProtocolMode.reminder,
) -> str:
    if not tools:
        return ""
    if mode is ToolProtocolMode.full:
        return build_local_tools_section(tools)
    return get_prompts().continuation_reminder


def build_tool_protocol_prompt(tools: Sequence[Mapping[str, Any]]) -> str:
    """Full overlay + catalog. Kept as the turn-1 protocol block."""
    return build_local_tools_section(tools)
