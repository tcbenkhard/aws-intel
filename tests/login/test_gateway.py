"""Tests for AWS CLI login and role chaining."""

import json
from pathlib import Path
import shutil
import subprocess
from datetime import datetime, timezone

import pytest

from aws_intel.login.gateway import AwsCliLoginGateway, LoginError
from aws_intel.login.model import Account


def test_logs_in_assumes_role_and_opens_authenticated_shell(monkeypatch) -> None:
    calls: list[tuple[list[str], dict[str, str]]] = []

    def runner(command, **options):
        environment = options.get("env", {})
        calls.append((command, environment))
        if command[:3] == ["aws", "sso", "login"]:
            return subprocess.CompletedProcess(command, 0)
        if command[:3] == ["aws", "configure", "export-credentials"]:
            return subprocess.CompletedProcess(
                command,
                0,
                json.dumps(
                    {
                        "AccessKeyId": "root-key",
                        "SecretAccessKey": "root-secret",
                        "SessionToken": "root-token",
                        "Expiration": "2026-08-01T13:30:00Z",
                    }
                ),
                "",
            )
        if command[:3] == ["aws", "sts", "assume-role"]:
            assert environment["AWS_ACCESS_KEY_ID"] == "root-key"
            return subprocess.CompletedProcess(
                command,
                0,
                json.dumps(
                    {
                        "Credentials": {
                            "AccessKeyId": "target-key",
                            "SecretAccessKey": "target-secret",
                            "SessionToken": "target-token",
                            "Expiration": "2026-08-01T13:00:00+00:00",
                        }
                    }
                ),
                "",
            )
        if command[:3] == ["aws", "sts", "get-caller-identity"]:
            assert environment["AWS_ACCESS_KEY_ID"] == "target-key"
            return subprocess.CompletedProcess(
                command, 0, json.dumps({"Account": "222222222222"}), ""
            )
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setenv("SHELL", "/bin/test-shell")
    chain = (
        Account(
            "hub",
            "111111111111",
            "standard-access",
            "eu-west-1",
            sso_start_url="https://example.awsapps.com/start",
            sso_region="eu-west-1",
        ),
        Account(
            "target",
            "222222222222",
            "standard-access",
            "eu-central-1",
            source="hub",
        ),
    )

    result = AwsCliLoginGateway(
        runner, clock=lambda: datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)
    ).open_shell(chain)

    assert result == 0
    assume_command = calls[2][0]
    assert "arn:aws:iam::222222222222:role/standard-access" in assume_command
    shell_command, shell_environment = calls[4]
    assert shell_command == ["/bin/test-shell"]
    assert shell_environment["AWS_ACCESS_KEY_ID"] == "target-key"
    assert shell_environment["AWS_REGION"] == "eu-central-1"
    assert shell_environment["AWSI_ACCOUNT"] == "target"
    assert shell_environment["AWSI_ROLE"] == "standard-access"
    assert shell_environment["PS1"].startswith("[standard-access@target] ")


def test_assume_role_passes_configured_session_duration(monkeypatch) -> None:
    calls: list[list[str]] = []

    def runner(command, **options):
        calls.append(command)
        if command[:3] == ["aws", "sso", "login"]:
            return subprocess.CompletedProcess(command, 0)
        if command[:3] == ["aws", "configure", "export-credentials"]:
            return subprocess.CompletedProcess(
                command,
                0,
                json.dumps(
                    {
                        "AccessKeyId": "root-key",
                        "SecretAccessKey": "root-secret",
                        "SessionToken": "root-token",
                        "Expiration": "2026-08-01T13:30:00Z",
                    }
                ),
                "",
            )
        if command[:3] == ["aws", "sts", "assume-role"]:
            return subprocess.CompletedProcess(
                command,
                0,
                json.dumps(
                    {
                        "Credentials": {
                            "AccessKeyId": "target-key",
                            "SecretAccessKey": "target-secret",
                            "SessionToken": "target-token",
                            "Expiration": "2026-08-01T20:00:00+00:00",
                        }
                    }
                ),
                "",
            )
        if command[:3] == ["aws", "sts", "get-caller-identity"]:
            return subprocess.CompletedProcess(
                command, 0, json.dumps({"Account": "222222222222"}), ""
            )
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setenv("SHELL", "/bin/test-shell")
    chain = (
        Account(
            "hub",
            "111111111111",
            "standard-access",
            "eu-west-1",
            sso_start_url="https://example.awsapps.com/start",
            sso_region="eu-west-1",
        ),
        Account(
            "target",
            "222222222222",
            "standard-access",
            "eu-central-1",
            source="hub",
            session_duration_hours=8,
        ),
    )

    result = AwsCliLoginGateway(
        runner, clock=lambda: datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)
    ).open_shell(chain)

    assert result == 0
    assume_command = next(
        command for command in calls if command[:3] == ["aws", "sts", "assume-role"]
    )
    assert "--duration-seconds" in assume_command
    assert assume_command[assume_command.index("--duration-seconds") + 1] == "28800"


def test_reports_session_expiration(monkeypatch, capsys) -> None:
    def runner(command, **options):
        if command[:3] == ["aws", "sso", "login"]:
            return subprocess.CompletedProcess(command, 0)
        if command[:3] == ["aws", "configure", "export-credentials"]:
            return subprocess.CompletedProcess(
                command,
                0,
                json.dumps(
                    {
                        "AccessKeyId": "key",
                        "SecretAccessKey": "secret",
                        "SessionToken": "token",
                        "Expiration": "2026-08-01T13:00:00Z",
                    }
                ),
                "",
            )
        if command[:3] == ["aws", "sts", "get-caller-identity"]:
            return subprocess.CompletedProcess(
                command, 0, json.dumps({"Account": "111111111111"}), ""
            )
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setenv("SHELL", "/bin/test-shell")
    account = Account(
        "hub",
        "111111111111",
        "standard-access",
        "eu-west-1",
        sso_start_url="https://example.awsapps.com/start",
        sso_region="eu-west-1",
    )

    result = AwsCliLoginGateway(
        runner, clock=lambda: datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)
    ).open_shell((account,))

    assert result == 0
    error = capsys.readouterr().err
    assert "\nSession valid until" in error
    assert "(1h 0m remaining)" in error
    assert "remaining).\nExit the shell" in error


def test_elevated_login_explains_when_team_role_cannot_be_retrieved() -> None:
    def runner(command, **options):
        if command[:3] == ["aws", "sso", "login"]:
            return subprocess.CompletedProcess(command, 0)
        return subprocess.CompletedProcess(command, 1, "", "Role not found")

    account = Account(
        "development",
        "111111111111",
        "elevated-access",
        "eu-west-1",
        sso_start_url="https://example.awsapps.com/start",
        sso_region="eu-west-1",
    )

    with pytest.raises(LoginError, match="make sure TEAM access is active") as error:
        AwsCliLoginGateway(runner).open_shell((account,), elevated=True)

    assert "AWS CLI" not in str(error.value)
    assert "ForbiddenException" not in str(error.value)


def test_prefixes_a_zsh_prompt_with_the_role_and_account_name() -> None:
    environment = {"PROMPT": "custom prompt % "}

    AwsCliLoginGateway._set_account_prompt(
        environment, "/bin/zsh", "development", "standard-access"
    )

    assert environment["PROMPT"] == "[standard-access@development] custom prompt % "


def test_colors_only_the_zsh_account_label() -> None:
    environment = {"PROMPT": "custom prompt % "}

    AwsCliLoginGateway._set_account_prompt(
        environment, "/bin/zsh", "development", "standard-access", "#12ABEF"
    )

    assert environment["PROMPT"] == (
        "%F{#12ABEF}[standard-access@development] %fcustom prompt % "
    )


def test_zsh_wrapper_applies_prompt_after_normal_zshrc(tmp_path: Path) -> None:
    original = tmp_path / "original"
    wrapper = tmp_path / "wrapper"
    original.mkdir()
    wrapper.mkdir()
    (original / ".zshrc").write_text("PROMPT='theme prompt ' \n", encoding="utf-8")

    AwsCliLoginGateway._write_zsh_startup_wrapper(wrapper, original)

    rc = (wrapper / ".zshrc").read_text(encoding="utf-8")
    assert f"source {original / '.zshrc'}" in rc
    assert rc.index("source ") < rc.index(
        '_awsi_label="[${AWSI_ROLE}@${AWSI_ACCOUNT}] "'
    )


def test_zsh_process_keeps_account_prefix_when_zshrc_replaces_prompt(
    tmp_path: Path,
) -> None:
    zsh = shutil.which("zsh")
    if zsh is None:
        pytest.skip("zsh is not installed")

    (tmp_path / ".zshrc").write_text("PROMPT='theme prompt ' \n", encoding="utf-8")

    def runner(command, **options):
        return subprocess.run(
            [*command, "-i", "-c", 'print -r -- "$PROMPT"'],
            env=options["env"],
            capture_output=True,
            check=False,
            text=True,
        )

    result = AwsCliLoginGateway(runner)._open_shell_process(
        zsh,
        {
            "HOME": str(tmp_path),
            "AWSI_ACCOUNT": "development",
            "AWSI_ROLE": "standard-access",
            "PATH": "/usr/bin:/bin",
        },
    )

    assert result.stdout.strip() == "[standard-access@development] theme prompt"
