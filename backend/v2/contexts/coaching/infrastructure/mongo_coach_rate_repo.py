"""Tenant-scoped Mongo repository for the ``coach_rates`` collection.

Write-side counterpart to the read-only rate lookup used by payout
computation (``composition.admin._MongoCoachRateRepository``). Indexes
live in migration 0102.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from backend.v2.contexts.coaching.application.use_cases.manage_coach_rates import (
    CoachRateAuditEntry,
)
from backend.v2.contexts.coaching.domain.payout import CoachRate
from backend.v2.shared.tenancy import TenantScopedRepository


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _legacy_billing_unit(doc: dict[str, Any]) -> str:
    billing_unit = doc.get("billing_unit")
    if billing_unit:
        return str(billing_unit)
    rate_type = str(doc.get("rate_type") or "").lower()
    if rate_type in {"percentage_of_expected_revenue", "percent_of_revenue"}:
        return "percent_of_revenue"
    if doc.get("percentage") is not None:
        return "percent_of_revenue"
    if rate_type == "per_hour":
        return "per_hour"
    return "per_session"


def _amount_minor(doc: dict[str, Any]) -> int:
    return int(doc.get("amount_minor", doc.get("amount_cents", doc.get("per_session_cents", 0))))


def _percent_bps(doc: dict[str, Any]) -> int | None:
    if doc.get("percent_bps") is not None:
        return int(doc["percent_bps"])
    if doc.get("percentage") is None:
        return None
    return int((Decimal(str(doc["percentage"])) * Decimal(100)).quantize(Decimal("1")))


def coach_rate_from_mongo_doc(doc: dict[str, Any]) -> CoachRate:
    effective_until = doc.get("effective_until")
    return CoachRate(
        rate_id=str(doc.get("rate_id") or doc.get("_id")),
        academy_id=str(doc["academy_id"]),
        coach_id=str(doc["coach_id"]),
        billing_unit=_legacy_billing_unit(doc),
        amount_minor=_amount_minor(doc),
        percent_bps=_percent_bps(doc),
        currency=str(doc.get("currency", "USD")).upper(),
        effective_from=_as_utc(doc["effective_from"]),
        effective_until=(None if effective_until is None else _as_utc(effective_until)),
        status=doc.get("status", "active"),
    )


class MongoCoachRateRepository(TenantScopedRepository):
    collection_name = "coach_rates"

    @classmethod
    def _to_domain(cls, doc: dict[str, Any]) -> CoachRate:
        return coach_rate_from_mongo_doc(doc)

    async def list_for_coach(self, coach_id: str) -> list[CoachRate]:
        cursor = self._find_many(
            {"coach_id": coach_id},
            sort=[("effective_from", -1)],
            limit=200,
        )
        return [self._to_domain(doc) async for doc in cursor]

    async def find_active(self, coach_id: str) -> CoachRate | None:
        doc = await self._find_one_in_collection(
            self.collection_name,
            {"coach_id": coach_id, "status": "active"},
            sort=[("effective_from", -1)],
        )
        return self._to_domain(doc) if doc else None

    async def supersede(self, rate_id: str, *, effective_until: datetime) -> None:
        await self._update_one(
            {"rate_id": rate_id},
            {"$set": {"status": "superseded", "effective_until": effective_until}},
        )

    async def insert(self, rate: CoachRate) -> None:
        doc = {k: v for k, v in rate.model_dump(mode="python").items() if k != "academy_id"}
        await self._insert_one(doc)


class MongoCoachRateAuditLogRepository(TenantScopedRepository):
    collection_name = "coach_rate_audit_log"

    async def append(self, entry: CoachRateAuditEntry) -> None:
        doc = {k: v for k, v in entry.model_dump(mode="python").items() if k != "academy_id"}
        await self._insert_one(doc)
