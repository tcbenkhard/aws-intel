"""AWS Intel command-line application."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("aws-intel")
except PackageNotFoundError:
    __version__ = "0.2.0"

__all__ = ["__version__"]
