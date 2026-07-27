import json

from copilot_cli.copilot.openai_proxy.tool_parser import parse_tool_calls, to_openai_tool_calls


def test_parse_single_tool_call():
    text = (
        "I'll read the file.\n"
        "<tool_call>\n"
        '{"name": "read", "arguments": {"path": "/tmp/foo.txt"}}\n'
        "</tool_call>"
    )
    content, calls = parse_tool_calls(text)

    assert content == "I'll read the file."
    assert len(calls) == 1
    assert calls[0].name == "read"
    assert json.loads(calls[0].arguments) == {"path": "/tmp/foo.txt"}


def test_parse_multiple_tool_calls():
    text = (
        "<tool_call>\n"
        '{"name": "bash", "arguments": {"command": "ls"}}\n'
        "</tool_call>\n"
        "<tool_call>\n"
        '{"name": "read", "arguments": {"path": "README.md"}}\n'
        "</tool_call>"
    )
    content, calls = parse_tool_calls(text)

    assert content is None
    assert len(calls) == 2
    assert calls[0].name == "bash"
    assert calls[1].name == "read"


def test_no_tool_calls_returns_original_text():
    text = "Just a normal assistant reply."
    content, calls = parse_tool_calls(text)

    assert content == text
    assert calls == []


def test_to_openai_tool_calls_shape():
    text = "<tool_call>\n" '{"name": "edit", "arguments": {"path": "a.py"}}\n' "</tool_call>"
    _, calls = parse_tool_calls(text)
    openai_calls = to_openai_tool_calls(calls)

    assert openai_calls[0]["type"] == "function"
    assert openai_calls[0]["function"]["name"] == "edit"
    assert json.loads(openai_calls[0]["function"]["arguments"]) == {"path": "a.py"}
