"""Parse Hermes-style <tool_call> blocks from Copilot text responses."""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from typing import Any

_TOOL_CALL_PATTERN = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.DOTALL)


@dataclass(frozen=True)
class ParsedToolCall:
    id: str
    name: str
    arguments: str


def parse_tool_calls(text: str) -> tuple[str | None, list[ParsedToolCall]]:
    """
    Extract tool calls from assistant text.

    Returns (content_without_tool_calls, tool_calls). content is None when the
    response is entirely tool calls.
    """
    if "<tool_call>" not in text:
        return text, []

    tool_calls: list[ParsedToolCall] = []
    for match in _TOOL_CALL_PATTERN.finditer(text):
        try:
            payload = json.loads(match.group(1))
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        name = payload.get("name")
        if not name:
            continue
        arguments = payload.get("arguments", {})
        arguments_str = arguments if isinstance(arguments, str) else json.dumps(arguments)
        tool_calls.append(
            ParsedToolCall(
                id=f"call_{uuid.uuid4().hex[:12]}",
                name=str(name),
                arguments=arguments_str,
            )
        )

    if not tool_calls:
        return text, []

    cleaned = _TOOL_CALL_PATTERN.sub("", text).strip()
    content = cleaned if cleaned else None
    return content, tool_calls


def to_openai_tool_calls(tool_calls: list[ParsedToolCall]) -> list[dict[str, Any]]:
    return [
        {
            "id": call.id,
            "type": "function",
            "function": {
                "name": call.name,
                "arguments": call.arguments,
            },
        }
        for call in tool_calls
    ]
