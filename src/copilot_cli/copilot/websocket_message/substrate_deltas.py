"""Extract Substrate SignalR streaming deltas from type-1 update frames."""

from __future__ import annotations

from typing import Any, Optional


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


# Substrate does not deliver every character through writeAtCursor: some
# segments only ever show up in the cumulative messages[].text snapshot.
# Releasing a delta immediately makes any segment it skipped unrecoverable,
# because streamed text cannot be retracted. ``None`` therefore means "only
# release what a snapshot has confirmed" (correctness first: a hub that never
# streams snapshots yields one chunk at end of turn). An int caps how many
# unconfirmed frames may pile up before the delta text is released anyway.
WAIT_FOR_SNAPSHOT = None

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

    Keeps an assembled string per turn: concatenated deltas, healed (replaced)
    by the request-scoped cumulative snapshot whenever one arrives. Only new
    suffixes are released; frames that would rewind are ignored.

    Deltas are not trusted to be complete. By default only snapshot-confirmed
    text is released, so a delta that skipped a segment is corrected by the
    next snapshot before the client ever sees it; unconfirmed text goes out at
    end of turn via :meth:`finalize`. ``heal_window_frames`` trades that
    guarantee for latency: ``0`` releases every delta immediately (segments
    the hub only sends via snapshot are then lost), ``n`` releases after n
    unconfirmed frames.
    """

    def __init__(self, heal_window_frames: Optional[int] = WAIT_FOR_SNAPSHOT) -> None:
        self._assembled = ""
        self._released_len = 0
        self._confirmed_len = 0
        self._heal_window_frames = heal_window_frames
        self._unconfirmed_frames = 0

    def feed(self, message: dict[str, Any], request_id: str | None = None) -> str | None:
        for delta in write_at_cursor_deltas(message):
            self._assembled += delta

        snapshot = snapshot_bot_text(message, request_id)
        if snapshot and self._apply_snapshot(snapshot):
            self._unconfirmed_frames = 0
        elif len(self._assembled) > self._confirmed_len:
            self._unconfirmed_frames += 1

        return self._release(self._release_upto())

    def finalize(self, final_text: str | None = None) -> str | None:
        """
        Release everything left, healed by the turn's final text when possible.

        ``final_text`` is the authoritative answer from the type-2 frame. It is
        adopted only when it demonstrably contains this turn's text, so an
        echoed answer from a previous turn can never be replayed.
        """
        if final_text and self._is_this_turn(final_text):
            offset = released_offset_in(final_text, self._assembled[: self._released_len])
            if offset is not None and offset >= self._released_len:
                self._assembled = final_text
                self._released_len = offset
                self._confirmed_len = len(final_text)
        return self._release(len(self._assembled))

    def flush(self) -> str | None:
        """Release anything still held back (end of turn, no final text available)."""
        return self._release(len(self._assembled))

    def _is_this_turn(self, text: str) -> bool:
        """True when ``text`` covers what this turn produced (or we produced nothing)."""
        anchor = self._assembled[: self._released_len] or self._assembled
        if not anchor:
            return True
        return released_offset_in(text, anchor) is not None

    def _apply_snapshot(self, snapshot: str) -> bool:
        """Heal assembled text from a cumulative snapshot; True when it lines up."""
        if len(snapshot) <= len(self._assembled):
            # Snapshot lags the delta stream; it can only confirm alignment.
            if not self._assembled.startswith(snapshot):
                return False
            self._confirmed_len = max(self._confirmed_len, len(snapshot))
            return True

        offset = released_offset_in(snapshot, self._assembled[: self._released_len])
        if offset is None or offset < self._released_len:
            return False

        # Drop unreleased delta text: the snapshot is authoritative, and the
        # deltas may have skipped a segment it carries.
        self._assembled = snapshot
        self._released_len = offset
        self._confirmed_len = len(snapshot)
        return True

    def _release_upto(self) -> int:
        window = self._heal_window_frames
        if window is not None and self._unconfirmed_frames >= window:
            return len(self._assembled)
        return min(self._confirmed_len, len(self._assembled))

    def _release(self, upto: int) -> str | None:
        if upto <= self._released_len:
            return None
        chunk = self._assembled[self._released_len : upto]
        self._released_len = upto
        if upto >= len(self._assembled):
            self._unconfirmed_frames = 0
        return chunk or None
