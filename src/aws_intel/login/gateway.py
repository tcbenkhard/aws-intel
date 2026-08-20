"""AWS CLI and shell boundaries for account login."""

from collections.abc import Callable, Sequence
import configparser
from datetime import datetime
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
from tempfile import TemporaryDirectory

from aws_intel.login.model import Account, Credentials

CommandRunner = Callable[..., subprocess.CompletedProcess[str]]
Clock = Callable[[], datetime]
SESSION_NAME_CHARACTERS = re.compile(r"[^A-Za-z0-9+=,.@_-]")


class LoginError(RuntimeError):
    """Raised when SSO login, role assumption, or shell startup fails."""


class AwsCliLoginGateway:
    """Create chained credentials and expose them to an interactive shell."""

    def __init__(
        self,
        runner: CommandRunner = subprocess.run,
        clock: Clock = lambda: datetime.now().astimezone(),
    ) -> None:
        self._runner = runner
        self._clock = clock

    def open_shell(self, chain: Sequence[Account], elevated: bool = False) -> int:
        root = chain[0]
        with TemporaryDirectory(prefix="awsi-login-") as directory:
            config_path = Path(directory) / "config"
            self._write_sso_config(config_path, root)
            bootstrap_environment = dict(os.environ)
            bootstrap_environment["AWS_CONFIG_FILE"] = str(config_path)
            try:
                credentials = self._cached_or_interactive_credentials(
                    bootstrap_environment
                )
                for account in chain[1:]:
                    credentials = self._assume_role(account, credentials)
            except LoginError as error:
                if elevated:
                    target = chain[-1]
                    raise LoginError(
                        f"could not retrieve elevated role {target.role_name!r} "
                        f"for {target.name!r}; make sure TEAM access is active "
                        "and retry"
                    ) from error
                raise

        target = chain[-1]
        self._verify_identity(target, credentials)
        environment = dict(os.environ)
        for variable in ("AWS_PROFILE", "AWS_CONFIG_FILE", "AWS_SHARED_CREDENTIALS_FILE"):
            environment.pop(variable, None)
        environment.update(credentials.environment())
        environment["AWS_REGION"] = target.region
        environment["AWS_DEFAULT_REGION"] = target.region
        environment["AWSI_ACCOUNT"] = target.name
        environment["AWSI_ROLE"] = target.role_name
        if target.color is not None:
            environment["AWSI_COLOR"] = target.color
        shell = environment.get("SHELL") or "/bin/sh"
        self._set_account_prompt(
            environment, shell, target.name, target.role_name, target.color
        )
        print(
            f"Authenticated as {target.name} ({target.account_id}) in {target.region}.\n"
            f"Session valid until {self._format_expiration(credentials.expires_at)} "
            f"({self._format_remaining(credentials.expires_at)} remaining).\n"
            "Exit the shell to return.",
            file=os.sys.stderr,
        )
        try:
            result = self._open_shell_process(shell, environment)
        except FileNotFoundError as error:
            raise LoginError(f"shell {shell!r} was not found") from error
        return result.returncode

    def _open_shell_process(
        self, shell: str, environment: dict[str, str]
    ) -> subprocess.CompletedProcess[str]:
        """Start a shell, applying the account prompt after zsh startup files."""
        if Path(shell).name != "zsh":
            return self._runner([shell], env=environment, check=False)

        original_zdotdir = Path(
            environment.get("ZDOTDIR") or environment.get("HOME") or Path.home()
        )
        with TemporaryDirectory(prefix="awsi-zsh-") as directory:
            wrapper_dir = Path(directory)
            self._write_zsh_startup_wrapper(wrapper_dir, original_zdotdir)
            zsh_environment = dict(environment)
            zsh_environment["ZDOTDIR"] = str(wrapper_dir)
            return self._runner([shell], env=zsh_environment, check=False)

    @staticmethod
    def _write_zsh_startup_wrapper(path: Path, original_zdotdir: Path) -> None:
        """Load normal zsh configuration before applying awsi's prompt label."""
        original_environment = original_zdotdir / ".zshenv"
        environment_lines = []
        if original_environment.is_file():
            environment_lines.append(f"source {shlex.quote(str(original_environment))}")
        environment_lines.append(f"export ZDOTDIR={shlex.quote(str(path))}")
        (path / ".zshenv").write_text(
            "\n".join(environment_lines) + "\n", encoding="utf-8"
        )

        original_rc = original_zdotdir / ".zshrc"
        rc_lines = [f"export ZDOTDIR={shlex.quote(str(original_zdotdir))}"]
        if original_rc.is_file():
            rc_lines.append(f"source {shlex.quote(str(original_rc))}")
        rc_lines.extend(
            (
                'if [[ -n ${AWSI_ACCOUNT:-} ]]; then',
                '  if [[ -n ${AWSI_ROLE:-} ]]; then',
                '    _awsi_label="[${AWSI_ROLE}@${AWSI_ACCOUNT}] "',
                "  else",
                '    _awsi_label="[${AWSI_ACCOUNT}] "',
                "  fi",
                '  if [[ -n ${AWSI_COLOR:-} ]]; then',
                '    _awsi_label="%F{${AWSI_COLOR}}${_awsi_label}%f"',
                "  fi",
                '  PROMPT="${_awsi_label}${PROMPT:-%n@%m %1~ %# }"',
                "  unset _awsi_label",
                "fi",
            )
        )
        (path / ".zshrc").write_text(
            "\n".join(rc_lines) + "\n", encoding="utf-8"
        )

    @staticmethod
    def _write_sso_config(path: Path, account: Account) -> None:
        parser = configparser.ConfigParser()
        parser["profile awsi-bootstrap"] = {
            "sso_start_url": account.sso_start_url or "",
            "sso_region": account.sso_region or "",
            "sso_account_id": account.account_id,
            "sso_role_name": account.role_name,
            "region": account.region,
        }
        with path.open("w", encoding="utf-8") as config_file:
            parser.write(config_file)

    def _export_credentials(self, environment: dict[str, str]) -> Credentials:
        response = self._run_json(
            [
                "aws", "configure", "export-credentials", "--profile",
                "awsi-bootstrap", "--format", "process",
            ],
            environment,
        )
        return self._credentials(response)

    def _cached_or_interactive_credentials(
        self, environment: dict[str, str]
    ) -> Credentials:
        """Reuse the AWS CLI SSO cache, authenticating only when it is unusable."""
        try:
            return self._export_credentials(environment)
        except LoginError:
            self._run_interactive(
                ["aws", "sso", "login", "--profile", "awsi-bootstrap"],
                environment,
            )
            return self._export_credentials(environment)

    def _assume_role(self, account: Account, source: Credentials) -> Credentials:
        environment = dict(os.environ)
        environment.update(source.environment())
        command = [
            "aws", "sts", "assume-role",
            "--role-arn", f"arn:aws:iam::{account.account_id}:role/{account.role_name}",
            "--role-session-name", self._session_name(account.name),
            "--region", account.region,
            "--output", "json", "--no-cli-pager",
        ]
        if account.session_duration_hours is not None:
            command += [
                "--duration-seconds",
                str(account.session_duration_hours * 3600),
            ]
        response = self._run_json(command, environment)
        try:
            value = response["Credentials"]
        except (KeyError, TypeError) as error:
            raise LoginError("AWS CLI returned an unexpected AssumeRole response") from error
        return self._credentials(value)

    def _verify_identity(
        self, account: Account, credentials: Credentials
    ) -> None:
        environment = dict(os.environ)
        environment.update(credentials.environment())
        response = self._run_json(
            [
                "aws",
                "sts",
                "get-caller-identity",
                "--region",
                account.region,
                "--output",
                "json",
                "--no-cli-pager",
            ],
            environment,
        )
        try:
            actual_account_id = response["Account"]  # type: ignore[index]
        except (KeyError, TypeError) as error:
            raise LoginError(
                "AWS CLI returned an unexpected caller identity response"
            ) from error
        if actual_account_id != account.account_id:
            raise LoginError(
                f"expected account {account.account_id}, but AWS authenticated "
                f"to {actual_account_id}"
            )

    def _run_json(self, command: list[str], environment: dict[str, str]) -> object:
        try:
            result = self._runner(
                command, env=environment, capture_output=True, check=False, text=True
            )
        except FileNotFoundError as error:
            raise LoginError("AWS CLI was not found. Install it and ensure 'aws' is on PATH.") from error
        if result.returncode != 0:
            raise LoginError(result.stderr.strip() or "AWS CLI exited unsuccessfully")
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError as error:
            raise LoginError("AWS CLI returned an unexpected response") from error

    def _run_interactive(self, command: list[str], environment: dict[str, str]) -> None:
        try:
            result = self._runner(command, env=environment, check=False)
        except FileNotFoundError as error:
            raise LoginError("AWS CLI was not found. Install it and ensure 'aws' is on PATH.") from error
        if result.returncode != 0:
            raise LoginError("AWS SSO login failed")

    @staticmethod
    def _credentials(value: object) -> Credentials:
        try:
            if not isinstance(value, dict):
                raise TypeError
            access_key = value["AccessKeyId"]
            secret_key = value["SecretAccessKey"]
            token = value["SessionToken"]
            expiration = value["Expiration"]
            if not all(
                isinstance(item, str) and item
                for item in (access_key, secret_key, token, expiration)
            ):
                raise TypeError
            expires_at = datetime.fromisoformat(expiration.replace("Z", "+00:00"))
            if expires_at.tzinfo is None:
                raise ValueError
            return Credentials(access_key, secret_key, token, expires_at)
        except (KeyError, TypeError, ValueError) as error:
            raise LoginError("AWS CLI returned incomplete credentials") from error

    @staticmethod
    def _format_expiration(expiration: datetime) -> str:
        return expiration.astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")

    def _format_remaining(self, expiration: datetime) -> str:
        seconds = max(0, int((expiration - self._clock()).total_seconds()))
        hours, remainder = divmod(seconds, 3600)
        minutes = remainder // 60
        if hours:
            return f"{hours}h {minutes}m"
        return f"{minutes}m"

    @staticmethod
    def _set_account_prompt(
        environment: dict[str, str],
        shell: str,
        account_name: str,
        role_name: str,
        color: str | None = None,
    ) -> None:
        """Prefix common shell prompts with the active role and account."""
        prefix = f"[{role_name}@{account_name}] "
        shell_name = Path(shell).name
        if shell_name == "zsh":
            prompt = environment.get("PROMPT", "%n@%m %1~ %# ")
            colored_prefix = f"%F{{{color}}}{prefix}%f" if color else prefix
            environment["PROMPT"] = colored_prefix + prompt
            return
        prompt = environment.get("PS1", r"\u@\h \W \$ ")
        if color:
            red, green, blue = (int(color[index:index + 2], 16) for index in (1, 3, 5))
            prefix = f"\\[\\033[38;2;{red};{green};{blue}m\\]{prefix}\\[\\033[0m\\]"
        environment["PS1"] = prefix + prompt

    @staticmethod
    def _session_name(account_name: str) -> str:
        normalized = SESSION_NAME_CHARACTERS.sub("-", f"awsi-{account_name}")
        return normalized[:64]
