"""In-memory mapping from proxy sessions to ChatAutomator instances."""

from __future__ import annotations

import hashlib
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from flask import Request

from copilot_cli.copilot.chat_automator.chat_automator import ChatAutomator
from copilot_cli.copilot.models.chat_argument import ChatArguments


class SessionStore:
    def __init__(self, chat_arguments: ChatArguments) -> None:
        self._chat_arguments = chat_arguments
        self._sessions: dict[str, ChatAutomator] = {}
        self._locks: dict[str, threading.Lock] = {}
        self._meta_lock = threading.Lock()

    @staticmethod
    def session_key_from_request(request: Request, messages: list[Any]) -> str:
        header = request.headers.get("X-Session-Id") or request.headers.get("X-Chat-Id")
        if header:
            return f"hdr_{header.strip()}"
        return SessionStore.session_key_from_messages(messages)

    @staticmethod
    def session_key_from_messages(messages: list[Any]) -> str:
        for message in messages:
            if message.get("role") == "user":
                content = message.get("content", "")
                if isinstance(content, list):
                    content = "\n".join(
                        block.get("text", "") for block in content if isinstance(block, dict)
                    )
                digest = hashlib.sha256(str(content).encode("utf-8")).hexdigest()[:16]
                return f"thread_{digest}"
        return "thread_default"

    def _lock_for(self, session_key: str) -> threading.Lock:
        with self._meta_lock:
            if session_key not in self._locks:
                self._locks[session_key] = threading.Lock()
            return self._locks[session_key]

    @contextmanager
    def lock_session(self, session_key: str) -> Iterator[None]:
        """Serialize one in-flight Copilot turn per session (backpressure)."""
        lock = self._lock_for(session_key)
        with lock:
            yield

    def get_automator(self, session_key: str, is_new_conversation: bool) -> ChatAutomator:
        with self._meta_lock:
            if is_new_conversation or session_key not in self._sessions:
                self._sessions[session_key] = ChatAutomator(self._chat_arguments)
            return self._sessions[session_key]

    def reset_session(self, session_key: str) -> ChatAutomator:
        with self._meta_lock:
            automator = ChatAutomator(self._chat_arguments)
            self._sessions[session_key] = automator
            return automator
