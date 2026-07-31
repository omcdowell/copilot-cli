"""Regression: second turn must not re-emit the previous bot answer.

Substrate type-1 ``update`` frames echo the conversation ``messages`` history.
On the second turn that history contains the previous bot reply, which
``fallback_bot_text`` picks up before any writeAtCursor delta arrives. The
stream must only yield the new turn's deltas.
"""

import json
from unittest.mock import MagicMock

import pytest

from copilot_cli.common.cache.cached_entity import CachedEntity
from copilot_cli.common.cache.token_cache import TokenCache
from copilot_cli.copilot.copilot_connector.copilot_connector import CopilotConnector
from copilot_cli.copilot.enums.copilot_scenario_enum import CopilotScenarioEnum
from copilot_cli.copilot.enums.verbose_enum import VerboseEnum
from copilot_cli.copilot.models.chat_argument import ChatArguments

_WS_DELIM = chr(30)


def _frame(payload: dict) -> str:
    return json.dumps(payload) + _WS_DELIM


class FakeStreamWebSocket:
    """Async-iterable fake matching connect_stream's usage."""

    def __init__(self, frames: list[str]) -> None:
        self.sent: list[str] = []
        self._frames = frames
        self._handshake_acked = False

    async def send(self, payload: str) -> None:
        self.sent.append(payload)

    async def recv(self) -> str:
        return _frame({})  # handshake ack

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._frames:
            raise StopAsyncIteration
        return self._frames.pop(0)

    async def __aenter__(self) -> "FakeStreamWebSocket":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None


@pytest.fixture
def connector(tmp_path) -> CopilotConnector:
    cache = TokenCache(str(tmp_path / "tokens.json"))
    cache.put_tokens(
        [
            CachedEntity(key=CopilotConnector._SUBSTRATE_TOKEN_CACHE_KEY, val="opaque-access-token"),
            CachedEntity(key=CopilotConnector._SUBSTRATE_OID_CACHE_KEY, val="object-id-123"),
            CachedEntity(key=CopilotConnector._SUBSTRATE_TID_CACHE_KEY, val="tenant-id-456"),
        ]
    )
    agents_response = MagicMock()
    agents_response.status_code = 200
    agents_response.json.return_value = {"gptList": []}
    args = ChatArguments(
        user="user@example.com",
        use_cached_access_token=True,
        scenario=CopilotScenarioEnum.officeweb,
        verbose=VerboseEnum.off,
    )
    connector = CopilotConnector(
        args,
        token_cache=cache,
        http_get=lambda *a, **k: agents_response,
    )
    connector.init_connection()
    return connector


async def _collect(connector: CopilotConnector, prompt: str) -> list[str]:
    return [chunk async for chunk in connector.connect_stream(prompt)]


@pytest.mark.asyncio
async def test_second_turn_history_echo_is_not_replayed(connector, monkeypatch) -> None:
    """Update frames carrying the previous answer must not be re-emitted."""
    frames = [
        # History echo arrives before any delta of the new answer.
        _frame(
            {
                "type": 1,
                "target": "update",
                "arguments": [
                    {
                        "messages": [
                            {"author": "user", "text": "first question"},
                            {"author": "bot", "text": "OLD ANSWER", "messageType": "Chat"},
                        ]
                    }
                ],
            }
        ),
        _frame({"type": 1, "target": "update", "arguments": [{"writeAtCursor": "New "}]}),
        _frame({"type": 1, "target": "update", "arguments": [{"writeAtCursor": "answer."}]}),
        _frame({"type": 3}),
    ]
    fake_ws = FakeStreamWebSocket(frames)
    monkeypatch.setattr(
        "copilot_cli.copilot.copilot_connector.copilot_connector.websockets.connect",
        lambda _url: fake_ws,
    )

    chunks = await _collect(connector, "second question")

    assert "".join(chunks) == "New answer."


@pytest.mark.asyncio
async def test_fallback_still_used_when_no_deltas_arrive(connector, monkeypatch) -> None:
    """A turn with no writeAtCursor deltas still yields the final bot text once."""
    frames = [
        _frame(
            {
                "type": 2,
                "item": {
                    "result": {"value": "Success"},
                    "messages": [{"author": "bot", "text": "buffered answer", "messageType": "Chat"}],
                },
            }
        ),
        _frame({"type": 3}),
    ]
    fake_ws = FakeStreamWebSocket(frames)
    monkeypatch.setattr(
        "copilot_cli.copilot.copilot_connector.copilot_connector.websockets.connect",
        lambda _url: fake_ws,
    )

    chunks = await _collect(connector, "question")

    assert chunks == ["buffered answer"]
