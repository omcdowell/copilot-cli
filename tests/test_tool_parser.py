import json
import logging

from copilot_cli.copilot.openai_proxy.tool_parser import parse_tool_calls, to_openai_tool_calls


def _fence(body: str) -> str:
    return "```tool_call\n" + body + "\n```"


def test_parse_single_tool_call():
    text = (
        "I'll read the file.\n"
        + _fence('{"name": "read", "arguments": {"path": "/tmp/foo.txt"}}')
    )
    content, calls = parse_tool_calls(text)

    assert content == "I'll read the file."
    assert len(calls) == 1
    assert calls[0].name == "read"
    assert json.loads(calls[0].arguments) == {"path": "/tmp/foo.txt"}


def test_parse_multiple_tool_calls():
    text = (
        _fence('{"name": "bash", "arguments": {"command": "ls"}}')
        + "\n"
        + _fence('{"name": "read", "arguments": {"path": "README.md"}}')
    )
    content, calls = parse_tool_calls(text)

    assert content is None
    assert len(calls) == 2
    assert calls[0].name == "bash"
    assert calls[1].name == "read"


def test_parse_adjacent_tool_calls_without_blank_closer():
    text = (
        '```tool_call\n{"name": "bash", "arguments": {"command": "ls"}}\n'
        '```tool_call\n{"name": "read", "arguments": {"path": "a.py"}}\n```'
    )
    content, calls = parse_tool_calls(text, salvage_unclosed=True)

    assert content is None
    assert [call.name for call in calls] == ["bash", "read"]


def test_no_tool_calls_returns_original_text():
    text = "Just a normal assistant reply."
    content, calls = parse_tool_calls(text)

    assert content == text
    assert calls == []


def test_python_fence_is_not_a_tool_call():
    text = "Here's code:\n```python\nprint(1)\n```"
    content, calls = parse_tool_calls(text)

    assert content == text
    assert calls == []


def test_to_openai_tool_calls_shape():
    text = _fence('{"name": "edit", "arguments": {"path": "a.py"}}')
    _, calls = parse_tool_calls(text)
    openai_calls = to_openai_tool_calls(calls)

    assert openai_calls[0]["type"] == "function"
    assert openai_calls[0]["function"]["name"] == "edit"
    assert json.loads(openai_calls[0]["function"]["arguments"]) == {"path": "a.py"}


def test_parse_nested_arguments():
    text = _fence('{"name": "write", "arguments": {"path": "a.py", "meta": {"n": 1}}}')
    content, calls = parse_tool_calls(text)

    assert content is None
    assert json.loads(calls[0].arguments) == {"path": "a.py", "meta": {"n": 1}}


def test_parse_json_containing_backticks():
    text = _fence('{"name": "write", "arguments": {"content": "```python\\nprint(1)\\n```"}}')
    _, calls = parse_tool_calls(text)

    assert calls[0].name == "write"
    assert json.loads(calls[0].arguments)["content"] == "```python\nprint(1)\n```"


def test_parse_case_variant_fence():
    text = "```TOOL_CALL\n" '{"name": "read", "arguments": {"path": "b.py"}}\n' "```"
    content, calls = parse_tool_calls(text)

    assert content is None
    assert len(calls) == 1
    assert calls[0].name == "read"


def test_parse_keeps_prose_after_tool_call():
    text = (
        "Before.\n"
        + _fence('{"name": "read", "arguments": {"path": "a.py"}}')
        + "\nAfter."
    )
    content, calls = parse_tool_calls(text)

    assert content == "Before.\n\nAfter."
    assert len(calls) == 1


def test_salvage_unclosed_tool_call():
    text = "I'll read it.\n" '```tool_call\n{"name": "read", "arguments": {"path": "a.py"}}'
    content, calls = parse_tool_calls(text, salvage_unclosed=True)

    assert content == "I'll read it."
    assert len(calls) == 1
    assert calls[0].name == "read"


def test_unclosed_without_salvage_stays_content():
    text = '```tool_call\n{"name": "read", "arguments": {"path": "a.py"}}'
    content, calls = parse_tool_calls(text)

    assert calls == []
    assert content == text


def test_unknown_tool_name_demoted_to_content():
    text = "Trying.\n" + _fence('{"name": "rogue", "arguments": {"x": 1}}')
    allowed = {"read", "bash"}
    content, calls = parse_tool_calls(text, allowed_tool_names=allowed)

    assert calls == []
    assert content == text


def test_allowed_tool_names_accepts_declared_tool():
    text = _fence('{"name": "read", "arguments": {"path": "a.py"}}')
    content, calls = parse_tool_calls(text, allowed_tool_names={"read"})

    assert content is None
    assert len(calls) == 1
    assert calls[0].name == "read"


def test_json_parse_failure_logs_warning(caplog):
    text = _fence('{"name": "read", not-json}')
    with caplog.at_level(logging.WARNING):
        content, calls = parse_tool_calls(text)

    assert calls == []
    assert content == text
    assert any("JSON parse failed" in record.message for record in caplog.records)


def test_missing_name_logs_warning(caplog):
    text = _fence('{"arguments": {"path": "a.py"}}')
    with caplog.at_level(logging.WARNING):
        content, calls = parse_tool_calls(text)

    assert calls == []
    assert content == text
    assert any("Missing tool name" in record.message for record in caplog.records)


def test_fence_without_valid_calls_logs_warning(caplog):
    text = "```tool_call\ndefinitely not json\n```"
    with caplog.at_level(logging.WARNING):
        content, calls = parse_tool_calls(text)

    assert calls == []
    assert content == text
    assert any("no valid tool calls parsed" in record.message for record in caplog.records)
