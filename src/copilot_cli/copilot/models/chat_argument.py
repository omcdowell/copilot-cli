from typing import NamedTuple, Optional

from copilot_cli.copilot.enums.copilot_scenario_enum import CopilotScenarioEnum
from copilot_cli.copilot.enums.verbose_enum import VerboseEnum


class ChatArguments(NamedTuple):
    """
    Chat arguments model

    """

    user: str
    use_cached_access_token: Optional[bool]
    scenario: CopilotScenarioEnum
    verbose: VerboseEnum
