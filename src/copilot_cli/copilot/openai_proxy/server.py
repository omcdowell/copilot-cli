"""OpenAI-compatible HTTP proxy for M365 Copilot."""

from __future__ import annotations

import os
import subprocess  # nosec
import time
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from flask import Flask, Response, jsonify, request

from copilot_cli.copilot.models.chat_argument import ChatArguments
from copilot_cli.copilot.openai_proxy.message_flattener import (
    build_continuation_prompt,
    flatten_messages,
    outstanding_tool_call_ids,
    tool_result_ids,
)
from copilot_cli.copilot.openai_proxy.session_store import SessionStore
from copilot_cli.copilot.openai_proxy.stream_chunks import iter_live_sse_with_keepalive
from copilot_cli.copilot.loggers.stream_trace import TRACE_ENV_VAR, StreamTrace
from copilot_cli.copilot.openai_proxy.prompt_config import ENV_VAR, current_prompts_path, get_prompts
from copilot_cli.copilot.openai_proxy.tool_parser import parse_tool_calls, to_openai_tool_calls
from copilot_cli.copilot.openai_proxy.tool_protocol import ToolProtocolMode

DEFAULT_MODEL_ID = "m365-copilot"


def build_identity() -> str:
    """Describe the code actually running, so a stale install is obvious.

    A `pip install .` (non-editable) box keeps serving site-packages after a
    `git pull`; printing the module path plus its revision makes that visible
    without shelling into the process.
    """
    import copilot_cli

    package_dir = Path(copilot_cli.__file__).resolve().parent
    try:
        from importlib.metadata import version

        package_version = version("copilot-cli")
    except Exception:  # noqa: BLE001 — identity output must never fail a start-up
        package_version = "unknown"

    revision = "no git checkout"
    try:
        completed = subprocess.run(  # nosec
            ["git", "-C", str(package_dir), "describe", "--always", "--dirty", "--tags"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if completed.returncode == 0 and completed.stdout.strip():
            revision = completed.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass

    trace = os.environ.get(TRACE_ENV_VAR)
    return (
        f"copilot-cli {package_version} ({revision})\n"
        f"  module: {package_dir}\n"
        f"  frame trace: {trace if trace else f'off (set {TRACE_ENV_VAR}=/path/trace.jsonl)'}"
    )


def _allowed_tool_names(tools: list[dict[str, Any]] | None) -> set[str] | None:
    if not tools:
        return None
    names: set[str] = set()
    for tool in tools:
        if tool.get("type") != "function":
            continue
        name = tool.get("function", {}).get("name")
        if name:
            names.add(str(name))
    return names or None


def create_app(
    chat_arguments: ChatArguments,
    *,
    tool_protocol: ToolProtocolMode | str = ToolProtocolMode.reminder,
) -> Flask:
    app = Flask(__name__)
    session_store = SessionStore(chat_arguments)
    protocol_mode = ToolProtocolMode(tool_protocol)

    @app.get("/v1/models")
    def list_models() -> Any:
        return jsonify(
            {
                "object": "list",
                "data": [
                    {
                        "id": DEFAULT_MODEL_ID,
                        "object": "model",
                        "created": int(time.time()),
                        "owned_by": "m365-copilot",
                    },
                    {
                        "id": "default",
                        "object": "model",
                        "created": int(time.time()),
                        "owned_by": "m365-copilot",
                    },
                ],
            }
        )

    @app.post("/v1/chat/completions")
    def chat_completions() -> Any:
        payload = request.get_json(silent=True) or {}
        messages = payload.get("messages", [])
        if not messages:
            return jsonify({"error": {"message": "messages is required", "type": "invalid_request_error"}}), 400

        model = payload.get("model", DEFAULT_MODEL_ID)
        tools = payload.get("tools")
        allowed_tool_names = _allowed_tool_names(tools)
        session_key = SessionStore.session_key_from_request(request, messages)
        is_new_conversation = session_store.is_new_conversation(request, messages, session_key)

        if is_new_conversation:
            prompt = flatten_messages(messages, tools)
        else:
            outstanding = outstanding_tool_call_ids(messages)
            results = set(tool_result_ids(messages))
            if outstanding and results < set(outstanding):
                return jsonify(
                    {
                        "error": {
                            "message": (
                                "Incomplete tool results: expected results for all "
                                f"{len(outstanding)} tool_calls before sending to Copilot"
                            ),
                            "type": "invalid_request_error",
                        }
                    }
                ), 400
            prompt = build_continuation_prompt(messages, tools, protocol_mode=protocol_mode)
            if not prompt.strip():
                return jsonify(
                    {"error": {"message": "No continuation content found", "type": "invalid_request_error"}}
                ), 400

        completion_id = f"chatcmpl-{uuid.uuid4().hex}"
        created = int(time.time())
        want_stream = bool(payload.get("stream"))

        def run_copilot_turn() -> str:
            with session_store.lock_session(session_key):
                automator = session_store.get_automator(session_key, is_new_conversation)
                text = automator.send_prompt_text(prompt)
                if not text and tools:
                    automator = session_store.reset_session(session_key)
                    text = automator.send_prompt_text(prompt)
                return text

        if want_stream:

            def live_events() -> Iterator[str]:
                with session_store.lock_session(session_key):
                    automator = session_store.get_automator(session_key, is_new_conversation)

                    def deltas() -> Iterator[str]:
                        saw_text = False
                        for chunk in automator.iter_prompt_text(prompt):
                            if chunk:
                                saw_text = True
                            yield chunk
                        if not saw_text and tools:
                            automator_retry = session_store.reset_session(session_key)
                            yield from automator_retry.iter_prompt_text(prompt)

                    yield from iter_live_sse_with_keepalive(
                        completion_id=completion_id,
                        created=created,
                        model=model,
                        deltas=deltas,
                        watch_tools=bool(tools),
                        allowed_tool_names=allowed_tool_names,
                    )

            return Response(
                live_events(),
                mimetype="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no",
                },
            )

        try:
            response_text = run_copilot_turn()
        except Exception as exc:  # noqa: BLE001 — surface upstream failures as JSON
            return jsonify(
                {
                    "error": {
                        "message": f"{type(exc).__name__}: {exc}",
                        "type": "copilot_proxy_error",
                        "code": "upstream_error",
                    }
                }
            ), 502

        content, parsed_tool_calls = parse_tool_calls(
            response_text,
            allowed_tool_names=allowed_tool_names,
            salvage_unclosed=True,
        )

        if parsed_tool_calls:
            message: dict[str, Any] = {
                "role": "assistant",
                "content": content,
                "tool_calls": to_openai_tool_calls(parsed_tool_calls),
            }
            finish_reason = "tool_calls"
        else:
            message = {
                "role": "assistant",
                "content": response_text,
            }
            finish_reason = "stop"

        return jsonify(
            {
                "id": completion_id,
                "object": "chat.completion",
                "created": created,
                "model": model,
                "choices": [
                    {
                        "index": 0,
                        "message": message,
                        "finish_reason": finish_reason,
                    }
                ],
                "usage": {
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0,
                },
            }
        )

    return app


def run_server(
    chat_arguments: ChatArguments,
    host: str,
    port: int,
    *,
    tool_protocol: ToolProtocolMode | str = ToolProtocolMode.reminder,
) -> None:
    protocol_mode = ToolProtocolMode(tool_protocol)
    app = create_app(chat_arguments, tool_protocol=protocol_mode)
    print(build_identity())
    print(f"M365 Copilot OpenAI proxy listening on http://{host}:{port}/v1")
    print(f"Continuation tool protocol: {protocol_mode.value}")
    get_prompts()
    prompts_path = current_prompts_path()
    if prompts_path is None:
        print(f"Prompts: built-in defaults ({ENV_VAR}=defaults)")
    else:
        print(f"Prompts: {prompts_path} (reloaded when the file changes)")
    if StreamTrace().enabled:
        print("Tracing raw Substrate frames (contains prompt and answer text).")
    app.run(host=host, port=port, threaded=True)
