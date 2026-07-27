import json
from unittest.mock import MagicMock

import pytest

from copilot_cli.common.cache.cached_entity import CachedEntity
from copilot_cli.common.cache.token_cache import TokenCache
from copilot_cli.copilot.copilot_connector.copilot_connector import CopilotConnector
from copilot_cli.copilot.enums.copilot_scenario_enum import CopilotScenarioEnum
from copilot_cli.copilot.enums.message_type_enum import MessageTypeEnum
from copilot_cli.copilot.enums.verbose_enum import VerboseEnum
from copilot_cli.copilot.exceptions.copilot_connection_failed_exception import (
    CopilotConnectionFailedException,
)
from copilot_cli.copilot.models.chat_argument import ChatArguments
from copilot_cli.copilot.websocket_message.websocket_message import WebsocketMessage

_WS_DELIM = chr(30)


def _ws_frame(payload: dict) -> str:
    return json.dumps(payload) + _WS_DELIM


def _copilot_final_frame(text: str = "Hello from Copilot") -> str:
    return _ws_frame(
        {
            "type": 2,
            "item": {
                "result": {"value": "Success"},
                "messages": [{"author": "bot", "text": text, "messageType": "Chat"}],
            },
        }
    )


@pytest.fixture
def chat_args() -> ChatArguments:
    return ChatArguments(
        user="user@example.com",
        use_cached_access_token=True,
        scenario=CopilotScenarioEnum.officeweb,
        verbose=VerboseEnum.off,
    )


@pytest.fixture
def token_cache(tmp_path) -> TokenCache:
    cache = TokenCache(str(tmp_path / "tokens.json"))
    cache.put_tokens(
        [
            CachedEntity(key=CopilotConnector._SUBSTRATE_TOKEN_CACHE_KEY, val="opaque-access-token"),
            CachedEntity(key=CopilotConnector._SUBSTRATE_OID_CACHE_KEY, val="object-id-123"),
            CachedEntity(key=CopilotConnector._SUBSTRATE_TID_CACHE_KEY, val="tenant-id-456"),
        ]
    )
    return cache


class FakeWebSocket:
    def __init__(self, responses: list[str]) -> None:
        self.sent: list[str] = []
        self._responses = responses
        self._recv_index = 0

    async def send(self, payload: str) -> None:
        self.sent.append(payload)

    async def recv(self) -> str:
        response = self._responses[self._recv_index]
        self._recv_index += 1
        return response

    async def __aenter__(self) -> "FakeWebSocket":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None


@pytest.mark.asyncio
async def test_connect_sends_protocol_ping_and_chat_then_returns_copilot_final(
    chat_args: ChatArguments,
    token_cache: TokenCache,
) -> None:
    fake_ws = FakeWebSocket(
        [
            _ws_frame({"protocol": "json", "version": 1}),
            _ws_frame({"type": 6}),
            _copilot_final_frame("answer"),
        ]
    )

    def websocket_connect(_url: str):
        return fake_ws

    agents_response = MagicMock()
    agents_response.status_code = 200
    agents_response.json.return_value = {"gptList": []}

    connector = CopilotConnector(
        chat_args,
        token_cache=token_cache,
        websocket_connect=websocket_connect,
        http_get=lambda *args, **kwargs: agents_response,
    )
    connector.init_connection()

    result = await connector.connect("hello prompt")

    assert len(fake_ws.sent) == 3
    assert json.loads(fake_ws.sent[0].split(_WS_DELIM)[0]) == {"protocol": "json", "version": 1}
    assert json.loads(fake_ws.sent[1].split(_WS_DELIM)[0]) == {"type": 6}
    chat_payload = json.loads(fake_ws.sent[2].split(_WS_DELIM)[0])
    assert chat_payload["type"] == 4
    assert chat_payload["arguments"][0]["message"]["text"] == "hello prompt"

    assert isinstance(result, WebsocketMessage)
    assert result.type() == MessageTypeEnum.copilot_final


def test_init_connection_builds_officeweb_chathub_url_from_cached_identity(
    chat_args: ChatArguments,
    token_cache: TokenCache,
) -> None:
    agents_response = MagicMock()
    agents_response.status_code = 200
    agents_response.json.return_value = {"gptList": []}

    connector = CopilotConnector(
        chat_args,
        token_cache=token_cache,
        http_get=lambda *args, **kwargs: agents_response,
    )
    connector.init_connection()

    url = connector.conversation_parameters.url
    assert "wss://substrate.office.com/m365Copilot/Chathub/object-id-123@tenant-id-456" in url
    assert "access_token=opaque-access-token" in url


def test_init_connection_fails_cleanly_when_oid_tid_unresolved_for_opaque_token(
    chat_args: ChatArguments,
    tmp_path,
    monkeypatch,
) -> None:
    cache = TokenCache(str(tmp_path / "opaque-only-tokens.json"))
    cache.put_tokens(
        [CachedEntity(key=CopilotConnector._SUBSTRATE_TOKEN_CACHE_KEY, val="opaque-access-token")]
    )

    jwt_decode = MagicMock()
    monkeypatch.setattr(
        "copilot_cli.copilot.copilot_connector.copilot_connector.jwt.decode",
        jwt_decode,
    )

    connector = CopilotConnector(chat_args, token_cache=cache)

    with pytest.raises(CopilotConnectionFailedException, match="Could not resolve tenant/object id"):
        connector.init_connection()

    jwt_decode.assert_not_called()
