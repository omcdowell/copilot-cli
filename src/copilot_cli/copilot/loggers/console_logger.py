from typing_extensions import override

from copilot_cli.copilot.loggers.ilogger import ILogger


class ConsoleLogger(ILogger):
    @override
    def log(self, message: str) -> None:
        print(message)
