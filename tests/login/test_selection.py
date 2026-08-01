"""Tests for interactive account selection."""

from io import StringIO
import os
import threading
import time

import pytest

from aws_intel.login.selection import (
    AccountSelectionError,
    select_account,
    select_elevated_access,
)


class InteractiveInput(StringIO):
    def isatty(self) -> bool:
        return True


def test_selects_account_by_number() -> None:
    output = StringIO()

    selected = select_account(
        ("development", "production"), InteractiveInput("2\n"), output
    )

    assert selected == "production"
    assert output.getvalue() == (
        "Select an AWS account:\n"
        "  1. development\n"
        "  2. production\n"
        "Account [1-2]: "
    )


def test_reprompts_after_invalid_selection() -> None:
    output = StringIO()

    selected = select_account(("development",), InteractiveInput("no\n2\n1\n"), output)

    assert selected == "development"
    assert output.getvalue().count("Please enter a number between 1 and 1.") == 2


def test_rejects_non_interactive_input() -> None:
    with pytest.raises(AccountSelectionError, match="account is required"):
        select_account(("development",), StringIO("1\n"), StringIO())


def test_rejects_empty_account_list() -> None:
    with pytest.raises(AccountSelectionError, match="no accounts are configured"):
        select_account((), InteractiveInput(""), StringIO())


def test_escape_immediately_cancels_account_selection() -> None:
    master, slave = os.openpty()

    def press_escape() -> None:
        time.sleep(0.05)
        os.write(master, b"\x1b")

    writer = threading.Thread(target=press_escape)
    try:
        writer.start()
        with os.fdopen(slave, encoding="utf-8", closefd=False) as terminal:
            with pytest.raises(AccountSelectionError, match="was cancelled"):
                select_account(("development",), terminal, StringIO())
    finally:
        writer.join()
        os.close(master)
        os.close(slave)


def test_selects_team_elevated_access() -> None:
    output = StringIO()

    elevated = select_elevated_access(
        "standard-access", "elevated-access", InteractiveInput("2\n"), output
    )

    assert elevated is True
    assert output.getvalue() == (
        "Select access role:\n"
        "  1. standard-access (standard access)\n"
        "  2. elevated-access (TEAM elevated)\n"
        "Access [1-2]: "
    )


def test_selects_standard_access() -> None:
    assert (
        select_elevated_access(
            "standard-access",
            "elevated-access",
            InteractiveInput("1\n"),
            StringIO(),
        )
        is False
    )
