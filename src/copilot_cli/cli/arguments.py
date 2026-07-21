import argparse

from copilot_cli.copilot.enums.copilot_scenario_enum import CopilotScenarioEnum
from copilot_cli.copilot.enums.verbose_enum import VerboseEnum


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="copilot-cli",
        description="Standalone M365 Copilot CLI — connect and interact with Copilot365 in Office/Teams.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  copilot-cli chat -u user@example.com -p 'pass' -s officeweb
  copilot-cli whoami -u user@example.com --cached-token -s officeweb
  copilot-cli dump -u user@example.com --cached-token -s officeweb -d ./whoami_out
        """,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    chat = subparsers.add_parser("chat", help="Interactive chat with Copilot365")
    _add_auth_args(chat)

    whoami = subparsers.add_parser("whoami", help="Recon: identify user context via Copilot")
    _add_auth_args(whoami)
    whoami.add_argument("-g", "--gui", action="store_true", help="Browse whoami output in a local GUI")

    dump = subparsers.add_parser("dump", help="Dump documents/emails using whoami recon output")
    _add_auth_args(dump)
    dump.add_argument("-d", "--directory", type=str, required=True, help="Path to whoami output directory")
    dump.add_argument("-g", "--gui", action="store_true", help="Browse dump output in a local GUI")

    spear = subparsers.add_parser("spear-phishing", help="Craft personalized emails via Copilot (research tool)")
    _add_auth_args(spear)

    gui = subparsers.add_parser("gui", help="Browse collected data in a local GUI")
    gui.add_argument("-d", "--directory", type=str, required=True, help="Data directory")

    return parser.parse_args()


def _add_auth_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("-u", "--user", required=True, type=str, help="User email to connect")
    parser.add_argument("-p", "--password", required=False, type=str, help="User password (needed if no cached token)")
    parser.add_argument(
        "--cached-token",
        action="store_true",
        help="Use cached substrate access token from tokens.json if present",
    )
    parser.add_argument(
        "-s",
        "--scenario",
        required=True,
        type=str,
        choices=[s.value for s in CopilotScenarioEnum],
        help="Copilot surface: officeweb (Business Chat) or teamshub (Teams)",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        required=False,
        type=str,
        default=VerboseEnum.off.value,
        choices=[v.value for v in VerboseEnum],
        help="Session log verbosity. Default: off",
    )
