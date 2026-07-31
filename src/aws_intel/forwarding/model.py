"""Application-owned models for SSM port forwarding."""

from dataclasses import dataclass


@dataclass(frozen=True)
class BastionHost:
    """An online SSM-managed EC2 instance."""

    instance_id: str
    name: str | None = None


@dataclass(frozen=True)
class PortMapping:
    """A local port mapped to a port on the remote host."""

    local_port: int
    remote_port: int


@dataclass(frozen=True)
class SavedForward:
    """A named forwarding definition stored in the user configuration."""

    name: str
    host: str
    port_mapping: PortMapping
    instance_id: str | None = None
    instance_name: str | None = None


@dataclass(frozen=True)
class ActiveForward:
    """A background forwarding process started by this application."""

    pid: int
    instance_id: str
    host: str
    port_mapping: PortMapping
    name: str | None = None
