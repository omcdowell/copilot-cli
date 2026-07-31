"""Extract Substrate SignalR streaming deltas from type-1 update frames."""

from __future__ import annotations

from typing import Any


def write_at_cursor_delta(message: dict[str, Any]) -> str | None:
    """
    Return the writeAtCursor text delta from a SignalR type-1 update, if any.

    Matches the kuchris/m365-copilot-openai-proxy Substrate client behaviour.
    """
    if message.get("type") != 1 or message.get("target") != "update":
        return None
    args = (message.get("arguments") or [{}])[0]
    if not isinstance(args, dict):
        return None
    delta = args.get("writeAtCursor")
    if not delta or not isinstance(delta, str):
        return None
    return delta


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
