"""Contract tests for the migrations CLI (``python -m backend.v2.migrations``).

Same fixtures and monkeypatch technique as ``test_migrations_runner_lock.py``:
the mongomock ``db`` fixture and a patched ``runner._discover_migrations``.
The tests target ``cli.run`` directly; argv parsing is covered separately.
"""

from __future__ import annotations

import asyncio
import runpy
import sys
from types import SimpleNamespace

import pytest

from backend.v2.migrations import cli, runner
from backend.v2.shared.scheduling.lease import COLLECTION as LEASE_COLLECTION


def _stub(calls: list[str], version: str, *, fail: bool = False):
    async def up(db) -> None:
        if fail:
            raise RuntimeError(f"{version} exploded")
        calls.append(version)

    return SimpleNamespace(version=version, up=up)


async def _registry_versions(db) -> set[str]:
    return {doc["version"] async for doc in db[runner.REGISTRY_COLLECTION].find({})}


@pytest.mark.asyncio
async def test_dry_run_lists_pending_and_applies_nothing(db, monkeypatch, capsys) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        runner,
        "_discover_migrations",
        lambda: [_stub(calls, "9001_first"), _stub(calls, "9002_second")],
    )
    await runner._record_applied(db, "9001_first")

    code = await cli.run(db, dry_run=True)

    assert code == cli.EXIT_OK
    assert calls == []
    assert await _registry_versions(db) == {"9001_first"}
    # Dry run never takes the lease either.
    assert await db[LEASE_COLLECTION].count_documents({}) == 0
    out = capsys.readouterr().out
    assert "event=pending_before" in out
    assert "'9002_second'" in out
    assert "'9001_first'" not in out.split("event=pending_before", 1)[1].splitlines()[0]
    assert "event=dry_run" in out


@pytest.mark.asyncio
async def test_apply_records_versions_and_returns_zero(db, monkeypatch, capsys) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        runner,
        "_discover_migrations",
        lambda: [_stub(calls, "9001_first"), _stub(calls, "9002_second")],
    )

    code = await cli.run(db, dry_run=False)

    assert code == cli.EXIT_OK
    assert calls == ["9001_first", "9002_second"]
    assert await _registry_versions(db) == {"9001_first", "9002_second"}
    assert await cli.pending_versions(db) == []
    out = capsys.readouterr().out
    assert "event=applied count=2" in out
    assert "event=pending_after count=0" in out


@pytest.mark.asyncio
async def test_failing_migration_returns_nonzero_and_stops(db, monkeypatch, capsys) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        runner,
        "_discover_migrations",
        lambda: [
            _stub(calls, "9001_first"),
            _stub(calls, "9002_boom", fail=True),
            _stub(calls, "9003_third"),
        ],
    )

    code = await cli.run(db, dry_run=False)

    assert code == cli.EXIT_FAILED
    assert calls == ["9001_first"]  # the later migration was never attempted
    assert await _registry_versions(db) == {"9001_first"}
    out = capsys.readouterr().out
    assert "event=failed" in out
    assert "9002_boom exploded" in out
    assert "event=pending_after count=2" in out


@pytest.mark.asyncio
async def test_timeout_returns_nonzero_without_applying(db, monkeypatch, capsys) -> None:
    calls: list[str] = []
    monkeypatch.setattr(runner, "_discover_migrations", lambda: [_stub(calls, "9001_first")])

    async def never_finishes(inner_db, **_kwargs):
        await asyncio.Event().wait()  # never set: models a lease that never frees
        return []

    monkeypatch.setattr(runner, "run_pending_migrations", never_finishes)

    # timeout 0 takes wait_for's immediate-cancel path: no real clock involved.
    code = await cli.run(db, dry_run=False, timeout_seconds=0)

    assert code == cli.EXIT_TIMEOUT
    assert calls == []
    assert await _registry_versions(db) == set()
    out = capsys.readouterr().out
    assert "event=timeout" in out


def test_python_dash_m_entry_point_is_wired(monkeypatch, capsys) -> None:
    # `python -m backend.v2.migrations --help` is what fly.toml's release_command
    # and the workflow's dry run resolve; --help exits 0 before settings load.
    monkeypatch.setattr(sys, "argv", ["backend.v2.migrations", "--help"])
    with pytest.raises(SystemExit) as exc_info:
        runpy.run_module("backend.v2.migrations", run_name="__main__", alter_sys=True)
    assert exc_info.value.code == 0
    assert "--dry-run" in capsys.readouterr().out


def test_parser_defaults_and_flags() -> None:
    parser = cli.build_parser()
    defaults = parser.parse_args([])
    assert defaults.dry_run is False
    assert defaults.timeout_seconds == cli.DEFAULT_TIMEOUT_SECONDS
    assert cli.DEFAULT_TIMEOUT_SECONDS > runner.MIGRATIONS_LEASE_TTL.total_seconds()

    flags = parser.parse_args(["--dry-run", "--timeout-seconds", "30"])
    assert flags.dry_run is True
    assert flags.timeout_seconds == 30.0
