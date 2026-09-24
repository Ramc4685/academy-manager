"""Composition for the unified family timeline (People CRM spec §5, roadmap L4a/L4b).

Wiring only. ``GET /admin/families/{id}/timeline`` merges, per family:

* billing's own family timeline (``MongoFamilyBillingReadModel.build``, the
  same builder as the Billing tab: money, billing admin actions, lifecycle
  events, invoice emails), as one source;
* coaching's shared coach notes (#665), read-only;
* the CRM's Mongo sources: attendance, requests, the ``audit_logs``
  allowlist with moved-family entries, and the CRM's notes, follow-ups and
  contacts.

The use case hangs off ``app.state.admin_family_index`` (``families_crm.py``)
as ``timeline`` so ``main.py`` and ``composition/admin.py`` need no new line.
"""

from __future__ import annotations

from typing import Any

from backend.v2.composition.families import compose_admin_families
from backend.v2.contexts.coaching.application.use_cases.shared_coach_notes import (
    ListSharedCoachNotes,
)
from backend.v2.contexts.coaching.infrastructure.mongo_shared_coach_notes_reader import (
    MongoSharedCoachNotesReader,
)
from backend.v2.contexts.crm.application.ports import (
    FamilyFollowUpRepository,
    FamilyNoteRepository,
)
from backend.v2.contexts.crm.application.timeline import (
    BillingTimelineSource,
    CoachNotesTimelineSource,
    FamilyRecordDirectory,
    GetFamilyTimeline,
)
from backend.v2.contexts.crm.infrastructure.family_timeline_sources import (
    AdminAuditTimelineSource,
    AttendanceTimelineSource,
    CrmRecordsTimelineSource,
    RequestsTimelineSource,
)
from backend.v2.contexts.crm.infrastructure.mongo_family_contacts_repo import (
    MongoFamilyContactRepository,
)
from backend.v2.contexts.identity.infrastructure.mongo_user_repo import MongoUserRepository


def compose_family_timeline(
    db: Any,
    *,
    families: FamilyRecordDirectory,
    notes: FamilyNoteRepository,
    follow_ups: FamilyFollowUpRepository,
) -> GetFamilyTimeline:
    return GetFamilyTimeline(
        families=families,
        aliases=MongoUserRepository(db),
        sources=(
            BillingTimelineSource(compose_admin_families(db).reader),
            CoachNotesTimelineSource(ListSharedCoachNotes(MongoSharedCoachNotesReader(db))),
            AttendanceTimelineSource(db),
            RequestsTimelineSource(db),
            AdminAuditTimelineSource(db),
            CrmRecordsTimelineSource(notes, follow_ups, MongoFamilyContactRepository(db)),
        ),
    )
