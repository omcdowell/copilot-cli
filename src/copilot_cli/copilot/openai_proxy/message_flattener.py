"""Flatten OpenAI chat messages into Copilot-safe prompt text."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from copilot_cli.copilot.openai_proxy.tool_protocol import build_tool_protocol_prompt


def _message_content(message: Mapping[str, Any]) -> str:
    content = message.get("content")
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text", "")))
        return "\n".join(parts)
    return str(content)


def _format_assistant_message(message: Mapping[str, Any]) -> str:
    tool_calls = message.get("tool_calls")
    parts: list[str] = []
    content = _message_content(message)
    if content:
        parts.append(f"[Assistant]: {content}")
    if tool_calls:
        for tool_call in tool_calls:
            function = tool_call.get("function", {})
            name = function.get("name", "")
            arguments = function.get("arguments", "{}")
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments)
                except json.JSONDecodeError:
                    arguments = {"raw": arguments}
            parts.append(
                f"<tool_call>\n{json.dumps({'name': name, 'arguments': arguments})}\n</tool_call>"
            )
    return "\n".join(parts)


def flatten_messages(
    messages: Sequence[Mapping[str, Any]],
    tools: Sequence[Mapping[str, Any]] | None = None,
) -> str:
    """
    Flatten OpenAI-style messages into a single prompt string for Copilot.

    System messages are inlined as [System] blocks. Tool results use Hermes
    <tool_response> tags so the model can continue tool loops.
    """
    parts: list[str] = []
    for message in messages:
        role = message.get("role", "")
        if role == "system":
            content = _message_content(message)
            if content:
                parts.append(f"[System]: {content}")
        elif role == "user":
            content = _message_content(message)
            if content:
                parts.append(f"[User]: {content}")
        elif role == "assistant":
            formatted = _format_assistant_message(message)
            if formatted:
                parts.append(formatted)
        elif role == "tool":
            content = _message_content(message)
            tool_name = message.get("name", "tool")
            payload = content
            try:
                payload = json.loads(content)
            except (json.JSONDecodeError, TypeError):
                payload = {"result": content}
            parts.append(
                f"<tool_response>\n{json.dumps({'name': tool_name, 'content': payload})}\n</tool_response>"
            )

    body = "\n\n".join(parts)
    if tools:
        protocol = build_tool_protocol_prompt(tools)
        return f"{protocol}\n\n{body}" if body else protocol
    return body


def extract_latest_user_message(messages: Sequence[Mapping[str, Any]]) -> str | None:
    """Return the content of the last user message, if any."""
    for message in reversed(messages):
        if message.get("role") == "user":
            content = _message_content(message)
            if content:
                return content
    return None


def count_user_messages(messages: Sequence[Mapping[str, Any]]) -> int:
    return sum(1 for message in messages if message.get("role") == "user")


def build_continuation_prompt(
    messages: Sequence[Mapping[str, Any]],
    tools: Sequence[Mapping[str, Any]] | None = None,
) -> str:
    """
    Build a follow-up prompt for an existing Substrate conversation.

    Prefer tool-result turns (Pi tool loop). Otherwise send the latest user
    message. When tools are present, re-inject the tool protocol so Copilot
    keeps emitting <tool_call> markup.
    """
    trailing: list[Mapping[str, Any]] = []
    for message in reversed(messages):
        role = message.get("role")
        if role in ("tool", "assistant") and (
            role == "tool" or message.get("tool_calls")
        ):
            trailing.append(message)
            continue
        break
    trailing.reverse()

    tool_results = [m for m in trailing if m.get("role") == "tool"]
    if tool_results:
        body = flatten_messages(trailing, tools=None)
    else:
        latest = extract_latest_user_message(messages) or ""
        body = latest

    if tools:
        protocol = build_tool_protocol_prompt(tools)
        return f"{protocol}\n\n{body}" if body else protocol
    return body
