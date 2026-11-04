"""Email-keyed opt-outs for prospects, plus the send-time gate over them.

A prospect (``crm_contacts`` row) is not a user, and the same person may file
several contacts (a second inquiry with a different phone or age makes a new
row), so a prospect's "stop emailing me" is stored by ``(academy_id, email)``
rather than by recipient id. Tenant-scoped like ``email_preferences``: an
opt-out from one academy's inquiry mail must not silence another academy.

The gate applies to every category, transactional included: a prospect has
no account, no invoice and no portal, so there is no message they must keep
receiving once they have said stop.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from backend.v2.contexts.communications.application.prospect_recipient import (
    prospect_contact_id,
)
from backend.v2.contexts.communications.application.send_gate import (
    ALLOW,
    GateVerdict,
    RecipientGate,
)
from backend.v2.contexts.communications.domain.email_category import EmailCategory
from backend.v2.contexts.communications.domain.email_preferences import normalize_email
from backend.v2.shared.tenancy.repository import TenantScopedRepository

log = logging.getLogger(__name__)


class MongoProspectOptOutRepository(TenantScopedRepository):
    """``email_prospect_opt_outs``, unique on ``(academy_id, email)`` (migration 0215)."""

    collection_name = "email_prospect_opt_outs"

    async def is_opted_out(self, email: str) -> bool:
        key = normalize_email(email)
        return bool(key) and await self._find_one({"email": key}) is not None

    async def opt_out(self, *, email: str, recipient_id: str, source: str = "link") -> None:
        key = normalize_email(email)
        if not key:
            return
        await self._update_one(
            {"email": key},
            {
                "$set": {"recipient_id": recipient_id, "source": source},
                "$setOnInsert": {"email": key, "opted_out_at": datetime.now(UTC)},
            },
            upsert=True,
        )


class ProspectOptOutGate(RecipientGate):
    """Vetoes any send to a prospect recipient whose address has opted out.

    Ignores non-prospect recipients (their choices live in ``email_preferences``)
    and never raises: a store outage logs and allows, like the other gates.
    """

    def __init__(self, repo: MongoProspectOptOutRepository) -> None:
        self._repo = repo

    async def check(
        self, *, recipient_user_id: str, email: str, category: EmailCategory
    ) -> GateVerdict:
        if prospect_contact_id(recipient_user_id) is None:
            return ALLOW
        try:
            opted_out = await self._repo.is_opted_out(email)
        except Exception as exc:
            log.error("prospect_opt_out_gate_unavailable: %s", exc)
            return ALLOW
        if not opted_out:
            return ALLOW
        return GateVerdict(allowed=False, reason="unsubscribed:prospect")
