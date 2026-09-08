"""Mongo read model behind ``GET /admin/reports/month-close``.

Spec: ``docs/superpowers/specs/2026-09-07-month-close-design.md`` §4.

Same shape as :mod:`collections_read_model`: this module only gathers facts —
a fixed number of batched Mongo reads, every one scoped by the request tenant
(``current_academy_id()`` resolved at build time, never at composition time) —
and hands them to the pure shaping rules in
:mod:`backend.v2.contexts.billing.application.month_close`. No rule about what
counts as odd, failed or collected lives here.

Error handling (spec §8): the primary sources — the period's invoices and
``cash_received_in_period`` — failing is a 500, because a Month close page
with a wrong "collected" is worse than no page. Secondary sources (charge
attempts, dunning ladders, the tuition-discount summary) degrade to empty and
name themselves in ``warnings``. When the card lookup fails, the
``autopay_no_card`` check is suppressed rather than guessed at.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from bson import ObjectId

from backend.v2.contexts.billing.application.admin_money import (
    invoice_final_amount_cents,
    invoice_outstanding_cents,
    invoice_paid_cents,
    month_bounds,
)
from backend.v2.contexts.billing.application.month_close import (
    InvoiceFacts,
    MonthCloseFacts,
    build_month_close_view,
)
from backend.v2.contexts.billing.domain.payment_attempt_kinds import (
    exclude_non_charge_attempts,
)
from backend.v2.contexts.billing.infrastructure.cash_received import (
    cash_received_in_period,
)
from backend.v2.contexts.billing.infrastructure.mongo_parent_billing_customer_repo import (
    MongoParentBillingCustomerRepository,
)
from backend.v2.shared.tenancy import current_academy_id

log = logging.getLogger(__name__)

_UTC_NAME = "UTC"
_SUCCEEDED_ATTEMPT_STATUS = "succeeded"


def _period_of(day: date) -> str:
    return f"{day.year:04d}-{day.month:02d}"


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _to_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value:
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def _opt_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _invoice_parent_id(doc: dict[str, Any]) -> str | None:
    return _opt_str(doc.get("parent_id")) or _opt_str(doc.get("parent_user_id"))


class MongoMonthCloseReadModel:
    """Batched facts → ``build_month_close_view`` for the admin Month close page."""

    def __init__(
        self,
        db: Any,
        *,
        academy_timezone: Callable[[str], Awaitable[str | None]],
        connected_accounts: Any,
        billing_settings: Any,
        customers: Any,
        tuition_discounts: Any = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._db = db
        self._academy_timezone = academy_timezone
        self._connected_accounts = connected_accounts
        self._billing_settings = billing_settings
        self._customers = customers
        self._tuition_discounts = tuition_discounts
        self._clock = clock

    # ------------------------------------------------------------------ entry

    async def build(self, period: str | None = None) -> dict[str, Any]:
        academy_id = current_academy_id()
        now = _as_utc(self._clock())
        tz_name = await self._resolve_timezone(academy_id)
        today = now.astimezone(ZoneInfo(tz_name)).date()
        period = period or _period_of(today)

        warnings: list[str] = []

        # --- primary sources: a failure here is a 500, never a wrong number.
        invoices = await self._period_invoices(academy_id, period)
        start, end = month_bounds(period)
        collected_cents = (
            await cash_received_in_period(self._db, academy_id=academy_id, start=start, end=end)
        ).net_cents

        invoice_ids = [inv["invoice_id"] for inv in invoices]
        enrollment_ids = sorted({eid for inv in invoices if (eid := inv.get("enrollment_id"))})
        parent_ids = {pid for inv in invoices if (pid := _invoice_parent_id(inv))}

        # --- secondary sources: degrade to empty and say so.
        attempts, ok = await self._secondary(
            self._attempts_by_invoice(academy_id, invoice_ids), {}, "payment attempts"
        )
        if not ok:
            warnings.append("attempts_unavailable")
        dunning, ok = await self._secondary(
            self._dunning_by_invoice(academy_id, invoice_ids), {}, "dunning states"
        )
        if not ok:
            warnings.append("dunning_unavailable")
        discounts, ok = await self._secondary(
            self._tuition_discount_summary(period), None, "tuition discounts"
        )
        if not ok:
            warnings.append("discounts_unavailable")

        autopay_by_enrollment = await self._autopay_by_enrollment(academy_id, enrollment_ids)
        enrollment_status = await self._enrollment_status(academy_id, enrollment_ids)
        users = await self._users(parent_ids)
        cards = await self._cards()
        connected_ready = await self._connected_account_ready()
        if cards is None:
            warnings.append("card_state_unavailable")

        facts = tuple(
            self._invoice_facts(
                inv,
                attempt=attempts.get(inv["invoice_id"]),
                dunning=dunning.get(inv["invoice_id"]),
                autopay_status=autopay_by_enrollment.get(inv.get("enrollment_id") or ""),
                enrollment_status=enrollment_status.get(inv.get("enrollment_id") or ""),
                enrollment_found=(inv.get("enrollment_id") or "") in enrollment_status,
                user=users.get(_invoice_parent_id(inv) or ""),
                cards=cards,
                connected_ready=connected_ready,
            )
            for inv in invoices
        )

        return build_month_close_view(
            MonthCloseFacts(
                period=period,
                today=today,
                timezone=tz_name,
                generated_at=now,
                invoices=facts,
                collected_cents=collected_cents,
                tuition_discounts=discounts,
                card_state_known=cards is not None,
                warnings=tuple(warnings),
            )
        )

    # ------------------------------------------------------------------ helpers

    @staticmethod
    async def _secondary(awaitable: Any, fallback: Any, label: str) -> tuple[Any, bool]:
        """Run a non-essential source; on failure return ``fallback`` and False.

        Mirrors the family read model: one broken join degrades its section
        instead of taking down the page.
        """
        try:
            return await awaitable, True
        except Exception:
            log.warning("month close read model: %s unavailable", label, exc_info=True)
            return fallback, False

    async def _resolve_timezone(self, academy_id: str) -> str:
        try:
            name = await self._academy_timezone(academy_id)
        except Exception:
            log.warning("month close read model: timezone lookup failed", exc_info=True)
            name = None
        if not name:
            return _UTC_NAME
        try:
            ZoneInfo(name)
        except Exception:
            log.warning("month close read model: unknown timezone %r, using UTC", name)
            return _UTC_NAME
        return name

    @staticmethod
    def _invoice_facts(
        inv: dict[str, Any],
        *,
        attempt: dict[str, Any] | None,
        dunning: dict[str, Any] | None,
        autopay_status: str | None,
        enrollment_status: str | None,
        enrollment_found: bool,
        user: dict[str, Any] | None,
        cards: dict[str, tuple[bool, str | None]] | None,
        connected_ready: bool | None,
    ) -> InvoiceFacts:
        parent_id = _invoice_parent_id(inv)
        has_card: bool | None = None
        if cards is not None and parent_id is not None:
            has_card = cards.get(parent_id, (False, None))[0]
        return InvoiceFacts(
            invoice_id=str(inv["invoice_id"]),
            invoice_number=_opt_str(inv.get("invoice_number")),
            status=str(inv.get("status") or ""),
            # The invoice's own face value, so ``voided_cents`` is the amount
            # that was cancelled; ``billed`` is paid + outstanding, as before.
            total_cents=invoice_final_amount_cents(inv),
            paid_cents=invoice_paid_cents(inv),
            outstanding_cents=invoice_outstanding_cents(inv),
            due_date=_to_date(inv.get("due_date")),
            delivery_status=str(inv.get("delivery_status") or "not_sent"),
            void_reason=_opt_str(inv.get("void_reason")),
            parent_id=parent_id,
            parent_name=_opt_str((user or {}).get("display_name"))
            or _opt_str((user or {}).get("name")),
            enrollment_id=_opt_str(inv.get("enrollment_id")),
            enrollment_found=enrollment_found,
            enrollment_status=enrollment_status,
            autopay_enrollment_status=autopay_status,
            has_card=has_card,
            connected_account_ready=connected_ready,
            has_charge_attempt=attempt is not None,
            has_succeeded_attempt=bool((attempt or {}).get("succeeded")),
            dunning_status=_opt_str((dunning or {}).get("status")),
            dunning_attempt_count=int((dunning or {}).get("attempt_count") or 0),
        )

    # ------------------------------------------------------------------ queries
    # Every query below carries ``academy_id`` (the request tenant) except the
    # ``users`` lookup, which is a global collection keyed by user id.

    async def _period_invoices(self, academy_id: str, period: str) -> list[dict[str, Any]]:
        """Every invoice of the period — **void and draft included**, because
        "5 voided, 2 still draft" is exactly what close needs to show."""
        cursor = self._db["invoices"].find(
            {
                "academy_id": academy_id,
                "period": period,
                "is_deleted": {"$ne": True},
            },
            {
                "_id": 0,
                "invoice_id": 1,
                "invoice_number": 1,
                "parent_id": 1,
                "parent_user_id": 1,
                "student_id": 1,
                "enrollment_id": 1,
                "period": 1,
                "status": 1,
                "amount_cents": 1,
                "total_cents": 1,
                "subtotal_cents": 1,
                "discount_cents": 1,
                "final_amount_cents": 1,
                "paid_amount_cents": 1,
                "balance_due_cents": 1,
                "due_date": 1,
                "created_at": 1,
                "delivery_status": 1,
                "last_sent_at": 1,
                "voided_at": 1,
                "void_reason": 1,
            },
        )
        docs = [doc async for doc in cursor]
        for doc in docs:
            doc["invoice_id"] = str(doc.get("invoice_id"))
            if doc.get("enrollment_id") is not None:
                doc["enrollment_id"] = str(doc["enrollment_id"])
        return docs

    async def _attempts_by_invoice(
        self, academy_id: str, invoice_ids: list[str]
    ) -> dict[str, dict[str, Any]]:
        """Per invoice: whether the worker tried, and whether it succeeded."""
        if not invoice_ids:
            return {}
        pipeline = [
            {
                "$match": exclude_non_charge_attempts(
                    {"academy_id": academy_id, "invoice_id": {"$in": invoice_ids}}
                )
            },
            {
                "$group": {
                    "_id": "$invoice_id",
                    "statuses": {"$addToSet": "$status"},
                }
            },
        ]
        cursor = self._db["payment_attempts"].aggregate(pipeline)
        return {
            str(doc["_id"]): {
                "succeeded": _SUCCEEDED_ATTEMPT_STATUS in (doc.get("statuses") or []),
            }
            async for doc in cursor
        }

    async def _dunning_by_invoice(
        self, academy_id: str, invoice_ids: list[str]
    ) -> dict[str, dict[str, Any]]:
        if not invoice_ids:
            return {}
        cursor = self._db["dunning_states"].find(
            {"academy_id": academy_id, "invoice_id": {"$in": invoice_ids}},
            {"_id": 0, "invoice_id": 1, "status": 1, "attempt_count": 1},
        )
        return {str(doc["invoice_id"]): doc async for doc in cursor}

    async def _autopay_by_enrollment(
        self, academy_id: str, enrollment_ids: list[str]
    ) -> dict[str, str | None]:
        if not enrollment_ids:
            return {}
        cursor = self._db["student_billing_enrollments"].find(
            {"academy_id": academy_id, "enrollment_id": {"$in": enrollment_ids}},
            {"_id": 0, "enrollment_id": 1, "autopay_enrollment_status": 1},
        )
        return {
            str(doc["enrollment_id"]): _opt_str(doc.get("autopay_enrollment_status"))
            async for doc in cursor
        }

    async def _enrollment_status(
        self, academy_id: str, enrollment_ids: list[str]
    ) -> dict[str, str | None]:
        """Present keys are the enrollments that exist; a missing key is the
        dangling reference ``invoice_without_enrollment`` reports."""
        if not enrollment_ids:
            return {}
        cursor = self._db["enrollments"].find(
            {"academy_id": academy_id, "enrollment_id": {"$in": enrollment_ids}},
            {"_id": 0, "enrollment_id": 1, "status": 1},
        )
        return {str(doc["enrollment_id"]): _opt_str(doc.get("status")) async for doc in cursor}

    async def _users(self, parent_ids: set[str]) -> dict[str, dict[str, Any]]:
        """``users`` is global (spans academies); keyed the way
        ``MongoUserRepository`` keys it, as the collections read model does."""
        if not parent_ids:
            return {}
        ids = sorted(parent_ids)
        raw_ids: list[Any] = list(ids) + [ObjectId(i) for i in ids if ObjectId.is_valid(i)]
        cursor = self._db["users"].find(
            {
                "$or": [
                    {"user_id": {"$in": ids}},
                    {"auth_uid": {"$in": ids}},
                    {"_id": {"$in": raw_ids}},
                ]
            },
            {"user_id": 1, "auth_uid": 1, "display_name": 1, "name": 1, "email": 1},
        )
        wanted = set(ids)
        users: dict[str, dict[str, Any]] = {}
        async for doc in cursor:
            for key in (doc.get("user_id"), doc.get("auth_uid"), doc.get("_id")):
                candidate = str(key) if key is not None else None
                if candidate in wanted:
                    users.setdefault(candidate, doc)
        return users

    async def _cards(self) -> dict[str, tuple[bool, str | None]] | None:
        """Per parent: (has chargeable card, last4). ``None`` when the lookup
        fails, which suppresses ``autopay_no_card`` instead of guessing."""
        try:
            docs = await self._customers.list_academy_customers()
        except Exception:
            log.warning("month close read model: customer lookup failed", exc_info=True)
            return None
        cards: dict[str, tuple[bool, str | None]] = {}
        for doc in docs:
            parent_id = _opt_str(doc.get("parent_id"))
            if not parent_id:
                continue
            label, last4 = MongoParentBillingCustomerRepository.display_payment_method(doc)
            cards[parent_id] = ((label, last4) != (None, None), last4)
        return cards

    async def _connected_account_ready(self) -> bool | None:
        try:
            account = await self._connected_accounts.get_for_academy()
            settings = await self._billing_settings.get()
        except Exception:
            log.warning("month close read model: connected-account lookup failed", exc_info=True)
            return None
        ready = account is not None and account.is_ready_for_charges()
        return bool(ready or getattr(settings, "allow_platform_charge_fallback", False))

    async def _tuition_discount_summary(self, period: str) -> dict[str, Any] | None:
        """``GET /admin/finance/tuition-discounts`` verbatim — the existing
        query is called, never re-implemented (spec §4.1 item 10)."""
        if self._tuition_discounts is None:
            return None
        summary = await self._tuition_discounts.execute(period)
        return {
            "gross_cents": summary.gross_tuition_cents,
            "discount_cents": summary.discount_cents,
            "net_cents": summary.net_tuition_cents,
            "by_category": [
                {"category": row.category, "amount_cents": row.discount_cents}
                for row in summary.by_category
            ],
        }
