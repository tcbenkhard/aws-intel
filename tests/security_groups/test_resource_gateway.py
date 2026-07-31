"""Tests for security group resource discovery."""

import json
from ipaddress import ip_network
import subprocess

import pytest

from aws_intel.security_groups.gateway import AwsCliError
from aws_intel.security_groups.resource_gateway import (
    AwsCliSecurityGroupResourceGateway,
)


def test_maps_ec2_and_managed_network_interfaces_to_resources() -> None:
    response = {
        "NetworkInterfaces": [
            {
                "NetworkInterfaceId": "eni-0123456789abcdef0",
                "InterfaceType": "interface",
                "Description": "Primary network interface",
                "Attachment": {"InstanceId": "i-0123456789abcdef0"},
            },
            {
                "NetworkInterfaceId": "eni-11111111111111111",
                "InterfaceType": "load_balancer",
                "Description": "ELB app/public/123",
                "Attachment": {},
            },
            {
                "NetworkInterfaceId": "eni-22222222222222222",
                "InterfaceType": "vpc_endpoint",
                "Description": "",
            },
        ]
    }

    def runner(
        command: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        payload = {"Tags": []} if "describe-tags" in command else response
        return subprocess.CompletedProcess([], 0, json.dumps(payload), "")

    resources = AwsCliSecurityGroupResourceGateway(runner).list_for_group(
        "sg-0123456789abcdef0"
    )

    assert resources[0].resource_type == "EC2 instance"
    assert resources[0].description == "i-0123456789abcdef0"
    assert resources[1].resource_type == "load balancer"
    assert resources[1].description == "ELB app/public/123"
    assert resources[2].resource_type == "vpc endpoint"
    assert resources[2].description is None


def test_filters_by_group_and_includes_managed_resources() -> None:
    commands: list[list[str]] = []

    def runner(
        command: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        if "describe-tags" in command:
            return subprocess.CompletedProcess([], 0, json.dumps({"Tags": []}), "")
        return subprocess.CompletedProcess(
            [], 0, json.dumps({"NetworkInterfaces": []}), ""
        )

    AwsCliSecurityGroupResourceGateway(runner).list_for_group("sg-12345678")

    assert "Name=group-id,Values=sg-12345678" in commands[0]
    assert "--include-managed-resources" in commands[0]


def test_finds_all_private_addresses_in_network_scoped_to_vpc() -> None:
    response = {
        "NetworkInterfaces": [
            {
                "NetworkInterfaceId": "eni-0123456789abcdef0",
                "InterfaceType": "interface",
                "Attachment": {"InstanceId": "i-0123456789abcdef0"},
                "PrivateIpAddresses": [
                    {"PrivateIpAddress": "10.253.4.27"},
                    {"PrivateIpAddress": "10.254.0.1"},
                ],
            },
            {
                "NetworkInterfaceId": "eni-11111111111111111",
                "InterfaceType": "vpc_endpoint",
                "Description": "endpoint",
                "PrivateIpAddresses": [{"PrivateIpAddress": "10.253.15.255"}],
            },
        ]
    }
    commands: list[list[str]] = []

    def runner(
        command: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        payload = {"Tags": []} if "describe-tags" in command else response
        return subprocess.CompletedProcess([], 0, json.dumps(payload), "")

    resources = AwsCliSecurityGroupResourceGateway(runner).list_for_private_network(
        "vpc-01234567", ip_network("10.253.0.0/20")
    )

    assert [resource.private_ip_address for resource in resources] == [
        "10.253.4.27",
        "10.253.15.255",
    ]
    assert resources[0].description == "i-0123456789abcdef0"
    assert "Name=vpc-id,Values=vpc-01234567" in commands[0]


def test_prefers_instance_and_network_interface_names() -> None:
    response = {
        "NetworkInterfaces": [
            {
                "NetworkInterfaceId": "eni-0123456789abcdef0",
                "InterfaceType": "interface",
                "Attachment": {"InstanceId": "i-0123456789abcdef0"},
            },
            {
                "NetworkInterfaceId": "eni-11111111111111111",
                "InterfaceType": "vpc_endpoint",
                "Description": "fallback endpoint description",
            },
        ]
    }
    tags = {
        "Tags": [
            {
                "ResourceId": "i-0123456789abcdef0",
                "Key": "Name",
                "Value": "orders-api",
            },
            {
                "ResourceId": "eni-11111111111111111",
                "Key": "Name",
                "Value": "private-s3-endpoint",
            },
        ]
    }

    def runner(
        command: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        payload = tags if "describe-tags" in command else response
        return subprocess.CompletedProcess([], 0, json.dumps(payload), "")

    resources = AwsCliSecurityGroupResourceGateway(runner).list_for_group(
        "sg-0123456789abcdef0"
    )

    assert resources[0].description == "orders-api"
    assert resources[1].description == "private-s3-endpoint"


def test_reports_aws_cli_errors() -> None:
    def runner(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess([], 255, "", "Access denied")

    with pytest.raises(AwsCliError, match="Access denied"):
        AwsCliSecurityGroupResourceGateway(runner).list_for_group("sg-12345678")
