from copilot_cli.cli.arguments import parse_arguments


def main() -> None:
    args = parse_arguments()
    print("copilot-cli — M365 Copilot command line")
    from copilot_cli.cli.runners import run

    run(args)


if __name__ == "__main__":
    main()
