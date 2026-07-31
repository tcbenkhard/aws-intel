"""Command-line entry point for AWS Intel."""

import argparse
from collections.abc import Sequence
import re
import sys

from aws_intel import __version__
from aws_intel.progress import spinner
from aws_intel.security_groups.gateway import AwsCliError, AwsCliSecurityGroupGateway
from aws_intel.security_groups.model import Direction
from aws_intel.security_groups.resource_gateway import (
    AwsCliSecurityGroupResourceGateway,
)
from aws_intel.security_groups.tree import (
    SecurityGroupTreeService,
    TreeNode,
    filter_tree,
    render_tree,
)

SECURITY_GROUP_ID = re.compile(r"^sg-[0-9a-fA-F]{8,17}$")
DEFAULT_SECURITY_GROUP_TREE_DEPTH = 1
MAX_SECURITY_GROUP_TREE_DEPTH = 3


class AwsIntelArgumentParser(argparse.ArgumentParser):
    """Argument parser with access to the registered utility parsers."""

    utility_parsers: dict[str, argparse.ArgumentParser]


def _security_group_tree_depth(value: str) -> int:
    """Parse a safe security group traversal depth."""
    try:
        depth = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("must be an integer") from error
    if not 1 <= depth <= MAX_SECURITY_GROUP_TREE_DEPTH:
        raise argparse.ArgumentTypeError(
            f"must be between 1 and {MAX_SECURITY_GROUP_TREE_DEPTH}"
        )
    return depth


def create_parser() -> AwsIntelArgumentParser:
    """Create the application's argument parser."""
    parser = AwsIntelArgumentParser(
        prog="awsi",
        usage="%(prog)s <utility> <options>",
        description="Retrieve useful information from AWS.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    utilities = parser.add_subparsers(
        dest="utility",
        metavar="<utility>",
        required=True,
    )
    security_group_tree = utilities.add_parser(
        "security-group-tree",
        help=(
            "Show attached resources, recursively connected security groups, "
            "and network ranges."
        ),
        description=(
            "Show attached resources and inbound and outbound security group "
            "connections. "
            "Uses the active AWS CLI credentials and region."
        ),
    )
    security_group_tree.add_argument(
        "security_group_ids",
        nargs="+",
        metavar="security-group-id",
        help=(
            "One or more starting security group IDs "
            "(for example, sg-0123456789abcdef0)."
        ),
    )
    security_group_tree.add_argument(
        "--depth",
        type=_security_group_tree_depth,
        default=DEFAULT_SECURITY_GROUP_TREE_DEPTH,
        metavar="DEPTH",
        help=(
            "Maximum connection depth to expand "
            f"(default: {DEFAULT_SECURITY_GROUP_TREE_DEPTH}; "
            f"maximum: {MAX_SECURITY_GROUP_TREE_DEPTH})."
        ),
    )
    security_group_tree.add_argument(
        "--filter",
        metavar="TEXT",
        help=(
            "Show only tree items matching TEXT (case-insensitive), including "
            "their descendants and ancestor paths."
        ),
    )
    direction = security_group_tree.add_mutually_exclusive_group()
    direction.add_argument(
        "--inbound",
        action="store_true",
        help="Show only inbound connections.",
    )
    direction.add_argument(
        "--outbound",
        action="store_true",
        help="Show only outbound connections.",
    )
    help_utility = utilities.add_parser(
        "help",
        help="Show all utilities or detailed help for one utility.",
        description="Show all utilities or detailed help for one utility.",
    )
    help_utility.add_argument(
        "help_utility",
        nargs="?",
        choices=utilities.choices,
        metavar="utility",
        help="Utility whose detailed help should be shown.",
    )
    parser.utility_parsers = utilities.choices
    return parser


def main(arguments: Sequence[str] | None = None) -> int:
    """Run the command-line application."""
    parser = create_parser()
    parsed = parser.parse_args(arguments)
    if parsed.utility == "help":
        if parsed.help_utility is None:
            parser.print_help()
        else:
            parser.utility_parsers[parsed.help_utility].print_help()
        return 0
    if parsed.utility == "security-group-tree":
        invalid_ids = [
            group_id
            for group_id in parsed.security_group_ids
            if not SECURITY_GROUP_ID.fullmatch(group_id)
        ]
        if invalid_ids:
            parser.error(
                f"security-group-id {invalid_ids[0]!r} must be an AWS security "
                "group ID such as sg-0123456789abcdef0"
            )
        security_group_ids = tuple(dict.fromkeys(parsed.security_group_ids))
        directions = (
            [Direction.INBOUND]
            if parsed.inbound
            else [Direction.OUTBOUND]
            if parsed.outbound
            else [Direction.INBOUND, Direction.OUTBOUND]
        )
        service = SecurityGroupTreeService(
            AwsCliSecurityGroupGateway(),
            AwsCliSecurityGroupResourceGateway(),
        )
        try:
            with spinner("Loading AWS resources..."):
                output = []
                for direction in directions:
                    trees = service.build_many(
                        security_group_ids,
                        direction,
                        parsed.depth,
                    )
                    filtered_trees = (
                        tuple(
                            filtered
                            for tree in trees
                            if (
                                filtered := filter_tree(tree, parsed.filter)
                            )
                            is not None
                        )
                        if parsed.filter is not None
                        else trees
                    )
                    if len(trees) == 1:
                        rendered = (
                            render_tree(filtered_trees[0])
                            if filtered_trees
                            else ""
                        )
                    else:
                        rendered = render_tree(
                            TreeNode(direction.value.upper(), filtered_trees)
                        )
                    output.append(
                        rendered
                        if len(trees) > 1
                        else "\n".join(
                            part
                            for part in (
                                direction.value.upper(),
                                rendered,
                            )
                            if part
                        )
                    )
        except AwsCliError as error:
            print(f"awsi: error: {error}", file=sys.stderr)
            return 1
        print("\n\n".join(output))
    return 0
