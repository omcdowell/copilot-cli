from copilot_cli.copilot.openai_proxy.message_flattener import (
    batch_ready,
    build_continuation_prompt,
    count_user_messages,
    extract_latest_user_message,
    flatten_messages,
)
from copilot_cli.copilot.openai_proxy.tool_protocol import (
    CONTINUATION_REMINDER,
    RECENCY_FOOTER,
    ToolProtocolMode,
)


def test_flatten_basic_roles():
    messages = [
        {"role": "system", "content": "Be helpful."},
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi there"},
        {"role": "user", "content": "Thanks"},
    ]
    prompt = flatten_messages(messages)

    assert "## Session context" in prompt
    assert "Be helpful." in prompt
    assert "[User]: Hello" in prompt
    assert "[Assistant]: Hi there" in prompt
    assert "## User request" in prompt
    assert "Thanks" in prompt
    assert "[User]: Thanks" not in prompt


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

    assert "```tool_call" in prompt
    assert '"name": "bash"' in prompt
    assert "```tool_response" in prompt
    assert "file.txt" in prompt
    assert "<tool_call>" not in prompt
    assert "<tool_response>" not in prompt


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
    messages = [
        {"role": "system", "content": "You are Pi."},
        {"role": "user", "content": "read README"},
    ]
    prompt = flatten_messages(messages, tools)

    assert prompt.startswith("## Local tools")
    assert "```tools" in prompt
    assert '"name": "read"' in prompt
    assert "```tool_call" in prompt
    assert "## Session context" in prompt
    assert "You are Pi." in prompt
    assert "## User request" in prompt
    assert "read README" in prompt
    assert prompt.rstrip().endswith(RECENCY_FOOTER)
    assert "<tools>" not in prompt
    assert "You are a function calling AI model" not in prompt


def test_extract_latest_user_message():
    messages = [
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "ok"},
        {"role": "user", "content": "second"},
    ]

    assert extract_latest_user_message(messages) == "second"
    assert count_user_messages(messages) == 2


def test_build_continuation_tool_loop_reminder_only():
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

    assert prompt.startswith("```tool_response")
    assert "README.md" in prompt
    assert prompt.rstrip().endswith(CONTINUATION_REMINDER)
    assert "```tool_call\n" not in prompt
    assert '"command": "ls"' not in prompt
    assert "[System]" not in prompt
    assert "## Local tools" not in prompt
    assert "```tools" not in prompt
    assert "tool_response fences" not in prompt


def test_build_continuation_full_reinjects_catalog():
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
        {"role": "tool", "tool_call_id": "call_1", "name": "bash", "content": "README.md"},
    ]
    prompt = build_continuation_prompt(messages, tools, protocol_mode=ToolProtocolMode.full)

    assert "```tool_response" in prompt
    assert "## Local tools" in prompt
    assert "```tools" in prompt
    assert prompt.index("```tool_response") < prompt.index("## Local tools")
    assert '"command": "ls"' not in prompt
    assert CONTINUATION_REMINDER not in prompt


def test_build_continuation_falls_back_to_latest_user():
    messages = [
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "ack"},
        {"role": "user", "content": "second question"},
    ]
    prompt = build_continuation_prompt(messages)

    assert "## User request" in prompt
    assert "second question" in prompt
    assert CONTINUATION_REMINDER not in prompt


def test_build_continuation_user_turn_with_tools_sandwiches_request():
    tools = [
        {
            "type": "function",
            "function": {"name": "read", "parameters": {"type": "object"}},
        }
    ]
    messages = [
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "ack"},
        {"role": "user", "content": "now read a.py"},
    ]
    prompt = build_continuation_prompt(messages, tools)

    assert prompt.startswith(CONTINUATION_REMINDER)
    assert "## User request" in prompt
    assert "now read a.py" in prompt
    assert prompt.rstrip().endswith(RECENCY_FOOTER)
    assert "```tools" not in prompt


def test_batch_ready_false_when_one_of_two_results():
    messages = [
        {"role": "user", "content": "check both"},
        {
            "role": "assistant",
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "bash", "arguments": '{"command": "ls"}'},
                },
                {
                    "id": "call_2",
                    "type": "function",
                    "function": {"name": "read", "arguments": '{"path": "a.py"}'},
                },
            ],
        },
        {"role": "tool", "tool_call_id": "call_1", "name": "bash", "content": "README.md"},
    ]

    assert batch_ready(messages) is False


def test_continuation_two_tool_results_are_one_prompt():
    tools = [
        {
            "type": "function",
            "function": {"name": "bash", "parameters": {"type": "object"}},
        },
        {
            "type": "function",
            "function": {"name": "read", "parameters": {"type": "object"}},
        },
    ]
    messages = [
        {"role": "user", "content": "check both"},
        {
            "role": "assistant",
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "bash", "arguments": '{"command": "ls"}'},
                },
                {
                    "id": "call_2",
                    "type": "function",
                    "function": {"name": "read", "arguments": '{"path": "a.py"}'},
                },
            ],
        },
        {"role": "tool", "tool_call_id": "call_2", "name": "read", "content": "def main():\n    pass"},
        {"role": "tool", "tool_call_id": "call_1", "name": "bash", "content": "README.md\nsrc"},
    ]

    prompt = build_continuation_prompt(messages, tools)

    assert prompt.count("```tool_response") == 2
    assert "README.md" in prompt
    assert "def main():" in prompt
    assert prompt.index("README.md") < prompt.index("def main():")
    assert prompt.startswith("```tool_response")
    assert prompt.rstrip().endswith(CONTINUATION_REMINDER)
    assert "## Local tools" not in prompt
    assert "## User request" not in prompt
    between = prompt.split("```tool_response")[1].split("```tool_response")[0]
    assert "##" not in between
