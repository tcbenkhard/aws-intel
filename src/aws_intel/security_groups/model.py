"""Application-owned security group models."""

from dataclasses import dataclass
from enum import Enum


class Direction(str, Enum):
    """A security group rule direction."""

    INBOUND = "inbound"
    OUTBOUND = "outbound"


@dataclass(frozen=True)
class SecurityGroupResource:
    """A resource attached to a security group through a network interface."""

    network_interface_id: str
    resource_type: str
    description: str | None = None
    private_ip_address: str | None = None


@dataclass(frozen=True)
class SecurityGroupConnection:
    """A target and the traffic allowed by one security group rule."""

    target: str
    protocol: str
    from_port: int | None = None
    to_port: int | None = None


@dataclass(frozen=True)
class SecurityGroup:
    """The security group data needed to build a connection tree."""

    group_id: str
    name: str
    inbound_connections: tuple[SecurityGroupConnection, ...]
    outbound_connections: tuple[SecurityGroupConnection, ...]
    vpc_id: str | None = None

    def connections(
        self, direction: Direction
    ) -> tuple[SecurityGroupConnection, ...]:
        """Return connections for the requested direction."""
        if direction is Direction.INBOUND:
            return self.inbound_connections
        return self.outbound_connections
