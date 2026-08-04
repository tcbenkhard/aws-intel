"""Command-line entry point for AWS Intel."""

import argparse
from collections.abc import Sequence
import os
import re
import sys

from aws_intel import __version__
from aws_intel.console.gateway import AwsConsoleGateway, ConsoleError
from aws_intel.forwarding.config import ForwardConfig, ForwardConfigError
from aws_intel.forwarding.gateway import AwsCliForwardingGateway, ForwardingError
from aws_intel.forwarding.model import ActiveForward, PortMapping, SavedForward
from aws_intel.forwarding.registry import ForwardRegistry, ForwardRegistryError
from aws_intel.forwarding.selection import (
    ForwardSelectionError,
    select_active_forwards,
    select_forwards,
)
from aws_intel.init.generator import InitError, InitGenerator
from aws_intel.login.config import AccountConfig, AccountConfigError
from aws_intel.login.gateway import AwsCliLoginGateway, LoginError
from aws_intel.login.selection import (
    AccountSelectionError,
    select_account,
    select_elevated_access,
)
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
from aws_intel.shell.init import render_zsh_init
from aws_intel.version_check import notify_if_update_available

SECURITY_GROUP_ID = re.compile(r"^sg-[0-9a-fA-F]{8,17}$")
DEFAULT_SECURITY_GROUP_TREE_DEPTH = 1
MAX_SECURITY_GROUP_TREE_DEPTH = 3
EC2_INSTANCE_ID = re.compile(r"^i-[0-9a-fA-F]{8,17}$")
FORWARD_ACTIONS = {
    "start",
    "save",
    "active",
    "stop",
    "restart",
    "hosts",
    "list",
    "configs",
}


class AwsIntelArgumentParser(argparse.ArgumentParser):
    """Argument parser with access to the registered utility parsers."""

    utility_parsers: dict[str, argparse.ArgumentParser]


class UtilityHelpFormatter(argparse.HelpFormatter):
    """Keep utility names and their descriptions on the same line."""

    def __init__(self, prog: str) -> None:
        super().__init__(prog, max_help_position=30)


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


def _port_mapping(value: str) -> PortMapping:
    """Parse LOCAL_PORT:REMOTE_PORT into a validated mapping."""
    parts = value.split(":")
    if len(parts) != 2:
        raise argparse.ArgumentTypeError("must be LOCAL_PORT:REMOTE_PORT")
    try:
        local_port, remote_port = (int(part) for part in parts)
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            "ports must be integers in LOCAL_PORT:REMOTE_PORT"
        ) from error
    if not all(1 <= port <= 65535 for port in (local_port, remote_port)):
        raise argparse.ArgumentTypeError("ports must be between 1 and 65535")
    return PortMapping(local_port, remote_port)


def _add_forward_connection_arguments(
    parser: argparse.ArgumentParser,
) -> None:
    """Add arguments that describe one forwarding connection."""
    bastion = parser.add_mutually_exclusive_group()
    bastion.add_argument(
        "--instance-id",
        metavar="INSTANCE_ID",
        help="EC2 instance ID of the SSM-managed bastion.",
    )
    bastion.add_argument(
        "--instance-name",
        metavar="NAME",
        help="Exact EC2 Name tag of the SSM-managed bastion.",
    )
    parser.add_argument(
        "--host",
        help="Hostname or IP address reachable from the bastion host.",
    )
    parser.add_argument(
        "--port",
        type=_port_mapping,
        metavar="LOCAL_PORT:REMOTE_PORT",
        help="Map a local TCP port to a port on the remote host.",
    )


def _normalize_forward_arguments(arguments: Sequence[str]) -> list[str]:
    """Translate the original forward syntax into backward-compatible actions."""
    normalized = list(arguments)
    if not normalized or normalized[0] != "forward" or len(normalized) == 1:
        return normalized
    first = normalized[1]
    if first in FORWARD_ACTIONS or first in {"-h", "--help"}:
        return normalized
    legacy = normalized[1:]
    if "--list" in legacy:
        legacy.remove("--list")
        return ["forward", "active", *legacy]
    if "--list-hosts" in legacy:
        legacy.remove("--list-hosts")
        return ["forward", "hosts", *legacy]
    kill = next((item for item in legacy if item.startswith("--kill=")), None)
    if kill is not None:
        legacy.remove(kill)
        return ["forward", "stop", kill.partition("=")[2], *legacy]
    if "--kill" in legacy:
        index = legacy.index("--kill")
        if index + 1 < len(legacy):
            reference = legacy[index + 1]
            del legacy[index : index + 2]
            return ["forward", "stop", reference, *legacy]
    if "--save" in legacy:
        legacy.remove("--save")
        return ["forward", "save", *legacy]
    return ["forward", "start", *legacy]


def create_parser() -> AwsIntelArgumentParser:
    """Create the application's argument parser."""
    parser = AwsIntelArgumentParser(
        prog="awsi",
        usage="%(prog)s <utility> <options>",
        description="Retrieve useful information from AWS.",
        formatter_class=UtilityHelpFormatter,
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
        prog="awsi security-group-tree",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        help=(
            "Show attached resources, recursively connected security groups, "
            "and network ranges."
        ),
        description=(
            "Show attached resources and inbound and outbound security group "
            "connections. "
            "Uses the active AWS CLI credentials and region."
        ),
        epilog=(
            "Examples:\n"
            "  awsi security-group-tree sg-0123456789abcdef0\n"
            "  awsi security-group-tree sg-0123456789abcdef0 --depth 2\n"
            "  awsi security-group-tree sg-0123456789abcdef0 --inbound\n"
            "  awsi security-group-tree sg-0123456789abcdef0 --filter database"
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
    forward = utilities.add_parser(
        "forward",
        prog="awsi forward",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        help="Forward a local port through an SSM-managed EC2 instance.",
        description=(
            "Start an SSM port forwarding session through an online, managed "
            "EC2 instance to a remote host. Uses the active AWS CLI credentials "
            "and region."
        ),
        epilog=(
            "Examples:\n"
            "  awsi forward start\n"
            "  awsi forward start apigateway-dev\n"
            "  awsi forward save apigateway-dev --instance-name=bastion "
            "--host=api.internal --port=9072:9072\n"
            "  awsi forward active\n"
            "  awsi forward stop\n"
            "  awsi forward stop apigateway-dev\n"
            "  awsi forward restart apigateway-dev\n"
            "  awsi forward hosts\n"
            "  awsi forward list"
        ),
    )
    forward_actions = forward.add_subparsers(
        dest="forward_action", metavar="<action>", required=True
    )
    forward_start = forward_actions.add_parser(
        "start",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        help="Start a saved or explicitly described forward.",
        epilog=(
            "Examples:\n"
            "  awsi forward start\n"
            "  awsi forward start apigateway-dev\n"
            "  awsi forward start apigateway-dev --instance-name=bastion "
            "--host=api.internal --port=9072:9072\n"
            "\n"
            "Running 'awsi forward start' without a name prompts for one or "
            "more saved forwards to start."
        ),
    )
    forward_start.add_argument(
        "saved_forward",
        nargs="?",
        metavar="NAME",
        help=(
            "Name for the forward; loads that name from .awsi/forwards.yaml "
            "when connection options are omitted."
        ),
    )
    _add_forward_connection_arguments(forward_start)
    forward_save = forward_actions.add_parser(
        "save",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        help="Save a forward without starting it.",
        epilog=(
            "Example:\n"
            "  awsi forward save apigateway-dev --instance-name=bastion "
            "--host=api.internal --port=9072:9072"
        ),
    )
    forward_save.add_argument(
        "config_name",
        metavar="NAME",
        help="Name to add or replace in .awsi/forwards.yaml.",
    )
    _add_forward_connection_arguments(forward_save)
    forward_actions.add_parser(
        "active",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        help="List active forwarding sessions.",
        epilog="Example:\n  awsi forward active",
    )
    forward_stop = forward_actions.add_parser(
        "stop",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        help="Stop one or all active forwards.",
        epilog=(
            "Examples:\n"
            "  awsi forward stop\n"
            "  awsi forward stop apigateway-dev\n"
            "  awsi forward stop 40234\n"
            "  awsi forward stop --all\n"
            "\n"
            "Running 'awsi forward stop' without a name prompts for one or "
            "more active forwards to stop."
        ),
    )
    stop_target = forward_stop.add_mutually_exclusive_group(required=False)
    stop_target.add_argument("reference", nargs="?", metavar="NAME_OR_PID")
    stop_target.add_argument(
        "--all", action="store_true", help="Stop every active forward."
    )
    forward_restart = forward_actions.add_parser(
        "restart",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        help="Restart one or all active forwards.",
        epilog=(
            "Examples:\n"
            "  awsi forward restart apigateway-dev\n"
            "  awsi forward restart 40234\n"
            "  awsi forward restart --all"
        ),
    )
    restart_target = forward_restart.add_mutually_exclusive_group(required=True)
    restart_target.add_argument("reference", nargs="?", metavar="NAME_OR_PID")
    restart_target.add_argument(
        "--all", action="store_true", help="Restart every active forward."
    )
    forward_actions.add_parser(
        "hosts",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        help="List online SSM-managed EC2 bastion hosts.",
        epilog="Example:\n  awsi forward hosts",
    )
    forward_actions.add_parser(
        "list",
        aliases=["configs"],
        formatter_class=argparse.RawDescriptionHelpFormatter,
        help="List saved forwarding configurations.",
        epilog="Example:\n  awsi forward list",
    )
    login = utilities.add_parser(
        "login",
        prog="awsi login",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        help="Open a shell authenticated to a configured AWS account.",
        description=(
            "Log in with AWS IAM Identity Center, assume any configured role "
            "chain, and open a shell containing the resulting temporary "
            "credentials. Exit that shell to return to the previous session."
        ),
        epilog=(
            "Examples:\n"
            "  awsi login --list\n"
            "  awsi login example-development\n"
            "  awsi login example-development --elevated"
        ),
    )
    login_target = login.add_mutually_exclusive_group()
    login_target.add_argument(
        "account",
        nargs="?",
        help="Account name from .awsi/accounts.yaml.",
    )
    login_target.add_argument(
        "--list",
        action="store_true",
        help="List configured account names without logging in.",
    )
    login.add_argument(
        "--elevated",
        action="store_true",
        help="Use the account's temporary TEAM elevated role.",
    )
    utilities.add_parser(
        "console",
        prog="awsi console",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        help="Open the AWS Console for the current awsi login session.",
        description=(
            "Open the AWS Management Console in the default browser using "
            "credentials from the shell created by awsi login."
        ),
        epilog="Example:\n  awsi login\n  awsi console",
    )
    shell_init = utilities.add_parser(
        "shell-init",
        prog="awsi shell-init",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        help="Print shell integration code for the current shell.",
        description=(
            "Print code that labels an authenticated shell with its AWS "
            "account name. Evaluate it from the shell startup file."
        ),
        epilog='Example for ~/.zshrc:\n  eval "$(awsi shell-init zsh)"',
    )
    shell_init.add_argument(
        "shell",
        choices=("zsh",),
        help="Shell whose initialization code should be printed.",
    )
    init = utilities.add_parser(
        "init",
        prog="awsi init",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        help="Generate boilerplate .awsi configuration files.",
        description=(
            "Write example accounts.yaml and forwards.yaml files to .awsi, "
            "populated with anonymized placeholder values, for editing into "
            "a real configuration."
        ),
        epilog="Examples:\n  awsi init\n  awsi init --force",
    )
    init.add_argument(
        "--force",
        action="store_true",
        help="Overwrite any existing accounts.yaml or forwards.yaml.",
    )
    help_utility = utilities.add_parser(
        "help",
        prog="awsi help",
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


def _start_forward(
    parser: argparse.ArgumentParser,
    instance_id: str | None,
    instance_name: str | None,
    host: str,
    port_mapping: PortMapping,
    forward_name: str | None,
) -> int:
    """Resolve the bastion instance, start, and register one forward."""
    if instance_id is not None and not EC2_INSTANCE_ID.fullmatch(instance_id):
        parser.error(
            f"--instance-id {instance_id!r} must be an EC2 instance "
            "ID such as i-0123456789abcdef0"
        )
    try:
        gateway = AwsCliForwardingGateway()
        resolved_instance_id = instance_id
        if instance_name is not None:
            with spinner("Resolving bastion instance..."):
                resolved_instance_id = gateway.resolve_instance_name(instance_name)
        assert resolved_instance_id is not None
        registry = ForwardRegistry()
        registry.ensure_startable(resolved_instance_id, host, port_mapping)
        pid = gateway.start(resolved_instance_id, host, port_mapping)
        registry.add(
            ActiveForward(pid, resolved_instance_id, host, port_mapping, forward_name)
        )
    except (ForwardingError, ForwardRegistryError) as error:
        print(f"awsi: error: {error}", file=sys.stderr)
        return 1
    label = f" {forward_name!r}" if forward_name is not None else ""
    print(f"Forward{label} started in the background with PID {pid}.")
    return 0


def main(arguments: Sequence[str] | None = None) -> int:
    """Run the command-line application."""
    notify_if_update_available(__version__)
    parser = create_parser()
    raw_arguments = list(sys.argv[1:] if arguments is None else arguments)
    parsed = parser.parse_args(_normalize_forward_arguments(raw_arguments))
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
                            if (filtered := filter_tree(tree, parsed.filter))
                            is not None
                        )
                        if parsed.filter is not None
                        else trees
                    )
                    if len(trees) == 1:
                        rendered = (
                            render_tree(filtered_trees[0]) if filtered_trees else ""
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
    if parsed.utility == "login":
        try:
            config = AccountConfig()
            if parsed.list:
                print("ACCOUNT")
                for name in config.list_names():
                    print(name)
                return 0
            account = parsed.account
            standard_chain = None
            if account is None:
                account = select_account(config.list_names())
                if not parsed.elevated:
                    elevated_role = config.elevated_role_name(account)
                    if elevated_role is not None:
                        standard_chain = config.resolve_chain(account)
                        parsed.elevated = select_elevated_access(
                            standard_chain[-1].role_name,
                            elevated_role,
                        )
            chain = (
                config.resolve_elevated(account)
                if parsed.elevated
                else standard_chain or config.resolve_chain(account)
            )
            return AwsCliLoginGateway().open_shell(chain, elevated=parsed.elevated)
        except (AccountConfigError, AccountSelectionError, LoginError) as error:
            print(f"awsi: error: {error}", file=sys.stderr)
            return 1
    if parsed.utility == "console":
        try:
            AwsConsoleGateway().open(os.environ)
        except ConsoleError as error:
            print(f"awsi: error: {error}", file=sys.stderr)
            return 1
        print("Opened the AWS Management Console in the default browser.")
        return 0
    if parsed.utility == "shell-init":
        print(render_zsh_init())
        return 0
    if parsed.utility == "init":
        try:
            result = InitGenerator().generate(force=parsed.force)
        except InitError as error:
            print(f"awsi: error: {error}", file=sys.stderr)
            return 1
        for path in result.written:
            print(f"Wrote boilerplate configuration to {path}.")
        for path in result.skipped:
            print(
                f"Skipped {path} (already exists); use --force to overwrite."
            )
        return 0
    if parsed.utility == "forward":
        if parsed.forward_action == "active":
            try:
                forwards = ForwardRegistry().list_active()
            except ForwardRegistryError as error:
                print(f"awsi: error: {error}", file=sys.stderr)
                return 1
            print("PID\tNAME\tINSTANCE_ID\tHOST\tPORT")
            for forward in forwards:
                print(
                    f"{forward.pid}\t{forward.name or '-'}\t"
                    f"{forward.instance_id}\t{forward.host}\t"
                    f"{forward.port_mapping.local_port}:"
                    f"{forward.port_mapping.remote_port}"
                )
            return 0
        if parsed.forward_action in {"stop", "restart"}:
            selected_forwards: tuple[ActiveForward, ...] | None = None
            if (
                parsed.forward_action == "stop"
                and not parsed.all
                and parsed.reference is None
            ):
                try:
                    active_forwards = ForwardRegistry().list_active()
                    selected_forwards = select_active_forwards(active_forwards)
                except (ForwardRegistryError, ForwardSelectionError) as error:
                    print(f"awsi: error: {error}", file=sys.stderr)
                    return 1
            restarted: list[ActiveForward] = []
            try:
                registry = ForwardRegistry()
                if selected_forwards is not None:
                    targets = selected_forwards
                elif parsed.all:
                    targets = registry.list_active()
                else:
                    assert parsed.reference is not None
                    targets = (registry.resolve(parsed.reference),)
                stopped = tuple(
                    registry.terminate(str(forward.pid)) for forward in targets
                )
                if parsed.forward_action == "restart":
                    gateway = AwsCliForwardingGateway()
                    for forward in stopped:
                        pid = gateway.start(
                            forward.instance_id,
                            forward.host,
                            forward.port_mapping,
                        )
                        replacement = ActiveForward(
                            pid,
                            forward.instance_id,
                            forward.host,
                            forward.port_mapping,
                            forward.name,
                        )
                        registry.add(replacement)
                        restarted.append(replacement)
            except (ForwardingError, ForwardRegistryError) as error:
                print(f"awsi: error: {error}", file=sys.stderr)
                return 1
            if parsed.forward_action == "restart":
                for forward in restarted:
                    label = f" {forward.name!r}" if forward.name is not None else ""
                    print(
                        f"Forward{label} restarted in the background with PID "
                        f"{forward.pid}."
                    )
            else:
                for forward in stopped:
                    label = f" {forward.name!r}" if forward.name is not None else ""
                    print(f"Forward{label} with PID {forward.pid} was terminated.")
            return 0
        if parsed.forward_action == "hosts":
            try:
                with spinner("Loading potential bastion hosts..."):
                    hosts = AwsCliForwardingGateway().list_hosts()
            except ForwardingError as error:
                print(f"awsi: error: {error}", file=sys.stderr)
                return 1
            for bastion in hosts:
                print(
                    bastion.instance_id
                    if bastion.name is None
                    else f"{bastion.instance_id}\t{bastion.name}"
                )
            return 0
        if parsed.forward_action in {"list", "configs"}:
            try:
                saved_forwards = ForwardConfig().list()
            except ForwardConfigError as error:
                print(f"awsi: error: {error}", file=sys.stderr)
                return 1
            print("NAME\tINSTANCE\tHOST\tPORT")
            for saved in saved_forwards:
                instance = saved.instance_id or saved.instance_name
                print(
                    f"{saved.name}\t{instance}\t{saved.host}\t"
                    f"{saved.port_mapping.local_port}:"
                    f"{saved.port_mapping.remote_port}"
                )
            return 0
        if parsed.forward_action == "save":
            if parsed.instance_id is None and parsed.instance_name is None:
                parser.error("forward save requires --instance-id or --instance-name")
            if parsed.host is None:
                parser.error("forward save requires --host")
            if parsed.port is None:
                parser.error("forward save requires --port LOCAL_PORT:REMOTE_PORT")
            if parsed.instance_id is not None and not EC2_INSTANCE_ID.fullmatch(
                parsed.instance_id
            ):
                parser.error(
                    f"--instance-id {parsed.instance_id!r} must be an EC2 "
                    "instance ID such as i-0123456789abcdef0"
                )
            configuration = ForwardConfig()
            try:
                configuration.save(
                    SavedForward(
                        name=parsed.config_name,
                        instance_id=parsed.instance_id,
                        instance_name=parsed.instance_name,
                        host=parsed.host,
                        port_mapping=parsed.port,
                    )
                )
            except ForwardConfigError as error:
                print(f"awsi: error: {error}", file=sys.stderr)
                return 1
            print(f"Forward {parsed.config_name!r} saved to {configuration.path}.")
            return 0

        assert parsed.forward_action == "start"
        has_connection_options = any(
            value is not None
            for value in (
                parsed.instance_id,
                parsed.instance_name,
                parsed.host,
                parsed.port,
            )
        )
        if parsed.saved_forward is None and not has_connection_options:
            try:
                saved_names = tuple(saved.name for saved in ForwardConfig().list())
                selected_names = select_forwards(saved_names)
            except (ForwardConfigError, ForwardSelectionError) as error:
                print(f"awsi: error: {error}", file=sys.stderr)
                return 1
            exit_code = 0
            for name in selected_names:
                try:
                    saved_forward = ForwardConfig().load(name)
                except ForwardConfigError as error:
                    print(f"awsi: error: {error}", file=sys.stderr)
                    exit_code = 1
                    continue
                exit_code = (
                    _start_forward(
                        parser,
                        saved_forward.instance_id,
                        saved_forward.instance_name,
                        saved_forward.host,
                        saved_forward.port_mapping,
                        saved_forward.name,
                    )
                    or exit_code
                )
            return exit_code

        forward_name = parsed.saved_forward
        if parsed.saved_forward is not None:
            if has_connection_options:
                forward_name = parsed.saved_forward
            else:
                try:
                    saved_forward = ForwardConfig().load(parsed.saved_forward)
                except ForwardConfigError as error:
                    print(f"awsi: error: {error}", file=sys.stderr)
                    return 1
                parsed.instance_id = saved_forward.instance_id
                parsed.instance_name = saved_forward.instance_name
                parsed.host = saved_forward.host
                parsed.port = saved_forward.port_mapping
                forward_name = saved_forward.name

        if parsed.instance_id is None and parsed.instance_name is None:
            parser.error(
                "forward start requires --instance-id, --instance-name, or "
                "a saved forward name"
            )
        if parsed.host is None:
            parser.error("forward requires --host")
        if parsed.port is None:
            parser.error("forward requires --port LOCAL_PORT:REMOTE_PORT")
        return _start_forward(
            parser,
            parsed.instance_id,
            parsed.instance_name,
            parsed.host,
            parsed.port,
            forward_name,
        )
    return 0
