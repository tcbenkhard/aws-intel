"""Interactive account selection for AWS login."""

from collections.abc import Sequence
from typing import TextIO

try:
    import termios
    import tty
except ImportError:  # pragma: no cover - used only on non-POSIX platforms
    termios = None  # type: ignore[assignment]
    tty = None  # type: ignore[assignment]


class AccountSelectionError(RuntimeError):
    """Raised when an account cannot be selected interactively."""


def _read_choice(
    input_stream: TextIO, output_stream: TextIO, cancellation: str
) -> str:
    """Read a line while allowing Escape to cancel immediately on a terminal."""
    if termios is None or tty is None:
        value = input_stream.readline()
        if value.startswith("\x1b"):
            raise AccountSelectionError(cancellation)
        return value
    try:
        descriptor = input_stream.fileno()
        attributes = termios.tcgetattr(descriptor)
    except (AttributeError, OSError):
        value = input_stream.readline()
        if value.startswith("\x1b"):
            raise AccountSelectionError(cancellation)
        return value

    characters: list[str] = []
    try:
        tty.setcbreak(descriptor)
        while True:
            character = input_stream.read(1)
            if character in {"", "\x04", "\x1b"}:
                print(file=output_stream)
                raise AccountSelectionError(cancellation)
            if character in {"\n", "\r"}:
                print(file=output_stream)
                return "".join(characters)
            if character in {"\x08", "\x7f"}:
                if characters:
                    characters.pop()
                    print("\b \b", end="", file=output_stream, flush=True)
                continue
            characters.append(character)
            print(character, end="", file=output_stream, flush=True)
    except KeyboardInterrupt as error:
        print(file=output_stream)
        raise AccountSelectionError(cancellation) from error
    finally:
        termios.tcsetattr(descriptor, termios.TCSADRAIN, attributes)


def select_account(
    names: Sequence[str], input_stream: TextIO, output_stream: TextIO
) -> str:
    """Prompt for one configured account and return its name."""
    if not input_stream.isatty():
        raise AccountSelectionError(
            "an account is required when input is not an interactive terminal"
        )
    if not names:
        raise AccountSelectionError("no accounts are configured")

    print("Select an AWS account:", file=output_stream)
    for number, name in enumerate(names, start=1):
        print(f"  {number}. {name}", file=output_stream)

    while True:
        print(f"Account [1-{len(names)}]: ", end="", file=output_stream, flush=True)
        choice = _read_choice(
            input_stream, output_stream, "account selection was cancelled"
        )
        if choice == "":
            raise AccountSelectionError("account selection was cancelled")
        try:
            index = int(choice.strip()) - 1
        except ValueError:
            index = -1
        if 0 <= index < len(names):
            return names[index]
        print(
            f"Please enter a number between 1 and {len(names)}.",
            file=output_stream,
        )


def select_elevated_access(
    standard_role_name: str,
    elevated_role_name: str,
    input_stream: TextIO,
    output_stream: TextIO,
) -> bool:
    """Ask whether to use standard access or a configured TEAM role."""
    if not input_stream.isatty():
        raise AccountSelectionError(
            "--elevated is required when input is not an interactive terminal"
        )
    print("Select access role:", file=output_stream)
    print(f"  1. {standard_role_name} (standard access)", file=output_stream)
    print(f"  2. {elevated_role_name} (TEAM elevated)", file=output_stream)
    while True:
        print("Access [1-2]: ", end="", file=output_stream, flush=True)
        choice = _read_choice(
            input_stream, output_stream, "access selection was cancelled"
        )
        if choice == "":
            raise AccountSelectionError("access selection was cancelled")
        if choice.strip() in {"1", "2"}:
            return choice.strip() == "2"
        print("Please enter a number between 1 and 2.", file=output_stream)
