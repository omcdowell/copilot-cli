"""Raw Substrate frame tracing for the streaming path.

The streaming proxy reconstructs answer text from writeAtCursor deltas and
messages[] snapshots. When the reconstruction is wrong there is no way to tell
which of the two the hub actually sent without the raw frames, so this writes
them verbatim, one JSON line per event.

Opt in with ``COPILOT_CLI_WS_TRACE=/path/to/trace.jsonl``. Off by default: the
trace contains prompt and answer text.
"""

from __future__ import annotations

import json
import os
import re
import time
from typing import Any, Optional

TRACE_ENV_VAR = "COPILOT_CLI_WS_TRACE"

# Chathub URLs carry ?access_token=...; never let one reach the trace file.
_SECRET_PATTERN = re.compile(r"(access_token=)[^&\"\s]+", re.IGNORECASE)


def _redact(text: str) -> str:
    return _SECRET_PATTERN.sub(r"\1<redacted>", text)


class StreamTrace:
    """Append-only JSONL trace of one streaming turn. No-op unless enabled."""

    def __init__(self, path: Optional[str] = None) -> None:
        self._path = path if path is not None else os.environ.get(TRACE_ENV_VAR)

    @property
    def enabled(self) -> bool:
        return bool(self._path)

    def event(self, kind: str, **fields: Any) -> None:
        if not self._path:
            return
        record: dict[str, Any] = {"t": round(time.time(), 3), "kind": kind}
        for key, value in fields.items():
            record[key] = _redact(value) if isinstance(value, str) else value
        try:
            with open(self._path, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError:
            # Tracing must never break a turn.
            self._path = None
