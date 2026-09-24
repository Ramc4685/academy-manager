"""Backup -> scratch restore -> verify on a real mongod (roadmap D6).

Uses ``real_db`` (every migration replayed, so the production indexes exist)
and the real ``mongodump`` / ``mongorestore`` binaries. Skipped when either
the server or the MongoDB Database Tools are missing; the ``restore-drill``
workflow installs both and runs this file.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any

import pytest
from pymongo import MongoClient

from backend.scripts import backup_restore as br

pytestmark = pytest.mark.skipif(
    shutil.which("mongodump") is None or shutil.which("mongorestore") is None,
    reason="MongoDB Database Tools (mongodump/mongorestore) not on PATH",
)

ACADEMY = "drill-academy"
OTHER = "drill-other-academy"


def _real_mongo_url() -> str:
    """Same resolution as ``conftest._real_mongo_url`` (the ``real_db`` server)."""
    return (
        os.environ.get("V2_MONGO_URL") or os.environ.get("MONGO_URL") or "mongodb://127.0.0.1:27017"
    )


async def _seed(db: Any) -> None:
    """A few tenant-scoped rows across two academies. Synthetic names only."""
    await db["academies"].insert_many(
        [
            {"_id": ACADEMY, "academy_id": ACADEMY, "display_name": "Drill Academy"},
            {"_id": OTHER, "academy_id": OTHER, "display_name": "Other Drill Academy"},
        ]
    )
    await db["students"].insert_many(
        [
            {
                "academy_id": ACADEMY,
                "student_id": f"stu-{i}",
                "parent_id": "par-1",
                "full_name": f"Test Student {i}",
            }
            for i in range(3)
        ]
        + [
            {
                "academy_id": OTHER,
                "student_id": "stu-x",
                "parent_id": "par-x",
                "full_name": "Sample Student",
            }
        ]
    )
    await db["sessions"].insert_one(
        {"academy_id": ACADEMY, "session_id": "ses-1", "name": "Drill Group A"}
    )


def _restore_db_name(source: str) -> str:
    return f"{source}_restore"


async def test_backup_restore_verify_round_trip(
    real_db: Any, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    await _seed(real_db)
    url = _real_mongo_url()
    source = real_db.name
    target = _restore_db_name(source)
    env = {"MONGO_URL": url, "SCRATCH_MONGO_URL": url}
    client: MongoClient[Any] = MongoClient(url, serverSelectionTimeoutMS=2000)
    client.drop_database(target)
    try:
        assert br.main(["backup", "--db", source, "--out-dir", str(tmp_path)], environ=env) == 0
        archives = sorted(tmp_path.glob(f"*{br.ARCHIVE_SUFFIX}"))
        assert len(archives) == 1
        manifest_path = archives[0].with_name(archives[0].name + br.MANIFEST_SUFFIX)
        manifest = json.loads(manifest_path.read_text())
        assert manifest["collections"]["students"]["count"] == 4
        # Migration-built indexes are recorded, not just _id_.
        assert len(manifest["collections"]["students"]["indexes"]) > 1
        assert manifest["archive_sha256"] == br.sha256_file(archives[0])

        restore = ["restore", "--archive", str(archives[0]), "--nsFrom", source, "--nsTo", target]
        assert br.main(restore, environ=env) == 0
        assert (
            br.main(["verify", "--manifest", str(manifest_path), "--db", target], environ=env) == 0
        )
        restored = client[target]
        assert restored["students"].count_documents({"academy_id": ACADEMY}) == 3
        assert restored["students"].count_documents({"academy_id": OTHER}) == 1
        # Collection options (the 0132 launch validators) come back too.
        options = restored["students"].options()
        assert "$jsonSchema" in options.get("validator", {})

        # A second restore into the now non-empty target is refused.
        assert br.main(restore, environ=env) == br.EXIT_REFUSED

        # Drift after restore is caught.
        restored["students"].delete_one({"student_id": "stu-x"})
        assert (
            br.main(["verify", "--manifest", str(manifest_path), "--db", target], environ=env)
            == br.EXIT_MISMATCH
        )
        assert "count mismatch: students expected 4 got 3" in capsys.readouterr().err

        # A tampered archive is refused before mongorestore runs.
        client.drop_database(target)
        with archives[0].open("ab") as handle:
            handle.write(b"tampered")
        assert br.main(restore, environ=env) == br.EXIT_REFUSED
    finally:
        client.drop_database(target)
        client.close()
