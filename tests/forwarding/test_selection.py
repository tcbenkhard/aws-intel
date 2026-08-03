"""Tests for interactive forward selection."""

from contextlib import contextmanager
from collections.abc import Iterator

from prompt_toolkit.input import Input, create_pipe_input
from prompt_toolkit.output import DummyOutput
import pytest

from aws_intel.forwarding.model import ActiveForward, PortMapping
from aws_intel.forwarding.selection import (
    ForwardSelectionError,
    select_active_forward,
    select_forward,
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


def test_selects_forward_by_confirming_the_first_choice() -> None:
    with _typed(ENTER) as pipe_input:
        selected = select_forward(
            ("apigateway-dev", "database"), input=pipe_input, output=DummyOutput()
        )

    assert selected == "apigateway-dev"


def test_selects_forward_after_navigating_with_arrow_keys() -> None:
    with _typed(ARROW_DOWN + ENTER) as pipe_input:
        selected = select_forward(
            ("apigateway-dev", "database"), input=pipe_input, output=DummyOutput()
        )

    assert selected == "database"


def test_rejects_non_interactive_input(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "aws_intel.interactive.selection.sys.stdin.isatty", lambda: False
    )

    with pytest.raises(ForwardSelectionError, match="forward is required"):
        select_forward(("apigateway-dev",))


def test_rejects_empty_forward_list() -> None:
    with _typed("") as pipe_input:
        with pytest.raises(ForwardSelectionError, match="no forwards are configured"):
            select_forward((), input=pipe_input, output=DummyOutput())


def test_cancelling_forward_selection_raises_error() -> None:
    with _typed(CANCEL) as pipe_input:
        with pytest.raises(ForwardSelectionError, match="was cancelled"):
            select_forward(("apigateway-dev",), input=pipe_input, output=DummyOutput())


def test_selects_active_forward_by_confirming_the_first_choice() -> None:
    forwards = (
        ActiveForward(4321, "i-01234567", "db.internal", PortMapping(1, 2), "primary"),
        ActiveForward(4322, "i-01234567", "db.internal", PortMapping(3, 4), None),
    )
    with _typed(ENTER) as pipe_input:
        selected = select_active_forward(
            forwards, input=pipe_input, output=DummyOutput()
        )

    assert selected == forwards[0]


def test_selects_active_forward_after_navigating_with_arrow_keys() -> None:
    forwards = (
        ActiveForward(4321, "i-01234567", "db.internal", PortMapping(1, 2), "primary"),
        ActiveForward(4322, "i-01234567", "db.internal", PortMapping(3, 4), None),
    )
    with _typed(ARROW_DOWN + ENTER) as pipe_input:
        selected = select_active_forward(
            forwards, input=pipe_input, output=DummyOutput()
        )

    assert selected == forwards[1]


def test_rejects_empty_active_forward_list() -> None:
    with _typed("") as pipe_input:
        with pytest.raises(
            ForwardSelectionError, match="no active forwards are configured"
        ):
            select_active_forward((), input=pipe_input, output=DummyOutput())


def test_cancelling_active_forward_selection_raises_error() -> None:
    forwards = (
        ActiveForward(4321, "i-01234567", "db.internal", PortMapping(1, 2), "primary"),
    )
    with _typed(CANCEL) as pipe_input:
        with pytest.raises(ForwardSelectionError, match="was cancelled"):
            select_active_forward(forwards, input=pipe_input, output=DummyOutput())
