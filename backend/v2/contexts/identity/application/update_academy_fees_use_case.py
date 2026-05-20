"""Update academy fee settings."""

from __future__ import annotations

from typing import Any, Optional, Protocol

from .get_academy_fees_use_case import GetAcademyFeesOutput


class AcademyWriteRepo(Protocol):
    async def update_by_id(self, academy_id: str, fields: dict[str, Any]) -> Optional[dict[str, Any]]: ...
    async def upsert_defaults(self, academy_id: str) -> dict[str, Any]: ...


class UpdateAcademyFeesUseCase:
    def __init__(self, academy_repo: AcademyWriteRepo) -> None:
        self._repo = academy_repo

    async def execute(self, academy_id: str, fields: dict[str, Any]) -> GetAcademyFeesOutput:
        # Nest under "fees" subdocument using dot-notation for $set.
        patch = {f"fees.{k}": v for k, v in fields.items() if v is not None}
        if not patch:
            doc = await self._repo.upsert_defaults(academy_id)
        else:
            doc = await self._repo.update_by_id(academy_id, patch)
        if not doc:
            raise LookupError(f"academy {academy_id} not found")
        fees = doc.get("fees") or doc
        return GetAcademyFeesOutput(
            default_monthly_cents=fees.get("default_monthly_cents") or fees.get("default_session_price_cents"),
            late_fee_cents=fees.get("late_fee_cents") or fees.get("late_cancellation_fee_cents"),
            grace_days=fees.get("grace_days"),
        )
