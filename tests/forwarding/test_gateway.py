"""Tests for the AWS CLI SSM forwarding gateway."""

import json
import subprocess
from types import SimpleNamespace

import pytest

from aws_intel.forwarding.gateway import (
    AwsCliForwardingGateway,
    ForwardingError,
    REMOTE_HOST_DOCUMENT,
)
from aws_intel.forwarding.model import PortMapping


def test_lists_online_ssm_ec2_instances_with_names() -> None:
    commands: list[list[str]] = []

    def runner(
        command: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        if command[1:3] == ["ssm", "describe-instance-information"]:
            response = {
                "InstanceInformationList": [
                    {"InstanceId": "i-22222222"},
                    {"InstanceId": "i-11111111"},
                ]
            }
        else:
            response = {
                "Reservations": [
                    {
                        "Instances": [
                            {
                                "InstanceId": "i-11111111",
                                "Tags": [{"Key": "Name", "Value": "bastion"}],
                            },
                            {"InstanceId": "i-22222222"},
                        ]
                    }
                ]
            }
        return subprocess.CompletedProcess(command, 0, json.dumps(response), "")

    hosts = AwsCliForwardingGateway(runner).list_hosts()

    assert [(host.instance_id, host.name) for host in hosts] == [
        ("i-11111111", "bastion"),
        ("i-22222222", None),
    ]
    assert "Key=PingStatus,Values=Online" in commands[0]
    assert "Key=ResourceType,Values=EC2Instance" in commands[0]
    assert commands[1][0:3] == ["aws", "ec2", "describe-instances"]
    assert commands[1][commands[1].index("--instance-ids") + 1 : -3] == [
        "i-22222222",
        "i-11111111",
    ]


def test_empty_host_list_does_not_query_ec2() -> None:
    commands: list[list[str]] = []

    def runner(
        command: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        return subprocess.CompletedProcess(
            command, 0, '{"InstanceInformationList": []}', ""
        )

    assert AwsCliForwardingGateway(runner).list_hosts() == ()
    assert len(commands) == 1


def test_starts_remote_host_forward_in_background() -> None:
    calls: list[tuple[list[str], dict[str, object]]] = []

    def process_starter(
        command: list[str], **kwargs: object
    ) -> subprocess.Popen[bytes]:
        calls.append((command, kwargs))
        return SimpleNamespace(pid=4321)  # type: ignore[return-value]

    result = AwsCliForwardingGateway(
        process_starter=process_starter,
        local_port_checker=lambda port: True,
    ).start(
        "i-0123456789abcdef0", "db.internal", PortMapping(15432, 5432)
    )

    assert result == 4321
    command, options = calls[0]
    assert command == [
        "aws",
        "ssm",
        "start-session",
        "--target",
        "i-0123456789abcdef0",
        "--document-name",
        REMOTE_HOST_DOCUMENT,
        "--parameters",
        '{"host":["db.internal"],"portNumber":["5432"],'
        '"localPortNumber":["15432"]}',
        "--no-cli-pager",
    ]
    assert options == {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "start_new_session": True,
    }


def test_rejects_an_unavailable_local_port() -> None:
    started = False

    def process_starter(
        command: list[str], **kwargs: object
    ) -> subprocess.Popen[bytes]:
        nonlocal started
        started = True
        return SimpleNamespace(pid=123)  # type: ignore[return-value]

    with pytest.raises(ForwardingError, match="local port 15432"):
        AwsCliForwardingGateway(
            process_starter=process_starter,
            local_port_checker=lambda port: False,
        ).start(
            "i-11111111",
            "db.internal",
            PortMapping(15432, 5432),
        )

    assert started is False


def test_reports_missing_aws_cli_when_starting_forward() -> None:
    def process_starter(
        command: list[str], **kwargs: object
    ) -> subprocess.Popen[bytes]:
        raise FileNotFoundError

    with pytest.raises(ForwardingError, match="AWS CLI was not found"):
        AwsCliForwardingGateway(
            process_starter=process_starter,
            local_port_checker=lambda port: True,
        ).start(
            "i-0123456789abcdef0", "db.internal", PortMapping(15432, 5432)
        )


def test_resolves_exact_name_tag_to_active_instance() -> None:
    commands: list[list[str]] = []

    def runner(
        command: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        response = {
            "Reservations": [
                {"Instances": [{"InstanceId": "i-0123456789abcdef0"}]}
            ]
        }
        return subprocess.CompletedProcess(command, 0, json.dumps(response), "")

    instance_id = AwsCliForwardingGateway(runner).resolve_instance_name(
        "public-bastion"
    )

    assert instance_id == "i-0123456789abcdef0"
    assert len(commands) == 1
    filters = json.loads(commands[0][commands[0].index("--filters") + 1])
    assert filters[0] == {
        "Name": "tag:Name",
        "Values": ["public-bastion"],
    }


@pytest.mark.parametrize(
    ("instance_ids", "message"),
    [
        ([], "no active EC2 instance has the Name tag 'bastion'"),
        (
            ["i-22222222", "i-11111111"],
            "multiple active EC2 instances have the Name tag 'bastion': "
            "i-11111111, i-22222222",
        ),
    ],
)
def test_name_resolution_requires_exactly_one_active_instance(
    instance_ids: list[str], message: str
) -> None:
    def runner(
        command: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        response = {
            "Reservations": [
                {
                    "Instances": [
                        {"InstanceId": instance_id}
                        for instance_id in instance_ids
                    ]
                }
            ]
        }
        return subprocess.CompletedProcess(command, 0, json.dumps(response), "")

    with pytest.raises(ForwardingError, match=message):
        AwsCliForwardingGateway(runner).resolve_instance_name("bastion")


def test_reports_aws_cli_query_errors() -> None:
    def runner(
        command: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 255, "", "Access denied")

    with pytest.raises(ForwardingError, match="Access denied"):
        AwsCliForwardingGateway(runner).list_hosts()
