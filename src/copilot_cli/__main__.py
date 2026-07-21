from copilot_cli.cli.arguments import parse_arguments


def main() -> None:
    print("copilot-cli — M365 Copilot command line")
    args = parse_arguments()
    from copilot_cli.cli.runners import run

    run(args)


if __name__ == "__main__":
    main()
