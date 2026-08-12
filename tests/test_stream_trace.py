"""The raw frame trace is the only ground truth for streaming bugs."""

import json

from copilot_cli.copilot.loggers.stream_trace import TRACE_ENV_VAR, StreamTrace


def test_trace_is_a_noop_when_not_configured(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv(TRACE_ENV_VAR, raising=False)
    trace = StreamTrace()

    assert not trace.enabled
    trace.event("frame", raw="{}")  # must not raise or create files

    assert list(tmp_path.iterdir()) == []


def test_trace_writes_one_json_line_per_event(tmp_path) -> None:
    path = tmp_path / "trace.jsonl"
    trace = StreamTrace(str(path))
    trace.event("turn_start", requestId="rid-1", prompt="hi")
    trace.event("frame", raw='{"type":1,"target":"update"}')

    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

    assert [r["kind"] for r in records] == ["turn_start", "frame"]
    assert records[0]["requestId"] == "rid-1"
    assert records[1]["raw"] == '{"type":1,"target":"update"}'
    assert all("t" in r for r in records)


def test_trace_redacts_access_tokens(tmp_path) -> None:
    path = tmp_path / "trace.jsonl"
    StreamTrace(str(path)).event("frame", raw="wss://substrate/x?access_token=SECRET-VALUE&X-Session=1")

    contents = path.read_text(encoding="utf-8")

    assert "SECRET-VALUE" not in contents
    assert "access_token=<redacted>" in contents


def test_trace_survives_an_unwritable_path(tmp_path) -> None:
    trace = StreamTrace(str(tmp_path / "missing-dir" / "trace.jsonl"))

    trace.event("frame", raw="{}")  # must swallow the OSError
    trace.event("frame", raw="{}")

    assert not trace.enabled
