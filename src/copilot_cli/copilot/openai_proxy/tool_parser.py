"""Parse Hermes-style <tool_call> blocks from Copilot text responses."""

from __future__ import annotations

import html
import json
import logging
import re
import uuid
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

_TOOL_OPEN_TAG = "<tool_call>"
_ESCAPED_OPEN_TAG = "&lt;tool_call&gt;"
TOOL_OPEN_TAG = _TOOL_OPEN_TAG
TOOL_HOLDBACK_CHARS = max(len(_TOOL_OPEN_TAG), len(_ESCAPED_OPEN_TAG))

_TOOL_CALL_PATTERN = re.compile(
    r"<tool_call>\s*(\{.*?\})\s*</tool_call>",
    re.DOTALL | re.IGNORECASE,
)
_UNCLOSED_TOOL_CALL_PATTERN = re.compile(
    r"<tool_call>\s*(\{.*)\s*$",
    re.DOTALL | re.IGNORECASE,
)
_FENCED_TOOL_BLOCK_PATTERN = re.compile(
    r"```(?:\w+)?\s*(<tool_call>.*?</tool_call>)\s*```",
    re.DOTALL | re.IGNORECASE,
)
_FENCED_UNCLOSED_TOOL_BLOCK_PATTERN = re.compile(
    r"```(?:\w+)?\s*(<tool_call>.*)\s*```?\s*$",
    re.DOTALL | re.IGNORECASE,
)
_TOOL_MARKUP_PATTERN = re.compile(r"<tool_call>", re.IGNORECASE)


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
    """Strip fences and HTML escapes so tag scanning tolerates noisy model output."""
    normalized = html.unescape(text)
    normalized = _FENCED_TOOL_BLOCK_PATTERN.sub(r"\1", normalized)
    normalized = _FENCED_UNCLOSED_TOOL_BLOCK_PATTERN.sub(r"\1", normalized)
    return normalized


def has_tool_call_markup(text: str) -> bool:
    return _TOOL_MARKUP_PATTERN.search(_normalize_text(text)) is not None


def find_tool_open_tag(text: str) -> int:
    """Return the start index of the earliest open tag (raw or HTML-escaped)."""
    lowered = text.lower()
    indices = [
        lowered.find(_TOOL_OPEN_TAG),
        lowered.find(_ESCAPED_OPEN_TAG.lower()),
    ]
    found = [index for index in indices if index != -1]
    return min(found) if found else -1


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


def _parse_block_payload(payload_raw: str, raw_snippet: str) -> ParsedToolCall | None:
    try:
        payload = json.loads(payload_raw)
    except json.JSONDecodeError:
        logger.warning("JSON parse failed for tool_call block: %s", _snippet(raw_snippet))
        return None
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

    for match in _TOOL_CALL_PATTERN.finditer(normalized):
        block_start, block_end = match.span()
        raw_snippet = match.group(0)
        call = _accept_tool_call(
            _parse_block_payload(match.group(1), raw_snippet),
            allowed_tool_names=allowed_tool_names,
            raw_snippet=raw_snippet,
        )
        if call is None:
            continue
        content_parts.append(normalized[last_end:block_start])
        last_end = block_end
        tool_calls.append(call)

    trailing = normalized[last_end:]
    if salvage_unclosed and _TOOL_MARKUP_PATTERN.search(trailing):
        closed_after_markup = re.search(r"</tool_call>\s*$", trailing, re.IGNORECASE) is None
        if closed_after_markup:
            unclosed = _UNCLOSED_TOOL_CALL_PATTERN.search(trailing)
            if unclosed:
                raw_snippet = unclosed.group(0)
                call = _accept_tool_call(
                    _parse_block_payload(unclosed.group(1), raw_snippet),
                    allowed_tool_names=allowed_tool_names,
                    raw_snippet=raw_snippet,
                )
                if call is not None:
                    content_parts.append(trailing[: unclosed.start()])
                    last_end = len(normalized)
                    tool_calls.append(call)
                    trailing = ""

    if not tool_calls:
        if has_tool_call_markup(text):
            logger.warning(
                "Tag-like content found but no valid tool calls parsed: %s",
                _snippet(normalized),
            )
        return text, []

    cleaned = "".join(content_parts) + trailing
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
