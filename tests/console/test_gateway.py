"""Tests for AWS console federation and browser access."""

import json
import urllib.parse

import pytest

from aws_intel.console.gateway import AwsConsoleGateway, ConsoleError


def test_opens_console_with_current_session_credentials() -> None:
    request_bodies: list[bytes] = []
    opened_urls: list[str] = []

    def requester(body: bytes) -> object:
        request_bodies.append(body)
        return {"SigninToken": "one-time-signin-token"}

    def browser_opener(url: str) -> bool:
        opened_urls.append(url)
        return True

    gateway = AwsConsoleGateway(requester, browser_opener)

    gateway.open(
        {
            "AWSI_ACCOUNT": "development",
            "AWS_ACCESS_KEY_ID": "access-key",
            "AWS_SECRET_ACCESS_KEY": "secret-key",
            "AWS_SESSION_TOKEN": "session-token",
            "AWS_REGION": "eu-central-1",
        }
    )

    request = urllib.parse.parse_qs(request_bodies[0].decode("utf-8"))
    assert request["Action"] == ["getSigninToken"]
    assert json.loads(request["Session"][0]) == {
        "sessionId": "access-key",
        "sessionKey": "secret-key",
        "sessionToken": "session-token",
    }
    login = urllib.parse.parse_qs(urllib.parse.urlparse(opened_urls[0]).query)
    assert login["Action"] == ["login"]
    assert login["SigninToken"] == ["one-time-signin-token"]
    assert login["Destination"] == [
        "https://console.aws.amazon.com/console/home?region=eu-central-1"
    ]
    assert "secret-key" not in opened_urls[0]
    assert "session-token" not in opened_urls[0]


def test_requires_an_awsi_login_shell() -> None:
    with pytest.raises(ConsoleError, match="no awsi login session was found"):
        AwsConsoleGateway(lambda _body: {}, lambda _url: True).open({})


def test_rejects_an_invalid_federation_response() -> None:
    gateway = AwsConsoleGateway(lambda _body: {}, lambda _url: True)

    with pytest.raises(ConsoleError, match="unexpected federation response"):
        gateway.open(
            {
                "AWSI_ACCOUNT": "development",
                "AWS_ACCESS_KEY_ID": "access-key",
                "AWS_SECRET_ACCESS_KEY": "secret-key",
                "AWS_SESSION_TOKEN": "session-token",
            }
        )


def test_reports_when_browser_cannot_be_opened() -> None:
    gateway = AwsConsoleGateway(
        lambda _body: {"SigninToken": "token"}, lambda _url: False
    )

    with pytest.raises(ConsoleError, match="browser could not be opened"):
        gateway.open(
            {
                "AWSI_ACCOUNT": "development",
                "AWS_ACCESS_KEY_ID": "access-key",
                "AWS_SECRET_ACCESS_KEY": "secret-key",
                "AWS_SESSION_TOKEN": "session-token",
            }
        )
