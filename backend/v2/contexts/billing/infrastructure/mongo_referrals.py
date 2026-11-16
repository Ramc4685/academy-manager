"""Mongo adapters for the referral programme (L9 C2).

* ``MongoReferralRepository``: ``referrals``, one row per referred family
  (``referral_referred_parent_unique``) and at most one row per referrer
  yearly reward slot (``referral_reward_slot_unique``), both from 0238.
* ``MongoReferralCodeRepository``: ``referral_codes``, one stable code per
  parent per academy (``referral_code_parent_unique`` /
  ``referral_code_unique``).
* ``MongoReferralSources``: read-only lookups across CRM contacts,
  registrations, enrollments, invoices, payments and disputes; identity
  (aliases, email, phone, name) comes from the users repository's
  ``resolve_parent_aliases``.

Every query here runs inside the academy's ``tenant_scope`` (request or the
daily job), so the tenant helpers stamp ``academy_id``. No ``$or`` across
partial-indexed fields (#894).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any, Protocol

from pymongo.errors import DuplicateKeyError

from backend.v2.contexts.billing.application.use_cases.referrals import (
    ClaimOutcome,
    FirstInvoice,
    Household,
    ReferralCandidate,
)
from backend.v2.contexts.billing.domain.payment_dispute import CLOSED_DISPUTE_STATUSES
from backend.v2.contexts.billing.domain.referral import IneligibleReason, Referral
from backend.v2.contexts.billing.infrastructure.mongo_monthly_billing import resolved_parent_id
from backend.v2.shared.tenancy import TenantScopedRepository
from backend.v2.shared.time import ensure_utc

_DATETIME_FIELDS = (
    "attributed_at",
    "qualified_at",
    "grant_due_at",
    "granted_at",
    "reviewed_at",
    "created_at",
    "updated_at",
)


def _referral(doc: dict[str, Any]) -> Referral:
    data = {k: v for k, v in doc.items() if k in Referral.model_fields}
    for field in _DATETIME_FIELDS:
        if isinstance(data.get(field), datetime):
            data[field] = ensure_utc(data[field])
    return Referral.model_validate(data)


class MongoReferralRepository(TenantScopedRepository):
    collection_name = "referrals"

    async def family_statuses(self) -> dict[str, str]:
        cursor = self.collection.find(self._scoped({}), {"referred_parent_id": 1, "status": 1})
        return {str(doc["referred_parent_id"]): str(doc["status"]) async for doc in cursor}

    async def insert_if_absent(self, referral: Referral) -> bool:
        doc = referral.model_dump(mode="python")
        doc.pop("academy_id", None)
        try:
            await self._insert_one(doc)
        except DuplicateKeyError:
            return False  # already recorded (another run, or the other source)
        return True

    async def replace_unreviewed(self, referral: Referral) -> bool:
        doc = referral.model_dump(
            mode="python", exclude={"academy_id", "referral_id", "created_at"}
        )
        result = await self._update_one(
            {"referred_parent_id": referral.referred_parent_id, "status": "needs_review"},
            {"$set": doc},
        )
        return bool(result.modified_count == 1)

    async def approve(self, referral_id: str, *, actor_id: str, now: datetime) -> bool:
        result = await self._update_one(
            {"referral_id": referral_id, "status": "needs_review"},
            {
                "$set": {
                    "status": "pending",
                    "reviewed_by": actor_id,
                    "reviewed_at": now,
                    "updated_at": now,
                }
            },
        )
        return bool(result.modified_count == 1)

    async def get(self, referral_id: str) -> Referral | None:
        doc = await self._find_one({"referral_id": referral_id})
        return _referral(doc) if doc else None

    async def list_pending(self) -> list[Referral]:
        cursor = self._find_many({"status": "pending"}, sort=[("created_at", 1)])
        return [_referral(doc) async for doc in cursor]

    async def list_recent(self, limit: int) -> list[Referral]:
        cursor = self._find_many({}, sort=[("created_at", -1), ("referral_id", -1)], limit=limit)
        return [_referral(doc) async for doc in cursor]

    async def count_granted_for(self, referrer_parent_id: str) -> int:
        return await self._count({"referrer_parent_id": referrer_parent_id, "status": "granted"})

    async def mark_qualified(
        self,
        referral_id: str,
        *,
        invoice_id: str,
        qualified_at: datetime,
        due_at: datetime,
        now: datetime,
    ) -> None:
        await self._update_one(
            {"referral_id": referral_id, "status": "pending", "qualified_at": None},
            {
                "$set": {
                    "qualified_invoice_id": invoice_id,
                    "qualified_at": qualified_at,
                    "grant_due_at": due_at,
                    "updated_at": now,
                }
            },
        )

    async def clear_qualification(self, referral_id: str, *, now: datetime) -> None:
        await self._update_one(
            {"referral_id": referral_id, "status": "pending"},
            {
                "$set": {
                    "qualified_invoice_id": None,
                    "qualified_at": None,
                    "grant_due_at": None,
                    "reward_key": None,
                    "reward_year": None,
                    "updated_at": now,
                }
            },
        )

    async def mark_ineligible(
        self, referral_id: str, reason: IneligibleReason, *, now: datetime
    ) -> None:
        await self._update_one(
            {"referral_id": referral_id, "status": "pending", "reward_key": None},
            {"$set": {"status": "ineligible", "reason": reason, "updated_at": now}},
        )

    async def count_reward_slots(self, referrer_parent_id: str, year: int) -> int:
        return await self._count(
            {
                "referrer_parent_id": referrer_parent_id,
                "reward_year": year,
                "reward_key": {"$gt": ""},
            }
        )

    async def claim_reward_slot(
        self, referral_id: str, *, key: str, year: int, now: datetime
    ) -> ClaimOutcome:
        try:
            result = await self._update_one(
                {"referral_id": referral_id, "status": "pending", "reward_key": None},
                {"$set": {"reward_key": key, "reward_year": year, "updated_at": now}},
            )
        except DuplicateKeyError:
            return "taken"
        return "claimed" if result.modified_count == 1 else "lost"

    async def mark_granted(
        self,
        referral_id: str,
        *,
        referrer_credit_id: str | None,
        referred_credit_id: str | None,
        now: datetime,
    ) -> None:
        await self._update_one(
            {"referral_id": referral_id, "status": "pending", "reward_key": {"$gt": ""}},
            {
                "$set": {
                    "status": "granted",
                    "referrer_credit_id": referrer_credit_id,
                    "referred_credit_id": referred_credit_id,
                    "granted_at": now,
                    "updated_at": now,
                }
            },
        )


class MongoReferralCodeRepository(TenantScopedRepository):
    collection_name = "referral_codes"

    async def code_for(self, parent_id: str) -> str | None:
        doc = await self._find_one({"parent_id": parent_id})
        return str(doc["referral_code"]) if doc else None

    async def insert(self, parent_id: str, code: str, *, now: datetime) -> bool:
        try:
            await self._insert_one(
                {"parent_id": parent_id, "referral_code": code, "created_at": now}
            )
        except DuplicateKeyError:
            return False
        return True

    async def parent_for(self, code: str) -> str | None:
        if not code:
            return None
        doc = await self._find_one({"referral_code": code})
        return str(doc["parent_id"]) if doc else None


class _ParentAliases(Protocol):
    async def resolve_parent_aliases(self, raw_ids: Sequence[str]) -> Mapping[str, Any]: ...


#: A dispute with one of these outcomes left the money with the academy.
_SETTLED_FOR_ACADEMY = sorted(CLOSED_DISPUTE_STATUSES - {"lost"})


class MongoReferralSources(TenantScopedRepository):
    """Read-only. ``collection_name`` is the CRM contacts; the other tenant
    collections go through the tenant-stamped ``*_in_collection`` helpers.
    Identity is global and comes from ``users`` (the users repository)."""

    collection_name = "crm_contacts"

    def __init__(self, db: Any, *, users: _ParentAliases) -> None:
        super().__init__(db)
        self._users = users

    async def candidates(self, *, since: datetime) -> list[ReferralCandidate]:
        found: list[ReferralCandidate] = []
        # A website inquiry carrying a code, converted at registration approval.
        async for doc in self._find_many(
            {
                "attribution.referral_code": {"$gt": ""},
                "converted_parent_id": {"$gt": ""},
                "created_at": {"$gte": since},
            },
            sort=[("created_at", 1)],
        ):
            found.append(
                ReferralCandidate(
                    referred_parent_id=str(doc["converted_parent_id"]),
                    code=str(doc["attribution"]["referral_code"]),
                    source="contact",
                    source_id=str(doc.get("contact_id") or ""),
                    attributed_at=ensure_utc(doc["created_at"]),
                    emails=(doc.get("email"),),
                    phones=(doc.get("phone_digits"),),
                )
            )
        # A registration carrying a code, once approved.
        async for doc in self._find_many_in_collection(
            "onboarding_applications",
            {
                "parent_profile.referral_code": {"$gt": ""},
                "status": "APPROVED",
                "created_at": {"$gte": since},
            },
            sort=[("created_at", 1)],
        ):
            profile = doc.get("parent_profile") or {}
            found.append(
                ReferralCandidate(
                    referred_parent_id=str(doc["parent_user_id"]),
                    code=str(profile["referral_code"]),
                    source="application",
                    source_id=str(doc.get("application_id") or ""),
                    attributed_at=ensure_utc(doc["created_at"]),
                    emails=(doc.get("parent_email"), profile.get("email")),
                    phones=(profile.get("phone"),),
                )
            )
        found.sort(key=lambda c: c.attributed_at)
        return found

    async def household(self, parent_id: str) -> Household:
        found = (await self._users.resolve_parent_aliases([parent_id])).get(parent_id)
        if found is None:
            return Household(ids=frozenset({parent_id}))
        return Household(
            ids=frozenset({parent_id, *found.aliases}),
            emails=(found.email,),
            phones=(found.phone,),
        )

    async def has_invoice_before(self, parent_ids: frozenset[str], at: datetime) -> bool:
        doc = await self._find_one_in_collection(
            "invoices",
            {
                "parent_id": {"$in": sorted(parent_ids)},
                "status": {"$ne": "void"},
                "is_deleted": {"$ne": True},
                "created_at": {"$lt": at},
            },
        )
        return doc is not None

    async def first_paid_invoice(
        self, parent_ids: frozenset[str], *, monthly_only: bool
    ) -> FirstInvoice | None:
        query: dict[str, Any] = {
            "parent_id": {"$in": sorted(parent_ids)},
            "status": "paid",
            "total_cents": {"$gt": 0},
            "is_deleted": {"$ne": True},
        }
        if monthly_only:
            # shortcut: a monthly tuition invoice is one with a class and no
            # header source (late fees, moves and manual extras carry one);
            # upgrade if invoices ever get an explicit kind.
            query |= {"enrollment_id": {"$gt": ""}, "source_type": None}
        # The earliest good one, so an old invoice left open (or refunded)
        # never blocks a family that has since paid.
        async for doc in self._find_many_in_collection(
            "invoices", query, sort=[("created_at", 1), ("invoice_id", 1)], limit=50
        ):
            if _refunded_in_full(doc) or await self._disputed(str(doc["invoice_id"])):
                continue
            invoice_id = str(doc["invoice_id"])
            last = await self._find_one_in_collection(
                "payment_allocations", {"invoice_id": invoice_id}, sort=[("created_at", -1)]
            )
            paid_at = (last or {}).get("created_at") or doc.get("updated_at") or doc["created_at"]
            return FirstInvoice(
                invoice_id=invoice_id, parent_id=str(doc["parent_id"]), paid_at=ensure_utc(paid_at)
            )
        return None

    async def invoice_still_paid(self, invoice_id: str) -> bool:
        doc = await self._find_one_in_collection("invoices", {"invoice_id": invoice_id})
        if doc is None or doc.get("status") != "paid" or int(doc.get("total_cents") or 0) <= 0:
            return False
        return not _refunded_in_full(doc) and not await self._disputed(invoice_id)

    async def _disputed(self, invoice_id: str) -> bool:
        """A dispute still open, or lost, on any payment applied to the invoice."""
        payment_ids = [
            str(doc["payment_id"])
            async for doc in self._find_many_in_collection(
                "payment_allocations", {"invoice_id": invoice_id}
            )
            if doc.get("payment_id")
        ]
        if not payment_ids:
            return False
        doc = await self._find_one_in_collection(
            "payment_disputes",
            {"payment_id": {"$in": payment_ids}, "outcome": {"$nin": _SETTLED_FOR_ACADEMY}},
        )
        return doc is not None

    async def billing_parent_id(self, parent_ids: frozenset[str]) -> str | None:
        ids = sorted(parent_ids)
        # One equality question per field, never an $or across fields (#894).
        for field_name in ("parent_id", "parent_user_id"):
            enrollment = await self._find_one_in_collection(
                "enrollments", {field_name: {"$in": ids}}, sort=[("created_at", -1)]
            )
            if enrollment is not None:
                return resolved_parent_id(enrollment, None) or None
        invoice = await self._find_one_in_collection(
            "invoices",
            {"parent_id": {"$in": ids}, "status": {"$ne": "void"}, "is_deleted": {"$ne": True}},
            sort=[("created_at", -1)],
        )
        return str(invoice["parent_id"]) if invoice else None

    async def display_names(self, parent_ids: set[str]) -> dict[str, str]:
        found = await self._users.resolve_parent_aliases(sorted(parent_ids))
        return {raw: str(alias.display_name or "") for raw, alias in found.items()}


def _refunded_in_full(invoice: Mapping[str, Any]) -> bool:
    return int(invoice.get("refunded_cents") or 0) >= int(invoice.get("total_cents") or 0)
