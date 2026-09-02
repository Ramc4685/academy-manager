"""Mongo-backed recipient email preferences and the send-time gate (#555).

Tenant-scoped, deliberately: a preference is a relationship between a family
and *one academy*. Unsubscribing from one academy's digests must not silence a
sibling enrolled elsewhere on the same platform. (Contrast the suppression
list in #556, which is intentionally cross-tenant because a dead mailbox is a
fact about the shared sender domain, not about a tenant.)
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from backend.v2.contexts.communications.application.ports import EmailPreferenceRepository
from backend.v2.contexts.communications.application.send_gate import (
    ALLOW,
    GateVerdict,
    RecipientGate,
)
from backend.v2.contexts.communications.domain.email_category import (
    UNSUBSCRIBABLE_CATEGORIES,
    EmailCategory,
)
from backend.v2.contexts.communications.domain.email_preferences import (
    EmailPreferences,
    normalize_email,
)
from backend.v2.shared.ids import new_ulid
from backend.v2.shared.tenancy.repository import TenantScopedRepository

log = logging.getLogger(__name__)


def _to_preferences(doc: dict[str, Any]) -> EmailPreferences:
    return EmailPreferences(
        preference_id=str(doc.get("preference_id") or ""),
        user_id=str(doc.get("user_id") or ""),
        email=doc.get("email"),
        campaigns_opted_out=bool(doc.get("campaigns_opted_out", False)),
        digests_opted_out=bool(doc.get("digests_opted_out", False)),
        # Absent field == opted in, so #612 needs no backfill migration.
        notifications_opted_out=bool(doc.get("notifications_opted_out", False)),
        opted_out_at=doc.get("opted_out_at"),
        source=doc.get("source"),
        updated_at=doc.get("updated_at"),
    )


class MongoEmailPreferenceRepository(TenantScopedRepository, EmailPreferenceRepository):
    """``email_preferences``, keyed ``(academy_id, user_id)``.

    Rows are created only on a real change, so an absent document means the
    recipient is opted in to everything.
    """

    collection_name = "email_preferences"

    async def get(self, user_id: str) -> EmailPreferences | None:
        doc = await self._find_one({"user_id": user_id})
        return _to_preferences(doc) if doc else None

    async def set_opt_outs(
        self,
        *,
        user_id: str,
        email: str | None,
        campaigns_opted_out: bool,
        digests_opted_out: bool,
        source: str,
        notifications_opted_out: bool | None = None,
    ) -> EmailPreferences:
        now = datetime.now(UTC)
        if notifications_opted_out is None:
            # "Leave unchanged" (#612): a caller that does not know about the
            # roster-alert category must not flip it. Read-then-write is a
            # benign race here — the loser of two concurrent saves is a
            # preference write the recipient made themselves, seconds apart.
            existing = await self.get(user_id)
            notifications_opted_out = bool(existing and existing.notifications_opted_out)
        opted_out_any = campaigns_opted_out or digests_opted_out or notifications_opted_out
        update: dict[str, Any] = {
            "$set": {
                "campaigns_opted_out": campaigns_opted_out,
                "digests_opted_out": digests_opted_out,
                "notifications_opted_out": notifications_opted_out,
                "source": source,
                "updated_at": now,
                # Cleared when the recipient opts back in, so the field always
                # answers "when did they last switch something off".
                "opted_out_at": now if opted_out_any else None,
            },
            "$setOnInsert": {"preference_id": new_ulid(), "user_id": user_id},
        }
        normalized = normalize_email(email)
        if normalized:
            update["$set"]["email"] = normalized
        doc = await self._find_one_and_update({"user_id": user_id}, update, upsert=True)
        if doc is None:  # pragma: no cover - upsert always returns the doc
            doc = await self._find_one({"user_id": user_id}) or {}
        return _to_preferences(doc)


class MongoEmailPreferenceGate(RecipientGate):
    """Send-time veto backed by ``email_preferences``.

    A preference gate NEVER blocks ``EmailCategory.TRANSACTIONAL``. Invoices,
    dunning notices, payment reminders and login invites are the record of an
    existing commercial relationship; CAN-SPAM's opt-out applies to commercial
    messages, not to these, and a family that suppressed its own invoice would
    be a billing incident. The gate returns ``ALLOW`` for ``TRANSACTIONAL``
    before it does a database read.

    It also never raises: a preference store that is down must not stop all
    mail (the #435 lesson), so an error logs loudly and allows.
    """

    def __init__(self, db: Any) -> None:
        self._repo = MongoEmailPreferenceRepository(db)

    async def check(
        self, *, recipient_user_id: str, email: str, category: EmailCategory
    ) -> GateVerdict:
        if category not in UNSUBSCRIBABLE_CATEGORIES:
            return ALLOW
        try:
            stored = await self._repo.get(recipient_user_id)
        except Exception as exc:
            log.error("email_preference_gate_unavailable: %s", exc)
            return ALLOW
        if stored is None or not stored.blocks(category):
            return ALLOW
        return GateVerdict(allowed=False, reason=f"unsubscribed:{category.value}")
