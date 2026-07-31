"""Persistent registry of background forwarding processes."""

import json
import os
from pathlib import Path
import signal
from tempfile import NamedTemporaryFile

from aws_intel.forwarding.model import ActiveForward, PortMapping


class ForwardRegistryError(RuntimeError):
    """Raised when saved forwarding state cannot be read or written."""


class ForwardNotFoundError(ForwardRegistryError):
    """Raised when no active registered forward matches a reference."""


class ForwardRegistry:
    """Store forwards launched by awsi and discard completed processes."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or self._default_path()

    def add(self, forward: ActiveForward) -> None:
        forwards = self._read()
        forwards.append(forward)
        self._write(forwards)

    def list_active(self) -> tuple[ActiveForward, ...]:
        forwards = self._read()
        active = [forward for forward in forwards if self._is_running(forward.pid)]
        if active != forwards:
            self._write(active)
        return tuple(active)

    def terminate(self, reference: str) -> ActiveForward:
        """Terminate one active forward, resolving names before process IDs."""
        forwards = list(self.list_active())
        named = [forward for forward in forwards if forward.name == reference]
        if len(named) > 1:
            raise ForwardRegistryError(
                f"multiple active forwards are named {reference!r}; use a PID"
            )
        if named:
            selected = named[0]
        else:
            try:
                pid = int(reference)
            except ValueError as error:
                raise ForwardNotFoundError(
                    f"no active forward matches {reference!r}"
                ) from error
            selected = next(
                (forward for forward in forwards if forward.pid == pid), None
            )
            if selected is None:
                raise ForwardNotFoundError(
                    f"no active forward matches {reference!r}"
                )
        try:
            os.killpg(selected.pid, signal.SIGTERM)
        except ProcessLookupError as error:
            self._write(
                [forward for forward in forwards if forward != selected]
            )
            raise ForwardNotFoundError(
                f"forward {reference!r} is no longer running"
            ) from error
        except PermissionError as error:
            raise ForwardRegistryError(
                f"permission denied while terminating forward {reference!r}"
            ) from error
        self._write([forward for forward in forwards if forward != selected])
        return selected

    @staticmethod
    def _default_path() -> Path:
        state_home = os.environ.get("XDG_STATE_HOME")
        root = Path(state_home) if state_home else Path.home() / ".local" / "state"
        return root / "aws-intel" / "forwards.json"

    @staticmethod
    def _is_running(pid: int) -> bool:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True

    def _read(self) -> list[ActiveForward]:
        if not self._path.exists():
            return []
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
            if not isinstance(payload, list):
                raise TypeError
            return [self._deserialize(item) for item in payload]
        except (
            OSError,
            json.JSONDecodeError,
            KeyError,
            TypeError,
            ValueError,
        ) as error:
            raise ForwardRegistryError(
                f"could not read forwarding state from {self._path}"
            ) from error

    def _write(self, forwards: list[ActiveForward]) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=self._path.parent,
                prefix="forwards-",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                json.dump([self._serialize(item) for item in forwards], temporary)
                temporary_path = Path(temporary.name)
            temporary_path.replace(self._path)
        except OSError as error:
            raise ForwardRegistryError(
                f"could not write forwarding state to {self._path}"
            ) from error

    @staticmethod
    def _serialize(forward: ActiveForward) -> dict[str, object]:
        return {
            "pid": forward.pid,
            "instance_id": forward.instance_id,
            "host": forward.host,
            "local_port": forward.port_mapping.local_port,
            "remote_port": forward.port_mapping.remote_port,
            "name": forward.name,
        }

    @staticmethod
    def _deserialize(item: object) -> ActiveForward:
        if not isinstance(item, dict):
            raise TypeError
        pid = item["pid"]
        instance_id = item["instance_id"]
        host = item["host"]
        local_port = item["local_port"]
        remote_port = item["remote_port"]
        name = item.get("name")
        if (
            not isinstance(pid, int)
            or isinstance(pid, bool)
            or not isinstance(instance_id, str)
            or not isinstance(host, str)
            or not isinstance(local_port, int)
            or isinstance(local_port, bool)
            or not isinstance(remote_port, int)
            or isinstance(remote_port, bool)
            or (name is not None and not isinstance(name, str))
        ):
            raise TypeError
        return ActiveForward(
            pid,
            instance_id,
            host,
            PortMapping(local_port, remote_port),
            name,
        )
