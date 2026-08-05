"""Tests for boilerplate .awsi configuration documents."""

from pathlib import Path

import yaml

from aws_intel.forwarding.config import ForwardConfig
from aws_intel.init.templates import (
    boilerplate_accounts_document,
    boilerplate_forwards_document,
)
from aws_intel.login.config import AccountConfig


def test_accounts_document_resolves_as_a_valid_chain(tmp_path: Path) -> None:
    path = tmp_path / "accounts.yaml"
    path.write_text(
        yaml.safe_dump(boilerplate_accounts_document(), sort_keys=False),
        encoding="utf-8",
    )
    config = AccountConfig(path)

    chain = config.resolve_chain("example-chained")

    assert [account.name for account in chain] == ["example-source", "example-chained"]
    source, chained = chain
    assert source.sso_start_url is not None
    assert source.sso_region is not None
    assert source.source is None
    assert chained.source == "example-source"
    assert chained.session_duration_hours is not None
    assert config.elevated_role_name("example-source") is not None
    assert config.elevated_role_name("example-chained") is not None


def test_accounts_document_resolves_elevated_access_for_both_accounts(
    tmp_path: Path,
) -> None:
    path = tmp_path / "accounts.yaml"
    path.write_text(
        yaml.safe_dump(boilerplate_accounts_document(), sort_keys=False),
        encoding="utf-8",
    )
    config = AccountConfig(path)

    for name in ("example-source", "example-chained"):
        elevated = config.resolve_elevated(name)
        assert elevated[-1].name == name
        assert elevated[0].sso_start_url is not None
        assert elevated[0].sso_region is not None
        assert elevated[-1].role_name == config.elevated_role_name(name)
        if len(elevated) > 1:
            assert elevated[0].role_name == "ExampleSourceElevatedRole"


def test_forwards_document_loads_as_a_valid_forward(tmp_path: Path) -> None:
    path = tmp_path / "forwards.yaml"
    path.write_text(
        yaml.safe_dump(boilerplate_forwards_document(), sort_keys=False),
        encoding="utf-8",
    )

    forward = ForwardConfig(path).load("example-forward")

    assert forward.instance_id is not None
    assert forward.instance_name is None
    assert forward.host
    assert forward.port_mapping.local_port and forward.port_mapping.remote_port
