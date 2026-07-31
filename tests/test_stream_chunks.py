import json

from copilot_cli.copilot.openai_proxy.stream_chunks import iter_completion_sse
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
