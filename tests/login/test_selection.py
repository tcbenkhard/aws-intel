"""Tests for interactive account selection."""

from contextlib import contextmanager
from collections.abc import Iterator

from prompt_toolkit.input import Input, create_pipe_input
from prompt_toolkit.output import DummyOutput
import pytest

from aws_intel.login.selection import (
    AccountSelectionError,
    select_account,
    select_elevated_access,
)

ENTER = "\r"
ARROW_DOWN = "\x1b[B"
CANCEL = "\x03"


@contextmanager
def _typed(text: str) -> Iterator[Input]:
    """Provide a prompt_toolkit input device pre-loaded with keystrokes."""
    with create_pipe_input() as pipe_input:
        pipe_input.send_text(text)
        yield pipe_input


def test_selects_account_by_confirming_the_first_choice() -> None:
    with _typed(ENTER) as pipe_input:
        selected = select_account(
            ("development", "production"), input=pipe_input, output=DummyOutput()
        )

    assert selected == "development"


def test_selects_account_after_navigating_with_arrow_keys() -> None:
    with _typed(ARROW_DOWN + ENTER) as pipe_input:
        selected = select_account(
            ("development", "production"), input=pipe_input, output=DummyOutput()
        )

    assert selected == "production"


def test_rejects_non_interactive_input(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "aws_intel.interactive.selection.sys.stdin.isatty", lambda: False
    )

    with pytest.raises(AccountSelectionError, match="account is required"):
        select_account(("development",))


def test_rejects_empty_account_list() -> None:
    with _typed("") as pipe_input:
        with pytest.raises(AccountSelectionError, match="no accounts are configured"):
            select_account((), input=pipe_input, output=DummyOutput())


def test_cancelling_account_selection_raises_error() -> None:
    with _typed(CANCEL) as pipe_input:
        with pytest.raises(AccountSelectionError, match="was cancelled"):
            select_account(("development",), input=pipe_input, output=DummyOutput())


def test_selects_team_elevated_access() -> None:
    with _typed(ARROW_DOWN + ENTER) as pipe_input:
        elevated = select_elevated_access(
            "standard-access",
            "elevated-access",
            input=pipe_input,
            output=DummyOutput(),
        )

    assert elevated is True


def test_selects_standard_access() -> None:
    with _typed(ENTER) as pipe_input:
        elevated = select_elevated_access(
            "standard-access",
            "elevated-access",
            input=pipe_input,
            output=DummyOutput(),
        )

    assert elevated is False


def test_rejects_non_interactive_input_for_elevated_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "aws_intel.interactive.selection.sys.stdin.isatty", lambda: False
    )

    with pytest.raises(AccountSelectionError, match="--elevated is required"):
        select_elevated_access("standard-access", "elevated-access")
