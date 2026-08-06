from prompt_toolkit import PromptSession
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.history import FileHistory

COMMANDS = [
    "help",
    "status",
    "company",
    "clear",
    "exit",
]

command_completer = WordCompleter(
    COMMANDS,
    ignore_case=True,
)


def run_shell() -> None:
    """Run the interactive smrik-fund shell."""
    session = PromptSession(
        history=FileHistory(".smrik-fund-history"),
        completer=command_completer,
        complete_while_typing=True,
    )

    print("smrik-fund interactive shell")
    print("Type 'help' for commands or 'exit' to quit.")

    while True:
        try:
            command = session.prompt("smrik-fund> ").strip()

            if not command:
                continue

            if command == "exit":
                print("Goodbye.")
                break

            if command == "help":
                print("Available commands: help, status, company, clear, exit")
                continue

            if command == "status":
                print("smrik-fund is alive")
                continue

            if command == "company":
                ticker = session.prompt("Ticker: ").strip().upper()
                print(f"Selected company: {ticker}")
                continue

            if command == "clear":
                print("\033[2J\033[H", end="")
                continue

            print(f"Unknown command: {command}")

        except KeyboardInterrupt:
            print("\nPress Ctrl+D or type 'exit' to quit.")

        except EOFError:
            print("\nGoodbye.")
            break
