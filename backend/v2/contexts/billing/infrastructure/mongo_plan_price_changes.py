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
* The edit fence: an owner edit (cancel, a class leaving or joining) first
  sets ``edit`` on the change (a token, a short lease and the classes it
  touches) and bumps ``revision``; the write itself is compare-and-set on the
  token. :func:`price_fence` is what a registration quote (and a
  class-cancellation credit) reads before and after it stores a charge: it
  refuses while an edit is open and changes whenever one started, so a quote
  that overlapped an edit is withdrawn and such a credit is re-sized.

See ``domain/plan_price_change.py`` for why the flip does not change any
charge.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from pymongo.errors import DuplicateKeyError

from backend.v2.contexts.billing.domain.credits import CLASS_CANCELLATION_SOURCE_TYPE
from backend.v2.contexts.billing.domain.errors import PriceChangeInFlight, PriceChangePending
from backend.v2.contexts.billing.domain.plan_price_change import (
    PlanPriceChange,
    class_fee_for_period,
    stored_class_fee_cents,
)
from backend.v2.shared.ids import new_ulid
from backend.v2.shared.tenancy import TenantScopedRepository, current_academy_id
from backend.v2.shared.time import academy_timezone_lookup
from backend.v2.shared.time.academy_timezone import resolve_academy_clock_timezone

PLAN_PRICE_CHANGES_COLLECTION = "plan_price_changes"
#: Statuses that can still move a charge (``cancelled`` never does).
_LIVE_STATUSES = ["scheduled", "applied"]
#: How long an owner edit holds a change. The edit itself takes well under a
#: second; the lease only frees a change whose editing request died midway.
EDIT_LEASE = timedelta(seconds=30)

#: What a registration quote compares before and after storing its snapshot.
PriceFence = tuple[tuple[str, int, str], ...]


def _wall_clock() -> datetime:
    return datetime.now(UTC)


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _no_open_edit(now: datetime) -> dict[str, Any]:
    """Filter: no owner edit holds the change (none, or its lease ran out)."""
    return {"$or": [{"edit": None}, {"edit.until": {"$lte": now}}]}


def _revision_is(revision: int) -> Any:
    """A change stored before ``revision`` existed reads as revision 0."""
    return {"$in": [0, None]} if revision == 0 else revision


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
        revision=int(doc.get("revision") or 0),
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


async def price_fence(db: Any, session_id: str, *, now: datetime) -> PriceFence:
    """Every change that covers (or an open edit is about to touch) this class.

    Raises :class:`PriceChangeInFlight` while an owner edit holds one of them.
    Two reads that return the same fence saw no edit start in between, so a
    price read between them is still the price.
    """
    cursor = db[PLAN_PRICE_CHANGES_COLLECTION].find(
        {
            "academy_id": current_academy_id(),
            "$or": [{"session_ids": session_id}, {"edit.session_ids": session_id}],
        },
        {"_id": 0, "change_id": 1, "revision": 1, "status": 1, "edit": 1},
    )
    fence: list[tuple[str, int, str]] = []
    async for doc in cursor:
        edit = doc.get("edit") or None
        if edit and edit.get("until") and _as_utc(edit["until"]) > now:
            raise PriceChangeInFlight(
                "Prices for this class are being updated. Try again in a moment.",
                session_id=session_id,
            )
        fence.append(
            (str(doc["change_id"]), int(doc.get("revision") or 0), str(doc.get("status") or ""))
        )
    return tuple(sorted(fence))


class MongoClassFeeResolver:
    """``ClassFeeForPeriod`` port over :func:`class_fee_cents_for_period`."""

    def __init__(self, db: Any, *, clock: Callable[[], datetime] = _wall_clock) -> None:
        self._db = db
        self._now = clock

    async def fee_cents_for_period(self, session_doc: Mapping[str, Any], period: str) -> int:
        return await class_fee_cents_for_period(self._db, session_doc, period)

    async def price_fence(self, session_id: str) -> PriceFence:
        return await price_fence(self._db, session_id, now=self._now())

    async def withdraw_quote(self, snapshot_id: str) -> None:
        """Retire an OPEN quote priced across an owner edit; it can never be paid."""
        await self._db["billing_calculation_snapshots"].update_one(
            {
                "academy_id": current_academy_id(),
                "snapshot_id": snapshot_id,
                "status": "OPEN",
            },
            {"$set": {"status": "SUPERSEDED", "superseded_reason": "plan_price_change_edit"}},
        )


class MongoPlanPriceChangeRepository(TenantScopedRepository):
    collection_name = PLAN_PRICE_CHANGES_COLLECTION

    def __init__(self, db: Any, *, clock: Callable[[], datetime] = _wall_clock) -> None:
        super().__init__(db)
        #: Wall clock for edit leases only (a lease is about this request, not
        #: about billing months), so it is never a test's frozen clock.
        self._lease_now = clock

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
                    "revision": 0,
                    "created_by": change.created_by,
                    "created_at": change.created_at,
                }
            )
        except DuplicateKeyError as exc:  # the 0212 index: a concurrent apply won
            raise PriceChangePending(
                "This plan already has a scheduled price change.", plan_id=change.plan_id
            ) from exc

    async def begin_edit(
        self, change_id: str, session_ids: Sequence[str]
    ) -> tuple[str, PlanPriceChange] | None:
        """Hold a scheduled change for an owner edit; ``(token, fresh change)``.

        ``None`` when the change is no longer scheduled or another edit holds
        it. ``session_ids`` are the classes the edit may touch beyond the
        change's own (a class about to join), so their quotes wait too.
        """
        now = self._lease_now()
        token = f"edit-{new_ulid()}"
        doc = await self._find_one_and_update(
            {"change_id": change_id, "status": "scheduled", **_no_open_edit(now)},
            {
                "$set": {
                    "edit": {
                        "token": token,
                        "until": now + EDIT_LEASE,
                        "session_ids": list(session_ids),
                    }
                },
                "$inc": {"revision": 1},
            },
        )
        return (token, _to_change(doc)) if doc else None

    async def end_edit(self, change_id: str, token: str) -> None:
        """Release an edit that wrote nothing (idempotent)."""
        await self._update_one(
            {"change_id": change_id, "edit.token": token}, {"$unset": {"edit": ""}}
        )

    async def cancel(self, change_id: str, *, token: str, actor_id: str, at: datetime) -> bool:
        """Cancel a scheduled change no class fee has moved for yet, under edit ``token``."""
        result = await self._update_one(
            {
                "change_id": change_id,
                "status": "scheduled",
                "edit.token": token,
                "flipped_session_ids": {"$size": 0},
            },
            {
                "$set": {"status": "cancelled", "cancelled_by": actor_id, "cancelled_at": at},
                "$unset": {"pending_plan_id": "", "edit": ""},
            },
        )
        return bool(result.modified_count == 1)

    async def record_flip(self, change_id: str, session_id: str, *, revision: int) -> bool:
        """Note a class as flipped BEFORE its fee is written (see the domain module).

        Only while the class is still in the change, the change is at
        ``revision`` (the one the scheduler read) and no owner edit holds it:
        a class the owner moved off the plan in the meantime is never flipped.
        """
        result = await self._update_one(
            {
                "change_id": change_id,
                "status": "scheduled",
                "session_ids": session_id,
                "revision": _revision_is(revision),
                **_no_open_edit(self._lease_now()),
            },
            {"$addToSet": {"flipped_session_ids": session_id}},
        )
        return bool(result.matched_count == 1)

    async def add_session(self, change_id: str, session_id: str, *, token: str) -> bool:
        """Add a class newly linked to the plan to a scheduled change, under edit ``token``."""
        result = await self._update_one(
            {"change_id": change_id, "status": "scheduled", "edit.token": token},
            {"$addToSet": {"session_ids": session_id}, "$unset": {"edit": ""}},
        )
        return bool(result.modified_count == 1)

    async def remove_session(self, change_id: str, session_id: str, *, token: str) -> bool:
        """Drop a class the owner moved off the plan, unless its fee has moved already."""
        result = await self._update_one(
            {
                "change_id": change_id,
                "status": "scheduled",
                "edit.token": token,
                "session_ids": session_id,
                "flipped_session_ids": {"$ne": session_id},
            },
            {"$pull": {"session_ids": session_id}, "$unset": {"edit": ""}},
        )
        return bool(result.modified_count == 1)

    async def mark_applied(
        self, change_id: str, *, revision: int, plan_flipped: bool, at: datetime
    ) -> bool:
        """Applied, unless an owner edit started since the scheduler read ``revision``."""
        result = await self._update_one(
            {
                "change_id": change_id,
                "status": "scheduled",
                "revision": _revision_is(revision),
                **_no_open_edit(self._lease_now()),
            },
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
          (registration) or monthly charge priced for that month;
        * a class-cancellation credit for one of the classes, for the month
          of the cancelled date (``billing_period``). A month not invoiced
          yet is credited from that month's class fee, so the credit carries
          the price as surely as an invoice would. Credits issued before
          ``billing_period`` was recorded carry no month and are not counted
          (no plan price change existed then, see the release note).
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
            credit = await self._find_one_in_collection(
                "account_credit_ledger",
                {
                    "source_type": CLASS_CANCELLATION_SOURCE_TYPE,
                    "session_id": {"$in": list(session_ids)},
                    "billing_period": {"$gt": ""},
                    "status": {"$ne": "VOIDED"},
                },
                sort=[("billing_period", -1)],
            )
            if credit and credit.get("billing_period"):
                periods.append(str(credit["billing_period"]))
        return max(periods) if periods else None

    async def has_charges_from(self, session_ids: Sequence[str], period: str) -> bool:
        """True when any month on or after ``period`` is charged or quoted for these classes.

        Everything :meth:`latest_invoiced_period` counts (a class-cancellation
        credit for a date in such a month included), plus an open,
        unexpired checkout quote (a parent can still pay it at its price),
        plus a registration quote, open or paid, that told the parent the
        price of a month on or after ``period`` ("Starting next month,
        tuition is $X": ``next_billing_period_label``).
        """
        latest = await self.latest_invoiced_period(session_ids)
        if latest is not None and latest >= period:
            return True
        if not session_ids:
            return False
        live_quote = {"status": "OPEN", **_unexpired(self._now())}
        quote = await self._find_one_in_collection(
            "billing_calculation_snapshots",
            {
                "session_id": {"$in": list(session_ids)},
                "$or": [
                    {"billing_period_label": {"$gte": period}, **live_quote},
                    {
                        "next_billing_period_label": {"$gte": period},
                        "$or": [{"status": "CONSUMED"}, live_quote],
                    },
                ],
            },
        )
        return quote is not None


def _unexpired(now: datetime) -> dict[str, Any]:
    return {"$or": [{"expires_at": None}, {"expires_at": {"$gt": now}}]}


class MongoAcademyBillingMonth:
    """The academy's current billing month on its own clock (the monthly run's)."""

    def __init__(self, db: Any, *, clock: Callable[[], datetime] = lambda: datetime.now(UTC)):
        self._reader = academy_timezone_lookup(db)
        self._now = clock

    async def current_period(self) -> str:
        zone = await resolve_academy_clock_timezone(self._reader, current_academy_id())
        return self._now().astimezone(ZoneInfo(zone)).strftime("%Y-%m")
