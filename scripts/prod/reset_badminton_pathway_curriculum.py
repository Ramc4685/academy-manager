#!/usr/bin/env python3
"""Reset BLNO production pathway curriculum and reload the local seed template.

Default mode is dry-run. Writes require:

    --apply --academy-id acad_blno_badminton --confirm-production acad_blno_badminton

Scope is intentionally limited to curriculum collections only:

- skill_programs
- skill_levels
- skills
- skill_criteria
- external_lesson_refs

Student progress collections are not touched.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from motor.motor_asyncio import AsyncIOMotorClient

if __file__ != "<stdin>":
    REPO_ROOT = Path(__file__).resolve().parents[2]
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))

from backend.v2.contexts.curriculum.application.use_cases.seed_curriculum import (
    seed_badminton_pathway,
)
from backend.v2.contexts.curriculum.infrastructure.mongo_criterion_repo import (
    MongoCriterionRepository,
)
from backend.v2.contexts.curriculum.infrastructure.mongo_ext_ref_repo import (
    MongoExternalRefRepository,
)
from backend.v2.contexts.curriculum.infrastructure.mongo_level_repo import (
    MongoLevelRepository,
)
from backend.v2.contexts.curriculum.infrastructure.mongo_program_repo import (
    MongoProgramRepository,
)
from backend.v2.contexts.curriculum.infrastructure.mongo_skill_repo import (
    MongoSkillRepository,
)
from backend.v2.shared.tenancy.context import tenant_scope

CURRICULUM_COLLECTIONS = (
    "skill_programs",
    "skill_levels",
    "skills",
    "skill_criteria",
    "external_lesson_refs",
)


def _json_default(value: object) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


async def _counts(db: Any, academy_id: str) -> dict[str, int]:
    return {
        collection: await db[collection].count_documents({"academy_id": academy_id})
        for collection in CURRICULUM_COLLECTIONS
    }


async def _backup(db: Any, academy_id: str, backup_dir: Path) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = backup_dir / f"prod-blno-pathway-curriculum-before-reset-{timestamp}.json"
    payload: dict[str, Any] = {
        "created_at": datetime.now(UTC),
        "academy_id": academy_id,
        "collections": {},
    }
    for collection in CURRICULUM_COLLECTIONS:
        docs = await db[collection].find({"academy_id": academy_id}).to_list(length=None)
        for doc in docs:
            doc["_id"] = str(doc["_id"])
        payload["collections"][collection] = docs
    path.write_text(json.dumps(payload, indent=2, default=_json_default) + "\n")
    return path


async def _delete_curriculum(db: Any, academy_id: str) -> dict[str, int]:
    deleted: dict[str, int] = {}
    for collection in CURRICULUM_COLLECTIONS:
        result = await db[collection].delete_many({"academy_id": academy_id})
        deleted[collection] = int(result.deleted_count)
    return deleted


async def _seed(db: Any, academy_id: str, created_by: str) -> dict[str, object]:
    with tenant_scope(academy_id):
        program = await seed_badminton_pathway(
            academy_id=academy_id,
            programs=MongoProgramRepository(db),
            levels=MongoLevelRepository(db),
            skills=MongoSkillRepository(db),
            criteria=MongoCriterionRepository(db),
            refs=MongoExternalRefRepository(db),
            created_by=created_by,
        )
    return program.model_dump(mode="json")


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--academy-id", default="blno")
    parser.add_argument("--mongo-url", default=os.environ.get("MONGO_URL"))
    parser.add_argument("--db-name", default=os.environ.get("DB_NAME", "academy_manager"))
    parser.add_argument("--backup-dir", default="/tmp/academy-manager-prod-backups")
    parser.add_argument("--created-by", default="prod-curriculum-reset")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm-production", default="")
    args = parser.parse_args()

    if args.academy_id not in {"blno", "acad_blno_badminton"}:
        raise SystemExit(
            "This script is scoped only for --academy-id blno or acad_blno_badminton"
        )
    if args.apply and args.confirm_production != args.academy_id:
        raise SystemExit("Apply requires --confirm-production blno")
    if not args.mongo_url:
        raise SystemExit("MONGO_URL is required")

    client: AsyncIOMotorClient = AsyncIOMotorClient(args.mongo_url)
    db = client[args.db_name]

    before = await _counts(db, args.academy_id)
    report: dict[str, object] = {
        "mode": "apply" if args.apply else "dry-run",
        "academy_id": args.academy_id,
        "db_name": args.db_name,
        "collections": list(CURRICULUM_COLLECTIONS),
        "before_counts": before,
        "student_progress_touched": False,
    }

    if not args.apply:
        print(json.dumps(report, indent=2))
        return

    backup_path = await _backup(db, args.academy_id, Path(args.backup_dir))
    deleted = await _delete_curriculum(db, args.academy_id)
    program = await _seed(db, args.academy_id, args.created_by)
    after = await _counts(db, args.academy_id)
    report.update(
        {
            "backup_path": str(backup_path),
            "deleted_counts": deleted,
            "seeded_program": program,
            "after_counts": after,
        }
    )
    print(json.dumps(report, indent=2, default=_json_default))


if __name__ == "__main__":
    asyncio.run(main())
