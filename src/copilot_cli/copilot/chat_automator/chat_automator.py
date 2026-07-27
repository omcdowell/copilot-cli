import asyncio
from typing import Optional

from copilot_cli.copilot.copilot_connector.copilot_connector import CopilotConnector
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
        response = self.__send_prompt_with_disengage_retry(prompt)
        if not response:
            return ""
        parsed = response.parsed_message
        return parsed.copilot_message or ""

    def __send_prompt_with_disengage_retry(self, prompt: str) -> Optional[WebsocketMessage]:
        response = self.__send_prompt_once(prompt)
        if response and response.parsed_message.is_disengaged:
            self.refresh_connector()
            response = self.__send_prompt_once(prompt)
        return response

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
