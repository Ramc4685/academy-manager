"""`backend/scripts/backup_restore.py` — pure pieces (roadmap D6).

Retention date math, the restore-target guard, manifest diffing and URI
redaction. The dump/restore round trip against a real mongod lives in
``tests/contract/test_backup_restore_roundtrip.py`` and in the
``restore-drill`` workflow.
"""

from __future__ import annotations

import datetime as dt
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from backend.scripts import backup_restore as br

NOW = dt.datetime(2026, 9, 23, 12, 0, 0, tzinfo=dt.UTC)
SECRET = "s3cr3t-Pa55"
CRED_URI = f"mongodb://backup_user:{SECRET}@db.example.internal:27017/?authSource=admin"


# --------------------------------------------------------------------------- prune


def _name(stamp: dt.datetime, db: str = "academy") -> str:
    return br.archive_name(db, stamp)


def test_archive_name_round_trips_its_utc_stamp() -> None:
    name = _name(NOW)
    assert name == "academy-20260923T120000Z.archive.gz"
    assert br.archive_timestamp(name) == NOW


def test_archive_name_normalises_a_non_utc_clock_to_utc() -> None:
    eastern = dt.timezone(dt.timedelta(hours=-5))
    assert _name(dt.datetime(2026, 9, 23, 7, 0, tzinfo=eastern)) == _name(NOW)


def test_prune_keeps_the_boundary_and_selects_only_older_archives() -> None:
    names = [
        _name(NOW - dt.timedelta(days=30)),  # exactly at the cutoff: kept
        _name(NOW - dt.timedelta(days=30, seconds=1)),  # one second past: expired
        _name(NOW - dt.timedelta(days=45)),
        _name(NOW - dt.timedelta(days=1)),
        _name(NOW + dt.timedelta(days=1)),  # clock skew: never expired
    ]
    expired = br.expired_archives(names, now=NOW, keep_days=30)
    assert expired == sorted(
        [_name(NOW - dt.timedelta(days=45)), _name(NOW - dt.timedelta(days=30, seconds=1))]
    )


def test_prune_never_selects_files_it_did_not_write() -> None:
    names = [
        "notes.txt",
        "academy-20200101T000000Z.archive.gz.manifest.json",  # sidecar: removed with its archive
        "academy-2020-01-01.archive.gz",  # the old manual DEPLOYMENT.md naming
        "academy-20201301T000000Z.archive.gz",  # month 13: not a real stamp
    ]
    assert br.expired_archives(names, now=NOW, keep_days=30) == []


def test_prune_handles_month_and_leap_year_boundaries() -> None:
    now = dt.datetime(2028, 3, 1, 0, 0, tzinfo=dt.UTC)  # 2028 is a leap year
    names = [
        _name(dt.datetime(2028, 1, 31, 0, 0, tzinfo=dt.UTC)),
        _name(dt.datetime(2028, 1, 30, 23, 59, tzinfo=dt.UTC)),
    ]
    # 30 days before 2028-03-01 is 2028-01-31 (Feb has 29 days).
    assert br.expired_archives(names, now=now, keep_days=30) == [names[1]]


def test_prune_rejects_zero_keep_days() -> None:
    with pytest.raises(ValueError):
        br.expired_archives([], now=NOW, keep_days=0)


def test_prune_is_a_dry_run_unless_apply(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    old = tmp_path / _name(dt.datetime.now(dt.UTC) - dt.timedelta(days=40))
    fresh = tmp_path / _name(dt.datetime.now(dt.UTC) - dt.timedelta(days=2))
    for path in (old, fresh):
        path.write_bytes(b"x")
        (tmp_path / (path.name + br.MANIFEST_SUFFIX)).write_text("{}")

    assert br.main(["prune", "--out-dir", str(tmp_path)], environ={}) == 0
    assert old.exists()
    assert "dry run" in capsys.readouterr().out

    assert br.main(["prune", "--out-dir", str(tmp_path), "--apply"], environ={}) == 0
    assert not old.exists()
    assert not (tmp_path / (old.name + br.MANIFEST_SUFFIX)).exists()
    assert fresh.exists()
    assert (tmp_path / (fresh.name + br.MANIFEST_SUFFIX)).exists()


# --------------------------------------------------------------------------- restore guard


def _guard(uri: str, **overrides: Any) -> list[str]:
    kwargs: dict[str, Any] = {
        "target_env": "SCRATCH_MONGO_URL",
        "target_uri": uri,
        "source_db": "academy",
        "target_db": "academy_restore",
        "environ": {},
        "i_know_this_is_prod": False,
        "allow_remote_target": False,
    }
    kwargs.update(overrides)
    return br.check_restore_target(**kwargs)


@pytest.mark.parametrize(
    "uri",
    [
        "mongodb://localhost:27017",
        "mongodb://127.0.0.1",
        "mongodb://[::1]:27017/?directConnection=true",
        "mongodb://mongo.localhost:27017",
    ],
)
def test_localhost_targets_are_allowed_by_default(uri: str) -> None:
    assert _guard(uri)


@pytest.mark.parametrize(
    "uri",
    [
        "mongodb+srv://u:p@cluster0.abcde.mongodb.net/?retryWrites=true",
        "mongodb://10.0.0.5:27017",
        "mongodb://localhost:27017,replica-2.internal:27017",  # one remote member is enough
    ],
)
def test_non_localhost_targets_are_refused_by_default(uri: str) -> None:
    with pytest.raises(br.Refused, match="not localhost"):
        _guard(uri)


def test_remote_scratch_target_needs_the_explicit_flag() -> None:
    assert _guard("mongodb://scratch.internal:27017", allow_remote_target=True) == [
        "scratch.internal"
    ]


def test_a_prod_named_target_env_var_is_refused_even_on_localhost() -> None:
    with pytest.raises(br.Refused, match="PROD_MONGO_"):
        _guard("mongodb://localhost", target_env="PROD_MONGO_URL")


def test_the_host_of_any_prod_env_var_is_refused_even_with_allow_remote() -> None:
    environ = {"PROD_MONGO_URL": "mongodb+srv://u:p@Prod-Cluster.example.net/app"}
    with pytest.raises(br.Refused, match="production/denylisted"):
        _guard(
            "mongodb+srv://other:creds@prod-cluster.example.net/",
            environ=environ,
            allow_remote_target=True,
        )


def test_the_explicit_denylist_env_is_honoured() -> None:
    environ = {"BACKUP_RESTORE_DENY_HOSTS": "db1.internal, db2.internal"}
    with pytest.raises(br.Refused, match="denylisted"):
        _guard("mongodb://db2.internal:27017", environ=environ, allow_remote_target=True)


def test_same_name_restore_is_refused() -> None:
    with pytest.raises(br.Refused, match="different"):
        _guard("mongodb://localhost", target_db="academy")


def test_the_prod_flag_overrides_every_guard() -> None:
    environ = {"PROD_MONGO_URL": "mongodb://prod.example.net"}
    assert _guard(
        "mongodb://prod.example.net",
        target_env="PROD_MONGO_URL",
        target_db="academy",
        environ=environ,
        i_know_this_is_prod=True,
    ) == ["prod.example.net"]


def test_restore_cli_refuses_a_remote_target_before_touching_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    archive = tmp_path / "academy-20260923T120000Z.archive.gz"
    archive.write_bytes(b"x")

    def _no_connect(uri: str) -> Any:  # pragma: no cover - must not be reached
        raise AssertionError("guard must refuse before connecting")

    monkeypatch.setattr(br, "mongo_client", _no_connect)
    code = br.main(
        ["restore", "--archive", str(archive), "--nsFrom", "academy", "--nsTo", "academy_r"],
        environ={"SCRATCH_MONGO_URL": CRED_URI},
    )
    assert code == br.EXIT_REFUSED
    err = capsys.readouterr().err
    assert "refused" in err and "not localhost" in err
    assert SECRET not in err


# --------------------------------------------------------------------------- manifest diff


def _snap(**collections: tuple[int, list[str]]) -> dict[str, dict[str, Any]]:
    return {name: {"count": c, "indexes": idx} for name, (c, idx) in collections.items()}


def test_identical_snapshots_have_no_problems() -> None:
    snap = _snap(students=(3, ["_id_", "academy_id_1"]), sessions=(0, ["_id_"]))
    assert br.diff_snapshots(snap, json.loads(json.dumps(snap))) == []


def test_diff_reports_every_kind_of_mismatch() -> None:
    expected = _snap(
        students=(3, ["_id_", "academy_id_1"]), sessions=(2, ["_id_"]), invoices=(1, ["_id_"])
    )
    actual = _snap(
        students=(2, ["_id_", "stray_1"]), sessions=(2, ["_id_"]), leftovers=(5, ["_id_"])
    )
    assert br.diff_snapshots(expected, actual) == [
        "missing collection: invoices",
        "unexpected collection: leftovers",
        "count mismatch: students expected 3 got 2",
        "missing index: students.academy_id_1",
        "unexpected index: students.stray_1",
    ]


def test_verify_cli_exits_non_zero_on_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    manifest = tmp_path / "m.json"
    manifest.write_text(
        json.dumps({"db": "academy", "archive": "a", "collections": _snap(students=(3, ["_id_"]))})
    )

    class _Client:
        def __getitem__(self, name: str) -> str:
            return name

        def close(self) -> None:
            pass

    monkeypatch.setattr(br, "mongo_client", lambda uri: _Client())
    monkeypatch.setattr(br, "snapshot_database", lambda db: _snap(students=(1, ["_id_"])))
    code = br.main(
        ["verify", "--manifest", str(manifest), "--db", "academy_r"],
        environ={"SCRATCH_MONGO_URL": "mongodb://localhost"},
    )
    assert code == br.EXIT_MISMATCH
    assert "count mismatch: students expected 3 got 1" in capsys.readouterr().err

    monkeypatch.setattr(br, "snapshot_database", lambda db: _snap(students=(3, ["_id_"])))
    assert (
        br.main(
            ["verify", "--manifest", str(manifest)],
            environ={"SCRATCH_MONGO_URL": "mongodb://localhost"},
        )
        == br.EXIT_OK
    )


# --------------------------------------------------------------------------- redaction


@pytest.mark.parametrize(
    ("uri", "expected"),
    [
        (CRED_URI, "mongodb://***@db.example.internal:27017/?authSource=admin"),
        (
            "mongodb+srv://u:p%40ss@c.mongodb.net/db?password=x&w=1",
            "mongodb+srv://***@c.mongodb.net/db?password=***&w=1",
        ),
        ("mongodb://localhost:27017", "mongodb://localhost:27017"),
        ("not a uri", "***"),
    ],
)
def test_redact_uri(uri: str, expected: str) -> None:
    assert br.redact_uri(uri) == expected


def test_redact_scrubs_uris_embedded_in_free_text() -> None:
    text = f"connection to {CRED_URI} failed; retry {CRED_URI}"
    redacted = br.redact(text)
    assert SECRET not in redacted and "backup_user" not in redacted
    assert "db.example.internal" in redacted


def test_driver_errors_carrying_the_uri_are_redacted(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    def _boom(uri: str) -> Any:
        raise RuntimeError(f"could not reach {uri} (user backup_user, password {SECRET})")

    monkeypatch.setattr(br, "mongo_client", _boom)
    code = br.main(
        ["backup", "--db", "academy", "--out-dir", str(tmp_path)],
        environ={"MONGO_URL": CRED_URI},
    )
    captured = capsys.readouterr()
    assert code == br.EXIT_MISMATCH
    assert CRED_URI not in captured.err + captured.out
    assert f"backup_user:{SECRET}" not in captured.err + captured.out


def test_tool_output_is_redacted_and_the_uri_never_reaches_argv(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    seen: dict[str, Any] = {}

    def _fake_run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        seen["argv"] = argv
        config = next(a for a in argv if a.startswith("--config="))
        path = Path(config.split("=", 1)[1])
        seen["config"] = path.read_text()
        seen["mode"] = path.stat().st_mode & 0o777
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr=f"connected to: {CRED_URI}\n")

    monkeypatch.setattr(br.shutil, "which", lambda name: "/usr/bin/" + name)
    monkeypatch.setattr(br.subprocess, "run", _fake_run)
    with br.uri_config_file(CRED_URI) as config:
        br.run_tool(["mongodump", f"--config={config}"], br.Out([CRED_URI]))
    assert not config.exists()  # deleted afterwards

    assert all(SECRET not in arg for arg in seen["argv"])
    assert json.loads(seen["config"].split(":", 1)[1]) == CRED_URI
    assert seen["mode"] == 0o600
    out = capsys.readouterr().out
    assert SECRET not in out and "db.example.internal" in out


def test_missing_uri_env_is_refused_without_echoing_other_env(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = br.main(
        ["backup", "--uri-env", "NOPE", "--db", "academy", "--out-dir", str(tmp_path)],
        environ={"MONGO_URL": CRED_URI},
    )
    assert code == br.EXIT_REFUSED
    assert SECRET not in capsys.readouterr().err
