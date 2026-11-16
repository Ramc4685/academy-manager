"""Report students hit by the November placement skill wipe (L5).

Read-only: it writes nothing. Before the fix, placing a student on a level
reset every skill row on it to ``NOT_STARTED``, even ones the student had
passed, and closed the old level as ``completed`` whatever was left. The
passing ``test_attempts`` survived, so they show what was lost.

Two lists, per academy:

* ``wiped_passes``: a ``NOT_STARTED`` skill row with a passing test attempt
  for the same student and skill.
* ``false_completions``: a ``completed`` level row whose student has not
  passed every active required skill of that level.

Both lists can hold false positives, so check each row before a repair:
a ``COACH_APPROVAL_ONLY`` or ``POINTS_BASED`` level completes without every
skill passed, and a skill added after a student finished the level shows up
as not passed on a ``completed`` row.

A repair (restore the passes, relabel the levels) needs the owner's approval
and is not part of this script.

Usage::

    MONGO_URL=... DB_NAME=... python backend/scripts/skill_wipe_audit.py
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from collections import defaultdict
from typing import Any

from motor.motor_asyncio import AsyncIOMotorClient


async def audit(db: Any) -> dict[str, Any]:
    """Grouped in Python so the same path runs under every test Mongo."""
    passed_attempts: dict[tuple[str, str, str], int] = defaultdict(int)
    async for doc in db["test_attempts"].find({"passed": True}):
        passed_attempts[(doc["academy_id"], doc["student_id"], doc["skill_id"])] += 1

    wiped: list[dict[str, Any]] = []
    passed_skills: dict[tuple[str, str], set[str]] = defaultdict(set)
    async for doc in db["student_skill_progress"].find({}):
        academy, student, skill = doc["academy_id"], doc["student_id"], doc["skill_id"]
        if doc.get("status") == "PASSED":
            passed_skills[(academy, student)].add(skill)
        elif doc.get("status") == "NOT_STARTED" and passed_attempts[(academy, student, skill)]:
            wiped.append(
                {
                    "academy_id": academy,
                    "student_id": student,
                    "skill_id": skill,
                    "level_id": doc.get("level_id"),
                    "passing_attempts": passed_attempts[(academy, student, skill)],
                }
            )

    required: dict[tuple[str, str], set[str]] = defaultdict(set)
    async for doc in db["skills"].find({"is_active": {"$ne": False}}):
        if doc.get("is_required", True):
            required[(doc["academy_id"], doc["level_id"])].add(doc["skill_id"])

    false_completions: list[dict[str, Any]] = []
    async for doc in db["student_level_progress"].find({"status": "completed"}):
        academy, student, level = doc["academy_id"], doc["student_id"], doc["level_id"]
        missing = required[(academy, level)] - passed_skills[(academy, student)]
        if missing:
            false_completions.append(
                {
                    "academy_id": academy,
                    "student_id": student,
                    "level_id": level,
                    "progress_id": doc.get("progress_id"),
                    "missing_skill_ids": sorted(missing),
                }
            )

    def key(row: dict[str, Any]) -> tuple[str, str, str]:
        return (row["academy_id"], row["student_id"], row.get("skill_id") or row["level_id"])

    return {
        "wiped_pass_count": len(wiped),
        "false_completion_count": len(false_completions),
        "affected_students": len(
            {(r["academy_id"], r["student_id"]) for r in wiped + false_completions}
        ),
        "wiped_passes": sorted(wiped, key=key),
        "false_completions": sorted(false_completions, key=key),
    }


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mongo-url", default=os.environ.get("MONGO_URL") or os.environ.get("V2_MONGO_URL")
    )
    parser.add_argument(
        "--db-name", default=os.environ.get("DB_NAME") or os.environ.get("V2_MONGO_DB")
    )
    args = parser.parse_args()
    if not args.mongo_url or not args.db_name:
        parser.error("--mongo-url/--db-name or MONGO_URL/DB_NAME is required")

    client = AsyncIOMotorClient(args.mongo_url)
    try:
        report = await audit(client[args.db_name])
        print(json.dumps({"db_name": args.db_name, **report}, indent=2, sort_keys=True))
    finally:
        client.close()
    return 1 if report["affected_students"] else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
