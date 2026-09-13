"""One definition of *cash received in a period*.

Spec: ``docs/superpowers/specs/2026-09-07-month-close-design.md`` §3.

Six different "collected this month" computations existed before this module
(§3.1). This is computation **B** — the reports dashboard's
``cash_collected_cents`` — lifted out verbatim so month close and the
dashboard share one reader and can never disagree.

Verbatim means exactly that: the same ``ledger_payment_effective_window_query``
window, the same success statuses, the same ``payment_revenue_net_cents`` for
ledger rows and ``payment_collected_cents`` for legacy rows, and the same
provider-key de-duplication of legacy ``payments`` against the period's
invoices, against successful ledger payments of *any* month (not just this
one), and against the invoices those ledger payments were allocated to. The
dashboard's existing tests are the proof that nothing moved.

The key sets are rebuilt here rather than passed in, because the legacy dedup
depends on all three of them and a caller that forgot one would silently
double-count. The dashboard keeps its own ``invoice_keys`` for its unrelated
``risk_payments`` pass.

**Not** used by the deposit slip or the QuickBooks journal (§3.2): the slip's
gross is ``amount_cents`` per ledger row where this reader's is
``paid_amount_cents``/``amount_received_cents`` when present, and the slip is
ledger-only where this reader folds in legacy rows. Pointing the slip here
would change book-keeping output, which needs its own sign-off (§11).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from bson import ObjectId
from bson.errors import InvalidId
from motor.motor_asyncio import AsyncIOMotorDatabase

from backend.v2.contexts.billing.application.admin_money import (
    invoice_provider_keys,
    ledger_payment_effective_at,
    ledger_payment_effective_month,
    ledger_payment_effective_window_query,
    legacy_payment_cash_candidate_query,
    payment_effective_at,
    payment_effective_month,
    payment_final_amount_cents,
    payment_provider_keys,
    payment_received_cents,
    report_zone,
)

#: Ledger statuses that count as money in the door. Refunded rows are included
#: because ``payment_revenue_net_cents`` nets the refund off, and a fully
#: refunded payment must land at zero rather than disappear.
SUCCESSFUL_LEDGER_STATUSES: list[str] = ["succeeded", "paid", "partially_refunded", "refunded"]

#: Legacy statuses whose ``payment_collected_cents`` is the received amount
#: with no refund netting (a partial or pending row banked what it banked).
_RECEIVED_ONLY_LEGACY_STATUSES = frozenset({"partially_paid", "pending", "failed"})

#: ``$in`` batch size for the dedup lookups. Bounded so one busy month cannot
#: build a single query document Mongo refuses.
_LOOKUP_BATCH = 500

_PAYMENT_MONEY_PROJECTION: dict[str, int] = {
    "payment_id": 1,
    "invoice_id": 1,
    "invoice_number": 1,
    "stripe_invoice_id": 1,
    "stripe_payment_intent_id": 1,
    "stripe_checkout_session_id": 1,
    "amount_cents": 1,
    "final_amount_cents": 1,
    "gross_amount_cents": 1,
    "amount": 1,
    "final_amount": 1,
    "gross_amount": 1,
    "discount_cents": 1,
    "discount": 1,
    "paid_amount_cents": 1,
    "amount_received_cents": 1,
    "paid_amount": 1,
    "amount_received": 1,
    "refunded_cents": 1,
    "payment_method": 1,
    "paid_at": 1,
    "created_at": 1,
}

_PROVIDER_KEY_PROJECTION: dict[str, int] = {
    "payment_id": 1,
    "invoice_id": 1,
    "invoice_number": 1,
    "stripe_invoice_id": 1,
    "stripe_payment_intent_id": 1,
    "stripe_checkout_session_id": 1,
}

#: The fields ``payment_provider_keys`` reads, in the order the dedup ``$or``
#: branches on them. Migration 0178 indexes every one of them.
_PROVIDER_KEY_FIELDS: tuple[str, ...] = tuple(_PROVIDER_KEY_PROJECTION)


@dataclass(frozen=True)
class CashReceivedRow:
    """One payment that landed in the period.

    ``gross_cents``/``refunded_cents`` are per-row and always satisfy
    ``max(gross - refunded, 0) == net``, so the totals below are the sum of
    their rows and never a separately computed figure.
    """

    payment_id: str
    at: datetime | None
    method: str | None
    gross_cents: int
    refunded_cents: int
    source: Literal["ledger", "legacy"]

    @property
    def net_cents(self) -> int:
        return max(self.gross_cents - self.refunded_cents, 0)


@dataclass(frozen=True)
class CashReceived:
    gross_cents: int
    refunded_cents: int
    #: ``gross - refunded`` floored at zero **per payment**, so one
    #: over-refunded row cannot eat another row's revenue.
    net_cents: int
    rows: tuple[CashReceivedRow, ...]


def _opt_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _ledger_amounts(payment: dict[str, Any]) -> tuple[int, int]:
    """``(gross, refunded)`` whose netting is ``payment_revenue_net_cents``."""
    paid = payment_received_cents(payment)
    if paid is None:
        paid = payment_final_amount_cents(payment)
    return paid, int(payment.get("refunded_cents") or 0)


def _legacy_amounts(payment: dict[str, Any]) -> tuple[int, int]:
    """``(gross, refunded)`` whose netting is ``payment_collected_cents``."""
    status = str(payment.get("status") or "")
    if status in _RECEIVED_ONLY_LEGACY_STATUSES:
        return max(payment_received_cents(payment) or 0, 0), 0
    if status in SUCCESSFUL_LEDGER_STATUSES:
        return _ledger_amounts(payment)
    # Any other status contributes nothing, exactly as
    # ``payment_collected_cents`` returns 0 for it.
    return 0, 0


async def cash_received_in_period(
    db: AsyncIOMotorDatabase[Any],
    *,
    academy_id: str,
    start: datetime,
    end: datetime,
    timezone_name: str | None = None,
) -> CashReceived:
    """Money actually received by ``academy_id`` between ``start`` and ``end``.

    ``start``/``end`` are the ``month_bounds`` of a single month; the period
    string the legacy queries need is derived from ``start``, which is exact
    because ``month_bounds`` always returns the first instant of the month.
    Since #608 that instant is the month's first instant *in the academy's
    zone*, so the label is read off the same clock the bounds were built on.
    """
    local_start = start.astimezone(report_zone(timezone_name))
    period = f"{local_start.year:04d}-{local_start.month:02d}"

    invoice_keys = await _period_invoice_keys(db, academy_id, period)
    ledger_rows, ledger_keys = await _ledger_rows(db, academy_id, start, end, period, timezone_name)
    legacy_candidates = await _legacy_candidates(
        db, academy_id, period=period, start=start, end=end, timezone_name=timezone_name
    )
    candidate_keys: set[str] = set()
    for candidate in legacy_candidates:
        candidate_keys |= payment_provider_keys(candidate)
    await _add_colliding_ledger_keys(db, academy_id, candidate_keys, ledger_keys)
    await _add_allocated_invoice_keys(db, academy_id, candidate_keys, ledger_keys)
    legacy_rows = _legacy_rows(legacy_candidates, excluded_keys=invoice_keys | ledger_keys)

    rows = tuple(ledger_rows + legacy_rows)
    return CashReceived(
        gross_cents=sum(row.gross_cents for row in rows),
        refunded_cents=sum(row.refunded_cents for row in rows),
        net_cents=sum(row.net_cents for row in rows),
        rows=rows,
    )


async def _period_invoice_keys(
    db: AsyncIOMotorDatabase[Any], academy_id: str, period: str
) -> set[str]:
    """Provider keys of the period's live invoices — a legacy row matching one
    of these was already counted through the ledger."""
    keys: set[str] = set()
    cursor = db["invoices"].find(
        {
            "academy_id": academy_id,
            "period": period,
            "status": {"$nin": ["void", "waived", "cancelled"]},
            "is_deleted": {"$ne": True},
        },
        {
            "invoice_id": 1,
            "invoice_number": 1,
            "stripe_invoice_id": 1,
            "stripe_payment_intent_id": 1,
        },
    )
    async for invoice in cursor:
        keys.update(invoice_provider_keys(invoice))
    return keys


async def _ledger_rows(
    db: AsyncIOMotorDatabase[Any],
    academy_id: str,
    start: datetime,
    end: datetime,
    period: str,
    timezone_name: str | None = None,
) -> tuple[list[CashReceivedRow], set[str]]:
    rows: list[CashReceivedRow] = []
    keys: set[str] = set()
    cursor = db["ledger_payments"].find(
        {
            "academy_id": academy_id,
            **ledger_payment_effective_window_query(start, end),
            "status": {"$in": SUCCESSFUL_LEDGER_STATUSES},
        },
        _PAYMENT_MONEY_PROJECTION,
    )
    async for payment in cursor:
        # The window query is deliberately loose (it accepts string dates too);
        # the month check is what actually decides membership.
        if ledger_payment_effective_month(payment, timezone_name) != period:
            continue
        keys.update(payment_provider_keys(payment))
        payment_id = str(payment.get("payment_id") or "")
        gross, refunded = _ledger_amounts(payment)
        rows.append(
            CashReceivedRow(
                payment_id=payment_id,
                at=ledger_payment_effective_at(payment),
                method=_opt_str(payment.get("payment_method")),
                gross_cents=gross,
                refunded_cents=refunded,
                source="ledger",
            )
        )
    return rows, keys


def _lookup_values(key: str) -> list[Any]:
    """Every stored shape ``key`` could have been written as.

    ``payment_provider_keys`` stringifies whatever it finds, so the old
    all-history scan matched an invoice number stored as an int, or an id
    stored as an ``ObjectId``, against a legacy row's string. A ``$in`` does
    not coerce, so the lookups below have to carry those shapes explicitly or
    they would silently stop de-duplicating those rows.
    """
    values: list[Any] = [key]
    if key.isdigit():
        values.append(int(key))
    if len(key) == 24:
        try:
            values.append(ObjectId(key))
        except (InvalidId, TypeError):
            pass
    return values


def _batches(keys: set[str]) -> list[list[Any]]:
    ordered = sorted(keys)
    return [
        [value for key in ordered[index : index + _LOOKUP_BATCH] for value in _lookup_values(key)]
        for index in range(0, len(ordered), _LOOKUP_BATCH)
    ]


async def _add_colliding_ledger_keys(
    db: AsyncIOMotorDatabase[Any],
    academy_id: str,
    candidate_keys: set[str],
    keys: set[str],
) -> None:
    """Ledger provider keys that a legacy candidate could collide with.

    A legacy row can carry the provider key of a ledger payment recorded in a
    different month; without this pass it would be counted twice. The obvious
    way to catch that is to stream *every* successful ledger payment and union
    its keys — which is what this did, on every dashboard load, unbounded by
    date (#526).

    Looking the collision up by key instead is exactly equivalent, not an
    approximation: ``keys`` is only ever consumed as
    ``payment_provider_keys(legacy_row) & keys``, so a ledger key no legacy
    candidate carries can never change a result. Nothing here is windowed by
    date, so a legacy row still dedupes against a ledger payment of any age.
    """
    if not candidate_keys:
        return
    for batch in _batches(candidate_keys):
        cursor = db["ledger_payments"].find(
            {
                "academy_id": academy_id,
                "status": {"$in": SUCCESSFUL_LEDGER_STATUSES},
                "$or": [{field: {"$in": batch}} for field in _PROVIDER_KEY_FIELDS],
            },
            _PROVIDER_KEY_PROJECTION,
        )
        async for payment in cursor:
            keys.update(payment_provider_keys(payment))


async def _add_allocated_invoice_keys(
    db: AsyncIOMotorDatabase[Any],
    academy_id: str,
    candidate_keys: set[str],
    keys: set[str],
) -> None:
    """Invoices a ledger payment settled — a legacy row keyed by such an
    invoice id is the same money.

    Walked backwards from the candidate keys for the same reason as
    ``_add_colliding_ledger_keys``: only an invoice a legacy candidate is
    actually keyed by can change the dedup. The second hop re-checks the
    status, because only a *successful* ledger payment supersedes legacy cash.
    """
    if not candidate_keys:
        return
    invoices_by_payment: dict[str, set[str]] = {}
    for batch in _batches(candidate_keys):
        cursor = db["payment_allocations"].find(
            {"academy_id": academy_id, "invoice_id": {"$in": batch}},
            {"invoice_id": 1, "payment_id": 1},
        )
        async for allocation in cursor:
            invoice_id = str(allocation.get("invoice_id") or "")
            payment_id = str(allocation.get("payment_id") or "")
            if invoice_id and payment_id:
                invoices_by_payment.setdefault(payment_id, set()).add(invoice_id)
    for batch in _batches(set(invoices_by_payment)):
        cursor = db["ledger_payments"].find(
            {
                "academy_id": academy_id,
                "status": {"$in": SUCCESSFUL_LEDGER_STATUSES},
                "payment_id": {"$in": batch},
            },
            {"payment_id": 1},
        )
        async for payment in cursor:
            keys.update(invoices_by_payment.get(str(payment.get("payment_id") or ""), set()))


async def _legacy_candidates(
    db: AsyncIOMotorDatabase[Any],
    academy_id: str,
    *,
    period: str,
    start: datetime,
    end: datetime,
    timezone_name: str | None = None,
) -> list[dict[str, Any]]:
    """Legacy ``payments`` rows whose effective month is ``period``, before
    de-duplication. Read before the dedup key sets are built so those lookups
    can be bounded by the keys these rows actually carry (#526)."""
    candidates: list[dict[str, Any]] = []
    cursor = db["payments"].find(
        legacy_payment_cash_candidate_query(academy_id, period, start, end),
        {
            **_PAYMENT_MONEY_PROJECTION,
            "status": 1,
            "payment_date": 1,
            "period": 1,
        },
    )
    async for payment in cursor:
        if payment_effective_month(payment, timezone_name) != period:
            continue
        candidates.append(payment)
    return candidates


def _legacy_rows(
    candidates: list[dict[str, Any]], *, excluded_keys: set[str]
) -> list[CashReceivedRow]:
    rows: list[CashReceivedRow] = []
    for payment in candidates:
        if payment_provider_keys(payment) & excluded_keys:
            continue
        gross, refunded = _legacy_amounts(payment)
        if gross == 0 and refunded == 0:
            # A status this reader does not count; keeping it would report
            # rows that contribute nothing to any total.
            continue
        rows.append(
            CashReceivedRow(
                payment_id=str(payment.get("payment_id") or ""),
                at=payment_effective_at(payment),
                method=_opt_str(payment.get("payment_method")),
                gross_cents=gross,
                refunded_cents=refunded,
                source="legacy",
            )
        )
    return rows
