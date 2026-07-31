import json
import time

from copilot_cli.copilot.openai_proxy.stream_chunks import (
    iter_completion_sse,
    iter_streaming_completion,
)
from copilot_cli.copilot.openai_proxy.tool_parser import ParsedToolCall


def _parse_sse(frames: list[str]) -> list[dict | str]:
    payloads: list[dict | str] = []
    for frame in frames:
        assert frame.startswith("data: ")
        assert frame.endswith("\n\n")
        body = frame[len("data: ") : -2]
        if body == "[DONE]":
            payloads.append(body)
        else:
            payloads.append(json.loads(body))
    return payloads


def test_stream_text_ends_with_finish_reason_and_done():
    frames = list(
        iter_completion_sse(
            completion_id="chatcmpl-test",
            created=1,
            model="default",
            content="Hello from Copilot",
            tool_calls=[],
        )
    )
    payloads = _parse_sse(frames)

    assert payloads[0]["choices"][0]["delta"] == {"role": "assistant"}
    assert payloads[1]["choices"][0]["delta"] == {"content": "Hello from Copilot"}
    assert payloads[2]["choices"][0]["delta"] == {}
    assert payloads[2]["choices"][0]["finish_reason"] == "stop"
    assert payloads[3] == "[DONE]"


def test_stream_tool_calls_finish_reason():
    call = ParsedToolCall(id="call_abc", name="read", arguments='{"path":"a.py"}')
    frames = list(
        iter_completion_sse(
            completion_id="chatcmpl-tools",
            created=2,
            model="default",
            content=None,
            tool_calls=[call],
        )
    )
    payloads = _parse_sse(frames)

    assert payloads[1]["choices"][0]["delta"]["tool_calls"][0]["function"]["name"] == "read"
    assert payloads[-2]["choices"][0]["finish_reason"] == "tool_calls"
    assert payloads[-1] == "[DONE]"


def _parse_streaming(frames: list[str]) -> list[dict | str]:
    return _parse_sse([f for f in frames if not f.startswith(":")])


def test_streaming_completion_emits_finish_reason():
    frames = list(
        iter_streaming_completion(
            completion_id="chatcmpl-live",
            created=3,
            model="default",
            produce=lambda: "Reply text",
        )
    )
    payloads = _parse_streaming(frames)

    assert payloads[0]["choices"][0]["delta"] == {"role": "assistant"}
    assert payloads[1]["choices"][0]["delta"] == {"content": "Reply text"}
    assert payloads[-2]["choices"][0]["finish_reason"] == "stop"
    assert payloads[-1] == "[DONE]"


def test_streaming_completion_parses_tool_calls():
    reply = 'Working on it.\n<tool_call>\n{"name": "read", "arguments": {"path": "a.py"}}\n</tool_call>'
    frames = list(
        iter_streaming_completion(
            completion_id="chatcmpl-live-tools",
            created=4,
            model="default",
            produce=lambda: reply,
        )
    )
    payloads = _parse_streaming(frames)

    tool_deltas = [
        p for p in payloads if isinstance(p, dict) and p.get("choices") and p["choices"][0]["delta"].get("tool_calls")
    ]
    assert tool_deltas, "expected a tool_calls delta"
    assert tool_deltas[0]["choices"][0]["delta"]["tool_calls"][0]["function"]["name"] == "read"
    assert payloads[-2]["choices"][0]["finish_reason"] == "tool_calls"


def test_streaming_completion_pings_while_waiting():
    def slow_produce() -> str:
        time.sleep(0.25)
        return "done"

    frames = list(
        iter_streaming_completion(
            completion_id="chatcmpl-slow",
            created=5,
            model="default",
            produce=slow_produce,
            ping_interval=0.05,
        )
    )
    assert any(f.startswith(": ping") for f in frames)
    payloads = _parse_streaming(frames)
    assert payloads[-2]["choices"][0]["finish_reason"] == "stop"
    assert payloads[-1] == "[DONE]"


def test_streaming_completion_error_frame_on_failure():
    def boom() -> str:
        raise RuntimeError("copilot auth failed")

    frames = list(
        iter_streaming_completion(
            completion_id="chatcmpl-err",
            created=6,
            model="default",
            produce=boom,
        )
    )
    payloads = _parse_streaming(frames)

    assert payloads[0]["choices"][0]["delta"] == {"role": "assistant"}
    error_frame = payloads[1]
    assert isinstance(error_frame, dict)
    assert "copilot auth failed" in error_frame["error"]["message"]
    assert payloads[-1] == "[DONE]"
    # No finish chunk after an error: openai SDK clients raise APIError on the
    # error frame before reaching end-of-stream.
    assert not any(
        isinstance(p, dict) and p.get("choices") and p["choices"][0].get("finish_reason") for p in payloads
    )
