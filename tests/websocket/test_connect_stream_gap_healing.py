"""End-to-end: connect_stream must not drop snapshot-only text segments.

Substrate delivers part of an answer only through the cumulative
``messages[].text`` snapshot, never through ``writeAtCursor``. The stream the
proxy hands to Pi must still match what the Copilot web UI renders.
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

FULL_TEXT = (
    "Hello Oliver! \U0001f44b\n\n"
    "I'm here to help with work tasks, coding, documents, Microsoft 365 questions, "
    "research, writing, and more.\n\n"
    "What would you like to do today?"
)


def _frame(payload: dict) -> str:
    return json.dumps(payload) + _WS_DELIM


def _delta(text: str) -> dict:
    return {"type": 1, "target": "update", "arguments": [{"writeAtCursor": text}]}


def _snapshot(text: str, request_id: str) -> dict:
    return {
        "type": 1,
        "target": "update",
        "arguments": [
            {"messages": [{"author": "bot", "messageType": "Chat", "requestId": request_id, "text": text}]}
        ],
    }


def _final(text: str, request_id: str) -> dict:
    return {
        "type": 2,
        "item": {
            "result": {"value": "Success"},
            "messages": [
                {"author": "bot", "messageType": "Chat", "requestId": request_id, "text": text}
            ],
        },
    }


class RequestIdAwareWebSocket:
    """Fake hub that echoes the turn's requestId back on its snapshot frames."""

    def __init__(self, snapshot_request_id: str | None = None) -> None:
        self.sent: list[str] = []
        self._frames: list[str] | None = None
        # None => snapshots carry the turn's requestId; a string => they don't.
        self._snapshot_request_id = snapshot_request_id

    async def send(self, payload: str) -> None:
        self.sent.append(payload)

    async def recv(self) -> str:
        return _frame({})  # handshake ack

    def _request_id(self) -> str:
        chat = json.loads(self.sent[-1].split(_WS_DELIM)[0])
        return chat["arguments"][0]["message"]["requestId"]

    def _build(self) -> list[str]:
        rid = self._snapshot_request_id or self._request_id()
        return [
            _frame(_delta("Oliver")),  # "Hello " never arrives as a delta
            _frame(_snapshot("Hello Oliver! \U0001f44b", rid)),
            _frame(_delta(" to help with work tasks, coding, documents,")),
            _frame(
                _snapshot(
                    "Hello Oliver! \U0001f44b\n\nI'm here to help with work tasks, coding, documents,",
                    rid,
                )
            ),
            _frame(_delta(" Microsoft 365 questions, research, writing, and more.\n\n")),
            _frame(
                _snapshot(
                    "Hello Oliver! \U0001f44b\n\nI'm here to help with work tasks, coding, "
                    "documents, Microsoft 365 questions, research, writing, and more.\n\nWhat would",
                    rid,
                )
            ),
            _frame(_delta(" you like to do today?")),
            _frame(_final(FULL_TEXT, rid)),
            _frame({"type": 3}),
        ]

    def __aiter__(self):
        self._frames = self._build()
        return self

    async def __anext__(self):
        if not self._frames:
            raise StopAsyncIteration
        return self._frames.pop(0)

    async def __aenter__(self) -> "RequestIdAwareWebSocket":
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


@pytest.mark.asyncio
async def test_stream_matches_web_answer_when_deltas_skip_segments(connector, monkeypatch) -> None:
    fake_ws = RequestIdAwareWebSocket()
    monkeypatch.setattr(
        "copilot_cli.copilot.copilot_connector.copilot_connector.websockets.connect",
        lambda _url: fake_ws,
    )

    chunks = [chunk async for chunk in connector.connect_stream("hi")]

    assert "".join(chunks) == FULL_TEXT


@pytest.mark.asyncio
async def test_no_gapped_text_is_streamed_when_snapshots_are_not_turn_scoped(
    connector, monkeypatch
) -> None:
    """If every snapshot is filtered out, the delta stream alone is untrustworthy.

    Nothing may be released until the final frame supplies the real answer.
    """
    fake_ws = RequestIdAwareWebSocket(snapshot_request_id="some-other-request-id")
    monkeypatch.setattr(
        "copilot_cli.copilot.copilot_connector.copilot_connector.websockets.connect",
        lambda _url: fake_ws,
    )

    chunks = [chunk async for chunk in connector.connect_stream("hi")]

    assert chunks == [FULL_TEXT]
