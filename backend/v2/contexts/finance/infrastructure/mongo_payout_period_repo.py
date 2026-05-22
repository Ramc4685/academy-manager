"""Mongo-backed ``PayoutPeriodRepository`` (Wave 5A Stream J).

Two collections:

- ``payout_periods`` — one document per (academy_id, coach_id,
  period_start, period_end). Unique index on that tuple gives us the
  natural-key idempotency.
- ``payout_period_lines`` — one document per occurrence on a period.
  Linked back to its period via ``period_id``.

Storing the lines separately (rather than embedded) makes the repo more
useful for analytics/reporting later — but the period and its lines are
always read+written together to preserve aggregate boundaries.

The repo extends ``TenantScopedRepository``, so every read/write is
pre-filtered by the current ``academy_id`` from the request scope.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from pymongo.errors import DuplicateKeyError

from backend.v2.contexts.finance.domain.payout_period import (
    PayoutPeriod,
    PersistedPayoutLine,
)
from backend.v2.shared.tenancy import TenantScopedRepository, current_academy_id


def _line_to_doc(line: PersistedPayoutLine, *, period_id: str) -> dict[str, Any]:
    return {
        "period_id": period_id,
        "occurrence_id": line.occurrence_id,
        "coach_id": line.coach_id,
        "basis": line.basis,
        "minutes": str(line.minutes),  # store Decimal as string to avoid float
        "amount_minor": int(line.amount_minor),
        "currency": line.currency,
        "rate_id": line.rate_id,
    }


def _line_from_doc(doc: dict[str, Any]) -> PersistedPayoutLine:
    return PersistedPayoutLine(
        occurrence_id=str(doc["occurrence_id"]),
        coach_id=str(doc["coach_id"]),
        basis=doc["basis"],
        minutes=Decimal(str(doc["minutes"])),
        amount_minor=int(doc["amount_minor"]),
        currency=str(doc["currency"]),
        rate_id=str(doc["rate_id"]),
    )


def _period_to_doc(period: PayoutPeriod) -> dict[str, Any]:
    return {
        "period_id": period.period_id,
        "coach_id": period.coach_id,
        "period_start": period.period_start,
        "period_end": period.period_end,
        "status": period.status,
        "currency": period.currency,
        "total_minor": int(period.total_minor),
        "unpaid_occurrence_ids": list(period.unpaid_occurrence_ids),
        "generated_at": period.generated_at,
        "approved_at": period.approved_at,
        "paid_at": period.paid_at,
    }


class MongoPayoutPeriodRepository(TenantScopedRepository):
    collection_name = "payout_periods"
    LINES_COLLECTION = "payout_period_lines"

    async def _hydrate(self, doc: dict[str, Any]) -> PayoutPeriod:
        academy_id = current_academy_id()
        cursor = self._db[self.LINES_COLLECTION].find(
            {"academy_id": academy_id, "period_id": doc["period_id"]}
        )
        lines = [_line_from_doc(line_doc) async for line_doc in cursor]
        return PayoutPeriod(
            period_id=str(doc["period_id"]),
            academy_id=academy_id,
            coach_id=str(doc["coach_id"]),
            period_start=doc["period_start"],
            period_end=doc["period_end"],
            status=doc.get("status", "draft"),
            currency=str(doc["currency"]),
            total_minor=int(doc["total_minor"]),
            lines=lines,
            unpaid_occurrence_ids=list(doc.get("unpaid_occurrence_ids", [])),
            generated_at=doc["generated_at"],
            approved_at=doc.get("approved_at"),
            paid_at=doc.get("paid_at"),
        )

    async def find_by_window(
        self,
        *,
        coach_id: str,
        period_start: datetime,
        period_end: datetime,
    ) -> PayoutPeriod | None:
        doc = await self._find_one(
            {
                "coach_id": coach_id,
                "period_start": period_start,
                "period_end": period_end,
            }
        )
        return await self._hydrate(doc) if doc else None

    async def find_by_id(self, period_id: str) -> PayoutPeriod | None:
        doc = await self._find_one({"period_id": period_id})
        return await self._hydrate(doc) if doc else None

    async def save(self, period: PayoutPeriod) -> PayoutPeriod:
        # Idempotent on natural key — if a period for this window already
        # exists, return it without overwriting. Callers wanting to
        # re-generate after rate edits go through an explicit "regenerate
        # draft" flow which is out of scope here.
        existing = await self.find_by_window(
            coach_id=period.coach_id,
            period_start=period.period_start,
            period_end=period.period_end,
        )
        if existing is not None:
            return existing

        try:
            await self._insert_one(_period_to_doc(period))
        except DuplicateKeyError:
            # Concurrent caller won the race; return what they wrote.
            again = await self.find_by_window(
                coach_id=period.coach_id,
                period_start=period.period_start,
                period_end=period.period_end,
            )
            if again is None:  # pragma: no cover - defensive
                raise
            return again

        academy_id = current_academy_id()
        if period.lines:
            await self._db[self.LINES_COLLECTION].insert_many(
                [
                    {**_line_to_doc(line, period_id=period.period_id), "academy_id": academy_id}
                    for line in period.lines
                ]
            )

        stored = await self.find_by_id(period.period_id)
        if stored is None:  # pragma: no cover - defensive
            raise RuntimeError("payout period save did not persist")
        return stored

    async def replace(self, period: PayoutPeriod) -> PayoutPeriod:
        result = await self._update_one(
            {"period_id": period.period_id},
            {"$set": _period_to_doc(period)},
        )
        if result.matched_count == 0:
            raise LookupError(f"PayoutPeriod {period.period_id!r} not found")
        # Lines are immutable once written, so we don't touch them here.
        stored = await self.find_by_id(period.period_id)
        if stored is None:  # pragma: no cover - defensive
            raise RuntimeError("payout period replace lost the document")
        return stored
