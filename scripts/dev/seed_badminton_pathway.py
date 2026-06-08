#!/usr/bin/env python3
"""Seed the badminton skill pathway for local development.

IDEMPOTENT — safe to run multiple times. Checks if pathway already exists
before creating. Uses _assert_local() to refuse non-local MongoDB.

Usage::

    backend/.venv/bin/python scripts/dev/seed_badminton_pathway.py

Override defaults via environment variables::

    MONGO_URL=mongodb://localhost:27017 \\
    DB_NAME=academy_manager \\
    ACADEMY_ID=dev-academy-001 \\
    backend/.venv/bin/python scripts/dev/seed_badminton_pathway.py
"""

from __future__ import annotations

import asyncio
import os
import sys

MONGO_URL: str = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME: str = os.environ.get("DB_NAME", "academy_manager")


def _assert_local() -> None:
    """Refuse to run against non-local MongoDB.

    Guards against accidentally pointing this seed at real infrastructure.
    Allows localhost, 127.0.0.1, and the Docker service name ``mongo``.
    """
    allowed = {"localhost", "127.0.0.1", "::1", "mongo"}
    import urllib.parse as _urlparse

    parsed = _urlparse.urlparse(MONGO_URL)
    host = (parsed.hostname or "").lower()
    if host not in allowed:
        print(
            f"ERROR: MONGO_URL={MONGO_URL!r} host {host!r} is not in the local allow-list "
            f"{sorted(allowed)}. Refusing to seed.",
            file=sys.stderr,
        )
        sys.exit(1)


async def main() -> None:
    _assert_local()

    from motor.motor_asyncio import AsyncIOMotorClient

    print(f"[seed] Connecting to {MONGO_URL} / {DB_NAME} …", file=sys.stderr)
    client: AsyncIOMotorClient = AsyncIOMotorClient(MONGO_URL)
    db = client[DB_NAME]

    # Lazy import so the script fails fast if PYTHONPATH is wrong
    from backend.v2.contexts.curriculum.application.use_cases.seed_curriculum import (
        seed_badminton_pathway,
    )
    from backend.v2.contexts.curriculum.infrastructure.mongo_program_repo import (
        MongoProgramRepository,
    )

    # Build lightweight in-process repos that write to Mongo
    # We use the Mongo repos from the infrastructure layer so the seed
    # produces exactly the same documents as the production code path.
    from backend.v2.contexts.curriculum.infrastructure.mongo_pathway_query import (
        MongoPathwayQuery,
    )

    # Dynamic import of remaining repos — they follow the same naming pattern
    import importlib

    def _get_repo(module_path: str, class_name: str) -> object:
        mod = importlib.import_module(module_path)
        cls = getattr(mod, class_name)
        return cls(db)

    programs = MongoProgramRepository(db)

    # Check if repos exist; fall back to minimal in-memory fakes if not yet
    # implemented (allows running the script during iterative development).
    try:
        levels = _get_repo(
            "backend.v2.contexts.curriculum.infrastructure.mongo_level_repo",
            "MongoLevelRepository",
        )
        skills = _get_repo(
            "backend.v2.contexts.curriculum.infrastructure.mongo_skill_repo",
            "MongoSkillRepository",
        )
        criteria = _get_repo(
            "backend.v2.contexts.curriculum.infrastructure.mongo_criterion_repo",
            "MongoCriterionRepository",
        )
        refs = _get_repo(
            "backend.v2.contexts.curriculum.infrastructure.mongo_ext_ref_repo",
            "MongoExternalRefRepository",
        )
    except (ImportError, AttributeError):
        print(
            "[seed] WARNING: Mongo curriculum repos not found; "
            "falling back to in-memory fakes for this run.",
            file=sys.stderr,
        )
        from backend.v2.tests.interface.test_admin_pathway import (  # type: ignore[import]
            FakeCriterionRepository,
            FakeExternalRefRepository,
            FakeLevelRepository,
            FakeSkillRepository,
        )

        levels = FakeLevelRepository()
        skills = FakeSkillRepository()
        criteria = FakeCriterionRepository()
        refs = FakeExternalRefRepository()

    academy_id: str = os.environ.get("ACADEMY_ID", "dev-academy-001")
    user_id: str = os.environ.get("SEED_USER_ID", "seed-script")

    from backend.v2.shared.tenancy.context import tenant_scope

    print(
        f"[seed] Seeding badminton pathway for academy_id={academy_id!r} …",
        file=sys.stderr,
    )

    with tenant_scope(academy_id):
        program = await seed_badminton_pathway(
            academy_id=academy_id,
            programs=programs,
            levels=levels,
            skills=skills,
            criteria=criteria,
            refs=refs,
            created_by=user_id,
        )

    print(
        f"[seed] Done. program_id={program.program_id!r}  name={program.name!r}",
        file=sys.stderr,
    )
    print(program.model_dump(mode="json"))

    client.close()


if __name__ == "__main__":
    asyncio.run(main())
