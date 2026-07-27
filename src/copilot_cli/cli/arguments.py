import argparse

from copilot_cli.copilot.enums.copilot_scenario_enum import CopilotScenarioEnum
from copilot_cli.copilot.enums.verbose_enum import VerboseEnum

_DESCRIPTION = "Connect to M365 Copilot (Office Business Chat or Teams) to chat, recon, dump, browse, or serve."

_EPILOG = """\
examples:
  copilot-cli chat -u user@contoso.com -s officeweb
  copilot-cli whoami -u user@contoso.com --cached-token -s officeweb
  copilot-cli dump -u user@contoso.com --cached-token -s officeweb -d ./whoami_out
  copilot-cli gui -d ./whoami_out
  copilot-cli serve -u user@contoso.com --cached-token -s officeweb --port 8787

auth:
  First run opens a visible Edge window (profile ~/.config/copilot-cli/msedge-profile).
  Sign in once; later runs reuse cookies. Prefer --cached-token once tokens.json exists.
  Override profile with COPILOT_CLI_BROWSER_PROFILE. No passwords on the CLI.

Run "copilot-cli <command> -h" for command-specific options.
"""


class _HelpFormatter(argparse.RawDescriptionHelpFormatter):
    def __init__(self, prog: str) -> None:
        super().__init__(prog, max_help_position=30, width=100)


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="copilot-cli",
        description=_DESCRIPTION,
        formatter_class=_HelpFormatter,
        epilog=_EPILOG,
    )
    subparsers = parser.add_subparsers(
        dest="command",
        required=True,
        title="commands",
        metavar="COMMAND",
    )

    chat = subparsers.add_parser(
        "chat",
        help="Interactive chat with Copilot365",
        description="Start an interactive Copilot365 chat session over the Substrate websocket.",
        formatter_class=_HelpFormatter,
        epilog="example:\n  copilot-cli chat -u user@contoso.com -s officeweb",
    )
    _add_auth_args(chat)

    whoami = subparsers.add_parser(
        "whoami",
        help="Identify user context via Copilot",
        description="Run recon prompts through Copilot to identify the signed-in user and context.",
        formatter_class=_HelpFormatter,
        epilog="example:\n  copilot-cli whoami -u user@contoso.com --cached-token -s officeweb",
    )
    _add_auth_args(whoami)
    whoami.add_argument(
        "-g",
        "--gui",
        action="store_true",
        help="Open the whoami output directory in the local GUI when finished",
    )

    dump = subparsers.add_parser(
        "dump",
        help="Dump documents/emails from whoami output",
        description="Dump documents and emails using a prior whoami recon output directory.",
        formatter_class=_HelpFormatter,
        epilog=(
            "example:\n"
            "  copilot-cli dump -u user@contoso.com --cached-token -s officeweb -d ./whoami_out"
        ),
    )
    _add_auth_args(dump)
    dump.add_argument(
        "-d",
        "--directory",
        type=str,
        required=True,
        metavar="DIR",
        help="Path to whoami output directory",
    )
    dump.add_argument(
        "-g",
        "--gui",
        action="store_true",
        help="Open the dump output directory in the local GUI when finished",
    )

    gui = subparsers.add_parser(
        "gui",
        help="Browse collected data in a local GUI",
        description="Serve a local file browser for a whoami or dump output directory.",
        formatter_class=_HelpFormatter,
        epilog="example:\n  copilot-cli gui -d ./whoami_out",
    )
    gui.add_argument(
        "-d",
        "--directory",
        type=str,
        required=True,
        metavar="DIR",
        help="Data directory to browse",
    )

    serve = subparsers.add_parser(
        "serve",
        help="OpenAI-compatible HTTP proxy for Pi and other clients",
        description=(
            "Expose an OpenAI-compatible HTTP proxy so Pi and other clients can use "
            "M365 Copilot as a model backend."
        ),
        formatter_class=_HelpFormatter,
        epilog=(
            "example:\n"
            "  copilot-cli serve -u user@contoso.com --cached-token -s officeweb --port 8787"
        ),
    )
    _add_auth_args(serve)
    proxy = serve.add_argument_group("proxy")
    proxy.add_argument(
        "--port",
        type=int,
        default=8787,
        metavar="PORT",
        help="HTTP listen port (default: 8787)",
    )
    proxy.add_argument(
        "--host",
        type=str,
        default="127.0.0.1",
        metavar="HOST",
        help="HTTP listen address (default: 127.0.0.1)",
    )

    return parser.parse_args()


def _add_auth_args(parser: argparse.ArgumentParser) -> None:
    auth = parser.add_argument_group("auth")
    auth.add_argument(
        "-u",
        "--user",
        required=True,
        metavar="EMAIL",
        type=str,
        help="User email to connect as",
    )
    auth.add_argument(
        "--cached-token",
        action="store_true",
        help="Use substrate_access_token from ./tokens.json when present",
    )
    auth.add_argument(
        "-s",
        "--scenario",
        required=True,
        metavar="SCENARIO",
        type=str,
        choices=[s.value for s in CopilotScenarioEnum],
        help="Copilot surface: officeweb (Business Chat) or teamshub (Teams)",
    )

    session = parser.add_argument_group("session")
    session.add_argument(
        "-v",
        "--verbose",
        required=False,
        metavar="LEVEL",
        type=str,
        default=VerboseEnum.off.value,
        choices=[v.value for v in VerboseEnum],
        help="Session log verbosity (default: off)",
    )
