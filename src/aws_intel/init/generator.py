"""Write boilerplate .awsi configuration files to disk."""

from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile

import yaml

from aws_intel.init.templates import (
    boilerplate_accounts_document,
    boilerplate_forwards_document,
)


class InitError(RuntimeError):
    """Raised when boilerplate configuration cannot be written."""


@dataclass(frozen=True)
class InitResult:
    """Paths written and skipped while generating boilerplate configuration."""

    written: tuple[Path, ...]
    skipped: tuple[Path, ...]


class InitGenerator:
    """Generate boilerplate accounts.yaml and forwards.yaml files."""

    def __init__(self, directory: Path | None = None) -> None:
        self._directory = directory or Path.cwd() / ".awsi"

    def generate(self, force: bool = False) -> InitResult:
        """Write boilerplate configuration files, skipping existing ones.

        When force is True, existing files are overwritten instead of
        skipped.
        """
        files = (
            (self._directory / "accounts.yaml", boilerplate_accounts_document()),
            (self._directory / "forwards.yaml", boilerplate_forwards_document()),
        )
        written: list[Path] = []
        skipped: list[Path] = []
        for path, document in files:
            if path.exists() and not force:
                skipped.append(path)
                continue
            self._write(path, document)
            written.append(path)
        return InitResult(written=tuple(written), skipped=tuple(skipped))

    @staticmethod
    def _write(path: Path, document: dict[str, object]) -> None:
        temporary_path: Path | None = None
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=path.parent,
                prefix=f"{path.stem}-",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                yaml.safe_dump(document, temporary, sort_keys=False)
                temporary_path = Path(temporary.name)
            temporary_path.replace(path)
        except OSError as error:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
            raise InitError(f"could not write configuration to {path}") from error
