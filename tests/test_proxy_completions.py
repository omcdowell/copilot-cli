"""Proxy prompt construction for Pi-shaped OpenAI requests."""

from copilot_cli.copilot.enums.copilot_scenario_enum import CopilotScenarioEnum
from copilot_cli.copilot.enums.verbose_enum import VerboseEnum
from copilot_cli.copilot.models.chat_argument import ChatArguments
from copilot_cli.copilot.openai_proxy.server import create_app

PI_SYSTEM = (
    "You are Pi, an interactive CLI tool that helps users with software engineering."
    " Available tools: bash, read, write, edit, grep."
)

BASH_TOOL = {
    "type": "function",
    "function": {
        "name": "bash",
        "description": "Run a shell command",
        "parameters": {"type": "object", "properties": {"command": {"type": "string"}}},
    },
}


class RecordingAutomator:
    """Stand-in for ChatAutomator that records Substrate prompts."""

    prompts: list[str] = []
    instances: int = 0

    def __init__(self, arguments: ChatArguments) -> None:
        RecordingAutomator.instances += 1

    def send_prompt_text(self, prompt: str) -> str:
        RecordingAutomator.prompts.append(prompt)
        return "ack"

    def iter_prompt_text(self, prompt: str):
        RecordingAutomator.prompts.append(prompt)
        yield "ack"


def _args() -> ChatArguments:
    return ChatArguments(
        user="test",
        use_cached_access_token=True,
        scenario=CopilotScenarioEnum.officeweb,
        verbose=VerboseEnum.off,
    )


def test_pi_tool_loop_does_not_resend_system_prompt(monkeypatch):
    """Pi always POSTs the full OpenAI history, including its system prompt.

    A tool-loop turn still has one user message, so the hash fallback used to
    treat every iteration as a brand-new Substrate conversation and flatten
    the whole transcript (system prompt included) into the prompt text.
    Follow-up turns must send only the new tool result.
    """
    RecordingAutomator.prompts = []
    RecordingAutomator.instances = 0
    monkeypatch.setattr(
        "copilot_cli.copilot.openai_proxy.session_store.ChatAutomator",
        RecordingAutomator,
    )

    client = create_app(_args()).test_client()
    first_messages = [
        {"role": "system", "content": PI_SYSTEM},
        {"role": "user", "content": "list files"},
    ]
    tool_loop_messages = [
        *first_messages,
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
    payload = {"model": "default", "stream": True, "tools": [BASH_TOOL]}

    first = client.post("/v1/chat/completions", json={**payload, "messages": first_messages})
    assert first.status_code == 200
    first.get_data()

    follow = client.post("/v1/chat/completions", json={**payload, "messages": tool_loop_messages})
    assert follow.status_code == 200
    follow.get_data()

    assert len(RecordingAutomator.prompts) == 2
    assert PI_SYSTEM in RecordingAutomator.prompts[0]
    assert "list files" in RecordingAutomator.prompts[0]
    assert "## Local tools" in RecordingAutomator.prompts[0]
    assert "## Session context" in RecordingAutomator.prompts[0]
    assert "## User request" in RecordingAutomator.prompts[0]
    assert PI_SYSTEM not in RecordingAutomator.prompts[1]
    assert "README.md" in RecordingAutomator.prompts[1]
    assert "```tool_response" in RecordingAutomator.prompts[1]
    assert "Continue. Local tool protocol is unchanged" in RecordingAutomator.prompts[1]
    assert "## Local tools" not in RecordingAutomator.prompts[1]
    assert RecordingAutomator.instances == 1


def test_full_tool_protocol_reinjects_catalog_on_continuation(monkeypatch):
    RecordingAutomator.prompts = []
    RecordingAutomator.instances = 0
    monkeypatch.setattr(
        "copilot_cli.copilot.openai_proxy.session_store.ChatAutomator",
        RecordingAutomator,
    )

    client = create_app(_args(), tool_protocol="full").test_client()
    first_messages = [
        {"role": "system", "content": PI_SYSTEM},
        {"role": "user", "content": "list files"},
    ]
    tool_loop_messages = [
        *first_messages,
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
    payload = {"model": "default", "stream": True, "tools": [BASH_TOOL]}

    client.post("/v1/chat/completions", json={**payload, "messages": first_messages}).get_data()
    client.post("/v1/chat/completions", json={**payload, "messages": tool_loop_messages}).get_data()

    assert "## Local tools" in RecordingAutomator.prompts[1]
    assert "```tools" in RecordingAutomator.prompts[1]
    assert "Continue. Local tool protocol is unchanged" not in RecordingAutomator.prompts[1]
