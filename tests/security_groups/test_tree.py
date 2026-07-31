"""Tests for security group tree building and rendering."""

from ipaddress import IPv4Network

from aws_intel.security_groups.model import (
    Direction,
    SecurityGroup,
    SecurityGroupConnection,
    SecurityGroupResource,
)
from aws_intel.security_groups.tree import (
    SecurityGroupTreeService,
    TreeNode,
    filter_tree,
    render_tree,
)


class FakeGateway:
    def __init__(self, groups: dict[str, SecurityGroup]) -> None:
        self.groups = groups

    def get(self, group_id: str) -> SecurityGroup:
        return self.groups[group_id]


class FakeResourceGateway:
    def __init__(
        self, resources: dict[str, tuple[SecurityGroupResource, ...]]
    ) -> None:
        self.resources = resources

    def list_for_group(
        self, group_id: str
    ) -> tuple[SecurityGroupResource, ...]:
        return self.resources.get(group_id, ())

    def list_for_private_network(
        self, vpc_id: str, network: IPv4Network
    ) -> tuple[SecurityGroupResource, ...]:
        return self.resources.get(str(network), ())


def test_builds_nested_tree_with_unicode_branches_and_stops_cycles() -> None:
    root_id = "sg-0123456789abcdef0"
    child_id = "sg-11111111"
    groups = {
        root_id: SecurityGroup(
            root_id,
            "web",
            (
                SecurityGroupConnection(child_id, "tcp", 443, 443),
                SecurityGroupConnection("10.2.3.0/24", "udp", 1000, 2000),
            ),
            (),
            "vpc-01234567",
        ),
        child_id: SecurityGroup(
            child_id,
            "load-balancer",
            (SecurityGroupConnection(root_id, "icmp", 8, -1),),
            (),
        ),
    }

    resources = {
        root_id: (
            SecurityGroupResource(
                "eni-0123456789abcdef0",
                "EC2 instance",
                "i-0123456789abcdef0",
            ),
        ),
        child_id: (
            SecurityGroupResource(
                "eni-11111111111111111",
                "load balancer",
                "ELB app/public/123",
            ),
        ),
        "10.2.3.0/24": (
            SecurityGroupResource(
                "eni-22222222222222222",
                "EC2 instance",
                "i-22222222222222222",
                "10.2.3.42",
            ),
        ),
    }

    tree = SecurityGroupTreeService(
        FakeGateway(groups), FakeResourceGateway(resources)
    ).build(
        root_id, Direction.INBOUND, max_depth=3
    )

    assert render_tree(tree) == (
        "web (sg-0123456789abcdef0)\n"
        "├── Assigned to\n"
        "│   └── EC2 instance: i-0123456789abcdef0 "
        "(eni-0123456789abcdef0)\n"
        "└── Sources\n"
        "    ├── tcp 443 from sg-11111111 (load-balancer)\n"
        "    │   ├── Assigned to\n"
        "    │   │   └── load balancer: ELB app/public/123 "
        "(eni-11111111111111111)\n"
        "    │   └── Sources\n"
        "    │       └── icmp type 8 from sg-0123456789abcdef0 "
        "(web) [cycle]\n"
        "    └── udp 1000-2000 from 10.2.3.0/24\n"
        "        └── 10.2.3.42 EC2 instance: "
        "i-22222222222222222 (eni-22222222222222222)"
    )


def test_empty_group_renders_only_root() -> None:
    group_id = "sg-0123456789abcdef0"
    group = SecurityGroup(group_id, "empty", (), ())

    tree = SecurityGroupTreeService(
        FakeGateway({group_id: group}), FakeResourceGateway({})
    ).build(
        group_id, Direction.OUTBOUND
    )

    assert render_tree(tree) == "empty (sg-0123456789abcdef0)"


def test_filter_tree_matches_case_insensitively_and_retains_context() -> None:
    tree = TreeNode(
        "root",
        (
            TreeNode("unrelated"),
            TreeNode("Assigned to", (TreeNode("root resource"),)),
            TreeNode(
                "Sources",
                (
                    TreeNode(
                        "tcp 5580 from 10.251.0.0/20",
                        (
                            TreeNode("EC2 instance: APIPortal-ACC"),
                            TreeNode("EC2 instance: other"),
                        ),
                    ),
                ),
            ),
        ),
    )

    filtered = filter_tree(tree, "acc")

    assert filtered is not None
    assert render_tree(filtered) == (
        "root\n"
        "├── Assigned to\n"
        "│   └── root resource\n"
        "└── Sources\n"
        "    └── tcp 5580 from 10.251.0.0/20\n"
        "        └── EC2 instance: APIPortal-ACC"
    )


def test_filter_tree_retains_descendants_of_matching_node() -> None:
    tree = TreeNode(
        "root",
        (TreeNode("ACC group", (TreeNode("assigned resource"),)),),
    )

    assert filter_tree(tree, "acc") == tree


def test_filter_tree_returns_none_when_nothing_matches() -> None:
    assert filter_tree(TreeNode("root", (TreeNode("child"),)), "missing") is None


def test_build_many_returns_each_requested_root() -> None:
    first_id = "sg-0123456789abcdef0"
    second_id = "sg-11111111"
    groups = {
        first_id: SecurityGroup(first_id, "first", (), ()),
        second_id: SecurityGroup(second_id, "second", (), ()),
    }

    trees = SecurityGroupTreeService(
        FakeGateway(groups), FakeResourceGateway({})
    ).build_many((first_id, second_id), Direction.INBOUND)

    assert tuple(tree.label for tree in trees) == (
        f"first ({first_id})",
        f"second ({second_id})",
    )


def test_default_depth_does_not_expand_connected_group_contents() -> None:
    root_id = "sg-0123456789abcdef0"
    child_id = "sg-11111111"
    groups = {
        root_id: SecurityGroup(
            root_id,
            "root",
            (SecurityGroupConnection(child_id, "tcp", 443, 443),),
            (),
        ),
        child_id: SecurityGroup(
            child_id,
            "child",
            (SecurityGroupConnection("10.0.0.0/8", "tcp", 80, 80),),
            (),
        ),
    }

    tree = SecurityGroupTreeService(
        FakeGateway(groups), FakeResourceGateway({})
    ).build(root_id, Direction.INBOUND)

    assert render_tree(tree) == (
        "root (sg-0123456789abcdef0)\n"
        "└── Sources\n"
        "    └── tcp 443 from sg-11111111 (child)"
    )


def test_does_not_resolve_public_or_ipv6_networks() -> None:
    group_id = "sg-0123456789abcdef0"
    group = SecurityGroup(
        group_id,
        "web",
        (
            SecurityGroupConnection("8.8.8.0/24", "tcp", 443, 443),
            SecurityGroupConnection("2001:db8::/64", "tcp", 443, 443),
        ),
        (),
        "vpc-01234567",
    )

    tree = SecurityGroupTreeService(
        FakeGateway({group_id: group}), FakeResourceGateway({})
    ).build(group_id, Direction.INBOUND)

    sources = tree.children[0]
    assert sources.label == "Sources"
    assert all(not connection.children for connection in sources.children)
