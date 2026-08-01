"""Tests for account chain configuration."""

from pathlib import Path

import pytest

from aws_intel.login.config import AccountConfig, AccountConfigError


def test_lists_account_names_in_configuration_order(tmp_path: Path) -> None:
    path = tmp_path / "accounts.yaml"
    path.write_text(
        """
version: 1
accounts:
  production:
    account_id: "111111111111"
    role_name: standard-access
  development:
    account_id: "222222222222"
    role_name: standard-access
""",
        encoding="utf-8",
    )

    assert AccountConfig(path).list_names() == ("production", "development")


def test_resolves_a_chain_from_sso_root_to_target(tmp_path: Path) -> None:
    path = tmp_path / "accounts.yaml"
    path.write_text(
        """
version: 1
accounts:
  hub:
    account_id: "111111111111"
    role_name: standard-access
    sso_start_url: https://example.awsapps.com/start
    sso_region: eu-west-1
    region: eu-west-1
  target:
    account_id: "222222222222"
    role_name: standard-access
    source: hub
    region: eu-central-1
""",
        encoding="utf-8",
    )

    chain = AccountConfig(path).resolve_chain("target")

    assert [account.name for account in chain] == ["hub", "target"]
    assert chain[0].sso_start_url == "https://example.awsapps.com/start"
    assert chain[1].source == "hub"


def test_rejects_a_chain_cycle(tmp_path: Path) -> None:
    path = tmp_path / "accounts.yaml"
    path.write_text(
        """
version: 1
accounts:
  first:
    account_id: "111111111111"
    role_name: standard-access
    source: second
  second:
    account_id: "222222222222"
    role_name: standard-access
    source: first
""",
        encoding="utf-8",
    )

    with pytest.raises(AccountConfigError, match="contains a cycle"):
        AccountConfig(path).resolve_chain("first")


def test_resolves_team_access_as_direct_sso_login(tmp_path: Path) -> None:
    path = tmp_path / "accounts.yaml"
    path.write_text(
        """
version: 1
accounts:
  hub:
    account_id: "111111111111"
    role_name: standard-access
    sso_start_url: https://example.awsapps.com/start
    sso_region: eu-west-1
  target:
    account_id: "222222222222"
    role_name: standard-access
    source: hub
    region: eu-central-1
    elevated_access:
      provider: team
      role_name: elevated-access
""",
        encoding="utf-8",
    )

    chain = AccountConfig(path).resolve_elevated("target")

    assert len(chain) == 1
    assert chain[0].name == "target"
    assert chain[0].role_name == "elevated-access"
    assert chain[0].account_id == "222222222222"
    assert chain[0].sso_start_url == "https://example.awsapps.com/start"
    assert chain[0].sso_region == "eu-west-1"
    assert AccountConfig(path).elevated_role_name("target") == "elevated-access"


def test_elevated_login_requires_team_configuration(tmp_path: Path) -> None:
    path = tmp_path / "accounts.yaml"
    path.write_text(
        """
version: 1
accounts:
  hub:
    account_id: "111111111111"
    role_name: standard-access
    sso_start_url: https://example.awsapps.com/start
    sso_region: eu-west-1
""",
        encoding="utf-8",
    )

    with pytest.raises(AccountConfigError, match="TEAM elevated access"):
        AccountConfig(path).resolve_elevated("hub")


def test_root_requires_sso_configuration(tmp_path: Path) -> None:
    path = tmp_path / "accounts.yaml"
    path.write_text(
        """
version: 1
accounts:
  hub:
    account_id: "111111111111"
    role_name: standard-access
    region: eu-west-1
""",
        encoding="utf-8",
    )

    with pytest.raises(AccountConfigError, match="must define sso_start_url"):
        AccountConfig(path).resolve_chain("hub")
