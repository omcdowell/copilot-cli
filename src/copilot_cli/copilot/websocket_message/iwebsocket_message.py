from abc import ABC, abstractmethod

from copilot_cli.copilot.enums.message_type_enum import MessageTypeEnum
from copilot_cli.copilot.websocket_message.websocket_parsed_message import WebsocketParsedMessage


class IWebsocketMessage(ABC):
    @property
    @abstractmethod
    def message(self) -> str:
        """
        returns the raw message as s string
        """

    @property
    @abstractmethod
    def parsed_message(self) -> WebsocketParsedMessage:
        """
        returns the parsed message
        """

    @abstractmethod
    def type(self) -> MessageTypeEnum:
        """
        returns the type of the message
        """

    @abstractmethod
    def formatted_str(self) -> str:
        """
        returns formatted message as string

        """

    @abstractmethod
    def is_success(self) -> bool:
        """
        returns whether the message is a success message
        """
