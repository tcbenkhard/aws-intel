"""Build and render security group connection trees."""

from dataclasses import dataclass
from ipaddress import IPv4Network, ip_network
from typing import Protocol

from aws_intel.security_groups.model import (
    Direction,
    SecurityGroup,
    SecurityGroupConnection,
    SecurityGroupResource,
)


class SecurityGroupGateway(Protocol):
    """Port for retrieving security groups."""

    def get(self, group_id: str) -> SecurityGroup:
        """Retrieve a security group by ID."""


class SecurityGroupResourceGateway(Protocol):
    """Port for finding resources attached to security groups."""

    def list_for_group(
        self, group_id: str
    ) -> tuple[SecurityGroupResource, ...]:
        """Return resources attached to a security group."""

    def list_for_private_network(
        self, vpc_id: str, network: IPv4Network
    ) -> tuple[SecurityGroupResource, ...]:
        """Return resources with addresses in a private IPv4 network."""


@dataclass(frozen=True)
class TreeNode:
    """One node in a security group connection tree."""

    label: str
    children: tuple["TreeNode", ...] = ()


def filter_tree(root: TreeNode, text: str) -> TreeNode | None:
    """Keep matches, their context paths, and assignment metadata."""
    normalized_text = text.casefold()
    if normalized_text in root.label.casefold():
        return root

    filtered_children = tuple(
        (child, filtered_child)
        for child in root.children
        if (filtered_child := filter_tree(child, text)) is not None
    )
    if not filtered_children:
        return None
    filtered_by_id = {
        id(original): filtered for original, filtered in filtered_children
    }
    children = tuple(
        child if child.label == "Assigned to" else filtered_by_id[id(child)]
        for child in root.children
        if child.label == "Assigned to" or id(child) in filtered_by_id
    )
    return TreeNode(root.label, children)


class SecurityGroupTreeService:
    """Recursively build trees of security group connections."""

    def __init__(
        self,
        gateway: SecurityGroupGateway,
        resource_gateway: SecurityGroupResourceGateway,
    ) -> None:
        self._gateway = gateway
        self._resource_gateway = resource_gateway
        self._cache: dict[str, SecurityGroup] = {}
        self._resource_cache: dict[str, tuple[SecurityGroupResource, ...]] = {}
        self._network_resource_cache: dict[
            tuple[str, IPv4Network], tuple[SecurityGroupResource, ...]
        ] = {}

    def build(
        self, root_id: str, direction: Direction, max_depth: int = 1
    ) -> TreeNode:
        """Build a depth-limited direction-specific tree."""
        return self._build_group(
            root_id, direction, frozenset(), current_depth=0, max_depth=max_depth
        )

    def build_many(
        self,
        root_ids: tuple[str, ...],
        direction: Direction,
        max_depth: int = 1,
    ) -> tuple[TreeNode, ...]:
        """Build direction-specific trees that share cached AWS lookups."""
        return tuple(
            self.build(root_id, direction, max_depth) for root_id in root_ids
        )

    def _build_group(
        self,
        group_id: str,
        direction: Direction,
        ancestors: frozenset[str],
        current_depth: int,
        max_depth: int,
    ) -> TreeNode:
        group = self._get(group_id)
        label = f"{group.name} ({group.group_id})"
        if group_id in ancestors:
            return TreeNode(f"{label} [cycle]")
        if current_depth >= max_depth:
            return TreeNode(label)

        next_ancestors = ancestors | {group_id}
        resources = tuple(
            TreeNode(_resource_label(resource))
            for resource in self._get_resources(group_id)
        )
        connections = tuple(
            self._build_connection(
                connection,
                direction,
                next_ancestors,
                group.vpc_id,
                current_depth,
                max_depth,
            )
            for connection in group.connections(direction)
        )
        children = (
            (TreeNode("Assigned to", resources),) if resources else ()
        ) + (
            (
                TreeNode(
                    "Sources"
                    if direction is Direction.INBOUND
                    else "Targets",
                    connections,
                ),
            )
            if connections
            else ()
        )
        return TreeNode(label, children)

    def _build_connection(
        self,
        connection: SecurityGroupConnection,
        direction: Direction,
        ancestors: frozenset[str],
        vpc_id: str | None,
        current_depth: int,
        max_depth: int,
    ) -> TreeNode:
        rule = _rule_label(connection)
        relationship = (
            "from" if direction is Direction.INBOUND else "to"
        )
        if connection.target.startswith("sg-"):
            group_node = self._build_group(
                connection.target,
                direction,
                ancestors,
                current_depth + 1,
                max_depth,
            )
            group = self._get(connection.target)
            target_label = f"{group.group_id} ({group.name})"
            if connection.target in ancestors:
                target_label += " [cycle]"
            return TreeNode(
                f"{rule} {relationship} {target_label}",
                group_node.children,
            )
        label = f"{rule} {relationship} {connection.target}"
        network = _private_ipv4_network(connection.target)
        if network is None or vpc_id is None:
            return TreeNode(label)
        resources = tuple(
            TreeNode(_resource_label(resource))
            for resource in self._get_network_resources(vpc_id, network)
        )
        return TreeNode(label, resources)

    def _get(self, group_id: str) -> SecurityGroup:
        if group_id not in self._cache:
            self._cache[group_id] = self._gateway.get(group_id)
        return self._cache[group_id]

    def _get_resources(
        self, group_id: str
    ) -> tuple[SecurityGroupResource, ...]:
        if group_id not in self._resource_cache:
            self._resource_cache[group_id] = self._resource_gateway.list_for_group(
                group_id
            )
        return self._resource_cache[group_id]

    def _get_network_resources(
        self, vpc_id: str, network: IPv4Network
    ) -> tuple[SecurityGroupResource, ...]:
        key = (vpc_id, network)
        if key not in self._network_resource_cache:
            self._network_resource_cache[key] = (
                self._resource_gateway.list_for_private_network(vpc_id, network)
            )
        return self._network_resource_cache[key]


def _resource_label(resource: SecurityGroupResource) -> str:
    address = (
        f"{resource.private_ip_address} "
        if resource.private_ip_address is not None
        else ""
    )
    details = (
        f": {resource.description}" if resource.description is not None else ""
    )
    return (
        f"{address}{resource.resource_type}{details} "
        f"({resource.network_interface_id})"
    )


_RFC_1918_NETWORKS = tuple(
    ip_network(cidr) for cidr in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
)


def _private_ipv4_network(target: str) -> IPv4Network | None:
    """Parse RFC 1918 IPv4 CIDRs, excluding public and IPv6 rule targets."""
    try:
        network = ip_network(target, strict=False)
    except ValueError:
        return None
    if not isinstance(network, IPv4Network):
        return None
    if any(network.subnet_of(private) for private in _RFC_1918_NETWORKS):
        return network
    return None


def _rule_label(connection: SecurityGroupConnection) -> str:
    protocol = connection.protocol.lower()
    if protocol == "-1":
        return "all traffic"
    if protocol in {"icmp", "icmpv6"}:
        return _icmp_label(protocol, connection.from_port, connection.to_port)
    if connection.from_port is None:
        return protocol
    if (
        connection.to_port is None
        or connection.to_port == connection.from_port
    ):
        return f"{protocol} {connection.from_port}"
    return f"{protocol} {connection.from_port}-{connection.to_port}"


def _icmp_label(
    protocol: str, icmp_type: int | None, icmp_code: int | None
) -> str:
    if icmp_type is None or icmp_type == -1:
        return protocol
    if icmp_code is None or icmp_code == -1:
        return f"{protocol} type {icmp_type}"
    return f"{protocol} type {icmp_type} code {icmp_code}"


def render_tree(root: TreeNode) -> str:
    """Render a tree using terminal-friendly Unicode branch characters."""
    lines = [root.label]

    def append_children(node: TreeNode, prefix: str) -> None:
        for index, child in enumerate(node.children):
            last = index == len(node.children) - 1
            lines.append(f"{prefix}{'└── ' if last else '├── '}{child.label}")
            append_children(child, prefix + ("    " if last else "│   "))

    append_children(root, "")
    return "\n".join(lines)
