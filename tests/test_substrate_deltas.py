"""Unit tests for Substrate writeAtCursor delta extraction."""

from copilot_cli.copilot.websocket_message.substrate_deltas import (
    fallback_bot_text,
    write_at_cursor_delta,
)


def test_write_at_cursor_delta_from_update():
    msg = {
        "type": 1,
        "target": "update",
        "arguments": [{"writeAtCursor": "Hello"}],
    }
    assert write_at_cursor_delta(msg) == "Hello"


def test_write_at_cursor_ignores_non_update():
    assert write_at_cursor_delta({"type": 1, "target": "other", "arguments": [{"writeAtCursor": "x"}]}) is None
    assert write_at_cursor_delta({"type": 2, "item": {}}) is None
    assert write_at_cursor_delta({"type": 6}) is None


def test_fallback_bot_text_from_type2():
    msg = {
        "type": 2,
        "item": {
            "messages": [
                {"author": "user", "text": "hi"},
                {"author": "bot", "text": "full reply"},
            ]
        },
    }
    assert fallback_bot_text(msg) == "full reply"


def test_fallback_bot_text_from_type1_messages():
    msg = {
        "type": 1,
        "target": "update",
        "arguments": [
            {
                "messages": [
                    {"author": "bot", "text": "partial snapshot"},
                ]
            }
        ],
    }
    assert fallback_bot_text(msg) == "partial snapshot"
