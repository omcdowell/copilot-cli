"""Synthesize OpenAI chat.completion.chunk SSE frames from a complete reply."""

from __future__ import annotations

import json
import threading
from typing import Any, Callable, Iterator

from copilot_cli.copilot.openai_proxy.tool_parser import ParsedToolCall, parse_tool_calls

PING_INTERVAL_SECONDS = 15.0


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


def _iter_reply_frames(
    *,
    completion_id: str,
    created: int,
    model: str,
    content: str | None,
    tool_calls: list[ParsedToolCall],
) -> Iterator[str]:
    """Yield content/tool-call deltas, the finish chunk, and [DONE]."""
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
    yield from _iter_reply_frames(
        completion_id=completion_id,
        created=created,
        model=model,
        content=content,
        tool_calls=tool_calls,
    )


def iter_streaming_completion(
    *,
    completion_id: str,
    created: int,
    model: str,
    produce: Callable[[], str],
    ping_interval: float = PING_INTERVAL_SECONDS,
) -> Iterator[str]:
    """
    Yield SSE frames while `produce` runs the (slow) Copilot turn in a thread.

    The role chunk is emitted before Copilot is contacted so clients get
    response headers and a first frame immediately; SSE comment pings keep the
    connection alive during long turns (first-message auth can take minutes).
    If `produce` raises, an OpenAI-style in-stream error frame is emitted —
    the openai SDK surfaces it as an APIError with the real message instead of
    "Stream ended without finish_reason" or a socket error.
    """
    yield _sse(
        _chunk(
            completion_id=completion_id,
            created=created,
            model=model,
            delta={"role": "assistant"},
        )
    )

    result: dict[str, Any] = {}

    def _worker() -> None:
        try:
            result["text"] = produce()
        except BaseException as exc:  # surfaced to the client as an error frame
            result["error"] = exc

    thread = threading.Thread(target=_worker, name="copilot-turn", daemon=True)
    thread.start()
    while True:
        thread.join(ping_interval)
        if not thread.is_alive():
            break
        yield ": ping\n\n"

    error = result.get("error")
    if error is not None:
        yield _sse(
            {
                "error": {
                    "message": f"{type(error).__name__}: {error}",
                    "type": "copilot_proxy_error",
                    "code": "upstream_error",
                }
            }
        )
        yield _sse("[DONE]")
        return

    response_text = result.get("text") or ""
    content, tool_calls = parse_tool_calls(response_text)
    yield from _iter_reply_frames(
        completion_id=completion_id,
        created=created,
        model=model,
        content=content if tool_calls else response_text,
        tool_calls=tool_calls,
    )
