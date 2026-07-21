from copilot_cli.common.file_browser.app import FileBrowserApp
from copilot_cli.copilot.loggers.console_logger import ConsoleLogger


class Gui:
    def __init__(self) -> None:
        self.__console_logger = ConsoleLogger()

    def run(self, cache_path: str) -> None:
        self.__console_logger.log("Starting a localhost ..")
        self.__console_logger.log("To browse data navigate to http://127.0.0.1:8080")

        file_browser = FileBrowserApp(cache_path)
        file_browser.run(debug=False, host="0.0.0.0", port=8080)  # nosec
