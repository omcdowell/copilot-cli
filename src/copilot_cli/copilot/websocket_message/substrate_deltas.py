"""Extract Substrate SignalR streaming deltas from type-1 update frames."""

from __future__ import annotations

from typing import Any


def write_at_cursor_deltas(message: dict[str, Any]) -> list[str]:
    """Return all writeAtCursor text deltas from a type-1 update frame."""
    if message.get("type") != 1 or message.get("target") != "update":
        return []
    deltas: list[str] = []
    for args in message.get("arguments") or []:
        if not isinstance(args, dict):
            continue
        delta = args.get("writeAtCursor")
        if isinstance(delta, str) and delta:
            deltas.append(delta)
    return deltas


def write_at_cursor_delta(message: dict[str, Any]) -> str | None:
    """
    Return the first writeAtCursor text delta from a SignalR type-1 update, if any.

    Matches the kuchris/m365-copilot-openai-proxy Substrate client behaviour.
    """
    deltas = write_at_cursor_deltas(message)
    return deltas[0] if deltas else None


# Interstitials ("Searching your work content…", search queries, cards) are bot
# messages on the same requestId, but they are not the answer being written.
_ANSWER_MESSAGE_TYPES = (None, "Chat")


def _is_answer_entry(entry: dict[str, Any], request_id: str | None) -> bool:
    if entry.get("author") == "user":
        return False
    if entry.get("messageType") not in _ANSWER_MESSAGE_TYPES:
        return False
    if request_id is not None and entry.get("requestId") != request_id:
        return False
    return True


def snapshot_bot_text(message: dict[str, Any], request_id: str | None = None) -> str | None:
    """
    Best-effort bot text snapshot from messages[] on type-1 update or type-2 item.

    When ``request_id`` is set, only bot messages with that requestId are considered
    (skips echoed history from prior turns). Non-``Chat`` messages (loader/search
    interstitials) are never treated as the answer text.
    """
    msg_type = message.get("type")
    if msg_type == 1 and message.get("target") == "update":
        arg_entries = message.get("arguments") or []
    elif msg_type == 2:
        arg_entries = [{"messages": (message.get("item") or {}).get("messages")}]
    else:
        return None

    best: str | None = None
    for args in arg_entries:
        if not isinstance(args, dict):
            continue
        msgs = args.get("messages")
        if not msgs:
            continue
        entries = msgs if isinstance(msgs, list) else [msgs]
        for entry in reversed(entries):
            if not isinstance(entry, dict):
                continue
            if not _is_answer_entry(entry, request_id):
                continue
            text = entry.get("text")
            if isinstance(text, str) and text:
                if best is None or len(text) > len(best):
                    best = text
                break
    return best


def fallback_bot_text(message: dict[str, Any]) -> str | None:
    """Best-effort full bot text from type-1 update or type-2 item payloads."""
    msg_type = message.get("type")
    if msg_type == 1 and message.get("target") == "update":
        args = (message.get("arguments") or [{}])[0]
        if not isinstance(args, dict):
            return None
        msgs = args.get("messages")
    elif msg_type == 2:
        msgs = (message.get("item") or {}).get("messages")
    else:
        return None

    if not msgs:
        return None
    entries = msgs if isinstance(msgs, list) else [msgs]
    for entry in reversed(entries):
        if not isinstance(entry, dict):
            continue
        if entry.get("author") == "user":
            continue
        text = entry.get("text")
        if isinstance(text, str) and text:
            return text
    return None


# How many consecutive snapshot-free frames may be released before we stop
# waiting for a healing snapshot. Substrate does not deliver every character
# through writeAtCursor: some segments only ever show up in messages[].text.
# Releasing a delta immediately makes any segment it skipped unrecoverable,
# so delta-only frames are held for a short window first.
HEAL_WINDOW_FRAMES = 4

# Tail sizes tried when re-anchoring an already-released prefix inside a
# snapshot. Bounded so a diverged turn stays O(1) per frame.
_ANCHOR_SIZES = (64, 32, 16, 8)


def released_offset_in(snapshot: str, released: str) -> int | None:
    """
    Return how much of ``snapshot`` is already covered by ``released`` text.

    Normally ``released`` is a prefix of the snapshot. After an unrecoverable
    gap (text streamed while a segment was missing) it is not, so the tail of
    the released text is located inside the snapshot instead and streaming
    re-anchors there. ``None`` means the snapshot is unrelated (history echo,
    a different answer) and must be ignored.
    """
    if not released:
        return 0
    if snapshot.startswith(released):
        return len(released)
    sizes = [size for size in _ANCHOR_SIZES if size <= len(released)] or [len(released)]
    for size in sizes:
        index = snapshot.rfind(released[-size:])
        if index != -1:
            return index + size
    return None


class CumulativeTextReconstructor:
    """
    Reconstruct streaming bot text from writeAtCursor deltas and messages[] snapshots.

    Keeps an assembled string per turn: concatenated deltas, healed by the
    request-scoped cumulative snapshot whenever one arrives. Only new suffixes
    are released; frames that would rewind are ignored.

    Deltas alone are not trusted to be complete, so a run of snapshot-free
    frames is held back for up to ``heal_window_frames`` frames. Text released
    to the client cannot be retracted, and a snapshot can only fill a gap that
    is still ahead of the release point. Pass ``heal_window_frames=0`` to
    release every delta immediately (no gap healing).
    """

    def __init__(self, heal_window_frames: int = HEAL_WINDOW_FRAMES) -> None:
        self._assembled = ""
        self._released_len = 0
        self._heal_window_frames = heal_window_frames
        self._frames_held = 0

    def feed(self, message: dict[str, Any], request_id: str | None = None) -> str | None:
        for delta in write_at_cursor_deltas(message):
            self._assembled += delta

        snapshot = snapshot_bot_text(message, request_id)
        confirmed = self._apply_snapshot(snapshot) if snapshot else False

        if len(self._assembled) <= self._released_len:
            return None

        if not confirmed:
            self._frames_held += 1
            if self._frames_held < self._heal_window_frames:
                return None

        return self._release()

    def flush(self) -> str | None:
        """Release anything still held back (end of turn)."""
        if len(self._assembled) <= self._released_len:
            return None
        return self._release()

    def _apply_snapshot(self, snapshot: str) -> bool:
        """Heal assembled text from a cumulative snapshot; True when it lines up."""
        released = self._assembled[: self._released_len]
        if len(snapshot) <= len(self._assembled):
            # Snapshot lags the delta stream; it only confirms alignment.
            return self._assembled.startswith(snapshot)

        offset = released_offset_in(snapshot, released)
        if offset is None or offset < self._released_len:
            return False

        self._assembled = snapshot
        self._released_len = offset
        return True

    def _release(self) -> str | None:
        chunk = self._assembled[self._released_len :]
        self._released_len = len(self._assembled)
        self._frames_held = 0
        return chunk or None
