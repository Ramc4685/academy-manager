"""Composition for the public tenant page's admin writes (Lane B1).

Wiring only, zero lines in ``composition/admin.py`` (at its line budget).
Attached at ``app.state.admin_public_page`` by ``main.py`` and read by
``interfaces/admin/public_page_routes.py``:

* programs CRUD, class-to-program assignment and per-class public fields
  (Enrollment context, ``application/use_cases/programs.py``);
* the academy-level ``public_page`` settings and the academy's own web
  address for the "View page" link (Identity context,
  ``application/public_page_settings.py``), for the B5 settings panel and
  the B2 public read.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from bson import ObjectId

from backend.v2.contexts.enrollment.application.use_cases.programs import (
    ArchiveProgram,
    AssignClassToProgram,
    CreateProgram,
    ListClassPublicProfiles,
    ListPrograms,
    SetClassPublicFields,
    UpdateProgram,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_class_public_profile_repo import (
    MongoClassPublicProfileRepository,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_program_repo import (
    MongoProgramRepository,
)
from backend.v2.contexts.identity.application.public_page_settings import (
    GetPublicPageAddress,
    GetPublicPageSettings,
    UpdatePublicPageSettings,
)
from backend.v2.contexts.identity.domain.identity_aliases import identity_aliases
from backend.v2.contexts.identity.infrastructure.mongo_academy_repo import (
    MongoAcademyRepository,
)


@dataclass(frozen=True)
class AdminPublicPage:
    create_program: CreateProgram
    update_program: UpdateProgram
    archive_program: ArchiveProgram
    list_programs: ListPrograms
    assign_class_to_program: AssignClassToProgram
    set_class_public_fields: SetClassPublicFields
    list_class_public_profiles: ListClassPublicProfiles
    get_public_page_settings: GetPublicPageSettings
    update_public_page_settings: UpdatePublicPageSettings
    get_public_page_address: GetPublicPageAddress


#: Roles that may carry a public coach profile.
_PROFILE_ROLES = ["coach", "assistant_coach"]


class MongoCoachRoster:
    """Which of these ids are active coaches of THIS academy.

    ``users`` is global and ids are matched alias-aware (``user_id``,
    ``auth_uid``, ``firebase_uid``, ``_id``), exactly as the session staff
    names are; the membership row (explicit ``academy_id``, active, coach role)
    is what makes an id count, so another academy's coach never qualifies.
    """

    def __init__(self, db: Any) -> None:
        self._db = db

    async def coach_ids(self, academy_id: str, candidate_ids: list[str]) -> set[str]:
        wanted = sorted({cid for cid in candidate_ids if cid})
        if not wanted:
            return set()
        or_filter: list[dict[str, Any]] = [
            {"user_id": {"$in": wanted}},
            {"auth_uid": {"$in": wanted}},
            {"firebase_uid": {"$in": wanted}},
        ]
        oids = [ObjectId(cid) for cid in wanted if ObjectId.is_valid(cid)]
        if oids:
            or_filter.append({"_id": {"$in": oids}})
        aliases: dict[str, set[str]] = {cid: {cid} for cid in wanted}
        async for user in self._db["users"].find({"$or": or_filter}):
            known = identity_aliases(
                user.get("user_id"), user.get("auth_uid"), user.get("firebase_uid"), user.get("_id")
            )
            for cid in wanted:
                if cid in known:
                    aliases[cid].update(known)
        pool = sorted(set().union(*aliases.values()))
        member_ids = {
            str(doc.get("user_id"))
            async for doc in self._db["academy_memberships"].find(
                {
                    "academy_id": academy_id,
                    "user_id": {"$in": pool},
                    # A missing status reads as active, like the membership repo.
                    "$or": [{"status": "active"}, {"status": {"$exists": False}}],
                    "roles": {"$in": _PROFILE_ROLES},
                },
                {"user_id": 1},
            )
        }
        return {cid for cid, known in aliases.items() if known & member_ids}


def compose_admin_public_page(
    db: Any, *, media_url_base: str | None = None, media_store: Any = None
) -> AdminPublicPage:
    programs = MongoProgramRepository(db)
    profiles = MongoClassPublicProfileRepository(db)
    academies = MongoAcademyRepository(db)
    update_program = UpdateProgram(programs)
    return AdminPublicPage(
        create_program=CreateProgram(programs),
        update_program=update_program,
        archive_program=ArchiveProgram(update_program),
        list_programs=ListPrograms(programs),
        assign_class_to_program=AssignClassToProgram(programs, profiles),
        set_class_public_fields=SetClassPublicFields(profiles),
        list_class_public_profiles=ListClassPublicProfiles(profiles),
        get_public_page_settings=GetPublicPageSettings(academies),
        update_public_page_settings=UpdatePublicPageSettings(
            academies, MongoCoachRoster(db), upload_url_base=media_url_base, media_store=media_store
        ),
        get_public_page_address=GetPublicPageAddress(academies),
    )
