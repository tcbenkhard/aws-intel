"""Persistent configuration for named port forwarding definitions."""

from pathlib import Path
from tempfile import NamedTemporaryFile

import yaml

from aws_intel.forwarding.model import PortMapping, SavedForward


class ForwardConfigError(RuntimeError):
    """Raised when forwarding configuration cannot be read or written."""


class ForwardConfig:
    """Add or replace named forwards in the user's YAML configuration."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or Path.cwd() / ".awsi" / "forwards.yaml"

    @property
    def path(self) -> Path:
        return self._path

    def save(self, forward: SavedForward) -> None:
        forwards = self._read()
        forwards[forward.name] = self._serialize(forward)
        self._write({"forwards": forwards})

    def load(self, name: str) -> SavedForward:
        """Load one named forwarding definition."""
        definition = self._read().get(name)
        if definition is None:
            raise ForwardConfigError(
                f"no forward named {name!r} in {self._path}"
            )
        try:
            return self._deserialize(name, definition)
        except (KeyError, TypeError, ValueError) as error:
            raise ForwardConfigError(
                f"forward {name!r} in {self._path} is invalid"
            ) from error

    def list(self) -> tuple[SavedForward, ...]:
        """Load all saved forwarding definitions in file order."""
        definitions = self._read()
        try:
            return tuple(
                self._deserialize(name, definition)
                for name, definition in definitions.items()
            )
        except (KeyError, TypeError, ValueError) as error:
            raise ForwardConfigError(
                f"could not read forwarding configuration from {self._path}"
            ) from error

    def _read(self) -> dict[str, object]:
        if not self._path.exists():
            return {}
        try:
            document = yaml.safe_load(self._path.read_text(encoding="utf-8"))
            if document is None:
                return {}
            if not isinstance(document, dict):
                raise TypeError
            forwards = document.get("forwards", {})
            if not isinstance(forwards, dict) or not all(
                isinstance(name, str) and isinstance(value, dict)
                for name, value in forwards.items()
            ):
                raise TypeError
            return dict(forwards)
        except (OSError, TypeError, yaml.YAMLError) as error:
            raise ForwardConfigError(
                f"could not read forwarding configuration from {self._path}"
            ) from error

    def _write(self, document: dict[str, object]) -> None:
        temporary_path: Path | None = None
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
                yaml.safe_dump(document, temporary, sort_keys=False)
                temporary_path = Path(temporary.name)
            temporary_path.replace(self._path)
        except OSError as error:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
            raise ForwardConfigError(
                f"could not write forwarding configuration to {self._path}"
            ) from error

    @staticmethod
    def _serialize(forward: SavedForward) -> dict[str, object]:
        definition: dict[str, object] = {}
        if forward.instance_id is not None:
            definition["instance-id"] = forward.instance_id
        if forward.instance_name is not None:
            definition["instance-name"] = forward.instance_name
        definition["host"] = forward.host
        definition["port"] = (
            f"{forward.port_mapping.local_port}:"
            f"{forward.port_mapping.remote_port}"
        )
        return definition

    @staticmethod
    def _deserialize(name: str, definition: object) -> SavedForward:
        if not isinstance(definition, dict):
            raise TypeError
        instance_id = definition.get("instance-id")
        instance_name = definition.get("instance-name")
        host = definition["host"]
        port = definition["port"]
        if (
            (instance_id is None) == (instance_name is None)
            or (instance_id is not None and not isinstance(instance_id, str))
            or (instance_name is not None and not isinstance(instance_name, str))
            or not isinstance(host, str)
            or not isinstance(port, str)
        ):
            raise TypeError
        port_parts = port.split(":")
        if len(port_parts) != 2:
            raise ValueError
        local_port, remote_port = (int(part) for part in port_parts)
        if not all(1 <= value <= 65535 for value in (local_port, remote_port)):
            raise ValueError
        return SavedForward(
            name=name,
            instance_id=instance_id,
            instance_name=instance_name,
            host=host,
            port_mapping=PortMapping(local_port, remote_port),
        )
