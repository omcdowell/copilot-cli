"""Synthesize OpenAI chat.completion.chunk SSE frames.

Live path holds back a short character window so we can detect tool_call
fences without waiting for the full Substrate reply. Already-sent SSE tokens
cannot be retracted — the holdback is what prevents leaking the fence opener.
"""

from __future__ import annotations

import json
import queue
import threading
from collections.abc import Callable, Iterator
from typing import Any

from copilot_cli.copilot.openai_proxy.tool_parser import (
    TOOL_HOLDBACK_CHARS,
    ParsedToolCall,
    find_tool_open_tag,
    has_tool_call_markup,
    parse_tool_calls,
    remaining_content_after_streamed,
)

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


def _error_frames(exc: BaseException) -> Iterator[str]:
    yield _sse(
        {
            "error": {
                "message": f"{type(exc).__name__}: {exc}",
                "type": "copilot_proxy_error",
                "code": "upstream_error",
            }
        }
    )
    yield _sse("[DONE]")


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
            yield _content_frame(completion_id, created, model, content)
        yield from _tool_call_frames(completion_id, created, model, tool_calls)
        finish_reason = "tool_calls"
    else:
        text = content or ""
        if text:
            yield _content_frame(completion_id, created, model, text)
        finish_reason = "stop"

    yield from _finish_frames(completion_id, created, model, finish_reason)


def _iter_live_body(
    *,
    completion_id: str,
    created: int,
    model: str,
    deltas: Iterator[str],
    watch_tools: bool,
    holdback_chars: int,
    allowed_tool_names: set[str] | None,
) -> Iterator[str]:
    full = ""
    emitted = 0
    tool_mode = False
    open_at = -1

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

        open_at = find_tool_open_tag(full)
        if open_at != -1:
            if open_at > emitted:
                yield _content_frame(completion_id, created, model, full[emitted:open_at])
                emitted = open_at
            tool_mode = True
            continue

        flush_upto = len(full) - holdback_chars
        if flush_upto > emitted:
            yield _content_frame(completion_id, created, model, full[emitted:flush_upto])
            emitted = flush_upto

    if watch_tools and (tool_mode or has_tool_call_markup(full)):
        content, tool_calls = parse_tool_calls(
            full,
            allowed_tool_names=allowed_tool_names,
            salvage_unclosed=True,
        )
        if tool_calls:
            streamed_prefix = full[:open_at] if tool_mode and open_at != -1 else full[:emitted]
            leftover = remaining_content_after_streamed(content, streamed_prefix)
            if leftover:
                yield _content_frame(completion_id, created, model, leftover)
            yield from _tool_call_frames(completion_id, created, model, tool_calls)
            yield from _finish_frames(completion_id, created, model, "tool_calls")
            return

        if allowed_tool_names is not None:
            _, unfiltered_calls = parse_tool_calls(
                full,
                allowed_tool_names=None,
                salvage_unclosed=True,
            )
            if unfiltered_calls:
                remainder = full[emitted:]
                if remainder:
                    yield _content_frame(completion_id, created, model, remainder)
                yield from _finish_frames(completion_id, created, model, "stop")
                return

        if tool_mode and open_at != -1 and open_at > emitted:
            yield _content_frame(completion_id, created, model, full[emitted:open_at])
            emitted = open_at
        elif not tool_mode and emitted < len(full):
            open_at = find_tool_open_tag(full)
            if open_at != -1 and open_at > emitted:
                yield _content_frame(completion_id, created, model, full[emitted:open_at])
                emitted = open_at
        yield from _finish_frames(completion_id, created, model, "stop")
        return

    if watch_tools and emitted < len(full):
        yield _content_frame(completion_id, created, model, full[emitted:])

    yield from _finish_frames(completion_id, created, model, "stop")


def _start_delta_worker(deltas: Callable[[], Iterator[str]]) -> tuple[queue.Queue[Any], list[BaseException]]:
    q: queue.Queue[Any] = queue.Queue()
    errors: list[BaseException] = []

    def _worker() -> None:
        try:
            for delta in deltas():
                q.put(delta)
        except BaseException as exc:
            errors.append(exc)
        finally:
            q.put(None)

    threading.Thread(target=_worker, name="substrate-deltas", daemon=True).start()
    return q, errors


def _iter_queued_deltas(q: queue.Queue[Any], errors: list[BaseException]) -> Iterator[str]:
    while True:
        item = q.get()
        if errors:
            raise errors[0]
        if item is None:
            return
        yield item


def iter_live_sse(
    *,
    completion_id: str,
    created: int,
    model: str,
    deltas: Iterator[str],
    watch_tools: bool,
    holdback_chars: int = TOOL_HOLDBACK_CHARS,
    allowed_tool_names: set[str] | None = None,
) -> Iterator[str]:
    """
    Stream Substrate deltas as OpenAI SSE with optional tool_call fence detection.

    When ``watch_tools`` is true, the last ``holdback_chars`` characters are not
    flushed until it is clear they are not the start of a ``tool_call`` fence. Once
    that opening fence is seen, content streaming stops; remaining deltas are
    buffered and parsed into OpenAI ``tool_calls`` at the end.
    """
    yield _role_frame(completion_id, created, model)
    yield from _iter_live_body(
        completion_id=completion_id,
        created=created,
        model=model,
        deltas=deltas,
        watch_tools=watch_tools,
        holdback_chars=holdback_chars,
        allowed_tool_names=allowed_tool_names,
    )


def iter_live_sse_with_keepalive(
    *,
    completion_id: str,
    created: int,
    model: str,
    deltas: Callable[[], Iterator[str]],
    watch_tools: bool,
    holdback_chars: int = TOOL_HOLDBACK_CHARS,
    allowed_tool_names: set[str] | None = None,
    ping_interval: float = PING_INTERVAL_SECONDS,
) -> Iterator[str]:
    """
    Like iter_live_sse but emits SSE comment pings while waiting for the first delta.

    The role chunk goes out immediately; pings keep Pi clients alive during
    slow first-message auth. Upstream failures become in-stream OpenAI error frames.
    """
    yield _role_frame(completion_id, created, model)

    q, errors = _start_delta_worker(deltas)

    while True:
        try:
            item = q.get(timeout=ping_interval)
        except queue.Empty:
            if errors:
                yield from _error_frames(errors[0])
                return
            yield ": ping\n\n"
            continue
        if errors:
            yield from _error_frames(errors[0])
            return
        if item is None:
            yield from _iter_live_body(
                completion_id=completion_id,
                created=created,
                model=model,
                deltas=iter([]),
                watch_tools=watch_tools,
                holdback_chars=holdback_chars,
                allowed_tool_names=allowed_tool_names,
            )
            return

        def all_deltas(first: str = item) -> Iterator[str]:
            yield first
            yield from _iter_queued_deltas(q, errors)

        try:
            yield from _iter_live_body(
                completion_id=completion_id,
                created=created,
                model=model,
                deltas=all_deltas(),
                watch_tools=watch_tools,
                holdback_chars=holdback_chars,
                allowed_tool_names=allowed_tool_names,
            )
        except BaseException as exc:
            yield from _error_frames(exc)
        return


def iter_completion_sse(
    *,
    completion_id: str,
    created: int,
    model: str,
    content: str | None,
    tool_calls: list[ParsedToolCall],
) -> Iterator[str]:
    """Yield OpenAI-compatible SSE lines for a completed Copilot reply."""
    yield _role_frame(completion_id, created, model)
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

    Used when the reply is buffered (non-incremental). For true Substrate
    streaming, prefer iter_live_sse_with_keepalive.
    """
    yield _role_frame(completion_id, created, model)

    result: dict[str, Any] = {}

    def _worker() -> None:
        try:
            result["text"] = produce()
        except BaseException as exc:
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
        yield from _error_frames(error)
        return

    response_text = result.get("text") or ""
    content, tool_calls = parse_tool_calls(response_text, salvage_unclosed=True)
    yield from _iter_reply_frames(
        completion_id=completion_id,
        created=created,
        model=model,
        content=content if tool_calls else response_text,
        tool_calls=tool_calls,
    )
