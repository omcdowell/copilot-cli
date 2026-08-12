"""Regression: snapshot-only text segments must not be dropped from the stream.

Real Substrate turns do not deliver every character through ``writeAtCursor``.
Some segments (typically the greeting head, emoji, and sentence starts after a
paragraph break) only ever appear in the cumulative ``messages[].text``
snapshot carried by later type-1 ``update`` frames.

Observed symptom (M365 Copilot web vs. pi through the proxy):

    web: "Hello Oliver! <wave>\n\nI'm here to help ... \n\nWhat would you like to do today?"
    pi:  "Oliver to help ... \n\n you like to do today?"

i.e. exactly the snapshot-only segments went missing, because the healing
snapshot was rejected as "divergent" once the delta stream had already been
released with a gap in it.
"""

from copilot_cli.copilot.websocket_message.substrate_deltas import CumulativeTextReconstructor

RID = "turn-1"

FULL_TEXT = (
    "Hello Oliver! \U0001f44b\n\n"
    "I'm here to help with work tasks, coding, documents, Microsoft 365 questions, "
    "research, writing, and more.\n\n"
    "What would you like to do today?"
)


def _delta(text: str) -> dict:
    return {"type": 1, "target": "update", "arguments": [{"writeAtCursor": text}]}


def _snapshot(upto: str, *, request_id: str = RID) -> dict:
    return {
        "type": 1,
        "target": "update",
        "arguments": [
            {
                "messages": [
                    {"author": "bot", "messageType": "Chat", "requestId": request_id, "text": upto}
                ]
            }
        ],
    }


def _final(text: str, *, request_id: str = RID) -> dict:
    return {
        "type": 2,
        "item": {
            "result": {"value": "Success"},
            "messages": [
                {"author": "bot", "messageType": "Chat", "requestId": request_id, "text": text}
            ],
        },
    }


# The exact interleaving that produced the truncated pi output: every
# writeAtCursor delta skips a segment that only the next snapshot carries.
TRANSCRIPT = [
    _delta("Oliver"),  # "Hello " never arrives as a delta
    _snapshot("Hello Oliver! \U0001f44b"),
    _delta(" to help with work tasks, coding, documents,"),  # "\n\nI'm here" skipped
    _snapshot(
        "Hello Oliver! \U0001f44b\n\nI'm here to help with work tasks, coding, documents,"
    ),
    _delta(" Microsoft 365 questions, research, writing, and more.\n\n"),
    _snapshot(
        "Hello Oliver! \U0001f44b\n\nI'm here to help with work tasks, coding, documents, "
        "Microsoft 365 questions, research, writing, and more.\n\nWhat would"
    ),
    _delta(" you like to do today?"),  # "What would" skipped
    _final(FULL_TEXT),
    {"type": 3},
]


def _run(frames: list[dict], **kwargs) -> str:
    reconstructor = CumulativeTextReconstructor(**kwargs)
    chunks = [reconstructor.feed(frame, RID) for frame in frames]
    chunks.append(reconstructor.flush())
    return "".join(chunk for chunk in chunks if chunk)


def test_snapshot_only_segments_are_streamed() -> None:
    assert _run(TRANSCRIPT) == FULL_TEXT


def test_no_text_is_duplicated_when_snapshots_lag_behind_deltas() -> None:
    frames = [
        _delta("Hello"),
        _delta(" Oliver"),
        _snapshot("Hello"),  # snapshot lags one delta behind
        _delta("!"),
        _snapshot("Hello Oliver!"),
        _final("Hello Oliver!"),
        {"type": 3},
    ]
    assert _run(frames) == "Hello Oliver!"


def test_stream_realigns_after_an_unrecoverable_gap() -> None:
    """With healing disabled the head is lost, but the tail must still arrive once."""
    frames = [
        _delta("Oliver"),
        _snapshot("Hello Oliver! \U0001f44b"),
        _delta(" to help."),
        _final("Hello Oliver! \U0001f44b\n\nI'm here to help."),
        {"type": 3},
    ]
    streamed = _run(frames, heal_window_frames=0)

    assert "Oliver" in streamed
    assert streamed.endswith(" to help.")
    assert streamed.count("Oliver") == 1
    assert streamed.count(" to help.") == 1


def test_gapped_deltas_are_replaced_by_the_final_text_when_no_snapshot_streams() -> None:
    """Some hubs only send messages[] on the final frame, or tag it with another id.

    Nothing is confirmed mid-turn, so no gapped delta text may reach the client:
    the authoritative final answer is what gets streamed, in one piece.
    """
    frames = [
        _delta("Oliver"),
        _delta(" to help with work tasks, coding, documents,"),
        _delta(" Microsoft 365 questions, research, writing, and more.\n\n"),
        _delta(" you like to do today?"),
        {"type": 3},
    ]
    reconstructor = CumulativeTextReconstructor()
    streamed = [reconstructor.feed(frame, RID) for frame in frames]
    streamed.append(reconstructor.finalize(FULL_TEXT))  # type-2 text the connector kept

    assert [chunk for chunk in streamed if chunk] == [FULL_TEXT]


def test_finalize_never_replays_a_longer_answer_from_a_previous_turn() -> None:
    """fallback_bot_text is not requestId-scoped; an echo must not be adopted."""
    reconstructor = CumulativeTextReconstructor()
    assert reconstructor.feed(_delta("New answer."), RID) is None

    echoed_previous_answer = "A much longer answer from the previous turn, unrelated to this one."

    assert reconstructor.finalize(echoed_previous_answer) == "New answer."


def test_finalize_appends_only_the_missing_tail_when_text_was_already_streamed() -> None:
    reconstructor = CumulativeTextReconstructor(heal_window_frames=0)
    assert reconstructor.feed(_delta("Hello Oliver!"), RID) == "Hello Oliver!"

    assert reconstructor.finalize("Hello Oliver! How can I help?") == " How can I help?"
    assert reconstructor.finalize("Hello Oliver! How can I help?") is None


def test_interstitial_bot_messages_are_not_used_as_snapshots() -> None:
    """Loader/search interstitials share the requestId but are not the answer."""
    interstitial = {
        "type": 1,
        "target": "update",
        "arguments": [
            {
                "messages": [
                    {
                        "author": "bot",
                        "messageType": "InternalLoaderMessage",
                        "requestId": RID,
                        "text": "Searching your work content for the answer\u2026",
                    }
                ]
            }
        ],
    }
    frames = [
        _delta("Working"),
        interstitial,
        _snapshot("Working on it."),
        _final("Working on it."),
        {"type": 3},
    ]
    assert _run(frames) == "Working on it."
