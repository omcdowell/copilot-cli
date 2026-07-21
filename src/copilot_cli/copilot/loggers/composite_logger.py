from typing_extensions import override

from copilot_cli.copilot.loggers.ilogger import ILogger


class CompositeLogger(ILogger):
    def __init__(self, loggers: list) -> None:
        self.__loggers = loggers

    @override
    def log(self, message: str) -> None:
        for logger in self.__loggers:
            logger.log(message)
