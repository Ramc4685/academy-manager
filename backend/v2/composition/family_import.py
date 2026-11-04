"""Composition for the CSV family and student import (roadmap L8a).

``POST /admin/imports/families/preview`` and ``.../commit`` run
``PreviewFamilyImport`` and ``CommitFamilyImport`` (``contexts/crm``).
Wiring only:

* the family index is built FRESH (no cache) on every call, so a commit
  sees the families a preview or another admin added a moment ago; the
  duplicate finder's other lookups are the same ones the duplicate warning
  uses (``composition/people_duplicates.py``);
* students are written through enrollment's ``MongoStudentWriter`` (the
  CRM does not own ``students``);
* the batch store and audit rows are the CRM's own repositories.

The bundle is attached lazily by ``interfaces/admin/family_import_routes.py``
(``app.state.admin_family_import``), so ``main.py`` and ``composition/admin.py``
stay untouched.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date
from typing import Any

from backend.v2.composition.families_crm import _index_model
from backend.v2.composition.people_duplicates import _AcademyMemberDirectory
from backend.v2.contexts.crm.application.use_cases.family_import import (
    CommitFamilyImport,
    FamilyImportPlanner,
    PreviewFamilyImport,
)
from backend.v2.contexts.crm.infrastructure.mongo_crm_contact_repo import (
    MongoCrmContactRepository,
)
from backend.v2.contexts.crm.infrastructure.mongo_family_contacts_repo import (
    MongoFamilyContactRepository,
)
from backend.v2.contexts.crm.infrastructure.mongo_import_batch_repo import (
    MongoImportAuditLog,
    MongoImportBatchRepository,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_student_writer import (
    MongoStudentWriter,
)


@dataclass(frozen=True)
class AdminFamilyImport:
    preview: PreviewFamilyImport
    commit: CommitFamilyImport
    #: The academy's calendar day (its timezone): the "not in the future"
    #: bound for a date of birth.
    academy_today: Callable[[str], Awaitable[date]]


def compose_admin_family_import(db: Any) -> AdminFamilyImport:
    fresh_index = _index_model(db, 0.0)
    planner = FamilyImportPlanner(
        families=fresh_index,
        family_contacts=MongoFamilyContactRepository(db),
        members=_AcademyMemberDirectory(db),
        inquiries=MongoCrmContactRepository(db),
    )
    batches = MongoImportBatchRepository(db)
    audit = MongoImportAuditLog(db)
    return AdminFamilyImport(
        preview=PreviewFamilyImport(planner=planner, batches=batches, audit=audit),
        commit=CommitFamilyImport(
            planner=planner,
            batches=batches,
            students=MongoStudentWriter(db),
            audit=audit,
        ),
        academy_today=fresh_index.academy_today,
    )
