"""Tests for the command-line entry point."""

from ipaddress import IPv4Network

import pytest

from aws_intel.security_groups.model import (
    SecurityGroup,
    SecurityGroupConnection,
)
from aws_intel.cli import main


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
    assert "security-group-tree" in output
    assert "Show attached resources, recursively connected" in output
    assert "help                Show all utilities or detailed help" in output


def test_help_utility_shows_detailed_utility_help(
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = main(["help", "security-group-tree"])

    assert result == 0
    output = capsys.readouterr().out
    assert output.startswith(
        "usage: awsi security-group-tree [-h] [--depth DEPTH]"
    )
    assert "One or more starting security group IDs" in output
    assert "Maximum connection depth to expand" in output


def test_help_utility_rejects_unknown_utility(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["help", "unknown"])

    assert exit_info.value.code == 2
    assert "invalid choice: 'unknown'" in capsys.readouterr().err


def test_version_exits_successfully(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["--version"])

    assert exit_info.value.code == 0
    assert capsys.readouterr().out.startswith("awsi ")


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
            outbound_connections=(
                SecurityGroupConnection("0.0.0.0/0", "-1"),
            ),
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

    result = main(
        ["security-group-tree", "sg-0123456789abcdef0", "--inbound"]
    )

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
