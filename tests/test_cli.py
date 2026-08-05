"""Tests for the command-line entry point."""

from collections.abc import Iterator
from contextlib import contextmanager
from ipaddress import IPv4Network
from pathlib import Path

import pytest

from aws_intel.security_groups.model import (
    SecurityGroup,
    SecurityGroupConnection,
)
from aws_intel.cli import main
from aws_intel.forwarding.config import ForwardConfig
from aws_intel.forwarding.model import ActiveForward, BastionHost, PortMapping
from aws_intel.forwarding.registry import ForwardRegistryError


@pytest.fixture(autouse=True)
def disable_pypi_version_check(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep CLI tests deterministic and independent of the network."""
    monkeypatch.setattr(
        "aws_intel.cli.notify_if_update_available", lambda _version: None
    )


def test_each_invocation_checks_for_an_update(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checked_versions: list[str] = []
    monkeypatch.setattr(
        "aws_intel.cli.notify_if_update_available", checked_versions.append
    )

    assert main(["help"]) == 0

    assert len(checked_versions) == 1


def test_help_exits_successfully(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["--help"])

    assert exit_info.value.code == 0
    assert "Retrieve useful information from AWS." in capsys.readouterr().out


def test_help_utility_lists_all_utilities(
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = main(["help"])

    assert result == 0
    output = capsys.readouterr().out
    normalized_output = " ".join(output.split())
    assert "security-group-tree Show attached resources" in normalized_output
    assert "Show attached resources, recursively connected" in normalized_output
    assert "help" in normalized_output
    assert "Show all utilities or detailed help" in normalized_output
    assert "login" in normalized_output
    assert "shell-init" not in normalized_output


def test_help_utility_shows_detailed_utility_help(
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = main(["help", "security-group-tree"])

    assert result == 0
    output = capsys.readouterr().out
    normalized_output = " ".join(output.split())
    assert output.startswith("usage: awsi security-group-tree [-h] [--depth DEPTH]")
    assert "One or more starting security group IDs" in normalized_output
    assert "Maximum connection depth to expand" in normalized_output
    assert "Examples:" in output
    assert "awsi security-group-tree sg-0123456789abcdef0 --depth 2" in output
    assert "awsi security-group-tree sg-0123456789abcdef0 --inbound" in output
    assert "awsi security-group-tree sg-0123456789abcdef0 --filter database" in output


def test_help_utility_rejects_unknown_utility(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["help", "unknown"])

    assert exit_info.value.code == 2
    assert "invalid choice: 'unknown'" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("arguments", "example"),
    [
        (["forward", "--help"], "awsi forward start apigateway-dev"),
        (["forward", "start", "--help"], "awsi forward start apigateway-dev"),
        (["forward", "save", "--help"], "awsi forward save apigateway-dev"),
        (["forward", "active", "--help"], "awsi forward active"),
        (["forward", "stop", "--help"], "awsi forward stop apigateway-dev"),
        (["forward", "restart", "--help"], "awsi forward restart apigateway-dev"),
        (["forward", "hosts", "--help"], "awsi forward hosts"),
        (["forward", "list", "--help"], "awsi forward list"),
    ],
)
def test_forward_help_includes_examples(
    arguments: list[str],
    example: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(arguments)

    assert exit_info.value.code == 0
    output = capsys.readouterr().out
    assert "Example" in output
    assert example in output


def test_version_exits_successfully(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["--version"])

    assert exit_info.value.code == 0
    assert capsys.readouterr().out.startswith("awsi ")


def test_init_writes_boilerplate_configuration_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)

    result = main(["init"])

    accounts_path = tmp_path / ".awsi" / "accounts.yaml"
    forwards_path = tmp_path / ".awsi" / "forwards.yaml"
    assert result == 0
    assert accounts_path.exists()
    assert forwards_path.exists()
    output = capsys.readouterr().out
    assert f"Wrote boilerplate configuration to {accounts_path}." in output
    assert f"Wrote boilerplate configuration to {forwards_path}." in output


def test_init_skips_existing_files_without_force(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    accounts_path = tmp_path / ".awsi" / "accounts.yaml"
    accounts_path.parent.mkdir(parents=True)
    accounts_path.write_text("version: 1\naccounts: {}\n", encoding="utf-8")

    result = main(["init"])

    assert result == 0
    output = capsys.readouterr().out
    assert f"Skipped {accounts_path} (already exists)" in output
    assert accounts_path.read_text(encoding="utf-8") == "version: 1\naccounts: {}\n"


def test_init_force_overwrites_existing_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    accounts_path = tmp_path / ".awsi" / "accounts.yaml"
    accounts_path.parent.mkdir(parents=True)
    accounts_path.write_text("version: 1\naccounts: {}\n", encoding="utf-8")

    result = main(["init", "--force"])

    assert result == 0
    assert accounts_path.read_text(encoding="utf-8") != "version: 1\naccounts: {}\n"


def test_login_resolves_chain_and_opens_shell(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected_chain = (object(),)

    class FakeAccountConfig:
        def resolve_chain(self, name: str) -> tuple[object, ...]:
            assert name == "development"
            return expected_chain

    class FakeLoginGateway:
        def open_shell(self, chain: tuple[object, ...], elevated: bool = False) -> int:
            assert chain is expected_chain
            assert elevated is False
            return 0

    monkeypatch.setattr("aws_intel.cli.AccountConfig", FakeAccountConfig)
    monkeypatch.setattr("aws_intel.cli.AwsCliLoginGateway", FakeLoginGateway)

    assert main(["login", "development"]) == 0


def test_login_without_account_selects_interactively(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected_chain = (object(),)

    class FakeAccountConfig:
        def list_names(self) -> tuple[str, ...]:
            return ("development", "production")

        def resolve_chain(self, name: str) -> tuple[object, ...]:
            assert name == "production"
            return expected_chain

        def elevated_role_name(self, name: str) -> None:
            assert name == "production"
            return None

    class FakeLoginGateway:
        def open_shell(self, chain: tuple[object, ...], elevated: bool = False) -> int:
            assert chain is expected_chain
            assert elevated is False
            return 0

    monkeypatch.setattr("aws_intel.cli.AccountConfig", FakeAccountConfig)
    monkeypatch.setattr("aws_intel.cli.AwsCliLoginGateway", FakeLoginGateway)
    monkeypatch.setattr(
        "aws_intel.cli.select_account",
        lambda names: names[1],
    )

    assert main(["login"]) == 0


def test_login_without_account_can_select_team_elevated_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected_chain = (object(),)

    class FakeAccountConfig:
        def list_names(self) -> tuple[str, ...]:
            return ("development",)

        def elevated_role_name(self, name: str) -> str:
            assert name == "development"
            return "elevated-access"

        def resolve_elevated(self, name: str) -> tuple[object, ...]:
            assert name == "development"
            return expected_chain

        def resolve_chain(self, name: str) -> tuple[object, ...]:
            assert name == "development"

            class StandardAccount:
                role_name = "standard-access"

            return (StandardAccount(),)

    class FakeLoginGateway:
        def open_shell(self, chain: tuple[object, ...], elevated: bool = False) -> int:
            assert chain is expected_chain
            assert elevated is True
            return 0

    monkeypatch.setattr("aws_intel.cli.AccountConfig", FakeAccountConfig)
    monkeypatch.setattr("aws_intel.cli.AwsCliLoginGateway", FakeLoginGateway)
    monkeypatch.setattr(
        "aws_intel.cli.select_account",
        lambda names: names[0],
    )
    monkeypatch.setattr(
        "aws_intel.cli.select_elevated_access",
        lambda standard_role, elevated_role: (
            standard_role == "standard-access" and elevated_role == "elevated-access"
        ),
    )

    assert main(["login"]) == 0


def test_login_list_prints_configured_accounts_without_logging_in(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    class FakeAccountConfig:
        def list_names(self) -> tuple[str, ...]:
            return ("development", "production")

    class UnexpectedLoginGateway:
        def __init__(self) -> None:
            pytest.fail("login gateway should not be created when listing accounts")

    monkeypatch.setattr("aws_intel.cli.AccountConfig", FakeAccountConfig)
    monkeypatch.setattr("aws_intel.cli.AwsCliLoginGateway", UnexpectedLoginGateway)

    assert main(["login", "--list"]) == 0
    assert capsys.readouterr().out == "ACCOUNT\ndevelopment\nproduction\n"


def test_login_list_rejects_an_account(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["login", "development", "--list"])

    assert exit_info.value.code == 2
    assert "not allowed with argument account" in capsys.readouterr().err


def test_elevated_login_resolves_team_role_and_opens_shell(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected_chain = (object(),)

    class FakeAccountConfig:
        def resolve_elevated(self, name: str) -> tuple[object, ...]:
            assert name == "development"
            return expected_chain

    class FakeLoginGateway:
        def open_shell(self, chain: tuple[object, ...], elevated: bool = False) -> int:
            assert chain is expected_chain
            assert elevated is True
            return 0

    monkeypatch.setattr("aws_intel.cli.AccountConfig", FakeAccountConfig)
    monkeypatch.setattr("aws_intel.cli.AwsCliLoginGateway", FakeLoginGateway)

    assert main(["login", "development", "--elevated"]) == 0


def test_console_opens_browser_for_current_environment(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    opened_environments: list[object] = []

    class FakeConsoleGateway:
        def open(self, environment: object) -> None:
            opened_environments.append(environment)

    monkeypatch.setattr("aws_intel.cli.AwsConsoleGateway", FakeConsoleGateway)

    assert main(["console"]) == 0
    assert len(opened_environments) == 1
    assert "Opened the AWS Management Console" in capsys.readouterr().out


def test_shell_init_prints_zsh_integration(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["shell-init", "zsh"]) == 0
    assert "AWSI_ACCOUNT" in capsys.readouterr().out


def test_utility_is_required(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main([])

    assert exit_info.value.code == 2
    assert "the following arguments are required: <utility>" in (
        capsys.readouterr().err
    )


class FakeGateway:
    def get(self, group_id: str) -> SecurityGroup:
        return SecurityGroup(
            group_id=group_id,
            name="web",
            inbound_connections=(
                SecurityGroupConnection("10.0.0.0/8", "tcp", 443, 443),
            ),
            outbound_connections=(SecurityGroupConnection("0.0.0.0/0", "-1"),),
        )


class FakeResourceGateway:
    def list_for_group(self, group_id: str) -> tuple[object, ...]:
        return ()

    def list_for_private_network(
        self, vpc_id: str, network: IPv4Network
    ) -> tuple[object, ...]:
        return ()


def test_security_group_tree_shows_both_directions_by_default(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr("aws_intel.cli.AwsCliSecurityGroupGateway", FakeGateway)
    monkeypatch.setattr(
        "aws_intel.cli.AwsCliSecurityGroupResourceGateway",
        FakeResourceGateway,
    )

    result = main(["security-group-tree", "sg-0123456789abcdef0"])

    assert result == 0
    assert capsys.readouterr().out == (
        "INBOUND\n"
        "web (sg-0123456789abcdef0)\n"
        "└── Sources\n"
        "    └── tcp 443 from 10.0.0.0/8\n\n"
        "OUTBOUND\n"
        "web (sg-0123456789abcdef0)\n"
        "└── Targets\n"
        "    └── all traffic to 0.0.0.0/0\n"
    )


def test_security_group_tree_can_show_only_inbound(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr("aws_intel.cli.AwsCliSecurityGroupGateway", FakeGateway)
    monkeypatch.setattr(
        "aws_intel.cli.AwsCliSecurityGroupResourceGateway",
        FakeResourceGateway,
    )

    result = main(["security-group-tree", "sg-0123456789abcdef0", "--inbound"])

    assert result == 0
    output = capsys.readouterr().out
    assert output.startswith("INBOUND\n")
    assert "OUTBOUND" not in output


def test_security_group_tree_filters_case_insensitively(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr("aws_intel.cli.AwsCliSecurityGroupGateway", FakeGateway)
    monkeypatch.setattr(
        "aws_intel.cli.AwsCliSecurityGroupResourceGateway",
        FakeResourceGateway,
    )

    result = main(
        [
            "security-group-tree",
            "sg-0123456789abcdef0",
            "--inbound",
            "--filter=TCP 443",
        ]
    )

    assert result == 0
    assert capsys.readouterr().out == (
        "INBOUND\n"
        "web (sg-0123456789abcdef0)\n"
        "└── Sources\n"
        "    └── tcp 443 from 10.0.0.0/8\n"
    )


@pytest.mark.parametrize(
    "filter_text",
    ["WEB", "SG-0123456789ABCDEF0"],
)
def test_security_group_tree_filter_matches_name_or_id_in_label(
    filter_text: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr("aws_intel.cli.AwsCliSecurityGroupGateway", FakeGateway)
    monkeypatch.setattr(
        "aws_intel.cli.AwsCliSecurityGroupResourceGateway",
        FakeResourceGateway,
    )

    result = main(
        [
            "security-group-tree",
            "sg-0123456789abcdef0",
            "--inbound",
            "--filter",
            filter_text,
        ]
    )

    assert result == 0
    assert capsys.readouterr().out == (
        "INBOUND\n"
        "web (sg-0123456789abcdef0)\n"
        "└── Sources\n"
        "    └── tcp 443 from 10.0.0.0/8\n"
    )


def test_security_group_tree_filter_with_no_matches_shows_heading(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr("aws_intel.cli.AwsCliSecurityGroupGateway", FakeGateway)
    monkeypatch.setattr(
        "aws_intel.cli.AwsCliSecurityGroupResourceGateway",
        FakeResourceGateway,
    )

    result = main(
        [
            "security-group-tree",
            "sg-0123456789abcdef0",
            "--inbound",
            "--filter",
            "missing",
        ]
    )

    assert result == 0
    assert capsys.readouterr().out == "INBOUND\n"


def test_security_group_tree_combines_multiple_starting_groups(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr("aws_intel.cli.AwsCliSecurityGroupGateway", FakeGateway)
    monkeypatch.setattr(
        "aws_intel.cli.AwsCliSecurityGroupResourceGateway",
        FakeResourceGateway,
    )

    result = main(
        [
            "security-group-tree",
            "sg-0123456789abcdef0",
            "sg-11111111",
            "--inbound",
        ]
    )

    assert result == 0
    assert capsys.readouterr().out == (
        "INBOUND\n"
        "├── web (sg-0123456789abcdef0)\n"
        "│   └── Sources\n"
        "│       └── tcp 443 from 10.0.0.0/8\n"
        "└── web (sg-11111111)\n"
        "    └── Sources\n"
        "        └── tcp 443 from 10.0.0.0/8\n"
    )


def test_direction_flags_are_mutually_exclusive(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(
            [
                "security-group-tree",
                "sg-0123456789abcdef0",
                "--inbound",
                "--outbound",
            ]
        )

    assert exit_info.value.code == 2
    assert "not allowed with argument" in capsys.readouterr().err


@pytest.mark.parametrize("depth", ["0", "4", "not-an-integer"])
def test_security_group_tree_rejects_invalid_depth(
    depth: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(
            [
                "security-group-tree",
                "sg-0123456789abcdef0",
                "--depth",
                depth,
            ]
        )

    assert exit_info.value.code == 2
    assert "--depth" in capsys.readouterr().err


def test_security_group_id_is_validated_before_aws_request(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["security-group-tree", "not-a-security-group"])

    assert exit_info.value.code == 2
    assert "must be an AWS security group ID" in capsys.readouterr().err


def test_each_security_group_id_is_validated_before_aws_request(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(
            [
                "security-group-tree",
                "sg-0123456789abcdef0",
                "not-a-security-group",
            ]
        )

    assert exit_info.value.code == 2
    assert "'not-a-security-group' must be" in capsys.readouterr().err


class FakeForwardingGateway:
    starts: list[tuple[str, str, PortMapping]] = []

    def list_hosts(self) -> tuple[BastionHost, ...]:
        return (
            BastionHost("i-0123456789abcdef0", "public-bastion"),
            BastionHost("i-11111111"),
        )

    def start(self, instance_id: str, host: str, port_mapping: PortMapping) -> int:
        self.starts.append((instance_id, host, port_mapping))
        return 4321

    def resolve_instance_name(self, name: str) -> str:
        assert name == "public-bastion"
        return "i-0123456789abcdef0"


class FakeForwardRegistry:
    added: list[object] = []
    active: tuple[object, ...] = ()

    def add(self, forward: object) -> None:
        self.added.append(forward)

    def list_active(self) -> tuple[object, ...]:
        return self.active

    def ensure_startable(
        self, instance_id: str, host: str, port_mapping: PortMapping
    ) -> None:
        for forward in self.active:
            if isinstance(forward, ActiveForward) and (
                forward.instance_id == instance_id
                and forward.host == host
                and forward.port_mapping == port_mapping
            ):
                raise ForwardRegistryError(
                    f"this forward is already running with PID {forward.pid}"
                )

    def terminate(self, reference: str) -> ActiveForward:
        forward = self.resolve(reference)
        type(self).active = tuple(item for item in self.active if item != forward)
        return forward

    def resolve(self, reference: str) -> ActiveForward:
        for forward in self.active:
            if isinstance(forward, ActiveForward) and (
                forward.name == reference or str(forward.pid) == reference
            ):
                return forward
        raise AssertionError(f"unexpected forward reference: {reference}")


@pytest.fixture(autouse=True)
def fake_forward_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeForwardRegistry.added = []
    FakeForwardRegistry.active = ()
    monkeypatch.setattr("aws_intel.cli.ForwardRegistry", FakeForwardRegistry)


def test_forward_starts_requested_port_mapping(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    FakeForwardingGateway.starts = []
    monkeypatch.setattr("aws_intel.cli.AwsCliForwardingGateway", FakeForwardingGateway)

    result = main(
        [
            "forward",
            "start",
            "primary-database",
            "--instance-id=i-0123456789abcdef0",
            "--host=db.internal",
            "--port=15432:5432",
        ]
    )

    assert result == 0
    assert FakeForwardingGateway.starts == [
        (
            "i-0123456789abcdef0",
            "db.internal",
            PortMapping(local_port=15432, remote_port=5432),
        )
    ]
    assert FakeForwardRegistry.added == [
        ActiveForward(
            4321,
            "i-0123456789abcdef0",
            "db.internal",
            PortMapping(local_port=15432, remote_port=5432),
            "primary-database",
        )
    ]
    assert capsys.readouterr().out == (
        "Forward 'primary-database' started in the background with PID 4321.\n"
    )


def test_forward_rejects_an_identical_active_forward(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    FakeForwardingGateway.starts = []
    FakeForwardRegistry.active = (
        ActiveForward(
            9876,
            "i-0123456789abcdef0",
            "db.internal",
            PortMapping(15432, 5432),
            "primary-database",
        ),
    )
    monkeypatch.setattr("aws_intel.cli.AwsCliForwardingGateway", FakeForwardingGateway)

    result = main(
        [
            "forward",
            "start",
            "primary-database",
            "--instance-id=i-0123456789abcdef0",
            "--host=db.internal",
            "--port=15432:5432",
        ]
    )

    assert result == 1
    assert FakeForwardingGateway.starts == []
    assert "already running with PID 9876" in capsys.readouterr().err


def test_forward_save_writes_configuration_without_starting(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / ".awsi" / "forwards.yaml"
    FakeForwardingGateway.starts = []
    monkeypatch.setattr("aws_intel.cli.AwsCliForwardingGateway", FakeForwardingGateway)
    monkeypatch.setattr("aws_intel.cli.ForwardConfig", lambda: ForwardConfig(path))

    result = main(
        [
            "forward",
            "save",
            "apigateway-dev",
            "--instance-name=solo-connect-bastion-dev",
            "--host=api.internal",
            "--port=9072:9072",
        ]
    )

    assert result == 0
    assert FakeForwardingGateway.starts == []
    assert "instance-name: solo-connect-bastion-dev" in path.read_text(encoding="utf-8")
    assert capsys.readouterr().out == (f"Forward 'apigateway-dev' saved to {path}.\n")


def test_forward_starts_named_configuration_from_current_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_directory = tmp_path / ".awsi"
    config_directory.mkdir()
    (config_directory / "forwards.yaml").write_text(
        "forwards:\n"
        "  apigateway:\n"
        "    instance-id: i-0123456789abcdef0\n"
        "    host: api.internal\n"
        "    port: 9072:443\n",
        encoding="utf-8",
    )
    FakeForwardingGateway.starts = []
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("aws_intel.cli.AwsCliForwardingGateway", FakeForwardingGateway)

    result = main(["forward", "start", "apigateway"])

    assert result == 0
    assert FakeForwardingGateway.starts == [
        (
            "i-0123456789abcdef0",
            "api.internal",
            PortMapping(9072, 443),
        )
    ]
    assert FakeForwardRegistry.added == [
        ActiveForward(
            4321,
            "i-0123456789abcdef0",
            "api.internal",
            PortMapping(9072, 443),
            "apigateway",
        )
    ]
    assert capsys.readouterr().out == (
        "Forward 'apigateway' started in the background with PID 4321.\n"
    )


def test_forward_start_without_arguments_selects_and_starts_multiple_saved_forwards(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_directory = tmp_path / ".awsi"
    config_directory.mkdir()
    (config_directory / "forwards.yaml").write_text(
        "forwards:\n"
        "  apigateway:\n"
        "    instance-id: i-0123456789abcdef0\n"
        "    host: api.internal\n"
        "    port: 9072:443\n"
        "  database:\n"
        "    instance-id: i-11111111\n"
        "    host: db.internal\n"
        "    port: 15432:5432\n",
        encoding="utf-8",
    )
    FakeForwardingGateway.starts = []
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("aws_intel.cli.AwsCliForwardingGateway", FakeForwardingGateway)
    selected: list[tuple[tuple[str, ...], tuple[str, ...]]] = []

    def select(
        names: tuple[str, ...], *, active_names: tuple[str, ...]
    ) -> tuple[str, ...]:
        selected.append((names, active_names))
        return names

    monkeypatch.setattr("aws_intel.cli.select_forwards", select)

    result = main(["forward", "start"])

    assert result == 0
    assert FakeForwardingGateway.starts == [
        ("i-0123456789abcdef0", "api.internal", PortMapping(9072, 443)),
        ("i-11111111", "db.internal", PortMapping(15432, 5432)),
    ]
    assert selected == [(("apigateway", "database"), ())]
    assert capsys.readouterr().out == (
        "Forward 'apigateway' started in the background with PID 4321.\n"
        "Forward 'database' started in the background with PID 4321.\n"
    )


def test_forward_start_without_arguments_selects_and_starts_saved_forward(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_directory = tmp_path / ".awsi"
    config_directory.mkdir()
    (config_directory / "forwards.yaml").write_text(
        "forwards:\n"
        "  apigateway:\n"
        "    instance-id: i-0123456789abcdef0\n"
        "    host: api.internal\n"
        "    port: 9072:443\n",
        encoding="utf-8",
    )
    FakeForwardingGateway.starts = []
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("aws_intel.cli.AwsCliForwardingGateway", FakeForwardingGateway)
    monkeypatch.setattr(
        "aws_intel.cli.select_forwards",
        lambda names, *, active_names: (names[0],),
    )

    result = main(["forward", "start"])

    assert result == 0
    assert FakeForwardingGateway.starts == [
        (
            "i-0123456789abcdef0",
            "api.internal",
            PortMapping(9072, 443),
        )
    ]
    assert capsys.readouterr().out == (
        "Forward 'apigateway' started in the background with PID 4321.\n"
    )


def test_forward_start_disables_running_saved_forwards_in_selection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_directory = tmp_path / ".awsi"
    config_directory.mkdir()
    (config_directory / "forwards.yaml").write_text(
        "forwards:\n"
        "  apigateway:\n"
        "    instance-id: i-0123456789abcdef0\n"
        "    host: api.internal\n"
        "    port: 9072:443\n"
        "  database:\n"
        "    instance-id: i-11111111\n"
        "    host: db.internal\n"
        "    port: 15432:5432\n",
        encoding="utf-8",
    )
    FakeForwardRegistry.active = (
        ActiveForward(
            9876,
            "i-0123456789abcdef0",
            "api.internal",
            PortMapping(9072, 443),
            "apigateway",
        ),
    )
    received_active_names: list[tuple[str, ...]] = []

    def select(
        names: tuple[str, ...], *, active_names: tuple[str, ...]
    ) -> tuple[str, ...]:
        assert names == ("apigateway", "database")
        received_active_names.append(active_names)
        return ("database",)

    FakeForwardingGateway.starts = []
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("aws_intel.cli.select_forwards", select)
    monkeypatch.setattr("aws_intel.cli.AwsCliForwardingGateway", FakeForwardingGateway)

    assert main(["forward", "start"]) == 0
    assert received_active_names == [("apigateway",)]
    assert FakeForwardingGateway.starts == [
        ("i-11111111", "db.internal", PortMapping(15432, 5432))
    ]


def test_forward_start_without_arguments_reports_no_saved_forwards(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)

    assert main(["forward", "start"]) == 1
    assert "no forwards are configured" in capsys.readouterr().err


def test_forward_stop_without_arguments_selects_and_stops_active_forward(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    FakeForwardRegistry.active = (
        ActiveForward(
            9876,
            "i-0123456789abcdef0",
            "db.internal",
            PortMapping(15432, 5432),
            "primary-database",
        ),
    )
    monkeypatch.setattr(
        "aws_intel.cli.select_active_forwards", lambda forwards: (forwards[0],)
    )

    result = main(["forward", "stop"])

    assert result == 0
    assert FakeForwardRegistry.active == ()
    assert (
        "Forward 'primary-database' with PID 9876 was terminated."
        in capsys.readouterr().out
    )


def test_forward_stop_without_arguments_selects_and_stops_multiple_active_forwards(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    FakeForwardRegistry.active = (
        ActiveForward(
            9876,
            "i-0123456789abcdef0",
            "db.internal",
            PortMapping(15432, 5432),
            "primary-database",
        ),
        ActiveForward(202, "i-22222222", "api.internal", PortMapping(3, 4)),
    )
    monkeypatch.setattr(
        "aws_intel.cli.select_active_forwards", lambda forwards: forwards
    )

    result = main(["forward", "stop"])

    assert result == 0
    assert FakeForwardRegistry.active == ()
    assert capsys.readouterr().out == (
        "Forward 'primary-database' with PID 9876 was terminated.\n"
        "Forward with PID 202 was terminated.\n"
    )


def test_forward_stop_without_arguments_reports_no_active_forwards(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["forward", "stop"]) == 1
    assert "no active forwards are configured" in capsys.readouterr().err


def test_forward_reports_unknown_saved_configuration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)

    assert main(["forward", "missing"]) == 1
    assert "no forward named 'missing'" in capsys.readouterr().err


@pytest.mark.parametrize("action", ["list", "configs"])
def test_forward_list_lists_saved_definitions(
    action: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_directory = tmp_path / ".awsi"
    config_directory.mkdir()
    (config_directory / "forwards.yaml").write_text(
        "forwards:\n"
        "  apigateway:\n"
        "    instance-name: bastion\n"
        "    host: api.internal\n"
        "    port: 9072:443\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    assert main(["forward", action]) == 0
    assert capsys.readouterr().out == (
        "NAME\tINSTANCE\tHOST\tPORT\napigateway\tbastion\tapi.internal\t9072:443\n"
    )


def test_forward_lists_active_background_sessions(
    capsys: pytest.CaptureFixture[str],
) -> None:
    FakeForwardRegistry.active = (
        ActiveForward(
            4321,
            "i-0123456789abcdef0",
            "db.internal",
            PortMapping(15432, 5432),
            "primary-database",
        ),
    )

    result = main(["forward", "active"])

    assert result == 0
    assert capsys.readouterr().out == (
        "PID\tNAME\tINSTANCE_ID\tHOST\tPORT\n"
        "4321\tprimary-database\ti-0123456789abcdef0\tdb.internal\t"
        "15432:5432\n"
    )


def test_legacy_forward_list_flag_prints_active_column_names_when_empty(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["forward", "--list"]) == 0
    assert capsys.readouterr().out == "PID\tNAME\tINSTANCE_ID\tHOST\tPORT\n"


def test_forward_kills_background_session_by_name(
    capsys: pytest.CaptureFixture[str],
) -> None:
    FakeForwardRegistry.active = (
        ActiveForward(
            4321,
            "i-0123456789abcdef0",
            "db.internal",
            PortMapping(15432, 5432),
            "primary-database",
        ),
    )

    result = main(["forward", "stop", "primary-database"])

    assert result == 0
    assert capsys.readouterr().out == (
        "Forward 'primary-database' with PID 4321 was terminated.\n"
    )


def test_forward_stop_all_terminates_every_active_session(
    capsys: pytest.CaptureFixture[str],
) -> None:
    FakeForwardRegistry.active = (
        ActiveForward(101, "i-11111111", "db.internal", PortMapping(1, 2), "db"),
        ActiveForward(202, "i-22222222", "api.internal", PortMapping(3, 4)),
    )

    assert main(["forward", "stop", "--all"]) == 0
    assert FakeForwardRegistry.active == ()
    assert capsys.readouterr().out == (
        "Forward 'db' with PID 101 was terminated.\n"
        "Forward with PID 202 was terminated.\n"
    )


def test_forward_restart_relaunches_active_session(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    original = ActiveForward(
        101, "i-11111111", "db.internal", PortMapping(15432, 5432), "database"
    )
    FakeForwardRegistry.active = (original,)
    FakeForwardingGateway.starts = []
    monkeypatch.setattr("aws_intel.cli.AwsCliForwardingGateway", FakeForwardingGateway)

    assert main(["forward", "restart", "database"]) == 0
    assert FakeForwardingGateway.starts == [
        ("i-11111111", "db.internal", PortMapping(15432, 5432))
    ]
    assert FakeForwardRegistry.added == [
        ActiveForward(
            4321,
            "i-11111111",
            "db.internal",
            PortMapping(15432, 5432),
            "database",
        )
    ]
    assert capsys.readouterr().out == (
        "Forward 'database' restarted in the background with PID 4321.\n"
    )


def test_forward_restart_all_relaunches_every_active_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    FakeForwardRegistry.active = (
        ActiveForward(101, "i-11111111", "db.internal", PortMapping(1, 2), "db"),
        ActiveForward(202, "i-22222222", "api.internal", PortMapping(3, 4)),
    )
    FakeForwardingGateway.starts = []
    monkeypatch.setattr("aws_intel.cli.AwsCliForwardingGateway", FakeForwardingGateway)

    assert main(["forward", "restart", "--all"]) == 0
    assert FakeForwardingGateway.starts == [
        ("i-11111111", "db.internal", PortMapping(1, 2)),
        ("i-22222222", "api.internal", PortMapping(3, 4)),
    ]


def test_forward_resolves_name_with_loading_indicator_before_starting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    class TrackingGateway(FakeForwardingGateway):
        def resolve_instance_name(self, name: str) -> str:
            events.append(f"resolve:{name}")
            return "i-0123456789abcdef0"

        def start(self, instance_id: str, host: str, port_mapping: PortMapping) -> int:
            events.append(f"start:{instance_id}")
            return 0

    @contextmanager
    def tracking_spinner(message: str) -> Iterator[None]:
        events.append(f"spinner:{message}")
        yield
        events.append("spinner:stop")

    monkeypatch.setattr("aws_intel.cli.AwsCliForwardingGateway", TrackingGateway)
    monkeypatch.setattr("aws_intel.cli.spinner", tracking_spinner)

    result = main(
        [
            "forward",
            "start",
            "--instance-name=public-bastion",
            "--host=db.internal",
            "--port=15432:5432",
        ]
    )

    assert result == 0
    assert events == [
        "spinner:Resolving bastion instance...",
        "resolve:public-bastion",
        "spinner:stop",
        "start:i-0123456789abcdef0",
    ]


def test_forward_hosts_lists_ids_and_optional_names(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr("aws_intel.cli.AwsCliForwardingGateway", FakeForwardingGateway)

    result = main(["forward", "hosts"])

    assert result == 0
    assert capsys.readouterr().out == (
        "i-0123456789abcdef0\tpublic-bastion\ni-11111111\n"
    )


def test_forward_hosts_shows_loading_indicator_while_fetching(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    class TrackingGateway(FakeForwardingGateway):
        def list_hosts(self) -> tuple[BastionHost, ...]:
            events.append("fetch")
            return ()

    @contextmanager
    def tracking_spinner(message: str) -> Iterator[None]:
        events.append(f"start:{message}")
        yield
        events.append("stop")

    monkeypatch.setattr("aws_intel.cli.AwsCliForwardingGateway", TrackingGateway)
    monkeypatch.setattr("aws_intel.cli.spinner", tracking_spinner)

    result = main(["forward", "hosts"])

    assert result == 0
    assert events == [
        "start:Loading potential bastion hosts...",
        "fetch",
        "stop",
    ]


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        (
            ["forward"],
            "required: <action>",
        ),
        (
            ["forward", "--instance-id=i-01234567", "--port=1:2"],
            "requires --host",
        ),
        (
            ["forward", "--instance-id=i-01234567", "--host=x"],
            "requires --port",
        ),
        (
            [
                "forward",
                "--instance-id=i-01234567",
                "--host=x",
                "--port=1:2",
                "--save",
            ],
            "required: NAME",
        ),
        (
            [
                "forward",
                "--instance-id=i-01234567",
                "--host=x",
                "--port=0:443",
            ],
            "ports must be between 1 and 65535",
        ),
        (
            [
                "forward",
                "--instance-id=i-01234567",
                "--host=x",
                "--port=local:443",
            ],
            "ports must be integers",
        ),
        (
            [
                "forward",
                "--instance-id=i-01234567",
                "--host=x",
                "--port=443",
            ],
            "must be LOCAL_PORT:REMOTE_PORT",
        ),
        (
            ["forward", "--instance-id=i-01234567", "--list-hosts"],
            "unrecognized arguments",
        ),
        (
            ["forward", "--instance-id=i-01234567", "--list"],
            "unrecognized arguments",
        ),
        (
            ["forward", "--instance-id=i-01234567", "--kill", "4321"],
            "unrecognized arguments",
        ),
        (
            [
                "forward",
                "--instance-id=not-an-instance",
                "--host=x",
                "--port=1:2",
            ],
            "must be an EC2 instance ID",
        ),
    ],
)
def test_forward_rejects_invalid_arguments(
    arguments: list[str],
    message: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(arguments)

    assert exit_info.value.code == 2
    assert message in capsys.readouterr().err


def test_forward_host_selectors_are_mutually_exclusive(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(
            [
                "forward",
                "--instance-id=i-01234567",
                "--instance-name=bastion",
                "--host=x",
                "--port=1:2",
            ]
        )

    assert exit_info.value.code == 2
    assert "not allowed with argument" in capsys.readouterr().err


def test_forward_start_rejects_removed_name_option(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(
            [
                "forward",
                "start",
                "--instance-id=i-01234567",
                "--host=x",
                "--port=1:2",
                "--name=legacy-name",
            ]
        )

    assert exit_info.value.code == 2
    assert "unrecognized arguments: --name=legacy-name" in capsys.readouterr().err
