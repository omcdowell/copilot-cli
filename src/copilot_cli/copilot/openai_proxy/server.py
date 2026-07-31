"""OpenAI-compatible HTTP proxy for M365 Copilot."""

from __future__ import annotations

import time
import uuid
from typing import Any

from flask import Flask, Response, jsonify, request

from copilot_cli.copilot.models.chat_argument import ChatArguments
from copilot_cli.copilot.openai_proxy.message_flattener import (
    build_continuation_prompt,
    count_user_messages,
    flatten_messages,
)
from copilot_cli.copilot.openai_proxy.session_store import SessionStore
from copilot_cli.copilot.openai_proxy.stream_chunks import iter_streaming_completion
from copilot_cli.copilot.openai_proxy.tool_parser import parse_tool_calls, to_openai_tool_calls

DEFAULT_MODEL_ID = "m365-copilot"


def create_app(chat_arguments: ChatArguments) -> Flask:
    app = Flask(__name__)
    session_store = SessionStore(chat_arguments)

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
        session_key = SessionStore.session_key_from_request(request, messages)
        is_new_conversation = count_user_messages(messages) <= 1

        if is_new_conversation:
            prompt = flatten_messages(messages, tools)
        else:
            prompt = build_continuation_prompt(messages, tools)
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
            # Copilot returns one full reply; synthesize OpenAI SSE so Pi gets
            # finish_reason. The turn runs inside the generator: headers and the
            # role chunk go out immediately, pings keep the connection alive
            # during slow first-message auth, and automator failures become
            # in-stream OpenAI error frames instead of HTML 500s.
            return Response(
                iter_streaming_completion(
                    completion_id=completion_id,
                    created=created,
                    model=model,
                    produce=run_copilot_turn,
                ),
                mimetype="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
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

        content, parsed_tool_calls = parse_tool_calls(response_text)

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


def run_server(chat_arguments: ChatArguments, host: str, port: int) -> None:
    app = create_app(chat_arguments)
    print(f"M365 Copilot OpenAI proxy listening on http://{host}:{port}/v1")
    app.run(host=host, port=port, threaded=True)
