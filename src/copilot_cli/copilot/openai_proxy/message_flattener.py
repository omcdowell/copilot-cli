"""Flatten OpenAI chat messages into Copilot-safe prompt text."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from copilot_cli.copilot.openai_proxy.prompt_config import get_prompts, render_session_context
from copilot_cli.copilot.openai_proxy.tool_protocol import (
    TOOL_CALL_FENCE,
    TOOL_RESPONSE_FENCE,
    ToolProtocolMode,
    build_continuation_header,
    build_local_tools_section,
    format_fence,
)


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


def _tool_payload(content: str) -> Any:
    try:
        return json.loads(content)
    except (json.JSONDecodeError, TypeError):
        return content


def _format_tool_call_fence(tool_call: Mapping[str, Any]) -> str:
    function = tool_call.get("function", {})
    name = function.get("name", "")
    arguments = function.get("arguments", "{}")
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except json.JSONDecodeError:
            arguments = {"raw": arguments}
    return format_fence(
        TOOL_CALL_FENCE,
        json.dumps({"name": name, "arguments": arguments}),
    )


def _format_assistant_message(message: Mapping[str, Any]) -> str:
    tool_calls = message.get("tool_calls")
    parts: list[str] = []
    content = _message_content(message)
    if content:
        prefix = get_prompts().assistant_role_prefix
        parts.append(f"{prefix} {content}")
    if tool_calls:
        for tool_call in tool_calls:
            parts.append(_format_tool_call_fence(tool_call))
    return "\n".join(parts)


def _format_tool_message(message: Mapping[str, Any]) -> str:
    content = _message_content(message)
    tool_name = message.get("name", "tool")
    payload = {"name": tool_name, "content": _tool_payload(content)}
    return format_fence(TOOL_RESPONSE_FENCE, json.dumps(payload))


def _format_message(message: Mapping[str, Any]) -> str:
    role = message.get("role", "")
    if role == "system":
        content = _message_content(message)
        return content
    if role == "user":
        content = _message_content(message)
        if not content:
            return ""
        prefix = get_prompts().user_role_prefix
        return f"{prefix} {content}"
    if role == "assistant":
        return _format_assistant_message(message)
    if role == "tool":
        return _format_tool_message(message)
    return ""


def _join_sections(sections: Iterable[str]) -> str:
    return "\n\n".join(section for section in sections if section)


def flatten_messages(
    messages: Sequence[Mapping[str, Any]],
    tools: Sequence[Mapping[str, Any]] | None = None,
) -> str:
    """
    Flatten OpenAI-style messages into a single prompt string for Copilot.

    Turn-1 shape when tools are present:

        ## Local tools  (overlay + ```tools catalog)
        ## Session context  (config pi_system, or Pi's system prompt if passthrough)
        [intermediate transcript]
        ## User request
        recency footer
    """
    prompts = get_prompts()
    systems: list[str] = []
    rest: list[Mapping[str, Any]] = []
    for message in messages:
        if message.get("role") == "system":
            content = _message_content(message)
            if content:
                systems.append(content)
        else:
            rest.append(message)

    last_user_index = None
    for index in range(len(rest) - 1, -1, -1):
        if rest[index].get("role") == "user":
            last_user_index = index
            break

    if last_user_index is None:
        history_before: Sequence[Mapping[str, Any]] = rest
        last_user = None
        history_after: Sequence[Mapping[str, Any]] = ()
    else:
        history_before = rest[:last_user_index]
        last_user = rest[last_user_index]
        history_after = rest[last_user_index + 1 :]

    sections: list[str] = []
    if tools:
        sections.append(build_local_tools_section(tools))
    client_system = "\n\n".join(systems)
    session_context = (
        client_system
        if prompts.use_client_system_prompt
        else render_session_context(prompts.pi_system, client_system)
    )
    if session_context:
        sections.append(f"{prompts.session_context_heading}\n\n{session_context}")

    before_text = _join_sections(_format_message(message) for message in history_before)
    if before_text:
        sections.append(before_text)

    if last_user is not None:
        user_content = _message_content(last_user)
        if user_content:
            sections.append(f"{prompts.user_request_heading}\n\n{user_content}")

    after_text = _join_sections(_format_message(message) for message in history_after)
    if after_text:
        sections.append(after_text)

    if tools:
        sections.append(prompts.recency_footer)

    return _join_sections(sections)


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


def _trailing_tool_loop(messages: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    trailing: list[Mapping[str, Any]] = []
    for message in reversed(messages):
        role = message.get("role")
        if role in ("tool", "assistant") and (role == "tool" or message.get("tool_calls")):
            trailing.append(message)
            continue
        break
    trailing.reverse()
    return trailing


def build_continuation_prompt(
    messages: Sequence[Mapping[str, Any]],
    tools: Sequence[Mapping[str, Any]] | None = None,
    *,
    protocol_mode: ToolProtocolMode = ToolProtocolMode.reminder,
) -> str:
    """
    Build a follow-up prompt for an existing Substrate conversation.

    Prefer tool-result turns (Pi tool loop). Otherwise send the latest user
    message. Tool-loop continuations send only ```tool_response fences, then a
    short tool_call reminder (``full`` re-sends overlay and catalog after the
    results). User-turn continuations still sandwich the request with the
    reminder and recency footer.
    """
    trailing = _trailing_tool_loop(messages)
    tool_results = [message for message in trailing if message.get("role") == "tool"]

    header = build_continuation_header(tools, protocol_mode)
    sections: list[str] = []

    if tool_results:
        body = _join_sections(_format_message(message) for message in tool_results)
        if body:
            sections.append(body)
        if header:
            sections.append(header)
        return _join_sections(sections)

    prompts = get_prompts()
    if header:
        sections.append(header)
    latest = extract_latest_user_message(messages) or ""
    if latest:
        sections.append(f"{prompts.user_request_heading}\n\n{latest}")
    if tools:
        sections.append(prompts.recency_footer)
    return _join_sections(sections)
