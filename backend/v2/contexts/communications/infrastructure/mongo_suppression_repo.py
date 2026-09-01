"""Mongo-backed email suppression list, plus the send-time gate over it.

**Deliberately NOT tenant-scoped** — this is not a ``TenantScopedRepository``,
following the documented precedent of ``MongoMagicLinkRepository``. Two
reasons, both load-bearing:

* the Resend sender domain is shared by every academy, so a hard bounce
  observed while academy A was mailing must stop academy B from mailing the
  same address, or the reputation damage this list exists to prevent still
  happens;
* the webhook that writes it has no tenant to scope to — Resend's payload
  carries an address and nothing else.

``first_seen_academy_id`` is recorded as best-effort audit attribution only.
It is never a query filter.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from pymongo.errors import DuplicateKeyError

from backend.v2.contexts.communications.application.send_gate import (
    ALLOW,
    GateVerdict,
)
from backend.v2.contexts.communications.domain.email_category import EmailCategory
from backend.v2.contexts.communications.domain.email_suppression import (
    EmailSuppression,
    SuppressionReason,
    escalates,
    normalize_email,
)
from backend.v2.shared.ids import new_ulid
from backend.v2.shared.tenancy.context import _current as _tenant_context

log = logging.getLogger(__name__)


def _as_utc(value: Any) -> datetime | None:
    if not isinstance(value, datetime):
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _best_effort_academy_id() -> str | None:
    """The tenant that happened to be in scope, for audit only.

    Read straight off the ContextVar rather than ``current_academy_id()``:
    the webhook path legitimately has no tenant, and that must be ``None``,
    not an exception.
    """
    return _tenant_context.get()


class MongoSuppressionRepository:
    """Read/write access to ``email_suppressions``, keyed by address."""

    collection_name = "email_suppressions"

    def __init__(self, db: Any) -> None:
        self._suppressions = db[self.collection_name]

    async def record(
        self,
        *,
        email: str,
        reason: SuppressionReason,
        bounce_subtype: str | None = None,
        provider_event_id: str | None = None,
    ) -> EmailSuppression:
        key = normalize_email(email)
        now = datetime.now(UTC)
        existing = await self._suppressions.find_one({"email": key})
        if existing is None:
            doc = {
                "suppression_id": new_ulid(),
                "email": key,
                "reason": reason.value,
                "bounce_subtype": bounce_subtype,
                "provider": "resend",
                "provider_event_id": provider_event_id,
                "first_seen_at": now,
                "last_seen_at": now,
                "first_seen_academy_id": _best_effort_academy_id(),
                "active": True,
                "released_at": None,
                "released_by": None,
            }
            try:
                await self._suppressions.insert_one(dict(doc))
                return _to_model(doc)
            except DuplicateKeyError:
                # Concurrent first write for the same address — fall through
                # to the update path so the two events merge instead of one
                # of them vanishing.
                existing = await self._suppressions.find_one({"email": key})
                if existing is None:  # pragma: no cover - defensive
                    return _to_model(doc)

        current = _reason_of(existing)
        # Escalate only. A mailbox that has already hard-bounced does not
        # become deliverable because a later complaint arrives for it.
        next_reason = reason if escalates(current, reason) else current
        updates: dict[str, Any] = {
            "last_seen_at": now,
            "reason": next_reason.value,
            # A fresh provider event re-suppresses an address an admin had
            # released: the release was a judgement call, the bounce is a fact.
            "active": True,
            "released_at": None,
            "released_by": None,
        }
        if provider_event_id is not None:
            updates["provider_event_id"] = provider_event_id
        if bounce_subtype is not None:
            updates["bounce_subtype"] = bounce_subtype
        await self._suppressions.update_one({"email": key}, {"$set": updates})
        merged = {**existing, **updates}
        return _to_model(merged)

    async def get_active(self, email: str) -> EmailSuppression | None:
        doc = await self._suppressions.find_one({"email": normalize_email(email), "active": True})
        return _to_model(doc) if doc else None

    async def list_active(self, *, limit: int = 100) -> list[EmailSuppression]:
        cursor = self._suppressions.find({"active": True}).sort([("last_seen_at", -1)]).limit(limit)
        return [_to_model(doc) async for doc in cursor]

    async def release(self, *, email: str, released_by: str) -> bool:
        result = await self._suppressions.update_one(
            {"email": normalize_email(email), "active": True},
            {
                "$set": {
                    "active": False,
                    "released_at": datetime.now(UTC),
                    "released_by": released_by,
                }
            },
        )
        return bool(result.modified_count)


def _reason_of(doc: dict[str, Any]) -> SuppressionReason:
    try:
        return SuppressionReason(str(doc.get("reason")))
    except ValueError:
        # An unknown reason string must not crash a send. Treat it as the
        # least severe suppression we have.
        return SuppressionReason.MANUAL


def _to_model(doc: dict[str, Any]) -> EmailSuppression:
    first_seen = _as_utc(doc.get("first_seen_at")) or datetime.now(UTC)
    return EmailSuppression(
        email=str(doc.get("email") or ""),
        reason=_reason_of(doc),
        first_seen_at=first_seen,
        last_seen_at=_as_utc(doc.get("last_seen_at")) or first_seen,
        active=bool(doc.get("active", True)),
        bounce_subtype=doc.get("bounce_subtype"),
        provider=str(doc.get("provider") or "resend"),
        provider_event_id=doc.get("provider_event_id"),
        first_seen_academy_id=doc.get("first_seen_academy_id"),
        released_at=_as_utc(doc.get("released_at")),
        released_by=doc.get("released_by"),
    )


@dataclass
class MongoSuppressionGate:
    """Send-time suppression check — reason-aware (issue #556).

    - ``hard_bounce`` blocks **every** category, transactional included. The
      mailbox does not exist; sending is not "delivering an invoice", it is
      burning the shared sender domain's reputation for every tenant. The
      invoice is still in the parent portal; the admin sees the suppression in
      the delivery log.
    - ``complaint`` (spam report) blocks ``DIGEST`` and ``CAMPAIGN``; **allows**
      ``TRANSACTIONAL``. A complaint is a marketing signal, not proof the
      address is dead.
    - ``manual`` (admin-added) → same treatment as ``complaint``.
    - ``soft_bounce`` / ``delivery_delayed`` → **never** suppress. Recorded as
      a provider event, nothing more. A full mailbox is not a dead address.

    Suppression is evaluated *before* preferences, and ``hard_bounce``
    overrides everything.

    A store outage returns ALLOW and logs: mail that should have been stopped
    is a deliverability cost, but a gate that fails closed on a Mongo blip
    stops every invoice in the system (the #435 lesson).
    """

    suppressions: MongoSuppressionRepository

    async def check(
        self, *, recipient_user_id: str, email: str, category: EmailCategory
    ) -> GateVerdict:
        try:
            record = await self.suppressions.get_active(email)
        except Exception:
            log.exception("suppression_gate_unavailable: allowing send for category=%s", category)
            return ALLOW
        if record is None or not record.blocks(category):
            return ALLOW
        return GateVerdict(allowed=False, reason=record.gate_reason)
