"""Mongo side of scheduled plan price changes (Settings overhaul Phase 6 PR 26).

* ``plan_price_changes``: one document per owner decision, owned by billing.
  ``pending_plan_id`` is set only while a change is ``scheduled``; the
  migration 0212 partial unique index on ``(academy_id, pending_plan_id)``
  makes "one pending change per plan" hold under concurrent applies.
* :func:`class_fee_cents_for_period`: the ONE read every charge path uses for
  "what is this class charged for billing month X". It is the stored fee
  (``stored_class_fee_cents``, exactly the monthly run's read) with the
  academy's recorded changes for that class applied. No change on record
  means the stored fee, unchanged.
* :class:`MongoPriceChangeFlipWriter`: the only writer of class fees and plan
  prices here, used by the scheduler once a change's month has started. Both
  writes are compare-and-set against the old price, so a fee the owner edited
  by hand is never overwritten. It never touches invoices, invoice lines,
  payments or calculation snapshots.

See ``domain/plan_price_change.py`` for why the flip does not change any
charge.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from pymongo.errors import DuplicateKeyError

from backend.v2.contexts.billing.domain.errors import PriceChangePending
from backend.v2.contexts.billing.domain.plan_price_change import (
    PlanPriceChange,
    class_fee_for_period,
    stored_class_fee_cents,
)
from backend.v2.shared.tenancy import TenantScopedRepository, current_academy_id
from backend.v2.shared.time import academy_timezone_lookup
from backend.v2.shared.time.academy_timezone import resolve_academy_clock_timezone

PLAN_PRICE_CHANGES_COLLECTION = "plan_price_changes"
#: Statuses that can still move a charge (``cancelled`` never does).
_LIVE_STATUSES = ["scheduled", "applied"]


def _to_change(doc: Mapping[str, Any]) -> PlanPriceChange:
    return PlanPriceChange(
        change_id=str(doc["change_id"]),
        plan_id=str(doc["plan_id"]),
        old_cents=int(doc["old_cents"]),
        new_cents=int(doc["new_cents"]),
        effective_period=str(doc["effective_period"]),
        session_ids=tuple(str(s) for s in doc.get("session_ids") or ()),
        status=doc.get("status") or "scheduled",
        flipped_session_ids=tuple(str(s) for s in doc.get("flipped_session_ids") or ()),
        created_by=str(doc.get("created_by") or ""),
        created_at=doc.get("created_at"),
    )


async def class_fee_cents_for_period(db: Any, session_doc: Mapping[str, Any], period: str) -> int:
    """The class's monthly fee for billing month ``period`` (``YYYY-MM``).

    Tenant: the academy in scope (every charge path runs inside one). A class
    with no recorded plan price change, which is every class today, costs one
    indexed lookup and returns ``stored_class_fee_cents(session_doc)``.
    """
    stored = stored_class_fee_cents(session_doc)
    session_id = str(session_doc.get("session_id") or "")
    if not session_id:
        return stored
    cursor = db[PLAN_PRICE_CHANGES_COLLECTION].find(
        {
            "academy_id": current_academy_id(),
            "session_ids": session_id,
            "status": {"$in": _LIVE_STATUSES},
        }
    )
    changes = [_to_change(doc) async for doc in cursor]
    if not changes:
        return stored
    return class_fee_for_period(
        session_id=session_id, stored_fee_cents=stored, period=period, changes=changes
    )


class MongoClassFeeResolver:
    """``ClassFeeForPeriod`` port over :func:`class_fee_cents_for_period`."""

    def __init__(self, db: Any) -> None:
        self._db = db

    async def fee_cents_for_period(self, session_doc: Mapping[str, Any], period: str) -> int:
        return await class_fee_cents_for_period(self._db, session_doc, period)


class MongoPlanPriceChangeRepository(TenantScopedRepository):
    collection_name = PLAN_PRICE_CHANGES_COLLECTION

    async def list_live(self) -> list[PlanPriceChange]:
        """Scheduled and applied changes, oldest month first."""
        cursor = self._find_many(
            {"status": {"$in": _LIVE_STATUSES}}, sort=[("effective_period", 1), ("change_id", 1)]
        )
        return [_to_change(doc) async for doc in cursor]

    async def list_scheduled(self) -> list[PlanPriceChange]:
        cursor = self._find_many(
            {"status": "scheduled"}, sort=[("effective_period", 1), ("change_id", 1)]
        )
        return [_to_change(doc) async for doc in cursor]

    async def get(self, change_id: str) -> PlanPriceChange | None:
        doc = await self._find_one({"change_id": change_id})
        return _to_change(doc) if doc else None

    async def insert(self, change: PlanPriceChange) -> None:
        """Record a scheduled change; :class:`PriceChangePending` if the plan has one."""
        if await self._find_one({"pending_plan_id": change.plan_id, "status": "scheduled"}):
            raise PriceChangePending(
                "This plan already has a scheduled price change.", plan_id=change.plan_id
            )
        try:
            await self._insert_one(
                {
                    "change_id": change.change_id,
                    "plan_id": change.plan_id,
                    "pending_plan_id": change.plan_id,
                    "old_cents": change.old_cents,
                    "new_cents": change.new_cents,
                    "effective_period": change.effective_period,
                    "session_ids": list(change.session_ids),
                    "flipped_session_ids": [],
                    "status": "scheduled",
                    "created_by": change.created_by,
                    "created_at": change.created_at,
                }
            )
        except DuplicateKeyError as exc:  # the 0212 index: a concurrent apply won
            raise PriceChangePending(
                "This plan already has a scheduled price change.", plan_id=change.plan_id
            ) from exc

    async def cancel(self, change_id: str, *, actor_id: str, at: datetime) -> bool:
        """Cancel a scheduled change no class fee has moved for yet."""
        result = await self._update_one(
            {"change_id": change_id, "status": "scheduled", "flipped_session_ids": {"$size": 0}},
            {
                "$set": {"status": "cancelled", "cancelled_by": actor_id, "cancelled_at": at},
                "$unset": {"pending_plan_id": ""},
            },
        )
        return bool(result.modified_count == 1)

    async def record_flip(self, change_id: str, session_id: str) -> bool:
        """Note a class as flipped BEFORE its fee is written (see the domain module).

        Only while the class is still in the change: a class the owner moved
        off the plan in the meantime is never flipped.
        """
        result = await self._update_one(
            {"change_id": change_id, "status": "scheduled", "session_ids": session_id},
            {"$addToSet": {"flipped_session_ids": session_id}},
        )
        return bool(result.matched_count == 1)

    async def add_session(self, change_id: str, session_id: str) -> bool:
        """Add a class newly linked to the plan to a scheduled change."""
        result = await self._update_one(
            {"change_id": change_id, "status": "scheduled"},
            {"$addToSet": {"session_ids": session_id}},
        )
        return bool(result.modified_count == 1)

    async def remove_session(self, change_id: str, session_id: str) -> bool:
        """Drop a class the owner moved off the plan, unless its fee has moved already."""
        result = await self._update_one(
            {
                "change_id": change_id,
                "status": "scheduled",
                "session_ids": session_id,
                "flipped_session_ids": {"$ne": session_id},
            },
            {"$pull": {"session_ids": session_id}},
        )
        return bool(result.modified_count == 1)

    async def mark_applied(self, change_id: str, *, plan_flipped: bool, at: datetime) -> bool:
        result = await self._update_one(
            {"change_id": change_id, "status": "scheduled"},
            {
                "$set": {"status": "applied", "applied_at": at, "plan_flipped": plan_flipped},
                "$unset": {"pending_plan_id": ""},
            },
        )
        return bool(result.modified_count == 1)


def _new_fee_fields(doc: Mapping[str, Any], new_cents: int, at: datetime) -> dict[str, Any]:
    """``amount_cents`` plus every legacy fee field the class already carries.

    Some displays read ``monthly_price_cents`` / ``monthly_price`` directly,
    so a legacy class keeps them in step with the fee that is charged.
    """
    fields: dict[str, Any] = {"amount_cents": new_cents, "updated_at": at}
    if doc.get("monthly_price_cents") is not None:
        fields["monthly_price_cents"] = new_cents
    if doc.get("monthly_price") is not None:
        fields["monthly_price"] = new_cents / 100
    return fields


class MongoPriceChangeFlipWriter(TenantScopedRepository):
    """Moves a class fee and a plan price from old to new, compare-and-set."""

    collection_name = "sessions"

    async def current_class_fee(self, session_id: str) -> int | None:
        doc = await self._find_one({"session_id": session_id})
        return stored_class_fee_cents(doc) if doc else None

    async def flip_class_fee(
        self, session_id: str, *, old_cents: int, new_cents: int, at: datetime
    ) -> bool:
        doc = await self._find_one({"session_id": session_id})
        if doc is None or stored_class_fee_cents(doc) != old_cents:
            return False
        # Pin every fee field to what was read, so a concurrent hand edit of
        # any of them makes this a no-op instead of being overwritten.
        result = await self._update_one(
            {
                "session_id": session_id,
                "amount_cents": doc.get("amount_cents"),
                "monthly_price_cents": doc.get("monthly_price_cents"),
                "monthly_price": doc.get("monthly_price"),
            },
            {"$set": _new_fee_fields(doc, new_cents, at)},
        )
        return bool(result.modified_count == 1)

    async def flip_plan_price(
        self, plan_id: str, *, old_cents: int, new_cents: int, at: datetime
    ) -> bool:
        result = await self._db["session_types"].update_one(
            self._scoped({"session_type_id": plan_id, "price_cents": old_cents}),
            {"$set": {"price_cents": new_cents, "updated_at": at}},
        )
        return bool(result.modified_count == 1)


class MongoInvoicedPeriodReader(TenantScopedRepository):
    """Which billing months already carry charges for some classes."""

    collection_name = "enrollments"

    def __init__(self, db: Any, *, clock: Callable[[], datetime] = lambda: datetime.now(UTC)):
        super().__init__(db)
        self._now = clock

    async def latest_invoiced_period(self, session_ids: Sequence[str]) -> str | None:
        """Newest billing month that already has a charge, among these sources.

        * a recorded monthly generation run for the academy;
        * an invoice (``invoices``), a monthly invoice key
          (``billing_invoice_keys``) or a monthly payment (``payments``) for
          any enrollment in the classes, whatever the enrollment's status;
        * a consumed calculation snapshot for one of the classes: a checkout
          (registration) or monthly charge priced for that month.
        """
        periods: list[str] = []
        run = await self._find_one_in_collection(
            "billing_generation_runs", {}, sort=[("period", -1)]
        )
        if run and run.get("period"):
            periods.append(str(run["period"]))
        if session_ids:
            enrollment_ids = [
                str(doc["enrollment_id"])
                async for doc in self._find_many_in_collection(
                    "enrollments",
                    {"session_id": {"$in": list(session_ids)}},
                    {"_id": 0, "enrollment_id": 1},
                )
                if doc.get("enrollment_id")
            ]
            if enrollment_ids:
                for collection in ("invoices", "billing_invoice_keys", "payments"):
                    doc = await self._find_one_in_collection(
                        collection,
                        {"enrollment_id": {"$in": enrollment_ids}, "period": {"$gt": ""}},
                        sort=[("period", -1)],
                    )
                    if doc and doc.get("period"):
                        periods.append(str(doc["period"]))
            snapshot = await self._find_one_in_collection(
                "billing_calculation_snapshots",
                {
                    "session_id": {"$in": list(session_ids)},
                    "status": "CONSUMED",
                    "billing_period_label": {"$gt": ""},
                },
                sort=[("billing_period_label", -1)],
            )
            if snapshot and snapshot.get("billing_period_label"):
                periods.append(str(snapshot["billing_period_label"]))
        return max(periods) if periods else None

    async def has_charges_from(self, session_ids: Sequence[str], period: str) -> bool:
        """True when any month on or after ``period`` is charged or quoted for these classes.

        Everything :meth:`latest_invoiced_period` counts, plus an open,
        unexpired checkout quote: a parent can still pay it at its price.
        """
        latest = await self.latest_invoiced_period(session_ids)
        if latest is not None and latest >= period:
            return True
        if not session_ids:
            return False
        quote = await self._find_one_in_collection(
            "billing_calculation_snapshots",
            {
                "session_id": {"$in": list(session_ids)},
                "status": "OPEN",
                "billing_period_label": {"$gte": period},
                "$or": [{"expires_at": None}, {"expires_at": {"$gt": self._now()}}],
            },
        )
        return quote is not None


class MongoAcademyBillingMonth:
    """The academy's current billing month on its own clock (the monthly run's)."""

    def __init__(self, db: Any, *, clock: Callable[[], datetime] = lambda: datetime.now(UTC)):
        self._reader = academy_timezone_lookup(db)
        self._now = clock

    async def current_period(self) -> str:
        zone = await resolve_academy_clock_timezone(self._reader, current_academy_id())
        return self._now().astimezone(ZoneInfo(zone)).strftime("%Y-%m")
