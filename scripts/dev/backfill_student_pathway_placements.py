#!/usr/bin/env python3
"""Backfill local/test student pathway placements.

Local-only by default. Places active students into the tenant's single active
pathway program using an explicit legacy skill-level mapping, and initializes
skill progress through the normal PlaceStudentInLevel use case.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from dataclasses import dataclass

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "academy_manager")
DEFAULT_MAPPING = {
    "beginner": 1,
    "intro": 1,
    "intermediate": 2,
    "advanced": 3,
}


@dataclass(frozen=True)
class BackfillReport:
    placed: int = 0
    skipped: int = 0
    unmappable: int = 0
    dry_run: bool = True


def _assert_local() -> None:
    allowed = {"localhost", "127.0.0.1", "::1", "mongo"}
    import urllib.parse as _urlparse

    parsed = _urlparse.urlparse(MONGO_URL)
    host = (parsed.hostname or "").lower()
    if host not in allowed:
        print(
            f"ERROR: MONGO_URL={MONGO_URL!r} host {host!r} is not in the local allow-list "
            f"{sorted(allowed)}. Refusing to backfill.",
            file=sys.stderr,
        )
        sys.exit(1)


def _mapped_sequence(student: dict[str, object]) -> int | None:
    raw = str(student.get("level") or student.get("skill_level") or "").strip().lower()
    if raw.isdigit():
        return int(raw)
    return DEFAULT_MAPPING.get(raw)


async def backfill_student_pathway_placements(
    db: object,
    *,
    academy_id: str,
    actor_id: str = "backfill-script",
    dry_run: bool = True,
) -> BackfillReport:
    from backend.v2.composition.pathway import compose_curriculum, compose_student_progress
    from backend.v2.contexts.student_progress.application.use_cases.get_pathway_placement import (
        StudentPathwayPlacementRequest,
    )
    from backend.v2.contexts.student_progress.application.use_cases.place_student import (
        PlaceStudentInLevelCommand,
    )
    from backend.v2.shared.tenancy.context import tenant_scope

    placed = 0
    skipped = 0
    unmappable = 0

    with tenant_scope(academy_id):
        curriculum = compose_curriculum(db)  # type: ignore[arg-type]
        progress = compose_student_progress(db, None)  # type: ignore[arg-type]
        program = await curriculum.resolve_default_program.execute()
        levels = await curriculum.list_levels.execute(program.program_id)
        levels_by_sequence = {level.sequence: level for level in levels}

        cursor = db["students"].find(  # type: ignore[index]
            {
                "academy_id": academy_id,
                "status": "active",
                "is_deleted": {"$ne": True},
            },
            sort=[("created_at", 1), ("student_id", 1)],
        )
        async for student in cursor:
            student_id = str(student["student_id"])
            active = await progress.get_pathway_placement.execute(
                StudentPathwayPlacementRequest(
                    student_id=student_id,
                    program_id=program.program_id,
                )
            )
            if active.level_id is not None:
                skipped += 1
                continue

            sequence = _mapped_sequence(student)
            level = levels_by_sequence.get(sequence or 0)
            if level is None:
                unmappable += 1
                continue

            if not dry_run:
                await progress.place_student.execute(
                    PlaceStudentInLevelCommand(
                        student_id=student_id,
                        program_id=program.program_id,
                        level_id=level.level_id,
                        placed_by=actor_id,
                    )
                )
            placed += 1

    return BackfillReport(placed=placed, skipped=skipped, unmappable=unmappable, dry_run=dry_run)


async def _main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--academy-id", default=os.environ.get("ACADEMY_ID", "blno"))
    parser.add_argument("--apply", action="store_true", help="Write placements; default is dry run.")
    args = parser.parse_args()

    _assert_local()

    from motor.motor_asyncio import AsyncIOMotorClient

    client = AsyncIOMotorClient(MONGO_URL)
    try:
        report = await backfill_student_pathway_placements(
            client[DB_NAME],
            academy_id=args.academy_id,
            dry_run=not args.apply,
        )
    finally:
        client.close()

    print(
        {
            "placed": report.placed,
            "skipped": report.skipped,
            "unmappable": report.unmappable,
            "dry_run": report.dry_run,
        }
    )


if __name__ == "__main__":
    asyncio.run(_main())
