"""Tests for interactive forward selection."""

from contextlib import contextmanager
from collections.abc import Iterator

from prompt_toolkit.input import Input, create_pipe_input
from prompt_toolkit.output import DummyOutput
import pytest
import questionary

from aws_intel.forwarding.model import ActiveForward, PortMapping
from aws_intel.forwarding.selection import (
    ForwardSelectionError,
    select_active_forwards,
    select_forwards,
)

SPACE = " "
ENTER = "\r"
ARROW_DOWN = "\x1b[B"
CANCEL = "\x03"


@contextmanager
def _typed(text: str) -> Iterator[Input]:
    """Provide a prompt_toolkit input device pre-loaded with keystrokes."""
    with create_pipe_input() as pipe_input:
        pipe_input.send_text(text)
        yield pipe_input


def test_selects_one_forward_by_toggling_the_first_choice() -> None:
    with _typed(SPACE + ENTER) as pipe_input:
        selected = select_forwards(
            ("apigateway-dev", "database"), input=pipe_input, output=DummyOutput()
        )

    assert selected == ("apigateway-dev",)


def test_selects_multiple_forwards_after_navigating_with_arrow_keys() -> None:
    with _typed(SPACE + ARROW_DOWN + SPACE + ENTER) as pipe_input:
        selected = select_forwards(
            ("apigateway-dev", "database"), input=pipe_input, output=DummyOutput()
        )

    assert selected == ("apigateway-dev", "database")


def test_active_forward_is_visible_but_cannot_be_selected() -> None:
    with _typed(SPACE + ENTER) as pipe_input:
        selected = select_forwards(
            ("apigateway-dev", "database"),
            active_names=("apigateway-dev",),
            input=pipe_input,
            output=DummyOutput(),
        )

    assert selected == ("database",)


def test_active_forward_has_a_single_active_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_choices: list[questionary.Choice] = []

    def capture_choices(
        _message: str, choices: list[questionary.Choice], **_kwargs: object
    ) -> list[str]:
        captured_choices.extend(choices)
        return []

    monkeypatch.setattr(
        "aws_intel.forwarding.selection.prompt_choices", capture_choices
    )

    select_forwards(("apigateway-dev",), active_names=("apigateway-dev",))

    assert captured_choices[0].title == "apigateway-dev"
    assert captured_choices[0].disabled == "active"


def test_rejects_non_interactive_input(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "aws_intel.interactive.selection.sys.stdin.isatty", lambda: False
    )

    with pytest.raises(ForwardSelectionError, match="forward is required"):
        select_forwards(("apigateway-dev",))


def test_rejects_empty_forward_list() -> None:
    with _typed("") as pipe_input:
        with pytest.raises(ForwardSelectionError, match="no forwards are configured"):
            select_forwards((), input=pipe_input, output=DummyOutput())


def test_rejects_confirming_without_toggling_any_choice() -> None:
    with _typed(ENTER) as pipe_input:
        with pytest.raises(
            ForwardSelectionError, match="at least one forward must be selected"
        ):
            select_forwards(("apigateway-dev",), input=pipe_input, output=DummyOutput())


def test_cancelling_forward_selection_raises_error() -> None:
    with _typed(CANCEL) as pipe_input:
        with pytest.raises(ForwardSelectionError, match="was cancelled"):
            select_forwards(("apigateway-dev",), input=pipe_input, output=DummyOutput())


def test_selects_one_active_forward_by_toggling_the_first_choice() -> None:
    forwards = (
        ActiveForward(4321, "i-01234567", "db.internal", PortMapping(1, 2), "primary"),
        ActiveForward(4322, "i-01234567", "db.internal", PortMapping(3, 4), None),
    )
    with _typed(SPACE + ENTER) as pipe_input:
        selected = select_active_forwards(
            forwards, input=pipe_input, output=DummyOutput()
        )

    assert selected == (forwards[0],)


def test_selects_multiple_active_forwards_after_navigating_with_arrow_keys() -> None:
    forwards = (
        ActiveForward(4321, "i-01234567", "db.internal", PortMapping(1, 2), "primary"),
        ActiveForward(4322, "i-01234567", "db.internal", PortMapping(3, 4), None),
    )
    with _typed(SPACE + ARROW_DOWN + SPACE + ENTER) as pipe_input:
        selected = select_active_forwards(
            forwards, input=pipe_input, output=DummyOutput()
        )

    assert selected == forwards


def test_rejects_empty_active_forward_list() -> None:
    with _typed("") as pipe_input:
        with pytest.raises(
            ForwardSelectionError, match="no active forwards are configured"
        ):
            select_active_forwards((), input=pipe_input, output=DummyOutput())


def test_cancelling_active_forward_selection_raises_error() -> None:
    forwards = (
        ActiveForward(4321, "i-01234567", "db.internal", PortMapping(1, 2), "primary"),
    )
    with _typed(CANCEL) as pipe_input:
        with pytest.raises(ForwardSelectionError, match="was cancelled"):
            select_active_forwards(forwards, input=pipe_input, output=DummyOutput())
