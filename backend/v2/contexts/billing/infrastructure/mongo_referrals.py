"""Mongo adapters for the referral programme (L9 C2).

* ``MongoReferralRepository``: ``referrals``, one row per referred family
  (``referral_referred_parent_unique``) and at most one row per referrer
  yearly reward slot (``referral_reward_slot_unique``), both from 0238.
* ``MongoReferralCodeRepository``: ``referral_codes``, one stable code per
  parent per academy (``referral_code_parent_unique`` /
  ``referral_code_unique``).
* ``MongoReferralSources``: read-only lookups across CRM contacts,
  registrations, users and invoices.

Every query here runs inside the academy's ``tenant_scope`` (request or the
daily job), so the tenant helpers stamp ``academy_id``. No ``$or`` across
partial-indexed fields (#894).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from bson import ObjectId
from pymongo.errors import DuplicateKeyError

from backend.v2.contexts.billing.application.use_cases.referrals import (
    ClaimOutcome,
    FirstInvoice,
    Household,
    ReferralCandidate,
)
from backend.v2.contexts.billing.domain.referral import IneligibleReason, Referral
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

    async def referred_parent_ids(self) -> set[str]:
        cursor = self.collection.find(self._scoped({}), {"referred_parent_id": 1})
        return {str(doc["referred_parent_id"]) async for doc in cursor}

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


_USER_REFERENCE_FIELDS = ("user_id", "firebase_uid", "auth_uid")


class MongoReferralSources(TenantScopedRepository):
    """Read-only. ``collection_name`` is the CRM contacts; the other
    collections go through the tenant-stamped ``*_in_collection`` helpers,
    except ``users``, which is global."""

    collection_name = "crm_contacts"

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

    async def _user(self, parent_id: str) -> dict[str, Any] | None:
        projection = {"user_id": 1, "firebase_uid": 1, "auth_uid": 1, "email": 1, "phone": 1}
        projection |= {"display_name": 1, "name": 1}
        # One equality per field, never an $or across fields (#894).
        for field_name in _USER_REFERENCE_FIELDS:
            doc = await self._db["users"].find_one({field_name: parent_id}, projection)
            if doc is not None:
                return dict(doc)
        by_id: list[Any] = [parent_id]
        if ObjectId.is_valid(parent_id):
            by_id.append(ObjectId(parent_id))
        doc = await self._db["users"].find_one({"_id": {"$in": by_id}}, projection)
        return dict(doc) if doc else None

    async def household(self, parent_id: str) -> Household:
        doc = await self._user(parent_id) or {}
        ids = {parent_id} | {
            str(doc[name]) for name in (*_USER_REFERENCE_FIELDS, "_id") if doc.get(name)
        }
        return Household(ids=frozenset(ids), emails=(doc.get("email"),), phones=(doc.get("phone"),))

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

    async def first_invoice(
        self, parent_ids: frozenset[str], *, monthly_only: bool
    ) -> FirstInvoice | None:
        query: dict[str, Any] = {
            "parent_id": {"$in": sorted(parent_ids)},
            "status": {"$ne": "void"},
            "is_deleted": {"$ne": True},
        }
        if monthly_only:
            # shortcut: a monthly tuition invoice is one with a class and no
            # header source (late fees, moves and manual extras carry one);
            # upgrade if invoices ever get an explicit kind.
            query |= {"enrollment_id": {"$gt": ""}, "source_type": None}
        doc = await self._find_one_in_collection(
            "invoices", query, sort=[("created_at", 1), ("invoice_id", 1)]
        )
        if doc is None:
            return None
        invoice_id = str(doc["invoice_id"])
        if doc.get("status") != "paid":
            return FirstInvoice(invoice_id=invoice_id, paid_at=None)
        last = await self._find_one_in_collection(
            "payment_allocations", {"invoice_id": invoice_id}, sort=[("created_at", -1)]
        )
        paid_at = (last or {}).get("created_at") or doc.get("updated_at") or doc["created_at"]
        return FirstInvoice(invoice_id=invoice_id, paid_at=ensure_utc(paid_at))

    async def display_names(self, parent_ids: set[str]) -> dict[str, str]:
        names: dict[str, str] = {}
        projection = {name: 1 for name in (*_USER_REFERENCE_FIELDS, "display_name", "name")}
        # One $in per field, never an $or across fields (#894).
        for field_name in _USER_REFERENCE_FIELDS:
            missing = sorted(parent_ids - names.keys())
            if not missing:
                break
            async for doc in self._db["users"].find({field_name: {"$in": missing}}, projection):
                names[str(doc[field_name])] = str(doc.get("display_name") or doc.get("name") or "")
        return names
