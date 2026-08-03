"""Interactive account selection for AWS login."""

from collections.abc import Sequence

import questionary
from prompt_toolkit.input import Input
from prompt_toolkit.output import Output

from aws_intel.interactive.selection import prompt_choice


class AccountSelectionError(RuntimeError):
    """Raised when an account cannot be selected interactively."""


def select_account(
    names: Sequence[str],
    *,
    input: Input | None = None,
    output: Output | None = None,
) -> str:
    """Prompt for one configured account and return its name."""
    if not names:
        raise AccountSelectionError("no accounts are configured")

    return prompt_choice(
        "Select an AWS account:",
        list(names),
        error_type=AccountSelectionError,
        non_interactive_message=(
            "an account is required when input is not an interactive terminal"
        ),
        cancelled_message="account selection was cancelled",
        input=input,
        output=output,
    )


def select_elevated_access(
    standard_role_name: str,
    elevated_role_name: str,
    *,
    input: Input | None = None,
    output: Output | None = None,
) -> bool:
    """Ask whether to use standard access or a configured TEAM role."""
    choices = [
        questionary.Choice(
            title=f"{standard_role_name} (standard access)", value=False
        ),
        questionary.Choice(title=f"{elevated_role_name} (TEAM elevated)", value=True),
    ]
    return prompt_choice(
        "Select access role:",
        choices,
        error_type=AccountSelectionError,
        non_interactive_message=(
            "--elevated is required when input is not an interactive terminal"
        ),
        cancelled_message="access selection was cancelled",
        input=input,
        output=output,
    )
