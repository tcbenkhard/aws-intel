"""Tests for the persistent forwarding process registry."""

import json
from pathlib import Path
import signal

import pytest

from aws_intel.forwarding.model import ActiveForward, PortMapping
from aws_intel.forwarding.registry import (
    ForwardNotFoundError,
    ForwardRegistry,
    ForwardRegistryError,
)


def test_lists_running_forwards_and_prunes_completed_processes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "forwards.json"
    registry = ForwardRegistry(path)
    running = ActiveForward(
        101, "i-11111111", "db.internal", PortMapping(1, 2), "database"
    )
    completed = ActiveForward(202, "i-22222222", "api.internal", PortMapping(3, 4))
    registry.add(running)
    registry.add(completed)

    def signal_process(pid: int, signal: int) -> None:
        if pid == completed.pid:
            raise ProcessLookupError

    monkeypatch.setattr("aws_intel.forwarding.registry.os.kill", signal_process)

    assert registry.list_active() == (running,)
    assert json.loads(path.read_text(encoding="utf-8")) == [
        {
            "pid": 101,
            "instance_id": "i-11111111",
            "host": "db.internal",
            "local_port": 1,
            "remote_port": 2,
            "name": "database",
        }
    ]


def test_reports_invalid_saved_state(tmp_path: Path) -> None:
    path = tmp_path / "forwards.json"
    path.write_text("not json", encoding="utf-8")

    with pytest.raises(ForwardRegistryError, match="could not read"):
        ForwardRegistry(path).list_active()


def test_rejects_an_identical_running_forward(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry = ForwardRegistry(tmp_path / "forwards.json")
    forward = ActiveForward(
        101, "i-11111111", "db.internal", PortMapping(15432, 5432), "database"
    )
    registry.add(forward)
    monkeypatch.setattr(
        "aws_intel.forwarding.registry.os.kill", lambda pid, value: None
    )

    with pytest.raises(ForwardRegistryError, match="already running with PID 101"):
        registry.ensure_startable(
            forward.instance_id, forward.host, forward.port_mapping
        )


def test_reads_registry_entries_saved_before_names_were_supported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "forwards.json"
    path.write_text(
        json.dumps(
            [
                {
                    "pid": 101,
                    "instance_id": "i-11111111",
                    "host": "db.internal",
                    "local_port": 1,
                    "remote_port": 2,
                }
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "aws_intel.forwarding.registry.os.kill", lambda pid, signal: None
    )

    assert ForwardRegistry(path).list_active() == (
        ActiveForward(101, "i-11111111", "db.internal", PortMapping(1, 2)),
    )


@pytest.mark.parametrize(
    ("reference", "expected_pid"),
    [("database", 101), ("202", 202)],
)
def test_terminates_forward_by_name_or_pid(
    reference: str,
    expected_pid: int,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = ForwardRegistry(tmp_path / "forwards.json")
    named = ActiveForward(
        101, "i-11111111", "db.internal", PortMapping(1, 2), "database"
    )
    unnamed = ActiveForward(202, "i-22222222", "api.internal", PortMapping(3, 4))
    registry.add(named)
    registry.add(unnamed)
    signals: list[tuple[int, signal.Signals]] = []
    monkeypatch.setattr(
        "aws_intel.forwarding.registry.os.kill", lambda pid, value: None
    )
    monkeypatch.setattr(
        "aws_intel.forwarding.registry.os.killpg",
        lambda pid, value: signals.append((pid, value)),
    )
    monkeypatch.setattr(registry, "_wait_for_process_group_exit", lambda pid: True)

    stopped = registry.terminate(reference)

    assert stopped.pid == expected_pid
    assert signals == [(expected_pid, signal.SIGINT)]
    assert all(item.pid != expected_pid for item in registry.list_active())


def test_force_kills_forward_that_does_not_exit_after_sigint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry = ForwardRegistry(tmp_path / "forwards.json")
    forward = ActiveForward(
        101, "i-11111111", "db.internal", PortMapping(1, 2), "database"
    )
    registry.add(forward)
    signals: list[tuple[int, signal.Signals]] = []
    waits = iter((False, True))
    monkeypatch.setattr(
        "aws_intel.forwarding.registry.os.kill", lambda pid, value: None
    )
    monkeypatch.setattr(
        "aws_intel.forwarding.registry.os.killpg",
        lambda pid, value: signals.append((pid, value)),
    )
    monkeypatch.setattr(
        registry, "_wait_for_process_group_exit", lambda pid: next(waits)
    )

    registry.terminate("database")

    assert signals == [(101, signal.SIGINT), (101, signal.SIGKILL)]
    assert registry.list_active() == ()


def test_name_match_takes_precedence_over_numeric_pid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry = ForwardRegistry(tmp_path / "forwards.json")
    registry.add(
        ActiveForward(101, "i-11111111", "db.internal", PortMapping(1, 2), "202")
    )
    registry.add(ActiveForward(202, "i-22222222", "api.internal", PortMapping(3, 4)))
    monkeypatch.setattr(
        "aws_intel.forwarding.registry.os.kill", lambda pid, value: None
    )
    terminated: list[int] = []
    monkeypatch.setattr(
        "aws_intel.forwarding.registry.os.killpg",
        lambda pid, value: terminated.append(pid),
    )
    monkeypatch.setattr(registry, "_wait_for_process_group_exit", lambda pid: True)

    registry.terminate("202")

    assert terminated == [101]


def test_resolves_forward_without_terminating_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry = ForwardRegistry(tmp_path / "forwards.json")
    forward = ActiveForward(
        101, "i-11111111", "db.internal", PortMapping(1, 2), "database"
    )
    registry.add(forward)
    monkeypatch.setattr(
        "aws_intel.forwarding.registry.os.kill", lambda pid, value: None
    )

    assert registry.resolve("database") == forward
    assert registry.list_active() == (forward,)


def test_rejects_ambiguous_or_unknown_forward_references(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry = ForwardRegistry(tmp_path / "forwards.json")
    for pid in (101, 202):
        registry.add(
            ActiveForward(
                pid,
                "i-11111111",
                "db.internal",
                PortMapping(pid, 443),
                "database",
            )
        )
    monkeypatch.setattr(
        "aws_intel.forwarding.registry.os.kill", lambda pid, value: None
    )

    with pytest.raises(ForwardRegistryError, match="multiple active forwards"):
        registry.terminate("database")
    with pytest.raises(ForwardNotFoundError, match="no active forward"):
        registry.terminate("missing")
