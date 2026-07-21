from copilot_cli.copilot.dump.dump import Dump
from copilot_cli.copilot.enums.copilot_scenario_enum import CopilotScenarioEnum
from copilot_cli.copilot.enums.verbose_enum import VerboseEnum
from copilot_cli.copilot.gui.gui import Gui
from copilot_cli.copilot.interactive_chat.interactive_chat import InteractiveChat
from copilot_cli.copilot.models.chat_argument import ChatArguments
from copilot_cli.copilot.spearphishing.automated_spear_phisher import AutomatedSpearPhisher
from copilot_cli.copilot.whoami.whoami import WhoAmI


def _chat_args(args) -> ChatArguments:
    return ChatArguments(
        user=args.user,
        password=args.password,
        use_cached_access_token=args.cached_token,
        verbose=VerboseEnum(args.verbose),
        scenario=CopilotScenarioEnum(args.scenario),
    )


def run(args) -> None:
    if args.command == "gui":
        Gui().run(args.directory)
        return

    parsed = _chat_args(args)

    if args.command == "chat":
        InteractiveChat(parsed).start_chat()
    elif args.command == "spear-phishing":
        AutomatedSpearPhisher(parsed).phish()
    elif args.command == "whoami":
        output_dir = WhoAmI(parsed).execute()
        if args.gui:
            Gui().run(output_dir)
    elif args.command == "dump":
        output_dir = Dump(parsed, args.directory).run()
        if args.gui:
            Gui().run(output_dir)
    else:
        raise SystemExit(f"Unknown command: {args.command}")
