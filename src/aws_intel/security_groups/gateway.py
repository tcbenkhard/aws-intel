"""AWS CLI boundary for security group information."""

from collections.abc import Callable
import json
import subprocess
from typing import Any

from aws_intel.security_groups.model import (
    SecurityGroup,
    SecurityGroupConnection,
)


class AwsCliError(RuntimeError):
    """Raised when the AWS CLI cannot retrieve requested AWS data."""


CommandRunner = Callable[..., subprocess.CompletedProcess[str]]


class AwsCliSecurityGroupGateway:
    """Retrieve security groups using the caller's AWS CLI configuration."""

    def __init__(self, runner: CommandRunner = subprocess.run) -> None:
        self._runner = runner

    def get(self, group_id: str) -> SecurityGroup:
        """Retrieve one security group."""
        try:
            result = self._runner(
                [
                    "aws",
                    "ec2",
                    "describe-security-groups",
                    "--group-ids",
                    group_id,
                    "--output",
                    "json",
                    "--no-cli-pager",
                ],
                capture_output=True,
                check=False,
                text=True,
            )
        except FileNotFoundError as error:
            raise AwsCliError(
                "AWS CLI was not found. Install it and ensure 'aws' is on PATH."
            ) from error

        if result.returncode != 0:
            diagnostic = result.stderr.strip() or "AWS CLI exited unsuccessfully"
            raise AwsCliError(diagnostic)

        try:
            groups = json.loads(result.stdout)["SecurityGroups"]
            group = groups[0]
        except (json.JSONDecodeError, KeyError, IndexError, TypeError) as error:
            raise AwsCliError("AWS CLI returned an unexpected response.") from error

        return SecurityGroup(
            group_id=group["GroupId"],
            name=group.get("GroupName") or group["GroupId"],
            inbound_connections=_connections(group.get("IpPermissions", [])),
            outbound_connections=_connections(
                group.get("IpPermissionsEgress", [])
            ),
            vpc_id=group.get("VpcId"),
        )


def _connections(
    permissions: list[dict[str, Any]],
) -> tuple[SecurityGroupConnection, ...]:
    """Extract unique connections and traffic details from rule permissions."""
    connections: list[SecurityGroupConnection] = []
    for permission in permissions:
        targets = [
            pair["GroupId"]
            for pair in permission.get("UserIdGroupPairs", [])
            if pair.get("GroupId")
        ]
        targets.extend(
            ip_range["CidrIp"]
            for ip_range in permission.get("IpRanges", [])
            if ip_range.get("CidrIp")
        )
        targets.extend(
            ip_range["CidrIpv6"]
            for ip_range in permission.get("Ipv6Ranges", [])
            if ip_range.get("CidrIpv6")
        )
        targets.extend(
            prefix["PrefixListId"]
            for prefix in permission.get("PrefixListIds", [])
            if prefix.get("PrefixListId")
        )
        connections.extend(
            SecurityGroupConnection(
                target=target,
                protocol=str(permission.get("IpProtocol", "-1")),
                from_port=permission.get("FromPort"),
                to_port=permission.get("ToPort"),
            )
            for target in targets
        )
    return tuple(dict.fromkeys(connections))
