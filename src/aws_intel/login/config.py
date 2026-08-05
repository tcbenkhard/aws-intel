"""Load account login chains from .awsi/accounts.yaml."""

from dataclasses import replace
from pathlib import Path
import re

import yaml

from aws_intel.login.model import Account

ACCOUNT_ID = re.compile(r"^[0-9]{12}$")


class AccountConfigError(RuntimeError):
    """Raised when account configuration is missing or invalid."""


class AccountConfig:
    """Read and resolve named AWS accounts."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or Path.cwd() / ".awsi" / "accounts.yaml"

    def list_names(self) -> tuple[str, ...]:
        """Return configured account names in configuration-file order."""
        return tuple(self._read())

    def elevated_role_name(self, name: str) -> str | None:
        """Return the configured TEAM role, if the account has one."""
        elevated_access = self._elevated_access(name)
        return elevated_access[0] if elevated_access is not None else None

    def _elevated_access(self, name: str) -> tuple[str, str | None] | None:
        """Return the target and optional source roles for elevated access."""
        accounts = self._read()
        definition = accounts.get(name)
        if definition is None:
            raise AccountConfigError(f"no account named {name!r} in {self._path}")
        if not isinstance(definition, dict):
            raise AccountConfigError(f"account {name!r} in {self._path} is invalid")
        elevated_access = definition.get("elevated_access")
        if elevated_access is None:
            return None
        try:
            if not isinstance(elevated_access, dict):
                raise TypeError
            provider = elevated_access.get("provider")
            role_name = elevated_access["role_name"]
            source_role = elevated_access.get("source_role")
            if (
                provider != "team"
                or not isinstance(role_name, str)
                or not role_name
                or (
                    source_role is not None
                    and (not isinstance(source_role, str) or not source_role)
                )
            ):
                raise TypeError
            return role_name, source_role
        except (KeyError, TypeError) as error:
            raise AccountConfigError(
                f"account {name!r} does not define valid TEAM elevated access"
            ) from error

    def resolve_chain(self, name: str) -> tuple[Account, ...]:
        accounts = self._read()
        chain: list[Account] = []
        seen: set[str] = set()
        current = name
        while True:
            if current in seen:
                raise AccountConfigError(
                    f"account chain for {name!r} contains a cycle at {current!r}"
                )
            seen.add(current)
            definition = accounts.get(current)
            if definition is None:
                raise AccountConfigError(
                    f"no account named {current!r} in {self._path}"
                )
            account = self._deserialize(current, definition)
            chain.append(account)
            if account.source is None:
                break
            current = account.source
        chain.reverse()
        root = chain[0]
        if root.sso_start_url is None or root.sso_region is None:
            raise AccountConfigError(
                f"root account {root.name!r} must define sso_start_url and sso_region"
            )
        return tuple(chain)

    def resolve_elevated(self, name: str) -> tuple[Account, ...]:
        """Resolve a chain with elevated target and optional source roles."""
        chain = self.resolve_chain(name)
        elevated_access = self._elevated_access(name)
        if elevated_access is None:
            raise AccountConfigError(
                f"account {name!r} does not define TEAM elevated access"
            )
        role_name, source_role = elevated_access

        sources = chain[:-1]
        if source_role is not None:
            sources = tuple(
                replace(account, role_name=source_role) for account in sources
            )
        return (*sources, replace(chain[-1], role_name=role_name))

    def _read(self) -> dict[str, object]:
        try:
            document = yaml.safe_load(self._path.read_text(encoding="utf-8"))
            if not isinstance(document, dict) or document.get("version") != 1:
                raise TypeError
            accounts = document.get("accounts")
            if not isinstance(accounts, dict) or not all(
                isinstance(name, str) and isinstance(value, dict)
                for name, value in accounts.items()
            ):
                raise TypeError
            return dict(accounts)
        except FileNotFoundError as error:
            raise AccountConfigError(
                f"account configuration was not found at {self._path}"
            ) from error
        except (OSError, TypeError, yaml.YAMLError) as error:
            raise AccountConfigError(
                f"could not read account configuration from {self._path}"
            ) from error

    def _deserialize(self, name: str, definition: object) -> Account:
        try:
            if not isinstance(definition, dict):
                raise TypeError
            account_id = definition["account_id"]
            role_name = definition["role_name"]
            region = definition.get("region", "eu-west-1")
            source = definition.get("source")
            sso_start_url = definition.get("sso_start_url")
            sso_region = definition.get("sso_region")
            elevated_access = definition.get("elevated_access")
            session_duration_hours = definition.get("session_duration_hours")
            string_values = (role_name, region, source, sso_start_url, sso_region)
            if (
                not isinstance(account_id, str)
                or not ACCOUNT_ID.fullmatch(account_id)
                or not all(value is None or isinstance(value, str) for value in string_values)
                or not role_name
                or not region
                or source == name
                or (
                    elevated_access is not None
                    and not isinstance(elevated_access, dict)
                )
            ):
                raise TypeError
            if source is not None and (sso_start_url is not None or sso_region is not None):
                raise TypeError
            if session_duration_hours is not None and (
                isinstance(session_duration_hours, bool)
                or not isinstance(session_duration_hours, int)
                or not 1 <= session_duration_hours <= 12
            ):
                raise TypeError
            if session_duration_hours is not None and source is None:
                raise TypeError
            return Account(
                name=name,
                account_id=account_id,
                role_name=role_name,
                region=region,
                source=source,
                sso_start_url=sso_start_url,
                sso_region=sso_region,
                session_duration_hours=session_duration_hours,
            )
        except (KeyError, TypeError) as error:
            raise AccountConfigError(
                f"account {name!r} in {self._path} is invalid"
            ) from error
