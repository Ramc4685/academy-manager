"""Composition for the anonymous public tenant page read (Lane B2).

Wiring only, zero lines in ``composition/admin.py`` (at its line budget).
Attached at ``app.state.public_page`` by ``main.py`` and read by
``interfaces/public/academy_page_routes.py``. Read use cases only: nothing
here writes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.v2.composition.admin_session_staff import attach_session_staff_names
from backend.v2.contexts.enrollment.application.use_cases.public_catalog import (
    ListPublicCatalog,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_program_repo import (
    MongoProgramRepository,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_session_repo import (
    MongoSessionRepository,
)
from backend.v2.contexts.identity.application.public_academy_profile import (
    GetPublicAcademyProfile,
)
from backend.v2.contexts.identity.infrastructure.mongo_academy_repo import (
    MongoAcademyRepository,
)


@dataclass(frozen=True)
class PublicPageRead:
    get_academy_profile: GetPublicAcademyProfile
    list_catalog: ListPublicCatalog


class _MemberCoachNames:
    """``CoachNameDirectory`` over the admin roster's membership-gated name
    lookup: a coach id only resolves to a name when that user holds a
    membership in the tenant in scope (``users`` is global)."""

    def __init__(self, db: Any) -> None:
        self._db = db

    async def display_names(self, coach_ids: list[str]) -> dict[str, str]:
        rows: list[dict[str, Any]] = [{"coach_id": cid} for cid in coach_ids]
        await attach_session_staff_names(self._db, rows)
        return {row["coach_id"]: row["coach_name"] for row in rows if row.get("coach_name")}


def compose_public_page_read(db: Any) -> PublicPageRead:
    return PublicPageRead(
        get_academy_profile=GetPublicAcademyProfile(MongoAcademyRepository(db)),
        list_catalog=ListPublicCatalog(
            programs=MongoProgramRepository(db),
            sessions=MongoSessionRepository(db),
            coach_names=_MemberCoachNames(db),
        ),
    )
