import json
import logging

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


def test_parse_fenced_tool_call():
    text = (
        "Checking now.\n"
        "```json\n"
        "<tool_call>\n"
        '{"name": "read", "arguments": {"path": "a.py"}}\n'
        "</tool_call>\n"
        "```"
    )
    content, calls = parse_tool_calls(text)

    assert content == "Checking now."
    assert len(calls) == 1
    assert calls[0].name == "read"


def test_parse_html_escaped_tool_call():
    text = (
        "Done.\n"
        "&lt;tool_call&gt;\n"
        '{"name": "bash", "arguments": {"command": "pwd"}}\n'
        "&lt;/tool_call&gt;"
    )
    content, calls = parse_tool_calls(text)

    assert content == "Done."
    assert len(calls) == 1
    assert calls[0].name == "bash"


def test_parse_case_variant_tags():
    text = (
        "<TOOL_CALL>\n"
        '{"name": "read", "arguments": {"path": "b.py"}}\n'
        "</Tool_Call>"
    )
    content, calls = parse_tool_calls(text)

    assert content is None
    assert len(calls) == 1
    assert calls[0].name == "read"


def test_parse_keeps_prose_after_tool_call():
    text = (
        "Before.\n"
        "<tool_call>\n"
        '{"name": "read", "arguments": {"path": "a.py"}}\n'
        "</tool_call>\n"
        "After."
    )
    content, calls = parse_tool_calls(text)

    assert content == "Before.\n\nAfter."
    assert len(calls) == 1


def test_salvage_unclosed_tool_call():
    text = (
        "I'll read it.\n"
        '<tool_call>{"name": "read", "arguments": {"path": "a.py"}}'
    )
    content, calls = parse_tool_calls(text, salvage_unclosed=True)

    assert content == "I'll read it."
    assert len(calls) == 1
    assert calls[0].name == "read"


def test_unknown_tool_name_demoted_to_content():
    text = (
        "Trying.\n"
        "<tool_call>\n"
        '{"name": "rogue", "arguments": {"x": 1}}\n'
        "</tool_call>"
    )
    allowed = {"read", "bash"}
    content, calls = parse_tool_calls(text, allowed_tool_names=allowed)

    assert calls == []
    assert content == text


def test_allowed_tool_names_accepts_declared_tool():
    text = '<tool_call>{"name": "read", "arguments": {"path": "a.py"}}</tool_call>'
    content, calls = parse_tool_calls(text, allowed_tool_names={"read"})

    assert content is None
    assert len(calls) == 1
    assert calls[0].name == "read"


def test_json_parse_failure_logs_warning(caplog):
    text = '<tool_call>{"name": "read", not-json}</tool_call>'
    with caplog.at_level(logging.WARNING):
        content, calls = parse_tool_calls(text)

    assert calls == []
    assert content == text
    assert any("JSON parse failed" in record.message for record in caplog.records)


def test_missing_name_logs_warning(caplog):
    text = '<tool_call>{"arguments": {"path": "a.py"}}</tool_call>'
    with caplog.at_level(logging.WARNING):
        content, calls = parse_tool_calls(text)

    assert calls == []
    assert content == text
    assert any("Missing tool name" in record.message for record in caplog.records)


def test_tag_like_without_valid_calls_logs_warning(caplog):
    text = "<tool_call>definitely not json</tool_call>"
    with caplog.at_level(logging.WARNING):
        content, calls = parse_tool_calls(text)

    assert calls == []
    assert content == text
    assert any("no valid tool calls parsed" in record.message for record in caplog.records)
