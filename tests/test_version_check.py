"""Tests for the non-fatal PyPI version check."""

import io
from urllib.error import URLError

import pytest

from aws_intel.version_check import find_newer_version, notify_if_update_available


class JsonResponse(io.BytesIO):
    """Context-managed byte response returned by a fake URL opener."""

    def __enter__(self) -> "JsonResponse":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


def response_for(version: str) -> JsonResponse:
    return JsonResponse(f'{{"info": {{"version": "{version}"}}}}'.encode())


def test_finds_a_newer_pypi_version() -> None:
    assert (
        find_newer_version(
            "1.2.3",
            open_url=lambda *_args, **_kwargs: response_for("1.3.0"),
        )
        == "1.3.0"
    )


@pytest.mark.parametrize("latest", ["1.2.3", "1.2.2"])
def test_ignores_versions_that_are_not_newer(latest: str) -> None:
    assert (
        find_newer_version(
            "1.2.3", open_url=lambda *_args, **_kwargs: response_for(latest)
        )
        is None
    )


def test_network_errors_are_non_fatal() -> None:
    def unavailable(*_args: object, **_kwargs: object) -> JsonResponse:
        raise URLError("offline")

    assert find_newer_version("1.2.3", open_url=unavailable) is None


def test_update_notice_is_written_to_stderr(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        "aws_intel.version_check.find_newer_version",
        lambda _version: "2.0.0",
    )

    notify_if_update_available("1.2.3")

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "1.2.3 -> 2.0.0" in captured.err
    assert "pip install --upgrade aws-intel" in captured.err
