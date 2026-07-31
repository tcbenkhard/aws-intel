"""Tests for the AWS CLI security group gateway."""

import json
import subprocess

import pytest

from aws_intel.security_groups.gateway import (
    AwsCliError,
    AwsCliSecurityGroupGateway,
)


def test_maps_aws_response_and_deduplicates_connections() -> None:
    response = {
        "SecurityGroups": [
            {
                "GroupId": "sg-0123456789abcdef0",
                "GroupName": "web",
                "VpcId": "vpc-01234567",
                "IpPermissions": [
                    {
                        "IpProtocol": "tcp",
                        "FromPort": 443,
                        "ToPort": 443,
                        "UserIdGroupPairs": [{"GroupId": "sg-11111111"}],
                        "IpRanges": [{"CidrIp": "10.0.0.0/8"}],
                        "Ipv6Ranges": [{"CidrIpv6": "2001:db8::/64"}],
                        "PrefixListIds": [{"PrefixListId": "pl-12345678"}],
                    },
                    {
                        "IpProtocol": "tcp",
                        "FromPort": 443,
                        "ToPort": 443,
                        "IpRanges": [{"CidrIp": "10.0.0.0/8"}],
                    },
                ],
                "IpPermissionsEgress": [
                    {
                        "IpProtocol": "-1",
                        "IpRanges": [{"CidrIp": "0.0.0.0/0"}],
                    }
                ],
            }
        ]
    }

    def runner(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess([], 0, json.dumps(response), "")

    group = AwsCliSecurityGroupGateway(runner).get("sg-0123456789abcdef0")

    assert group.name == "web"
    assert group.vpc_id == "vpc-01234567"
    assert tuple(
        connection.target for connection in group.inbound_connections
    ) == (
        "sg-11111111",
        "10.0.0.0/8",
        "2001:db8::/64",
        "pl-12345678",
    )
    assert all(
        connection.protocol == "tcp"
        and connection.from_port == 443
        and connection.to_port == 443
        for connection in group.inbound_connections
    )
    assert group.outbound_connections[0].target == "0.0.0.0/0"
    assert group.outbound_connections[0].protocol == "-1"


def test_reports_aws_cli_errors() -> None:
    def runner(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess([], 255, "", "Unable to locate credentials")

    with pytest.raises(AwsCliError, match="Unable to locate credentials"):
        AwsCliSecurityGroupGateway(runner).get("sg-0123456789abcdef0")
