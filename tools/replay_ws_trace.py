#!/usr/bin/env python3
"""Replay a COPILOT_CLI_WS_TRACE file and report where streamed text is lost.

Usage:
    COPILOT_CLI_WS_TRACE=/tmp/copilot-trace.jsonl copilot-cli serve ...   # capture
    python tools/replay_ws_trace.py /tmp/copilot-trace.jsonl              # analyse

Answers the questions the live symptom cannot:
  * does the hub send mid-stream messages[] snapshots at all?
  * do those snapshots carry the turn's requestId (or are they filtered out)?
  * what does the delta stream alone produce vs. the final authoritative text?
  * what does the current reconstructor produce, and what is missing from it?
"""

from __future__ import annotations

import json
import sys
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from copilot_cli.copilot.websocket_message.substrate_deltas import (  # noqa: E402
    CumulativeTextReconstructor,
    fallback_bot_text,
    snapshot_bot_text,
    write_at_cursor_deltas,
)


def _turns(path: Path) -> list[dict[str, Any]]:
    turns: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        kind = record.get("kind")
        if kind == "turn_start":
            current = {"requestId": record.get("requestId"), "frames": [], "released": []}
            turns.append(current)
        elif current is None:
            continue
        elif kind == "frame":
            current["frames"].append(json.loads(record["raw"].rstrip(chr(30))))
        elif kind in {"released", "flushed", "fallback"}:
            current["released"].append(record.get("text", ""))
    return turns


def _raw_snapshots(frame: dict[str, Any]) -> list[dict[str, Any]]:
    """Every bot messages[] entry in a frame, ignoring requestId/messageType filters."""
    if frame.get("type") == 1 and frame.get("target") == "update":
        arg_entries = frame.get("arguments") or []
    elif frame.get("type") == 2:
        arg_entries = [{"messages": (frame.get("item") or {}).get("messages")}]
    else:
        return []
    entries: list[dict[str, Any]] = []
    for args in arg_entries:
        if not isinstance(args, dict):
            continue
        msgs = args.get("messages") or []
        for entry in msgs if isinstance(msgs, list) else [msgs]:
            if isinstance(entry, dict) and entry.get("author") != "user" and entry.get("text"):
                entries.append(entry)
    return entries


def _report(index: int, turn: dict[str, Any]) -> None:
    rid = turn["requestId"]
    frames = turn["frames"]

    deltas = [d for frame in frames for d in write_at_cursor_deltas(frame)]
    delta_text = "".join(deltas)

    accepted = [s for frame in frames if (s := snapshot_bot_text(frame, rid))]
    mid_stream_accepted = [
        s for frame in frames if frame.get("type") == 1 and (s := snapshot_bot_text(frame, rid))
    ]
    raw_entries = [entry for frame in frames for entry in _raw_snapshots(frame)]
    rid_mismatch = [e for e in raw_entries if e.get("requestId") not in (None, rid)]
    non_chat = [e for e in raw_entries if e.get("messageType") not in (None, "Chat")]

    final = ""
    for frame in frames:
        final = fallback_bot_text(frame) or final

    replay = CumulativeTextReconstructor()
    replayed = "".join(
        chunk for chunk in [replay.feed(frame, rid) for frame in frames] + [replay.flush()] if chunk
    )
    live = "".join(turn["released"])
    truth = final or max(accepted, key=len, default="")

    print(f"=== turn {index} (requestId={rid}) ===")
    print(f"frames: {len(frames)}  deltas: {len(deltas)}")
    print(f"bot messages[] entries seen (unfiltered): {len(raw_entries)}")
    print(f"  accepted as snapshots: {len(accepted)}  of which mid-stream (type 1): {len(mid_stream_accepted)}")
    print(f"  dropped, requestId mismatch: {len(rid_mismatch)}  dropped, messageType: {len(non_chat)}")
    if rid_mismatch:
        seen = {str(e.get("requestId")) for e in rid_mismatch}
        print(f"    mismatching requestIds: {sorted(seen)[:4]}")
    if non_chat:
        print(f"    messageTypes: {sorted({str(e.get('messageType')) for e in non_chat})}")
    print()
    print(f"delta-only text  ({len(delta_text):5d} chars): {delta_text[:120]!r}")
    print(f"live released    ({len(live):5d} chars): {live[:120]!r}")
    print(f"replay (current) ({len(replayed):5d} chars): {replayed[:120]!r}")
    print(f"final/authorative({len(truth):5d} chars): {truth[:120]!r}")

    if truth and replayed != truth:
        print("\nMISSING from the streamed text:")
        for tag, i1, i2, j1, j2 in SequenceMatcher(None, replayed, truth).get_opcodes():
            if tag in {"insert", "replace"}:
                print(f"  at {i1:5d}: {truth[j1:j2]!r}")
            elif tag == "delete":
                print(f"  extra at {i1:5d}: {replayed[i1:i2]!r}")
    elif truth:
        print("\nstreamed text matches the final text exactly")
    print()


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    path = Path(sys.argv[1])
    turns = _turns(path)
    if not turns:
        print(f"no turns found in {path} (was COPILOT_CLI_WS_TRACE set on the serving process?)")
        return 1
    for index, turn in enumerate(turns, start=1):
        _report(index, turn)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
