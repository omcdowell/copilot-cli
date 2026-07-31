import asyncio
import queue
import threading
from collections.abc import Iterator
from typing import Optional

from copilot_cli.copilot.copilot_connector.copilot_connector import CopilotConnector, StreamOutcome
from copilot_cli.copilot.models.chat_argument import ChatArguments
from copilot_cli.copilot.websocket_message.websocket_message import WebsocketMessage


class ChatAutomator:
    """
    Class that is responsible for automating the chat with Copilot (non interactive mode)
    """

    def __init__(self, arguments: ChatArguments) -> None:
        self.__copilot_connector = CopilotConnector(arguments)
        self.__is_initialized = False

    def init_connector(self) -> None:
        """
        Initializes a connection to the Copilot
        """
        if not self.__is_initialized:
            self.__copilot_connector.init_connection()
        self.__is_initialized = True

    def refresh_connector(self) -> None:
        """
        Refreshes the connection to the Copilot
        """
        self.__copilot_connector.refresh_connection()
        self.__is_initialized = True

    def send_prompt(self, prompt: str) -> Optional[WebsocketMessage]:
        """
        Sends a user prompt to the copilot and gets the response as a websocket message
        """
        self.init_connector()
        return self.__send_prompt_once(prompt)

    def send_prompt_text(self, prompt: str) -> str:
        """
        Sends a user prompt and returns the Copilot reply as plain text.

        On Disengaged, refreshes the Substrate conversation once and retries.
        """
        self.init_connector()
        for attempt in range(2):
            outcome = StreamOutcome()
            text = "".join(self.__iter_prompt_once(prompt, outcome))
            if outcome.is_disengaged and attempt == 0:
                self.refresh_connector()
                continue
            return text
        return ""

    def iter_prompt_text(self, prompt: str) -> Iterator[str]:
        """
        Yield Substrate text deltas as they arrive (writeAtCursor).

        Falls back to a single full-text chunk when the hub does not stream.
        Live path does not retry Disengaged mid-stream (client may already have
        partial tokens); send_prompt_text still retries for buffered callers.
        """
        self.init_connector()
        yield from self.__iter_prompt_once(prompt, StreamOutcome())

    def __iter_prompt_once(self, prompt: str, outcome: StreamOutcome) -> Iterator[str]:
        """Bridge async connect_stream to a sync iterator for Flask workers."""
        q: queue.Queue = queue.Queue()
        sentinel = object()

        def worker() -> None:
            async def consume() -> None:
                try:
                    async for delta in self.__copilot_connector.connect_stream(prompt, outcome):
                        q.put(delta)
                except Exception as exc:  # noqa: BLE001 — re-raised on consumer side
                    q.put(exc)
                finally:
                    q.put(sentinel)

            asyncio.run(consume())

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        while True:
            item = q.get()
            if item is sentinel:
                break
            if isinstance(item, Exception):
                thread.join(timeout=5)
                raise item
            yield item
        thread.join(timeout=5)

    def __send_prompt_once(self, prompt: str) -> Optional[WebsocketMessage]:
        # asyncio.run works in Flask worker threads (no pre-existing loop).
        return asyncio.run(self.__copilot_connector.connect(prompt))

    def enable_bing_web_search(self) -> None:
        """
        Enables Bing Web Search plugin
        """
        self.__copilot_connector.enable_bing_web_search()

    def disable_bing_web_search(self) -> None:
        """
        Disables Bing Web Search plugin
        """
        self.__copilot_connector.disable_bing_web_search()
