"""AWS CLI boundary for SSM port forwarding."""

from collections.abc import Callable
import json
import socket
import subprocess

from aws_intel.forwarding.model import BastionHost, PortMapping

CommandRunner = Callable[..., subprocess.CompletedProcess[str]]
ProcessStarter = Callable[..., subprocess.Popen[bytes]]
LocalPortChecker = Callable[[int], bool]
REMOTE_HOST_DOCUMENT = "AWS-StartPortForwardingSessionToRemoteHost"
NOT_LOGGED_IN_MESSAGE = (
    "no active AWS session was found; run 'awsi login' to authenticate"
)
NOT_LOGGED_IN_DIAGNOSTICS = (
    "you must specify a region",
    "unable to locate credentials",
    "the security token included in the request is expired",
    "the config profile",
)


class ForwardingError(RuntimeError):
    """Raised when an AWS CLI forwarding operation fails."""


class AwsCliForwardingGateway:
    """Discover bastions and start forwarding using the caller's AWS CLI."""

    def __init__(
        self,
        runner: CommandRunner = subprocess.run,
        process_starter: ProcessStarter = subprocess.Popen,
        local_port_checker: LocalPortChecker | None = None,
    ) -> None:
        self._runner = runner
        self._process_starter = process_starter
        self._local_port_checker = local_port_checker or self._is_local_port_available

    def list_hosts(self) -> tuple[BastionHost, ...]:
        """Return online EC2 instances managed by Systems Manager."""
        response = self._run_json(
            [
                "aws",
                "ssm",
                "describe-instance-information",
                "--filters",
                "Key=PingStatus,Values=Online",
                "Key=ResourceType,Values=EC2Instance",
                "--output",
                "json",
                "--no-cli-pager",
            ]
        )
        try:
            information = response["InstanceInformationList"]
            if not isinstance(information, list):
                raise TypeError
            instance_ids = [
                item["InstanceId"]
                for item in information
                if isinstance(item, dict)
                and isinstance(item.get("InstanceId"), str)
            ]
            if len(instance_ids) != len(information):
                raise TypeError
        except (KeyError, TypeError) as error:
            raise ForwardingError(
                "AWS CLI returned an unexpected response."
            ) from error

        names = self._get_instance_names(instance_ids)
        return tuple(
            BastionHost(instance_id, names.get(instance_id))
            for instance_id in sorted(instance_ids)
        )

    def start(
        self, instance_id: str, host: str, port_mapping: PortMapping
    ) -> int:
        """Start a remote-host forwarding session in the background."""
        if not self._local_port_checker(port_mapping.local_port):
            raise ForwardingError(
                f"local port {port_mapping.local_port} is already in use"
            )
        try:
            process = self._process_starter(
                [
                    "aws",
                    "ssm",
                    "start-session",
                    "--target",
                    instance_id,
                    "--document-name",
                    REMOTE_HOST_DOCUMENT,
                    "--parameters",
                    json.dumps(
                        {
                            "host": [host],
                            "portNumber": [str(port_mapping.remote_port)],
                            "localPortNumber": [str(port_mapping.local_port)],
                        },
                        separators=(",", ":"),
                    ),
                    "--no-cli-pager",
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except FileNotFoundError as error:
            raise ForwardingError(
                "AWS CLI was not found. Install it and ensure 'aws' is on PATH."
            ) from error
        return process.pid

    @staticmethod
    def _is_local_port_available(port: int) -> bool:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
                listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                listener.bind(("127.0.0.1", port))
        except OSError:
            return False
        return True

    def resolve_instance_name(self, name: str) -> str:
        """Resolve an exact Name tag to one active EC2 instance ID."""
        instance_ids = self._find_active_instances("tag:Name", name)
        if not instance_ids:
            raise ForwardingError(
                f"no active EC2 instance has the Name tag {name!r}"
            )
        if len(instance_ids) > 1:
            raise ForwardingError(
                f"multiple active EC2 instances have the Name tag {name!r}: "
                + ", ".join(sorted(instance_ids))
            )
        return instance_ids[0]

    def _find_active_instances(
        self, filter_name: str, filter_value: str
    ) -> list[str]:
        """Return active instance IDs matching one EC2 filter."""
        response = self._run_json(
            [
                "aws",
                "ec2",
                "describe-instances",
                "--filters",
                json.dumps(
                    [
                        {"Name": filter_name, "Values": [filter_value]},
                        {
                            "Name": "instance-state-name",
                            "Values": ["pending", "running"],
                        },
                    ],
                    separators=(",", ":"),
                ),
                "--output",
                "json",
                "--no-cli-pager",
            ]
        )
        try:
            reservations = response["Reservations"]
            if not isinstance(reservations, list):
                raise TypeError
            instance_ids = []
            for reservation in reservations:
                if not isinstance(reservation, dict):
                    raise TypeError
                instances = reservation["Instances"]
                if not isinstance(instances, list):
                    raise TypeError
                for instance in instances:
                    if not isinstance(instance, dict):
                        raise TypeError
                    instance_id = instance["InstanceId"]
                    if not isinstance(instance_id, str):
                        raise TypeError
                    instance_ids.append(instance_id)
        except (KeyError, TypeError) as error:
            raise ForwardingError(
                "AWS CLI returned an unexpected response."
            ) from error

        return instance_ids

    def _get_instance_names(self, instance_ids: list[str]) -> dict[str, str]:
        if not instance_ids:
            return {}
        response = self._run_json(
            [
                "aws",
                "ec2",
                "describe-instances",
                "--instance-ids",
                *instance_ids,
                "--output",
                "json",
                "--no-cli-pager",
            ]
        )
        try:
            reservations = response["Reservations"]
            if not isinstance(reservations, list):
                raise TypeError
            names: dict[str, str] = {}
            for reservation in reservations:
                instances = reservation["Instances"]
                if not isinstance(instances, list):
                    raise TypeError
                for instance in instances:
                    instance_id = instance["InstanceId"]
                    if not isinstance(instance_id, str):
                        raise TypeError
                    tags = instance.get("Tags", [])
                    if not isinstance(tags, list):
                        raise TypeError
                    for tag in tags:
                        if (
                            isinstance(tag, dict)
                            and tag.get("Key") == "Name"
                            and isinstance(tag.get("Value"), str)
                        ):
                            names[instance_id] = tag["Value"]
                            break
            return names
        except (KeyError, TypeError) as error:
            raise ForwardingError(
                "AWS CLI returned an unexpected response."
            ) from error

    @staticmethod
    def _looks_like_not_logged_in(diagnostic: str) -> bool:
        lowered = diagnostic.lower()
        return any(
            fragment in lowered for fragment in NOT_LOGGED_IN_DIAGNOSTICS
        )

    def _run_json(self, command: list[str]) -> dict[str, object]:
        """Run an AWS CLI query; the AWS CLI paginates automatically."""
        try:
            result = self._runner(
                command,
                capture_output=True,
                check=False,
                text=True,
            )
        except FileNotFoundError as error:
            raise ForwardingError(
                "AWS CLI was not found. Install it and ensure 'aws' is on PATH."
            ) from error
        if result.returncode != 0:
            diagnostic = result.stderr.strip() or "AWS CLI exited unsuccessfully"
            if self._looks_like_not_logged_in(diagnostic):
                raise ForwardingError(NOT_LOGGED_IN_MESSAGE)
            raise ForwardingError(diagnostic)
        try:
            response = json.loads(result.stdout)
            if not isinstance(response, dict):
                raise TypeError
            return response
        except (json.JSONDecodeError, TypeError) as error:
            raise ForwardingError(
                "AWS CLI returned an unexpected response."
            ) from error
