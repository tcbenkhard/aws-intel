"""Tests for boilerplate .awsi configuration generation."""

from pathlib import Path

import pytest
import yaml

from aws_intel.init.generator import InitError, InitGenerator


def test_generate_writes_accounts_and_forwards_files(tmp_path: Path) -> None:
    directory = tmp_path / ".awsi"

    result = InitGenerator(directory).generate()

    assert result.written == (
        directory / "accounts.yaml",
        directory / "forwards.yaml",
    )
    assert result.skipped == ()
    assert (directory / "accounts.yaml").exists()
    assert (directory / "forwards.yaml").exists()


def test_generate_skips_existing_files_without_force(tmp_path: Path) -> None:
    directory = tmp_path / ".awsi"
    directory.mkdir()
    accounts_path = directory / "accounts.yaml"
    accounts_path.write_text("version: 1\naccounts: {}\n", encoding="utf-8")

    result = InitGenerator(directory).generate()

    assert accounts_path in result.skipped
    assert directory / "forwards.yaml" in result.written
    assert yaml.safe_load(accounts_path.read_text(encoding="utf-8")) == {
        "version": 1,
        "accounts": {},
    }


def test_generate_overwrites_existing_files_with_force(tmp_path: Path) -> None:
    directory = tmp_path / ".awsi"
    directory.mkdir()
    accounts_path = directory / "accounts.yaml"
    accounts_path.write_text("version: 1\naccounts: {}\n", encoding="utf-8")

    result = InitGenerator(directory).generate(force=True)

    assert result.skipped == ()
    assert accounts_path in result.written
    document = yaml.safe_load(accounts_path.read_text(encoding="utf-8"))
    assert document["accounts"]


def test_generate_reports_an_error_when_the_directory_cannot_be_created(
    tmp_path: Path,
) -> None:
    blocking_file = tmp_path / "not-a-directory"
    blocking_file.write_text("", encoding="utf-8")

    with pytest.raises(InitError, match="could not write configuration"):
        InitGenerator(blocking_file / ".awsi").generate()
