"""Shared terminal prompt for selecting one choice from a list."""

from collections.abc import Sequence
import sys

import questionary
from prompt_toolkit.input import Input
from prompt_toolkit.output import Output


def _prompt_toolkit_kwargs(
    input_device: Input | None, output_device: Output | None
) -> dict[str, Input | Output]:
    """Build the keyword arguments used to override questionary's terminal."""
    kwargs: dict[str, Input | Output] = {}
    if input_device is not None:
        kwargs["input"] = input_device
    if output_device is not None:
        kwargs["output"] = output_device
    return kwargs


def prompt_choice(
    message: str,
    choices: Sequence[object],
    *,
    error_type: type[Exception],
    non_interactive_message: str,
    cancelled_message: str,
    input: Input | None = None,
    output: Output | None = None,
) -> object:
    """Prompt for one choice from a list using an interactive terminal."""
    if input is None and not sys.stdin.isatty():
        raise error_type(non_interactive_message)

    try:
        selected = questionary.select(
            message,
            choices=list(choices),
            **_prompt_toolkit_kwargs(input, output),
        ).unsafe_ask()
    except KeyboardInterrupt as error:
        raise error_type(cancelled_message) from error
    if selected is None:
        raise error_type(cancelled_message)
    return selected
