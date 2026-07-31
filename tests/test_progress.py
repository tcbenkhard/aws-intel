"""Tests for terminal progress presentation."""

from io import StringIO

from aws_intel.progress import spinner


class TerminalStream(StringIO):
    """In-memory stream that behaves like an interactive terminal."""

    def isatty(self) -> bool:
        return True


def test_spinner_writes_to_and_clears_interactive_terminal() -> None:
    stream = TerminalStream()

    with spinner("Loading...", stream=stream):
        pass

    output = stream.getvalue()
    assert "Loading..." in output
    assert output.endswith("\r\033[2K")


def test_spinner_is_silent_for_noninteractive_stream() -> None:
    stream = StringIO()

    with spinner("Loading...", stream=stream):
        pass

    assert stream.getvalue() == ""
