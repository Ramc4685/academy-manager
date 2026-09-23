"""Composition for the public tenant page's admin writes (Lane B1).

Wiring only, zero lines in ``composition/admin.py`` (at its line budget).
Attached at ``app.state.admin_public_page`` by ``main.py`` and read by
``interfaces/admin/public_page_routes.py``:

* programs CRUD, class-to-program assignment and per-class public fields
  (Enrollment context, ``application/use_cases/programs.py``);
* the academy-level ``public_page`` settings (Identity context,
  ``application/public_page_settings.py``), for the B5 settings panel and
  the B2 public read.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

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
    GetPublicPageSettings,
    UpdatePublicPageSettings,
)
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


def compose_admin_public_page(db: Any) -> AdminPublicPage:
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
        update_public_page_settings=UpdatePublicPageSettings(academies),
    )
