"""Composition for the family Messages tab (People CRM Phase 6, roadmap L4c).

Wiring only. ``GET /admin/families/{id}/messages`` merges, per family, the
send logs the app already keeps (campaign deliveries, the parent digest,
absence-notice confirmations, invoice copies to family contacts) with the
contacts staff logged by hand (``family_contact_log``, migration 0203).
``POST .../messages/log`` and ``PATCH .../messages/log/{log_id}`` write the
log. The bundle hangs off ``app.state.admin_family_index`` (``families_crm.py``)
as ``messages`` so ``main.py`` and ``composition/admin.py`` need no new line.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.v2.contexts.crm.application.family_directory import IndexFamilyDirectory
from backend.v2.contexts.crm.application.family_messages import (
    CompleteFamilyContactLog,
    GetFamilyMessages,
    LogFamilyContact,
)
from backend.v2.contexts.crm.infrastructure.family_message_sources import (
    AbsenceNoticeSendsSource,
    CampaignDeliveriesSource,
    ContactLogSource,
    InvoiceContactCopiesSource,
    ParentDigestSource,
)
from backend.v2.contexts.crm.infrastructure.mongo_family_contact_log_repo import (
    MongoFamilyContactLogRepository,
)
from backend.v2.contexts.crm.infrastructure.mongo_family_contacts_repo import (
    MongoFamilyContactRepository,
)
from backend.v2.contexts.identity.infrastructure.mongo_user_repo import MongoUserRepository


@dataclass(frozen=True)
class AdminFamilyMessages:
    thread: GetFamilyMessages
    log: LogFamilyContact
    complete: CompleteFamilyContactLog


def compose_family_messages(db: Any, *, families: IndexFamilyDirectory) -> AdminFamilyMessages:
    logs = MongoFamilyContactLogRepository(db)
    return AdminFamilyMessages(
        thread=GetFamilyMessages(
            families=families,
            aliases=MongoUserRepository(db),
            sources=(
                CampaignDeliveriesSource(db),
                ParentDigestSource(db),
                AbsenceNoticeSendsSource(db),
                InvoiceContactCopiesSource(db, MongoFamilyContactRepository(db)),
                ContactLogSource(logs),
            ),
        ),
        log=LogFamilyContact(logs, families),
        complete=CompleteFamilyContactLog(logs, families),
    )
