"""Check PyPI for a newer aws-intel release."""

import json
import sys
from collections.abc import Callable
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from packaging.version import InvalidVersion, Version

PYPI_PROJECT_URL = "https://pypi.org/pypi/aws-intel/json"
REQUEST_TIMEOUT_SECONDS = 1.0


def find_newer_version(
    current_version: str,
    *,
    open_url: Callable[..., Any] = urlopen,
) -> str | None:
    """Return the latest PyPI version when it is newer than the installed one."""
    request = Request(
        PYPI_PROJECT_URL,
        headers={
            "Accept": "application/json",
            "User-Agent": f"aws-intel/{current_version}",
        },
    )
    try:
        with open_url(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            latest_version = json.load(response)["info"]["version"]
        if Version(latest_version) > Version(current_version):
            return latest_version
    except (
        HTTPError,
        URLError,
        TimeoutError,
        OSError,
        KeyError,
        TypeError,
        ValueError,
        InvalidVersion,
    ):
        pass
    return None


def notify_if_update_available(current_version: str) -> None:
    """Write a non-fatal update notice to standard error when appropriate."""
    latest_version = find_newer_version(current_version)
    if latest_version is not None:
        print(
            f"awsi: update available: {current_version} -> {latest_version} "
            "(run: pip install --upgrade aws-intel)",
            file=sys.stderr,
        )
