"""Composition for the People CRM family record page (Lane A4).

Wiring only, zero lines in ``composition/admin.py`` (at its line budget).
The family record page reuses what already exists wherever it can:

* Overview and Details read the family index row
  (``GET /admin/families/{id}/record``, ``composition/families_crm.py``);
* Billing and Timeline read ``GET /admin/families/{id}/billing``
  (``composition/families.py``);
* the child drawer's attendance Correct action is the existing admin
  correction route (#517, ``composition/attendance_corrections.py``).

The one new read is the child drawer's coach notes: the notes a coach shared
(#665), which the parent already sees.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.v2.contexts.coaching.application.use_cases.shared_coach_notes import (
    ListSharedCoachNotes,
)
from backend.v2.contexts.coaching.infrastructure.mongo_shared_coach_notes_reader import (
    MongoSharedCoachNotesReader,
)


@dataclass(frozen=True)
class AdminFamilyRecord:
    shared_coach_notes: ListSharedCoachNotes


def compose_admin_family_record(db: Any) -> AdminFamilyRecord:
    return AdminFamilyRecord(
        shared_coach_notes=ListSharedCoachNotes(MongoSharedCoachNotesReader(db)),
    )
