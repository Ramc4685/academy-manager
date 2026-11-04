"""Every family's money for one academy, in a fixed number of reads.

Backs the People CRM family index (``docs/design/people-crm/engineering-spec.md``
§3.2, "Data path"): open invoices with their due dates grouped by family, the
latest failed charge attempt per family, and the registration / card-on-file
state. Money is never built one family at a time: three academy-wide reads,
whatever the number of families, and the per-family arithmetic is
:func:`family_money.summarize_family_money`, the same rule the Billing tab's
header uses (``build_family_billing_view`` calls ``open_balance`` too).

Alias-aware without an ``$or``: invoices and customer rows are read
academy-wide (``academy_id`` equality, index-served) and grouped in memory by
whichever stored parent reference they carry, through the ``family_by_alias``
map the caller resolved (People CRM spec §1). Every query carries
``academy_id``.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from datetime import UTC, date, datetime
from typing import Any

from backend.v2.contexts.billing.application.autopay_eligibility import (
    CHARGEABLE_INVOICE_STATUSES,
)
from backend.v2.contexts.billing.application.family_billing import FAILURE_ATTEMPT_STATUSES
from backend.v2.contexts.billing.application.family_money import (
    FamilyMoneySummary,
    OpenInvoiceMoney,
    summarize_family_money,
)
from backend.v2.contexts.billing.domain.payment_attempt_kinds import (
    exclude_non_charge_attempts,
)
from backend.v2.contexts.billing.infrastructure.mongo_parent_billing_customer_repo import (
    MongoParentBillingCustomerRepository,
)

#: Invoice fields that may hold the family's parent reference, in preference order.
_INVOICE_PARENT_FIELDS = ("parent_id", "parent_user_id")


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


def _to_utc(value: Any) -> datetime | None:
    if not isinstance(value, datetime):
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _family_of(doc: Mapping[str, Any], family_by_alias: Mapping[str, str]) -> str | None:
    for field_name in _INVOICE_PARENT_FIELDS:
        raw = doc.get(field_name)
        if raw and str(raw) in family_by_alias:
            return family_by_alias[str(raw)]
    return None


class MongoFamilyMoneyReadModel:
    """Batched money facts → one :class:`FamilyMoneySummary` per family."""

    def __init__(self, db: Any) -> None:
        self._db = db

    async def summaries(
        self,
        *,
        academy_id: str,
        family_by_alias: Mapping[str, str],
        today: date,
    ) -> dict[str, FamilyMoneySummary]:
        """Money per family id, for every family named in ``family_by_alias``.

        ``family_by_alias`` maps every stored parent reference (roster
        ``user_id``, ``firebase_uid``, ``auth_uid``, ``_id``) to the family id
        it belongs to. A family with nothing open still gets a (zero) summary,
        so a missing entry always means "family unknown", never "owes nothing".
        """
        invoices, customers = await asyncio.gather(
            self._open_invoices(academy_id), self._customers(academy_id)
        )
        by_family: dict[str, list[OpenInvoiceMoney]] = {}
        family_by_invoice: dict[str, str] = {}
        for doc in invoices:
            family = _family_of(doc, family_by_alias)
            if family is None:
                continue
            by_family.setdefault(family, []).append(
                OpenInvoiceMoney(
                    status=str(doc.get("status") or ""),
                    balance_due_cents=_int(doc.get("balance_due_cents")),
                    due_date=_to_date(doc.get("due_date")),
                )
            )
            if doc.get("invoice_id"):
                family_by_invoice[str(doc["invoice_id"])] = family

        last_failure = await self._last_failures(academy_id, family_by_invoice)

        has_card: dict[str, bool] = {}
        invited: dict[str, datetime] = {}
        for doc in customers:
            family = family_by_alias.get(str(doc.get("parent_id") or ""))
            if family is None:
                continue
            label, last4 = MongoParentBillingCustomerRepository.display_payment_method(doc)
            has_card[family] = has_card.get(family, False) or (label, last4) != (None, None)
            at = _to_utc(doc.get("billing_setup_last_invited_at"))
            if at is not None and (family not in invited or at > invited[family]):
                invited[family] = at

        return {
            family: summarize_family_money(
                by_family.get(family, ()),
                today=today,
                last_failed_payment_at=last_failure.get(family),
                has_card=has_card.get(family, False),
                last_invited_at=invited.get(family),
            )
            for family in set(family_by_alias.values())
        }

    async def _open_invoices(self, academy_id: str) -> list[dict[str, Any]]:
        cursor = self._db["invoices"].find(
            {
                "academy_id": academy_id,
                "status": {"$in": sorted(CHARGEABLE_INVOICE_STATUSES)},
                "is_deleted": {"$ne": True},
            },
            {
                "_id": 0,
                "invoice_id": 1,
                "parent_id": 1,
                "parent_user_id": 1,
                "status": 1,
                "balance_due_cents": 1,
                "due_date": 1,
            },
        )
        return [doc async for doc in cursor]

    async def _customers(self, academy_id: str) -> list[dict[str, Any]]:
        cursor = self._db["parent_billing_customers"].find(
            {"academy_id": academy_id},
            {
                "_id": 0,
                "parent_id": 1,
                "payment_method_label": 1,
                "payment_method_last4": 1,
                "primary_setup_status": 1,
                "primary_payment_method_label": 1,
                "primary_payment_method_last4": 1,
                "autopay_payment_methods": 1,
                "billing_setup_last_invited_at": 1,
            },
        )
        return [doc async for doc in cursor]

    async def _last_failures(
        self, academy_id: str, family_by_invoice: Mapping[str, str]
    ) -> dict[str, datetime]:
        if not family_by_invoice:
            return {}
        cursor = self._db["payment_attempts"].find(
            exclude_non_charge_attempts(
                {"academy_id": academy_id, "invoice_id": {"$in": sorted(family_by_invoice)}}
            ),
            {"_id": 0, "invoice_id": 1, "status": 1, "created_at": 1},
        )
        newest: dict[str, datetime] = {}
        async for doc in cursor:
            if str(doc.get("status") or "") not in FAILURE_ATTEMPT_STATUSES:
                continue
            at = _to_utc(doc.get("created_at"))
            family = family_by_invoice.get(str(doc.get("invoice_id") or ""))
            if at is None or family is None:
                continue
            if family not in newest or at > newest[family]:
                newest[family] = at
        return newest
