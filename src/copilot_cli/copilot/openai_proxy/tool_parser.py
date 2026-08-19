"""Parse ```tool_call fenced JSON blocks from Copilot text responses."""

from __future__ import annotations

import html
import json
import logging
import re
import uuid
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

TOOL_OPEN_FENCE = "```tool_call"
TOOL_OPEN_TAG = TOOL_OPEN_FENCE  # streaming tests and holdback needle
# Hold enough suffix to distinguish ```tool_call from ```python / ```json / ```.
TOOL_HOLDBACK_CHARS = 16

_OPEN_FENCE = re.compile(r"```[ \t]*tool_call\b[^\n]*", re.IGNORECASE)
_CLOSE_FENCE = re.compile(r"\s*```(?![ \t]*tool_call\b)[ \t]*", re.IGNORECASE)
_TOOL_MARKUP_PATTERN = _OPEN_FENCE


@dataclass(frozen=True)
class ParsedToolCall:
    id: str
    name: str
    arguments: str


def _snippet(text: str, *, limit: int = 120) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return f"{compact[: limit - 3]}..."


def _normalize_text(text: str) -> str:
    return html.unescape(text)


def has_tool_call_markup(text: str) -> bool:
    return _TOOL_MARKUP_PATTERN.search(_normalize_text(text)) is not None


def find_tool_open_tag(text: str) -> int:
    """Return the start index of the earliest ```tool_call fence, or -1."""
    match = _OPEN_FENCE.search(text)
    return match.start() if match else -1


def remaining_content_after_streamed(content: str | None, streamed_prefix: str) -> str:
    """Return parsed content suffix that has not been streamed yet."""
    if not content:
        return ""
    if content.startswith(streamed_prefix):
        return content[len(streamed_prefix) :]
    stripped_content = content.strip()
    stripped_prefix = streamed_prefix.strip()
    if stripped_content.startswith(stripped_prefix):
        return stripped_content[len(stripped_prefix) :]
    return ""


def _decode_json_at(text: str, pos: int) -> tuple[Any, int] | None:
    slice_ = text[pos:]
    stripped = slice_.lstrip()
    skipped = len(slice_) - len(stripped)
    try:
        payload, end = json.JSONDecoder().raw_decode(stripped)
    except json.JSONDecodeError:
        return None
    return payload, pos + skipped + end


def _consume_close_fence(text: str, pos: int) -> int | None:
    match = _CLOSE_FENCE.match(text, pos)
    if match is None:
        return None
    return match.end()


def _parse_block_payload(payload: Any, raw_snippet: str) -> ParsedToolCall | None:
    if not isinstance(payload, dict):
        logger.warning("tool_call payload is not an object: %s", _snippet(raw_snippet))
        return None
    name = payload.get("name")
    if not name:
        logger.warning("Missing tool name in tool_call block: %s", _snippet(raw_snippet))
        return None
    arguments = payload.get("arguments", {})
    arguments_str = arguments if isinstance(arguments, str) else json.dumps(arguments)
    return ParsedToolCall(
        id=f"call_{uuid.uuid4().hex[:12]}",
        name=str(name),
        arguments=arguments_str,
    )


def _accept_tool_call(
    call: ParsedToolCall | None,
    *,
    allowed_tool_names: set[str] | None,
    raw_snippet: str,
) -> ParsedToolCall | None:
    if call is None:
        return None
    if allowed_tool_names is not None and call.name not in allowed_tool_names:
        logger.warning(
            "Unknown tool name %r in tool_call block, demoting to content: %s",
            call.name,
            _snippet(raw_snippet),
        )
        return None
    return call


def parse_tool_calls(
    text: str,
    *,
    allowed_tool_names: set[str] | None = None,
    salvage_unclosed: bool = False,
) -> tuple[str | None, list[ParsedToolCall]]:
    """
    Extract tool calls from assistant text.

    Returns (content_without_tool_calls, tool_calls). content is None when the
    response is entirely tool calls. Unknown tool names (when ``allowed_tool_names``
    is set) are left in content instead of being emitted as tool calls.
    """
    if not has_tool_call_markup(text):
        return text, []

    normalized = _normalize_text(text)
    tool_calls: list[ParsedToolCall] = []
    content_parts: list[str] = []
    last_end = 0
    search_from = 0

    while True:
        match = _OPEN_FENCE.search(normalized, search_from)
        if match is None:
            break

        decoded = _decode_json_at(normalized, match.end())
        if decoded is None:
            logger.warning("JSON parse failed for tool_call block: %s", _snippet(match.group(0)))
            search_from = match.start() + 3
            continue

        payload, json_end = decoded
        close_end = _consume_close_fence(normalized, json_end)
        if close_end is None:
            if not salvage_unclosed:
                search_from = match.start() + 3
                continue
            block_end = json_end
        else:
            block_end = close_end

        raw_snippet = normalized[match.start() : block_end]
        call = _accept_tool_call(
            _parse_block_payload(payload, raw_snippet),
            allowed_tool_names=allowed_tool_names,
            raw_snippet=raw_snippet,
        )
        if call is None:
            search_from = match.start() + 3
            continue

        content_parts.append(normalized[last_end : match.start()])
        last_end = block_end
        search_from = block_end
        tool_calls.append(call)

    if not tool_calls:
        if has_tool_call_markup(text):
            logger.warning(
                "Tag-like content found but no valid tool calls parsed: %s",
                _snippet(normalized),
            )
        return text, []

    cleaned = "".join(content_parts) + normalized[last_end:]
    cleaned = cleaned.strip()
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
