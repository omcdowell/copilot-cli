from types import SimpleNamespace

from copilot_cli.copilot.enums.copilot_scenario_enum import CopilotScenarioEnum
from copilot_cli.copilot.enums.verbose_enum import VerboseEnum
from copilot_cli.copilot.models.chat_argument import ChatArguments
from copilot_cli.copilot.openai_proxy.session_store import SessionStore


def _args() -> ChatArguments:
    return ChatArguments(
        user="test",
        use_cached_access_token=True,
        scenario=CopilotScenarioEnum.officeweb,
        verbose=VerboseEnum.off,
    )


def _request(headers: dict[str, str] | None = None):
    return SimpleNamespace(headers=headers or {})


def test_session_key_prefers_header_over_message_hash():
    messages = [{"role": "user", "content": "hello"}]
    key = SessionStore.session_key_from_request(
        _request({"X-Session-Id": "pi-abc"}),
        messages,
    )
    assert key == "hdr_pi-abc"
    assert SessionStore.session_key_from_messages(messages).startswith("thread_")


def test_header_session_is_new_only_until_first_sight():
    store = SessionStore(_args())
    request = _request({"X-Session-Id": "pi-1"})
    messages = [{"role": "user", "content": "hi"}]
    key = SessionStore.session_key_from_request(request, messages)

    assert store.is_new_conversation(request, messages, key) is True
    store.get_automator(key, is_new_conversation=True)
    assert store.is_new_conversation(request, messages, key) is False

    # Still one user message — header path must not reset on message count.
    assert store.is_new_conversation(request, messages, key) is False


def test_hash_fallback_reuses_session_after_first_turn():
    store = SessionStore(_args())
    request = _request()
    first = [{"role": "user", "content": "hi"}]
    tool_loop = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "yo"},
        {"role": "tool", "name": "bash", "content": "ok"},
    ]
    second = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "yo"},
        {"role": "user", "content": "again"},
    ]
    key = SessionStore.session_key_from_request(request, first)

    assert store.is_new_conversation(request, first, key) is True
    store.get_automator(key, is_new_conversation=True)
    assert store.is_new_conversation(request, first, key) is False
    assert store.is_new_conversation(request, tool_loop, key) is False
    assert store.is_new_conversation(request, second, key) is False
