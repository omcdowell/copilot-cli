import json
import time

from copilot_cli.copilot.openai_proxy.stream_chunks import iter_live_sse, iter_streaming_completion
from copilot_cli.copilot.openai_proxy.tool_parser import TOOL_OPEN_TAG


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


def _parse_streaming(frames: list[str]) -> list[dict | str]:
    return _parse_sse([f for f in frames if not f.startswith(":")])


def _content_pieces(payloads: list[dict | str]) -> list[str]:
    pieces: list[str] = []
    for payload in payloads:
        if not isinstance(payload, dict):
            continue
        delta = payload["choices"][0]["delta"]
        if "content" in delta:
            pieces.append(delta["content"])
    return pieces


def test_live_sse_text_ends_with_finish_reason_and_done():
    frames = list(
        iter_live_sse(
            completion_id="chatcmpl-test",
            created=1,
            model="default",
            deltas=iter(["Hello from Copilot"]),
            watch_tools=False,
        )
    )
    payloads = _parse_sse(frames)

    assert payloads[0]["choices"][0]["delta"] == {"role": "assistant"}
    assert payloads[1]["choices"][0]["delta"] == {"content": "Hello from Copilot"}
    assert payloads[2]["choices"][0]["delta"] == {}
    assert payloads[2]["choices"][0]["finish_reason"] == "stop"
    assert payloads[3] == "[DONE]"


def test_live_sse_forwards_deltas():
    frames = list(
        iter_live_sse(
            completion_id="chatcmpl-live",
            created=3,
            model="default",
            deltas=iter(["Hel", "lo", "!", ""]),
            watch_tools=False,
        )
    )
    payloads = _parse_sse(frames)

    assert payloads[0]["choices"][0]["delta"] == {"role": "assistant"}
    assert payloads[1]["choices"][0]["delta"] == {"content": "Hel"}
    assert payloads[2]["choices"][0]["delta"] == {"content": "lo"}
    assert payloads[3]["choices"][0]["delta"] == {"content": "!"}
    assert payloads[4]["choices"][0]["finish_reason"] == "stop"
    assert payloads[5] == "[DONE]"


def test_live_sse_holdback_streams_prose_then_tool_calls():
    tool_block = (
        f"{TOOL_OPEN_TAG}\n"
        '{"name": "read", "arguments": {"path": "a.py"}}\n'
        "```"
    )
    deltas = [
        "I'll check ",
        "that file.",
        "\n```",
        "tool_call\n",
        '{"name": "read", "arguments": {"path": "a.py"}}\n',
        "```",
    ]
    frames = list(
        iter_live_sse(
            completion_id="chatcmpl-hold",
            created=4,
            model="default",
            deltas=iter(deltas),
            watch_tools=True,
            allowed_tool_names={"read"},
        )
    )
    payloads = _parse_sse(frames)
    content = "".join(_content_pieces(payloads))

    assert content == "I'll check that file.\n"
    assert TOOL_OPEN_TAG not in content
    assert payloads[-2]["choices"][0]["finish_reason"] == "tool_calls"
    tool_delta = next(
        p["choices"][0]["delta"]["tool_calls"][0]
        for p in payloads
        if isinstance(p, dict) and "tool_calls" in p["choices"][0]["delta"]
    )
    assert tool_delta["function"]["name"] == "read"
    assert payloads[-1] == "[DONE]"
    assert tool_block in "".join(deltas)


def test_live_sse_holdback_flushes_when_no_tool_tag():
    frames = list(
        iter_live_sse(
            completion_id="chatcmpl-prose",
            created=5,
            model="default",
            deltas=iter(["Hello ", "world"]),
            watch_tools=True,
        )
    )
    payloads = _parse_sse(frames)
    assert "".join(_content_pieces(payloads)) == "Hello world"
    assert payloads[-2]["choices"][0]["finish_reason"] == "stop"


def test_live_sse_python_fence_is_content_not_tool_call():
    deltas = [
        "Here's code:\n",
        "```python\n",
        "print(1)\n",
        "```",
    ]
    frames = list(
        iter_live_sse(
            completion_id="chatcmpl-pyfence",
            created=5,
            model="default",
            deltas=iter(deltas),
            watch_tools=True,
            allowed_tool_names={"read"},
        )
    )
    payloads = _parse_sse(frames)
    content = "".join(_content_pieces(payloads))

    assert "```python" in content
    assert "print(1)" in content
    assert payloads[-2]["choices"][0]["finish_reason"] == "stop"


def test_live_sse_streams_prose_after_tool_call():
    deltas = [
        "Before.\n",
        "```tool_call\n",
        '{"name": "read", "arguments": {"path": "a.py"}}\n',
        "```\n",
        "After.",
    ]
    frames = list(
        iter_live_sse(
            completion_id="chatcmpl-after",
            created=6,
            model="default",
            deltas=iter(deltas),
            watch_tools=True,
            allowed_tool_names={"read"},
        )
    )
    payloads = _parse_sse(frames)
    content = "".join(_content_pieces(payloads))

    assert "Before." in content
    assert "After." in content
    assert TOOL_OPEN_TAG not in content
    assert payloads[-2]["choices"][0]["finish_reason"] == "tool_calls"


def test_live_sse_salvages_unclosed_tool_call():
    deltas = [
        "I'll read it.\n",
        '```tool_call\n{"name": "read", "arguments": {"path": "a.py"}}',
    ]
    frames = list(
        iter_live_sse(
            completion_id="chatcmpl-salvage",
            created=7,
            model="default",
            deltas=iter(deltas),
            watch_tools=True,
            allowed_tool_names={"read"},
        )
    )
    payloads = _parse_sse(frames)
    content = "".join(_content_pieces(payloads))

    assert content == "I'll read it.\n"
    assert TOOL_OPEN_TAG not in content
    assert payloads[-2]["choices"][0]["finish_reason"] == "tool_calls"


def test_live_sse_suppresses_unclosed_invalid_tool_call():
    deltas = [
        "Here we go.\n",
        '```tool_call\n{"name": "read", "arguments": {broken',
    ]
    frames = list(
        iter_live_sse(
            completion_id="chatcmpl-suppress",
            created=8,
            model="default",
            deltas=iter(deltas),
            watch_tools=True,
            allowed_tool_names={"read"},
        )
    )
    payloads = _parse_sse(frames)
    content = "".join(_content_pieces(payloads))

    assert content == "Here we go.\n"
    assert TOOL_OPEN_TAG not in content
    assert "broken" not in content
    assert payloads[-2]["choices"][0]["finish_reason"] == "stop"


def test_live_sse_unknown_tool_demoted_to_content():
    deltas = [
        "Trying.\n",
        "```tool_call\n",
        '{"name": "rogue", "arguments": {"x": 1}}\n',
        "```",
    ]
    frames = list(
        iter_live_sse(
            completion_id="chatcmpl-unknown",
            created=9,
            model="default",
            deltas=iter(deltas),
            watch_tools=True,
            allowed_tool_names={"read"},
        )
    )
    payloads = _parse_sse(frames)
    content = "".join(_content_pieces(payloads))

    assert "Trying." in content
    assert "rogue" in content
    assert payloads[-2]["choices"][0]["finish_reason"] == "stop"


def test_live_sse_parses_case_variant_tags():
    deltas = [
        "```TOOL_CALL\n",
        '{"name": "read", "arguments": {"path": "a.py"}}\n',
        "```",
    ]
    frames = list(
        iter_live_sse(
            completion_id="chatcmpl-case",
            created=10,
            model="default",
            deltas=iter(deltas),
            watch_tools=True,
            allowed_tool_names={"read"},
        )
    )
    payloads = _parse_sse(frames)

    assert payloads[-2]["choices"][0]["finish_reason"] == "tool_calls"
    assert "".join(_content_pieces(payloads)) == ""


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
    reply = 'Working on it.\n```tool_call\n{"name": "read", "arguments": {"path": "a.py"}}\n```'
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
    assert tool_deltas
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
    assert not any(
        isinstance(p, dict) and p.get("choices") and p["choices"][0].get("finish_reason") for p in payloads
    )
