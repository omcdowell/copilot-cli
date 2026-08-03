"""Unit tests for Substrate writeAtCursor delta extraction."""

from copilot_cli.copilot.websocket_message.substrate_deltas import (
    CumulativeTextReconstructor,
    fallback_bot_text,
    snapshot_bot_text,
    write_at_cursor_delta,
    write_at_cursor_deltas,
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


def test_write_at_cursor_deltas_from_multiple_arguments():
    msg = {
        "type": 1,
        "target": "update",
        "arguments": [
            {"writeAtCursor": "Hello"},
            {"writeAtCursor": " world"},
        ],
    }
    assert write_at_cursor_deltas(msg) == ["Hello", " world"]


def test_snapshot_bot_text_filters_by_request_id():
    rid = "turn-abc"
    msg = {
        "type": 1,
        "target": "update",
        "arguments": [
            {
                "messages": [
                    {"author": "user", "text": "old question"},
                    {"author": "bot", "text": "OLD ANSWER"},
                    {"author": "bot", "text": "new answer", "requestId": rid},
                ]
            }
        ],
    }
    assert snapshot_bot_text(msg, rid) == "new answer"
    assert snapshot_bot_text(msg, "other-id") is None


def test_snapshot_only_text_yields_via_reconstructor():
    rid = "snap-only"
    reconstructor = CumulativeTextReconstructor()
    msg = {
        "type": 1,
        "target": "update",
        "arguments": [
            {
                "messages": [
                    {"author": "bot", "text": "snapshot only", "requestId": rid},
                ]
            }
        ],
    }
    assert reconstructor.feed(msg, rid) == "snapshot only"
    assert reconstructor.feed(msg, rid) is None


def test_cursor_jump_snapshot_supplies_missing_sentence_start():
    rid = "jump-test"
    reconstructor = CumulativeTextReconstructor()
    msg = {
        "type": 1,
        "target": "update",
        "arguments": [
            {
                "writeAtCursor": " world.",
                "messages": [
                    {"author": "bot", "text": "Hello world.", "requestId": rid},
                ],
            }
        ],
    }
    assert reconstructor.feed(msg, rid) == "Hello world."


def test_snapshot_heal_then_later_delta_continues():
    rid = "heal-then-delta"
    reconstructor = CumulativeTextReconstructor()
    heal = {
        "type": 1,
        "target": "update",
        "arguments": [
            {
                "writeAtCursor": " world.",
                "messages": [
                    {"author": "bot", "text": "Hello world.", "requestId": rid},
                ],
            }
        ],
    }
    assert reconstructor.feed(heal, rid) == "Hello world."
    later = {
        "type": 1,
        "target": "update",
        "arguments": [{"writeAtCursor": "!"}],
    }
    assert reconstructor.feed(later, rid) == "!"


def test_divergent_snapshot_is_rejected():
    reconstructor = CumulativeTextReconstructor()
    first = {
        "type": 1,
        "target": "update",
        "arguments": [{"writeAtCursor": "AAAA"}],
    }
    second = {
        "type": 1,
        "target": "update",
        "arguments": [
            {
                "messages": [
                    {"author": "bot", "text": "BBBBBB"},
                ]
            }
        ],
    }
    assert reconstructor.feed(first) == "AAAA"
    assert reconstructor.feed(second) is None


def test_reconstructor_ignores_rewind_frames():
    reconstructor = CumulativeTextReconstructor()
    first = {
        "type": 1,
        "target": "update",
        "arguments": [{"writeAtCursor": "Hello world."}],
    }
    second = {
        "type": 1,
        "target": "update",
        "arguments": [{"writeAtCursor": ""}],
    }
    assert reconstructor.feed(first) == "Hello world."
    assert reconstructor.feed(second) is None


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
