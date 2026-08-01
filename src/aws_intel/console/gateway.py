"""AWS federation and browser boundaries for console access."""

from collections.abc import Callable, Mapping
import json
import urllib.parse
import urllib.request
import webbrowser

FEDERATION_ENDPOINT = "https://signin.aws.amazon.com/federation"
DEFAULT_DESTINATION = "https://console.aws.amazon.com/"
BrowserOpener = Callable[[str], bool]
FederationRequester = Callable[[bytes], object]


class ConsoleError(RuntimeError):
    """Raised when an authenticated console cannot be opened."""


class AwsConsoleGateway:
    """Exchange current AWS credentials for a console sign-in URL."""

    def __init__(
        self,
        requester: FederationRequester | None = None,
        browser_opener: BrowserOpener = webbrowser.open,
    ) -> None:
        self._requester = requester or self._request_signin_token
        self._browser_opener = browser_opener

    def open(self, environment: Mapping[str, str]) -> None:
        """Open the AWS console using credentials from an awsi login shell."""
        account = environment.get("AWSI_ACCOUNT")
        access_key = environment.get("AWS_ACCESS_KEY_ID")
        secret_key = environment.get("AWS_SECRET_ACCESS_KEY")
        session_token = environment.get("AWS_SESSION_TOKEN")
        if not account or not all((access_key, secret_key, session_token)):
            raise ConsoleError(
                "no awsi login session was found; run this command inside the "
                "shell opened by 'awsi login'"
            )

        session = json.dumps(
            {
                "sessionId": access_key,
                "sessionKey": secret_key,
                "sessionToken": session_token,
            },
            separators=(",", ":"),
        )
        request_body = urllib.parse.urlencode(
            {"Action": "getSigninToken", "Session": session}
        ).encode("utf-8")
        response = self._requester(request_body)
        try:
            if not isinstance(response, dict):
                raise TypeError
            signin_token = response["SigninToken"]
            if not isinstance(signin_token, str) or not signin_token:
                raise TypeError
        except (KeyError, TypeError) as error:
            raise ConsoleError("AWS returned an unexpected federation response") from error

        destination = self._destination(environment.get("AWS_REGION"))
        login_parameters = urllib.parse.urlencode(
            {
                "Action": "login",
                "Destination": destination,
                "SigninToken": signin_token,
            }
        )
        login_url = f"{FEDERATION_ENDPOINT}?{login_parameters}"
        if not self._browser_opener(login_url):
            raise ConsoleError("the system browser could not be opened")

    @staticmethod
    def _destination(region: str | None) -> str:
        if not region:
            return DEFAULT_DESTINATION
        query = urllib.parse.urlencode({"region": region})
        return f"{DEFAULT_DESTINATION}console/home?{query}"

    @staticmethod
    def _request_signin_token(request_body: bytes) -> object:
        request = urllib.request.Request(
            FEDERATION_ENDPOINT,
            data=request_body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return json.loads(response.read().decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ConsoleError("could not obtain an AWS console sign-in token") from error
