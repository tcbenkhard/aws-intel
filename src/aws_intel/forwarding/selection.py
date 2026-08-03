"""Interactive forward selection for AWS Intel."""

from collections.abc import Sequence

import questionary
from prompt_toolkit.input import Input
from prompt_toolkit.output import Output

from aws_intel.forwarding.model import ActiveForward
from aws_intel.interactive.selection import prompt_choice


class ForwardSelectionError(RuntimeError):
    """Raised when a forward cannot be selected interactively."""


def select_forward(
    names: Sequence[str],
    *,
    input: Input | None = None,
    output: Output | None = None,
) -> str:
    """Prompt for one saved forward and return its name."""
    if not names:
        raise ForwardSelectionError("no forwards are configured")

    return prompt_choice(
        "Select a forward:",
        list(names),
        error_type=ForwardSelectionError,
        non_interactive_message=(
            "a forward is required when input is not an interactive terminal"
        ),
        cancelled_message="forward selection was cancelled",
        input=input,
        output=output,
    )


def select_active_forward(
    forwards: Sequence[ActiveForward],
    *,
    input: Input | None = None,
    output: Output | None = None,
) -> ActiveForward:
    """Prompt for one active forward and return it."""
    if not forwards:
        raise ForwardSelectionError("no active forwards are configured")

    choices = [
        questionary.Choice(
            title=(
                f"{forward.name} (PID {forward.pid})"
                if forward.name is not None
                else f"PID {forward.pid}"
            ),
            value=forward,
        )
        for forward in forwards
    ]
    return prompt_choice(
        "Select a forward:",
        choices,
        error_type=ForwardSelectionError,
        non_interactive_message=(
            "an active forward is required when input is not an interactive terminal"
        ),
        cancelled_message="forward selection was cancelled",
        input=input,
        output=output,
    )
