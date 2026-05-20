"""Get academy fee settings."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, Protocol


class AcademyRepo(Protocol):
    async def find_by_id(self, academy_id: str) -> Optional[dict[str, Any]]: ...
    async def upsert_defaults(self, academy_id: str) -> dict[str, Any]: ...


@dataclass(frozen=True)
class GetAcademyFeesOutput:
    default_monthly_cents: Optional[int] = None
    late_fee_cents: Optional[int] = None
    grace_days: Optional[int] = None


class GetAcademyFeesUseCase:
    def __init__(self, academy_repo: AcademyRepo) -> None:
        self._repo = academy_repo

    async def execute(self, academy_id: str) -> GetAcademyFeesOutput:
        doc = await self._repo.find_by_id(academy_id)
        if not doc:
            doc = await self._repo.upsert_defaults(academy_id)
        fees = doc.get("fees") or doc  # fees may be nested or flat
        return GetAcademyFeesOutput(
            default_monthly_cents=fees.get("default_monthly_cents") or fees.get("default_session_price_cents"),
            late_fee_cents=fees.get("late_fee_cents") or fees.get("late_cancellation_fee_cents"),
            grace_days=fees.get("grace_days"),
        )
