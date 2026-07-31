"""Synthesize OpenAI chat.completion.chunk SSE frames from a complete reply."""

from __future__ import annotations

import json
from typing import Any, Iterator

from copilot_cli.copilot.openai_proxy.tool_parser import ParsedToolCall


def _sse(payload: dict[str, Any] | str) -> str:
    if isinstance(payload, str):
        return f"data: {payload}\n\n"
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _chunk(
    *,
    completion_id: str,
    created: int,
    model: str,
    delta: dict[str, Any],
    finish_reason: str | None = None,
) -> dict[str, Any]:
    return {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model,
        "choices": [
            {
                "index": 0,
                "delta": delta,
                "finish_reason": finish_reason,
            }
        ],
    }


def iter_completion_sse(
    *,
    completion_id: str,
    created: int,
    model: str,
    content: str | None,
    tool_calls: list[ParsedToolCall],
) -> Iterator[str]:
    """
    Yield OpenAI-compatible SSE lines for a completed Copilot reply.

    Pi's openai-completions client always requests stream=true and requires a
    final chunk with finish_reason before [DONE].
    """
    yield _sse(
        _chunk(
            completion_id=completion_id,
            created=created,
            model=model,
            delta={"role": "assistant"},
        )
    )

    if tool_calls:
        if content:
            yield _sse(
                _chunk(
                    completion_id=completion_id,
                    created=created,
                    model=model,
                    delta={"content": content},
                )
            )
        for index, call in enumerate(tool_calls):
            yield _sse(
                _chunk(
                    completion_id=completion_id,
                    created=created,
                    model=model,
                    delta={
                        "tool_calls": [
                            {
                                "index": index,
                                "id": call.id,
                                "type": "function",
                                "function": {
                                    "name": call.name,
                                    "arguments": call.arguments,
                                },
                            }
                        ]
                    },
                )
            )
        finish_reason = "tool_calls"
    else:
        text = content or ""
        if text:
            yield _sse(
                _chunk(
                    completion_id=completion_id,
                    created=created,
                    model=model,
                    delta={"content": text},
                )
            )
        finish_reason = "stop"

    yield _sse(
        _chunk(
            completion_id=completion_id,
            created=created,
            model=model,
            delta={},
            finish_reason=finish_reason,
        )
    )
    yield _sse("[DONE]")
