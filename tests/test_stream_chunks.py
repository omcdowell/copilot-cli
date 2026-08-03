import json

from copilot_cli.copilot.openai_proxy.stream_chunks import TOOL_OPEN_TAG, iter_live_sse


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
        "</tool_call>"
    )
    # Split so the opening tag arrives across multiple deltas.
    deltas = [
        "I'll check ",
        "that file.",
        "\n<",
        "tool_call>\n",
        '{"name": "read", "arguments": {"path": "a.py"}}\n',
        "</tool_call>",
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
    # Sanity: full text still parsed correctly from the joined deltas.
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


def test_live_sse_streams_prose_after_tool_call():
    deltas = [
        "Before.\n",
        "<tool_call>\n",
        '{"name": "read", "arguments": {"path": "a.py"}}\n',
        "</tool_call>\n",
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
        '<tool_call>{"name": "read", "arguments": {"path": "a.py"}}',
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
    assert "<tool_call>" not in content
    assert payloads[-2]["choices"][0]["finish_reason"] == "tool_calls"
    tool_delta = next(
        p["choices"][0]["delta"]["tool_calls"][0]
        for p in payloads
        if isinstance(p, dict) and "tool_calls" in p["choices"][0]["delta"]
    )
    assert tool_delta["function"]["name"] == "read"


def test_live_sse_suppresses_unclosed_invalid_tool_call():
    deltas = [
        "Here we go.\n",
        '<tool_call>{"name": "read", "arguments": {broken',
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
    assert "<tool_call>" not in content
    assert "broken" not in content
    assert payloads[-2]["choices"][0]["finish_reason"] == "stop"
    assert not any(
        isinstance(p, dict) and "tool_calls" in p["choices"][0]["delta"] for p in payloads
    )


def test_live_sse_unknown_tool_demoted_to_content():
    deltas = [
        "Trying.\n",
        "<tool_call>\n",
        '{"name": "rogue", "arguments": {"x": 1}}\n',
        "</tool_call>",
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
    assert not any(
        isinstance(p, dict) and "tool_calls" in p["choices"][0]["delta"] for p in payloads
    )


def test_live_sse_parses_case_variant_tags():
    deltas = [
        "<TOOL_CALL>\n",
        '{"name": "read", "arguments": {"path": "a.py"}}\n',
        "</Tool_Call>",
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
    tool_delta = next(
        p["choices"][0]["delta"]["tool_calls"][0]
        for p in payloads
        if isinstance(p, dict) and "tool_calls" in p["choices"][0]["delta"]
    )
    assert tool_delta["function"]["name"] == "read"
