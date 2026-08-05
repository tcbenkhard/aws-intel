"""Interactive forward selection for AWS Intel."""

from collections.abc import Sequence

import questionary
from prompt_toolkit.input import Input
from prompt_toolkit.output import Output

from aws_intel.forwarding.model import ActiveForward
from aws_intel.interactive.selection import prompt_choices


class ForwardSelectionError(RuntimeError):
    """Raised when a forward cannot be selected interactively."""


def select_forwards(
    names: Sequence[str],
    *,
    active_names: Sequence[str] = (),
    input: Input | None = None,
    output: Output | None = None,
) -> tuple[str, ...]:
    """Prompt for one or more saved forwards and return their names."""
    if not names:
        raise ForwardSelectionError("no forwards are configured")

    active = frozenset(active_names)
    choices = [
        questionary.Choice(
            title=f"{name} (active)" if name in active else name,
            value=name,
            disabled="already active" if name in active else None,
        )
        for name in names
    ]
    selected = prompt_choices(
        "Select forwards (space to toggle, enter to confirm):",
        choices,
        error_type=ForwardSelectionError,
        non_interactive_message=(
            "a forward is required when input is not an interactive terminal"
        ),
        cancelled_message="forward selection was cancelled",
        empty_selection_message="at least one forward must be selected",
        input=input,
        output=output,
    )
    return tuple(selected)


def select_active_forwards(
    forwards: Sequence[ActiveForward],
    *,
    input: Input | None = None,
    output: Output | None = None,
) -> tuple[ActiveForward, ...]:
    """Prompt for one or more active forwards and return them."""
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
    selected = prompt_choices(
        "Select forwards to stop (space to toggle, enter to confirm):",
        choices,
        error_type=ForwardSelectionError,
        non_interactive_message=(
            "an active forward is required when input is not an interactive terminal"
        ),
        cancelled_message="forward selection was cancelled",
        empty_selection_message="at least one active forward must be selected",
        input=input,
        output=output,
    )
    return tuple(selected)
