"""Synthesize OpenAI chat.completion.chunk SSE frames.

Live path holds back a short character window so we can detect Hermes
``<tool_call>`` tags without waiting for the full Substrate reply. Already-sent
SSE tokens cannot be retracted — the holdback is what prevents leaking the tag.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

from copilot_cli.copilot.openai_proxy.tool_parser import ParsedToolCall, parse_tool_calls

# Holdback lives in the proxy (not pi) so OpenAI clients never see a partial
# Hermes <tool_call> — one place, protocol-faithful.
TOOL_OPEN_TAG = "<tool_call>"
TOOL_HOLDBACK_CHARS = len(TOOL_OPEN_TAG)


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


def _role_frame(completion_id: str, created: int, model: str) -> str:
    return _sse(
        _chunk(
            completion_id=completion_id,
            created=created,
            model=model,
            delta={"role": "assistant"},
        )
    )


def _content_frame(completion_id: str, created: int, model: str, text: str) -> str:
    return _sse(
        _chunk(
            completion_id=completion_id,
            created=created,
            model=model,
            delta={"content": text},
        )
    )


def _tool_call_frames(
    completion_id: str, created: int, model: str, tool_calls: list[ParsedToolCall]
) -> Iterator[str]:
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


def _finish_frames(completion_id: str, created: int, model: str, finish_reason: str) -> Iterator[str]:
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


def iter_live_sse(
    *,
    completion_id: str,
    created: int,
    model: str,
    deltas: Iterator[str],
    watch_tools: bool,
    holdback_chars: int = TOOL_HOLDBACK_CHARS,
) -> Iterator[str]:
    """
    Stream Substrate deltas as OpenAI SSE with optional Hermes tool detection.

    When ``watch_tools`` is true, the last ``holdback_chars`` characters are not
    flushed until it is clear they are not the start of ``<tool_call>``. Once
    that opening tag is seen, content streaming stops; remaining deltas are
    buffered and parsed into OpenAI ``tool_calls`` at the end.

    OpenAI SSE cannot retract already-sent tokens — the holdback is the
    substitute for "removing" a partial tag from the stream.
    """
    yield _role_frame(completion_id, created, model)

    full = ""
    emitted = 0
    tool_mode = False

    for delta in deltas:
        if not delta:
            continue
        full += delta

        if not watch_tools:
            yield _content_frame(completion_id, created, model, delta)
            emitted = len(full)
            continue

        if tool_mode:
            continue

        open_at = full.find(TOOL_OPEN_TAG)
        if open_at != -1:
            # Flush any prose before the tag that has not been sent yet.
            if open_at > emitted:
                yield _content_frame(completion_id, created, model, full[emitted:open_at])
                emitted = open_at
            tool_mode = True
            continue

        # Keep a holdback so a split "<tool_call>" across deltas is not emitted.
        flush_upto = len(full) - holdback_chars
        if flush_upto > emitted:
            yield _content_frame(completion_id, created, model, full[emitted:flush_upto])
            emitted = flush_upto

    if watch_tools and tool_mode:
        _content, tool_calls = parse_tool_calls(full)
        # Content before the tag was already streamed; only emit tool_calls here.
        if tool_calls:
            yield from _tool_call_frames(completion_id, created, model, tool_calls)
            yield from _finish_frames(completion_id, created, model, "tool_calls")
            return
        # Tag-like text that did not parse — flush the remainder as content.
        remainder = full[emitted:]
        if remainder:
            yield _content_frame(completion_id, created, model, remainder)
        yield from _finish_frames(completion_id, created, model, "stop")
        return

    if watch_tools and emitted < len(full):
        yield _content_frame(completion_id, created, model, full[emitted:])

    yield from _finish_frames(completion_id, created, model, "stop")
