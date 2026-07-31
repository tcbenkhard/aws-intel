"""AWS CLI boundary for resources attached to security groups."""

from collections.abc import Callable
from ipaddress import IPv4Address, IPv4Network, ip_address
import json
import subprocess

from aws_intel.security_groups.gateway import AwsCliError
from aws_intel.security_groups.model import SecurityGroupResource

CommandRunner = Callable[..., subprocess.CompletedProcess[str]]


class AwsCliSecurityGroupResourceGateway:
    """Find resources using network interfaces associated with a security group."""

    def __init__(self, runner: CommandRunner = subprocess.run) -> None:
        self._runner = runner

    def list_for_group(self, group_id: str) -> tuple[SecurityGroupResource, ...]:
        """Return resources whose network interfaces use the security group."""
        interfaces = self._list_interfaces(f"Name=group-id,Values={group_id}")
        names = self._list_names(interfaces)
        return tuple(_to_resource(interface, names=names) for interface in interfaces)

    def list_for_private_network(
        self, vpc_id: str, network: IPv4Network
    ) -> tuple[SecurityGroupResource, ...]:
        """Return ENI resources with private IPv4 addresses in a network."""
        interfaces = self._list_interfaces(f"Name=vpc-id,Values={vpc_id}")
        names = self._list_names(interfaces)
        resources: list[SecurityGroupResource] = []
        for interface in interfaces:
            addresses = interface.get("PrivateIpAddresses", [])
            if not isinstance(addresses, list):
                raise AwsCliError("AWS CLI returned an unexpected response.")
            for address in addresses:
                if not isinstance(address, dict):
                    raise AwsCliError("AWS CLI returned an unexpected response.")
                private_ip = address.get("PrivateIpAddress")
                try:
                    parsed_address = ip_address(private_ip)
                except ValueError as error:
                    raise AwsCliError(
                        "AWS CLI returned an unexpected response."
                    ) from error
                if (
                    isinstance(parsed_address, IPv4Address)
                    and parsed_address in network
                ):
                    resources.append(_to_resource(interface, private_ip, names))
        return tuple(resources)

    def _list_names(self, interfaces: list[dict[str, object]]) -> dict[str, str]:
        """Return Name tags for attached instances and network interfaces."""
        resource_ids: list[str] = []
        for interface in interfaces:
            interface_id = interface.get("NetworkInterfaceId")
            if isinstance(interface_id, str):
                resource_ids.append(interface_id)
            attachment = interface.get("Attachment")
            instance_id = (
                attachment.get("InstanceId") if isinstance(attachment, dict) else None
            )
            if isinstance(instance_id, str):
                resource_ids.append(instance_id)

        if not resource_ids:
            return {}

        try:
            result = self._runner(
                [
                    "aws",
                    "ec2",
                    "describe-tags",
                    "--filters",
                    f"Name=resource-id,Values={','.join(resource_ids)}",
                    "Name=key,Values=Name",
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
            tags = json.loads(result.stdout)["Tags"]
            if not isinstance(tags, list):
                raise TypeError
            names: dict[str, str] = {}
            for tag in tags:
                if not isinstance(tag, dict):
                    raise TypeError
                resource_id = tag.get("ResourceId")
                value = tag.get("Value")
                if isinstance(resource_id, str) and isinstance(value, str) and value:
                    names[resource_id] = value
            return names
        except (json.JSONDecodeError, KeyError, TypeError) as error:
            raise AwsCliError("AWS CLI returned an unexpected response.") from error

    def _list_interfaces(self, resource_filter: str) -> list[dict[str, object]]:
        """Retrieve all matching ENIs; the AWS CLI paginates automatically."""
        try:
            result = self._runner(
                [
                    "aws",
                    "ec2",
                    "describe-network-interfaces",
                    "--filters",
                    resource_filter,
                    "--include-managed-resources",
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
            interfaces = json.loads(result.stdout)["NetworkInterfaces"]
            if not isinstance(interfaces, list) or not all(
                isinstance(interface, dict) for interface in interfaces
            ):
                raise TypeError
            return interfaces
        except (json.JSONDecodeError, KeyError, TypeError) as error:
            raise AwsCliError("AWS CLI returned an unexpected response.") from error


def _to_resource(
    interface: dict[str, object],
    private_ip_address: str | None = None,
    names: dict[str, str] | None = None,
) -> SecurityGroupResource:
    """Convert an AWS network interface into an application-owned resource."""
    names = names or {}
    interface_id = interface["NetworkInterfaceId"]
    if not isinstance(interface_id, str):
        raise TypeError

    attachment = interface.get("Attachment")
    instance_id = attachment.get("InstanceId") if isinstance(attachment, dict) else None
    if isinstance(instance_id, str):
        return SecurityGroupResource(
            network_interface_id=interface_id,
            resource_type="EC2 instance",
            description=names.get(instance_id, instance_id),
            private_ip_address=private_ip_address,
        )

    interface_type = interface.get("InterfaceType")
    resource_type = (
        interface_type.replace("_", " ")
        if isinstance(interface_type, str)
        else "network interface"
    )
    description = interface.get("Description")
    fallback_description = (
        description if isinstance(description, str) and description else None
    )
    return SecurityGroupResource(
        network_interface_id=interface_id,
        resource_type=resource_type,
        description=names.get(interface_id) or fallback_description,
        private_ip_address=private_ip_address,
    )
