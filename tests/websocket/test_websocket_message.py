import json

import pytest

from copilot_cli.copilot.enums.message_type_enum import MessageTypeEnum
from copilot_cli.copilot.websocket_message.websocket_message import WebsocketMessage

RECORD_SEPARATOR = chr(30)


def test_to_websocket_message_appends_record_separator_and_parses_json():
    payload = {"hello": "world", "type": 4}
    frame = WebsocketMessage.to_websocket_message(payload)

    assert frame.endswith(RECORD_SEPARATOR)
    assert json.loads(frame.split(RECORD_SEPARATOR)[0]) == payload

    msg = WebsocketMessage(frame)
    assert msg.message == frame


@pytest.mark.parametrize(
    ("payload", "expected_type"),
    [
        ({"type": 1}, MessageTypeEnum.copilot),
        ({"type": 2}, MessageTypeEnum.copilot_final),
        ({"type": 4}, MessageTypeEnum.user),
        ({"type": 6}, MessageTypeEnum.ping),
        ({}, MessageTypeEnum.none),
        ({"protocol": "json", "version": 1}, MessageTypeEnum.none),
    ],
)
def test_classifies_signalr_message_types(payload, expected_type):
    frame = WebsocketMessage.to_websocket_message(payload)
    msg = WebsocketMessage(frame)

    assert msg.type() == expected_type


def test_successful_copilot_final_parses_bot_chat_and_suggestions():
    payload = {
        "type": 2,
        "item": {
            "result": {"value": "Success"},
            "messages": [
                {
                    "author": "bot",
                    "messageType": "Chat",
                    "text": "Here is your answer.",
                    "suggestedResponses": [
                        {"text": "Tell me more"},
                        {"text": "Thanks"},
                    ],
                }
            ],
        },
    }
    msg = WebsocketMessage(WebsocketMessage.to_websocket_message(payload))

    parsed = msg.parsed_message

    assert parsed.type == MessageTypeEnum.copilot_final
    assert parsed.is_success is True
    assert parsed.copilot_message == "Here is your answer."
    assert parsed.suggestions == ["Tell me more", "Thanks"]
    assert parsed.is_disengaged is False


@pytest.mark.parametrize(
    ("result_value", "expected_success"),
    [
        ("ApologyResponseReturned", True),
        ("Error", False),
    ],
)
def test_copilot_final_success_and_failure_results(result_value, expected_success):
    payload = {
        "type": 2,
        "item": {
            "result": {"value": result_value, "message": "Something went wrong"},
            "messages": [
                {
                    "author": "bot",
                    "messageType": "Chat",
                    "text": "Sorry, I cannot help with that.",
                }
            ],
        },
    }
    msg = WebsocketMessage(WebsocketMessage.to_websocket_message(payload))

    assert msg.is_success() is expected_success
    assert msg.parsed_message.is_success is expected_success


def test_disengaged_copilot_final_uses_hidden_text():
    payload = {
        "type": 2,
        "item": {
            "result": {"value": "Success"},
            "messages": [
                {
                    "author": "bot",
                    "messageType": "Disengaged",
                    "hiddenText": "This conversation has ended.",
                }
            ],
        },
    }
    parsed = WebsocketMessage(WebsocketMessage.to_websocket_message(payload)).parsed_message

    assert parsed.is_disengaged is True
    assert parsed.copilot_message == "This conversation has ended."


def test_disengaged_copilot_final_uses_follow_on_chat_message():
    payload = {
        "type": 2,
        "item": {
            "result": {"value": "Success"},
            "messages": [
                {
                    "author": "bot",
                    "messageType": "Disengaged",
                    "hiddenText": "Conversation ended.",
                },
                {
                    "author": "bot",
                    "messageType": "Chat",
                    "text": "Here is the final response.",
                    "suggestedResponses": [{"text": "Start over"}],
                },
            ],
        },
    }
    parsed = WebsocketMessage(WebsocketMessage.to_websocket_message(payload)).parsed_message

    assert parsed.is_disengaged is True
    assert parsed.copilot_message == "Here is the final response."
    assert parsed.suggestions == ["Start over"]


def test_failed_copilot_final_exposes_error_text_in_parsed_message():
    payload = {
        "type": 2,
        "item": {
            "result": {"value": "Error", "message": "Something went wrong", "exception": "Boom"},
            "messages": [],
        },
    }
    parsed = WebsocketMessage(WebsocketMessage.to_websocket_message(payload)).parsed_message

    assert parsed.is_success is False
    assert "Error: Something went wrong" in parsed.copilot_message
    assert "Exception: Boom" in parsed.copilot_message
    assert "Value: Error" in parsed.copilot_message


def test_formatted_str_includes_copilot_prompt_and_suggestions_for_success():
    payload = {
        "type": 2,
        "item": {
            "result": {"value": "Success"},
            "messages": [
                {
                    "author": "bot",
                    "messageType": "Chat",
                    "text": "Here is your answer.",
                    "suggestedResponses": [{"text": "Tell me more"}],
                }
            ],
        },
    }
    formatted = WebsocketMessage(WebsocketMessage.to_websocket_message(payload)).formatted_str()

    assert "[Copilot]: Here is your answer." in formatted
    assert "Suggestions:" in formatted
    assert "1. Tell me more" in formatted
