"""Mongo sources of the family Messages thread (People CRM Phase 6, roadmap L4c).

Each source reads ONE family's rows of ONE academy, newest first, at most
``MESSAGES_CAP`` per query, and turns them into ``MessageEntry`` values. Every
query carries ``academy_id`` (the scope's academy, the request's tenant) and
is an equality (one per parent alias) or an ``$in`` on an indexed field:

* :class:`CampaignDeliveriesSource`: ``message_deliveries`` addressed to the
  parent (``message_deliveries_academy_recipient_sent``, 0101), with the
  campaign's subject from ``message_campaigns``.
* :class:`ParentDigestSource`: ``parent_digest_sends`` of the parent
  (``parent_digest_sends_academy_parent_date_unique``, 0148); empty digests
  (``skipped_empty``) were never sent and are left out.
* :class:`AbsenceNoticeSendsSource`: the confirmation email the PARENT got
  for an absence notice of one of the children (``absence_notice_sends``,
  audience ``parent``; 0172). The staff alert is not a message to the family.
* :class:`InvoiceContactCopiesSource`: invoice copies mailed to the family's
  own contacts (``invoice_contact_email_sends``, 0197), matched on the
  contact's email AND its ``contact_id``, so another family's contact with
  the same address never shows here.
* :class:`ContactLogSource`: contacts staff logged by hand
  (``family_contact_log``, 0203) through the tenant-scoped repository.

No row is written here; nothing here reads money.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from backend.v2.contexts.crm.application.family_messages import (
    FamilyContactLogRepository,
    FamilyMessagesScope,
    contact_log_entry,
)
from backend.v2.contexts.crm.application.ports import FamilyContactRepository
from backend.v2.contexts.crm.domain.family_messages import (
    MESSAGES_CAP,
    MessageEntry,
    MessageStatus,
    as_utc,
)

_SEND_STATUSES: dict[str, MessageStatus] = {
    "queued": "queued",
    "sent": "sent",
    "opened": "opened",
    "failed": "failed",
}


def _dt(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return as_utc(value)
    if isinstance(value, str) and value:
        # parent_digest_sends.sent_at is stored as an ISO string.
        try:
            return as_utc(datetime.fromisoformat(value.replace("Z", "+00:00")))
        except ValueError:
            return None
    return None


def _s(value: Any) -> str | None:
    return str(value) if value not in (None, "") else None


def _status(value: Any) -> MessageStatus | None:
    return _SEND_STATUSES.get(str(value or "queued"))


# ------------------------------------------------------------------ campaigns


class CampaignDeliveriesSource:
    name = "campaigns"

    def __init__(self, db: Any) -> None:
        self._db = db

    async def fetch(self, scope: FamilyMessagesScope) -> Sequence[MessageEntry]:
        rows: dict[str, dict[str, Any]] = {}
        for alias in scope.parent_aliases:
            cursor = self._db["message_deliveries"].find(
                {"academy_id": scope.academy_id, "recipient_user_id": alias},
                {
                    "_id": 0,
                    "delivery_id": 1,
                    "campaign_id": 1,
                    "recipient_email": 1,
                    "status": 1,
                    "sent_at": 1,
                    "opened_at": 1,
                    "failed_reason": 1,
                },
                sort=[("sent_at", -1)],
                limit=MESSAGES_CAP,
            )
            async for doc in cursor:
                if doc.get("delivery_id"):
                    rows[str(doc["delivery_id"])] = doc
        campaign_ids = sorted(
            {str(d["campaign_id"]) for d in rows.values() if d.get("campaign_id")}
        )
        campaigns: dict[str, dict[str, Any]] = {}
        if campaign_ids:
            cursor = self._db["message_campaigns"].find(
                {"academy_id": scope.academy_id, "campaign_id": {"$in": campaign_ids}},
                {"_id": 0, "campaign_id": 1, "subject": 1, "created_at": 1, "sent_at": 1},
            )
            campaigns = {str(c["campaign_id"]): c async for c in cursor}
        entries: list[MessageEntry] = []
        for delivery_id, doc in rows.items():
            status = _status(doc.get("status"))
            if status is None:
                continue
            campaign = campaigns.get(str(doc.get("campaign_id") or ""), {})
            at = (
                _dt(doc.get("sent_at"))
                or _dt(campaign.get("sent_at"))
                or _dt(campaign.get("created_at"))
            )
            if at is None:
                continue
            subject = _s(campaign.get("subject"))
            entries.append(
                MessageEntry(
                    entry_id=f"campaign:{delivery_id}",
                    at=at,
                    channel="email",
                    source="campaign",
                    status=status,
                    summary=f"Email: {subject}" if subject else "Academy email",
                    recipient=_s(doc.get("recipient_email")),
                    failed_reason=_s(doc.get("failed_reason")) if status == "failed" else None,
                )
            )
        return entries


# ------------------------------------------------------------------ digest


class ParentDigestSource:
    name = "digest"

    def __init__(self, db: Any) -> None:
        self._db = db

    async def fetch(self, scope: FamilyMessagesScope) -> Sequence[MessageEntry]:
        entries: list[MessageEntry] = []
        for alias in scope.parent_aliases:
            cursor = self._db["parent_digest_sends"].find(
                {"academy_id": scope.academy_id, "parent_id": alias},
                {
                    "_id": 0,
                    "digest_id": 1,
                    "digest_date": 1,
                    "status": 1,
                    "sent_at": 1,
                    "created_at": 1,
                    "failed_reason": 1,
                },
                sort=[("digest_date", -1)],
                limit=MESSAGES_CAP,
            )
            async for doc in cursor:
                status = _status(doc.get("status"))  # skipped_empty -> None
                at = _dt(doc.get("sent_at")) or _dt(doc.get("created_at"))
                if status is None or at is None or not doc.get("digest_id"):
                    continue
                day = str(doc.get("digest_date") or "")[:10]
                entries.append(
                    MessageEntry(
                        entry_id=f"digest:{doc['digest_id']}",
                        at=at,
                        channel="email",
                        source="digest",
                        status=status,
                        summary=f"Parent digest for {day}" if day else "Parent digest",
                        failed_reason=(
                            _s(doc.get("failed_reason")) if status == "failed" else None
                        ),
                    )
                )
        return entries


# ------------------------------------------------------------------ absence notices


class AbsenceNoticeSendsSource:
    name = "absence_notices"

    def __init__(self, db: Any) -> None:
        self._db = db

    async def fetch(self, scope: FamilyMessagesScope) -> Sequence[MessageEntry]:
        if not scope.student_ids:
            return []
        # Served by absence_notices_academy_student_submitted (0202).
        cursor = self._db["absence_notices"].find(
            {"academy_id": scope.academy_id, "student_id": {"$in": list(scope.student_ids)}},
            {"_id": 0, "notice_id": 1, "student_id": 1},
            sort=[("submitted_at", -1)],
            limit=MESSAGES_CAP,
        )
        children = {
            str(doc["notice_id"]): str(doc.get("student_id") or "")
            async for doc in cursor
            if doc.get("notice_id")
        }
        if not children:
            return []
        # Served by the (academy_id, notice_id, audience) unique index (0172).
        cursor = self._db["absence_notice_sends"].find(
            {
                "academy_id": scope.academy_id,
                "notice_id": {"$in": sorted(children)},
                "audience": "parent",
            },
            {
                "_id": 0,
                "send_id": 1,
                "notice_id": 1,
                "status": 1,
                "created_at": 1,
                "failed_reason": 1,
            },
        )
        entries: list[MessageEntry] = []
        async for doc in cursor:
            status = _status(doc.get("status"))
            at = _dt(doc.get("created_at"))
            if status is None or at is None or not doc.get("send_id"):
                continue
            child = scope.student_names.get(children.get(str(doc.get("notice_id")), ""), "Child")
            entries.append(
                MessageEntry(
                    entry_id=f"absence_notice:{doc['send_id']}",
                    at=at,
                    channel="email",
                    source="absence_notice",
                    status=status,
                    summary=f"Absence notice confirmation for {child}",
                    failed_reason=_s(doc.get("failed_reason")) if status == "failed" else None,
                )
            )
        return entries


# ------------------------------------------------------------------ invoice copies


class InvoiceContactCopiesSource:
    name = "invoice_copies"

    def __init__(self, db: Any, contacts: FamilyContactRepository) -> None:
        self._db = db
        self._contacts = contacts

    async def fetch(self, scope: FamilyMessagesScope) -> Sequence[MessageEntry]:
        contacts = await self._contacts.list_for_family(scope.family_id)
        by_id = {c.contact_id: c for c in contacts if c.email}
        entries: list[MessageEntry] = []
        for email in sorted({c.email for c in by_id.values() if c.email}):
            # Served by invoice_contact_email_sends_key_unique (0197) on its
            # (academy_id, recipient_email) prefix.
            cursor = self._db["invoice_contact_email_sends"].find(
                {
                    "academy_id": scope.academy_id,
                    "recipient_email": email,
                    "contact_id": {"$in": sorted(by_id)},
                },
                {
                    "_id": 0,
                    "send_id": 1,
                    "contact_id": 1,
                    "recipient_email": 1,
                    "status": 1,
                    "created_at": 1,
                    "failed_reason": 1,
                },
                sort=[("created_at", -1)],
                limit=MESSAGES_CAP,
            )
            async for doc in cursor:
                status = _status(doc.get("status"))
                at = _dt(doc.get("created_at"))
                contact = by_id.get(str(doc.get("contact_id") or ""))
                if status is None or at is None or contact is None or not doc.get("send_id"):
                    continue
                entries.append(
                    MessageEntry(
                        entry_id=f"invoice_copy:{doc['send_id']}",
                        at=at,
                        channel="email",
                        source="invoice_copy",
                        status=status,
                        summary=f"Invoice copy to {contact.name}",
                        recipient=_s(doc.get("recipient_email")),
                        failed_reason=(
                            _s(doc.get("failed_reason")) if status == "failed" else None
                        ),
                    )
                )
        return entries


# ------------------------------------------------------------------ staff log


class ContactLogSource:
    name = "contact_log"

    def __init__(self, logs: FamilyContactLogRepository) -> None:
        self._logs = logs

    async def fetch(self, scope: FamilyMessagesScope) -> Sequence[MessageEntry]:
        rows = await self._logs.list_for_family(scope.family_id, limit=MESSAGES_CAP)
        return [contact_log_entry(row) for row in rows]
