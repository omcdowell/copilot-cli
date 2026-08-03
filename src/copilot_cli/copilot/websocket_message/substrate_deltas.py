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


def snapshot_bot_text(message: dict[str, Any], request_id: str | None = None) -> str | None:
    """
    Best-effort bot text snapshot from messages[] on type-1 update or type-2 item.

    When ``request_id`` is set, only bot messages with that requestId are considered
    (skips echoed history from prior turns).
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
            if entry.get("author") == "user":
                continue
            if request_id is not None and entry.get("requestId") != request_id:
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


class CumulativeTextReconstructor:
    """
    Reconstruct streaming bot text from writeAtCursor deltas and messages[] snapshots.

    Keeps an assembled string from concatenated deltas per turn. On each frame the
    candidate is the longer of the request-scoped snapshot and assembled text. New
    suffixes are yielded; frames that would rewind are ignored.
    """

    def __init__(self) -> None:
        self._assembled = ""
        self._emitted_len = 0

    def feed(self, message: dict[str, Any], request_id: str | None = None) -> str | None:
        for delta in write_at_cursor_deltas(message):
            self._assembled += delta

        snapshot = snapshot_bot_text(message, request_id)
        candidate = self._assembled
        if snapshot and len(snapshot) > len(candidate):
            # Only adopt a longer snapshot when it extends what was already emitted.
            if self._emitted_len == 0 or snapshot[: self._emitted_len] == self._assembled[: self._emitted_len]:
                candidate = snapshot

        if len(candidate) <= self._emitted_len:
            return None

        chunk = candidate[self._emitted_len :]
        self._emitted_len = len(candidate)
        # Re-base so later writeAtCursor deltas append to the healed text.
        self._assembled = candidate
        return chunk if chunk else None
