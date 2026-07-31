"""Terminal progress presentation."""

from collections.abc import Iterator
from contextlib import contextmanager
import itertools
import sys
from threading import Event, Thread
from typing import TextIO


@contextmanager
def spinner(
    message: str,
    *,
    stream: TextIO | None = None,
    interval: float = 0.1,
) -> Iterator[None]:
    """Show a spinner on an interactive terminal for the duration of a task."""
    stream = stream or sys.stderr
    if not stream.isatty():
        yield
        return

    stopped = Event()
    frames = itertools.cycle("⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏")

    def animate() -> None:
        while not stopped.wait(interval):
            stream.write(f"\r{next(frames)} {message}")
            stream.flush()

    stream.write(f"\r{next(frames)} {message}")
    stream.flush()
    thread = Thread(target=animate, daemon=True)
    thread.start()
    try:
        yield
    finally:
        stopped.set()
        thread.join()
        stream.write("\r\033[2K")
        stream.flush()
