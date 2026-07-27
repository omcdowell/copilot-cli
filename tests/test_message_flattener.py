import json

from copilot_cli.copilot.openai_proxy.message_flattener import (
    count_user_messages,
    extract_latest_user_message,
    flatten_messages,
)


def test_flatten_basic_roles():
    messages = [
        {"role": "system", "content": "Be helpful."},
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi there"},
        {"role": "user", "content": "Thanks"},
    ]
    prompt = flatten_messages(messages)

    assert "[System]: Be helpful." in prompt
    assert "[User]: Hello" in prompt
    assert "[Assistant]: Hi there" in prompt
    assert "[User]: Thanks" in prompt


def test_flatten_tool_result_message():
    messages = [
        {"role": "user", "content": "run ls"},
        {
            "role": "assistant",
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "bash", "arguments": '{"command": "ls"}'},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "call_1", "name": "bash", "content": "file.txt"},
    ]
    prompt = flatten_messages(messages)

    assert "<tool_call>" in prompt
    assert '"name": "bash"' in prompt
    assert "<tool_response>" in prompt
    assert "file.txt" in prompt


def test_flatten_injects_tool_protocol():
    tools = [
        {
            "type": "function",
            "function": {
                "name": "read",
                "description": "Read a file",
                "parameters": {"type": "object", "properties": {"path": {"type": "string"}}},
            },
        }
    ]
    messages = [{"role": "user", "content": "read README"}]
    prompt = flatten_messages(messages, tools)

    assert "<tools>" in prompt
    assert '"name": "read"' in prompt
    assert "<tool_call>" in prompt


def test_extract_latest_user_message():
    messages = [
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "ok"},
        {"role": "user", "content": "second"},
    ]

    assert extract_latest_user_message(messages) == "second"
    assert count_user_messages(messages) == 2


def test_build_continuation_forwards_tool_results():
    from copilot_cli.copilot.openai_proxy.message_flattener import build_continuation_prompt

    tools = [
        {
            "type": "function",
            "function": {
                "name": "bash",
                "description": "Run a shell command",
                "parameters": {"type": "object", "properties": {"command": {"type": "string"}}},
            },
        }
    ]
    messages = [
        {"role": "system", "content": "You are a coding agent."},
        {"role": "user", "content": "list files"},
        {
            "role": "assistant",
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "bash", "arguments": '{"command": "ls"}'},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "call_1", "name": "bash", "content": "README.md\nsrc"},
    ]
    prompt = build_continuation_prompt(messages, tools)

    assert "<tools>" in prompt
    assert "<tool_response>" in prompt
    assert "README.md" in prompt
    assert "[System]" not in prompt


def test_build_continuation_falls_back_to_latest_user():
    from copilot_cli.copilot.openai_proxy.message_flattener import build_continuation_prompt

    messages = [
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "ack"},
        {"role": "user", "content": "second question"},
    ]
    prompt = build_continuation_prompt(messages)

    assert prompt == "second question"
