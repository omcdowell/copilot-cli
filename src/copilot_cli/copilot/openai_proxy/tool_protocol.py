"""Hermes-style tool protocol injection for emulated tool calling."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

TOOL_PROTOCOL_HEADER = (
    "You are a function calling AI model. You are provided with function signatures "
    "within <tools></tools> XML tags. You may call one or more functions to assist "
    "with the user query. Don't make assumptions about what values to plug into functions.\n\n"
    "Here are the available tools:\n"
    "<tools>\n{tools_json}\n</tools>\n\n"
    "For each function call return a JSON object with function name and arguments "
    "within <tool_call></tool_call> XML tags as follows:\n"
    "<tool_call>\n"
    '{{"name": <function-name>, "arguments": <args-dict>}}\n'
    "</tool_call>"
)


def build_tool_protocol_prompt(tools: Sequence[Mapping[str, Any]]) -> str:
    """Build the fixed Hermes-style tool protocol preamble from OpenAI tools."""
    normalized = [tool for tool in tools if tool.get("type") == "function"]
    tools_json = json.dumps(normalized, indent=2)
    return TOOL_PROTOCOL_HEADER.format(tools_json=tools_json)
