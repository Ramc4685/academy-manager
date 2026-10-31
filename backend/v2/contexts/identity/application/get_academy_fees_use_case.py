"""Get academy fee settings."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol


class AcademyRepo(Protocol):
    async def find_by_id(self, academy_id: str) -> dict[str, Any] | None: ...
    async def upsert_defaults(self, academy_id: str) -> dict[str, Any]: ...


@dataclass(frozen=True)
class GetAcademyFeesOutput:
    late_fee_cents: int | None = None
    grace_days: int | None = None
    #: When the late fee was last switched on (from unset/$0). The automated
    #: pass only charges invoices whose grace period was still running on that
    #: day, so turning a fee on never back-charges old overdue invoices.
    #: ``None`` for academies that turned it on before this was recorded.
    late_fee_effective_from: datetime | None = None


def fees_from_academy_doc(doc: dict[str, Any]) -> GetAcademyFeesOutput:
    """Read the fee settings from ``academies.fees`` and nowhere else.

    Money audit X8 (2026-09-25): this used to fall back to the whole academy
    document when ``fees`` was empty, and to ``late_cancellation_fee_cents``
    when ``late_fee_cents`` was absent. The late-fee pass reads this output,
    so a short-notice *cancellation* amount, or a stray top-level field, could
    be charged as a late-*payment* fee on every overdue invoice. Absent means
    unset, and unset charges nothing.
    """
    fees = doc.get("fees")
    if not isinstance(fees, dict):
        return GetAcademyFeesOutput()
    effective_from = fees.get("late_fee_effective_from")
    return GetAcademyFeesOutput(
        late_fee_cents=fees.get("late_fee_cents"),
        grace_days=fees.get("grace_days"),
        late_fee_effective_from=effective_from if isinstance(effective_from, datetime) else None,
    )


class GetAcademyFeesUseCase:
    def __init__(self, academy_repo: AcademyRepo) -> None:
        self._repo = academy_repo

    async def execute(self, academy_id: str) -> GetAcademyFeesOutput:
        doc = await self._repo.find_by_id(academy_id)
        if not doc:
            doc = await self._repo.upsert_defaults(academy_id)
        return fees_from_academy_doc(doc)
