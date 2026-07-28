"""Cross-academy financial rollup for franchise owners (UIM11).

This is a deliberate, narrow exception to "every read is tenant-scoped": the
academy set is resolved **server-side from the caller's own `owner`
memberships**. The request's tenant header contributes nothing — it can
neither add an academy nor remove one. Each academy is then read through the
normal per-academy, `academy_id`-filtered reader, so no cross-tenant query is
ever issued.
"""

from __future__ import annotations

from pydantic import BaseModel

from backend.v2.contexts.billing.application.ports import (
    AcademyFinancialSnapshotReader,
    OwnerAcademyDirectory,
)


class OwnerAcademyRollupRow(BaseModel):
    model_config = {"frozen": True}

    academy_id: str
    academy_name: str | None = None
    revenue_by_month: dict[str, int] = {}
    collected_cents: int = 0
    outstanding_cents: int = 0
    outstanding_invoice_count: int = 0


class OwnerRollupTotals(BaseModel):
    model_config = {"frozen": True}

    academy_count: int = 0
    revenue_by_month: dict[str, int] = {}
    collected_cents: int = 0
    outstanding_cents: int = 0
    outstanding_invoice_count: int = 0


class OwnerRollup(BaseModel):
    model_config = {"frozen": True}

    academies: list[OwnerAcademyRollupRow] = []
    totals: OwnerRollupTotals = OwnerRollupTotals()


class NotAFranchiseOwner(Exception):
    """Caller holds no active `owner` membership in any academy."""


class GetOwnerFinancialRollup:
    def __init__(
        self,
        *,
        academies: OwnerAcademyDirectory,
        snapshots: AcademyFinancialSnapshotReader,
    ) -> None:
        self._academies = academies
        self._snapshots = snapshots

    async def execute(self, *, user_id: str, months: tuple[str, ...] | None = None) -> OwnerRollup:
        owned = await self._academies.list_owner_academies(user_id)
        if not owned:
            raise NotAFranchiseOwner(user_id)

        rows: list[OwnerAcademyRollupRow] = []
        total_revenue: dict[str, int] = {}
        for ref in owned:
            snapshot = await self._snapshots.read(academy_id=ref.academy_id, months=months)
            rows.append(
                OwnerAcademyRollupRow(
                    academy_id=ref.academy_id,
                    academy_name=ref.academy_name,
                    revenue_by_month=snapshot.revenue_by_month,
                    collected_cents=snapshot.collected_cents,
                    outstanding_cents=snapshot.outstanding_cents,
                    outstanding_invoice_count=snapshot.outstanding_invoice_count,
                )
            )
            for month, cents in snapshot.revenue_by_month.items():
                total_revenue[month] = total_revenue.get(month, 0) + cents

        rows.sort(key=lambda row: (row.academy_name or row.academy_id).lower())
        return OwnerRollup(
            academies=rows,
            totals=OwnerRollupTotals(
                academy_count=len(rows),
                revenue_by_month=dict(sorted(total_revenue.items())),
                collected_cents=sum(row.collected_cents for row in rows),
                outstanding_cents=sum(row.outstanding_cents for row in rows),
                outstanding_invoice_count=sum(row.outstanding_invoice_count for row in rows),
            ),
        )
