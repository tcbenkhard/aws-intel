"""Tests for saved forwarding configuration."""

from pathlib import Path

import pytest
import yaml

from aws_intel.forwarding.config import ForwardConfig, ForwardConfigError
from aws_intel.forwarding.model import PortMapping, SavedForward


def test_default_path_is_under_current_working_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)

    assert ForwardConfig().path == tmp_path / ".awsi" / "forwards.yaml"


def test_saves_named_forward_to_yaml(tmp_path: Path) -> None:
    path = tmp_path / ".awsi" / "forwards.yaml"

    ForwardConfig(path).save(
        SavedForward(
            name="apigateway-dev",
            instance_name="solo-connect-bastion-dev",
            host="api.internal",
            port_mapping=PortMapping(9072, 9072),
        )
    )

    assert yaml.safe_load(path.read_text(encoding="utf-8")) == {
        "forwards": {
            "apigateway-dev": {
                "instance-name": "solo-connect-bastion-dev",
                "host": "api.internal",
                "port": "9072:9072",
            }
        }
    }


def test_loads_named_forward_from_yaml(tmp_path: Path) -> None:
    path = tmp_path / "forwards.yaml"
    path.write_text(
        "forwards:\n"
        "  apigateway:\n"
        "    instance-name: bastion\n"
        "    host: api.internal\n"
        "    port: 9072:443\n",
        encoding="utf-8",
    )

    assert ForwardConfig(path).load("apigateway") == SavedForward(
        name="apigateway",
        instance_name="bastion",
        host="api.internal",
        port_mapping=PortMapping(9072, 443),
    )


def test_lists_saved_forwards_in_file_order(tmp_path: Path) -> None:
    path = tmp_path / "forwards.yaml"
    config = ForwardConfig(path)
    config.save(
        SavedForward("database", "db.internal", PortMapping(5432, 5432), "i-01234567")
    )
    config.save(
        SavedForward(
            "api",
            "api.internal",
            PortMapping(8080, 80),
            instance_name="bastion",
        )
    )

    assert tuple(item.name for item in config.list()) == ("database", "api")

def test_reports_unknown_saved_forward(tmp_path: Path) -> None:
    path = tmp_path / "forwards.yaml"

    with pytest.raises(ForwardConfigError, match="no forward named 'missing'"):
        ForwardConfig(path).load("missing")


def test_save_preserves_other_forwards_and_replaces_same_name(
    tmp_path: Path,
) -> None:
    path = tmp_path / "forwards.yaml"
    config = ForwardConfig(path)
    config.save(
        SavedForward("database", "db.internal", PortMapping(5432, 5432), "i-01234567")
    )
    config.save(
        SavedForward("api", "api.internal", PortMapping(8080, 80), "i-11111111")
    )
    config.save(
        SavedForward("database", "new-db.internal", PortMapping(15432, 5432), "i-01234567")
    )

    forwards = yaml.safe_load(path.read_text(encoding="utf-8"))["forwards"]
    assert tuple(forwards) == ("database", "api")
    assert forwards["database"]["host"] == "new-db.internal"
    assert forwards["database"]["port"] == "15432:5432"


def test_rejects_invalid_existing_configuration(tmp_path: Path) -> None:
    path = tmp_path / "forwards.yaml"
    path.write_text("forwards: invalid\n", encoding="utf-8")

    with pytest.raises(ForwardConfigError, match="could not read"):
        ForwardConfig(path).save(
            SavedForward("api", "api.internal", PortMapping(8080, 80), "i-11111111")
        )
