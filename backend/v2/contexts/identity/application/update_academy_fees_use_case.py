"""Update academy fee settings."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Protocol

from .get_academy_fees_use_case import GetAcademyFeesOutput, fees_from_academy_doc


class AcademyWriteRepo(Protocol):
    async def find_by_id(self, academy_id: str) -> dict[str, Any] | None: ...
    async def update_by_id(
        self, academy_id: str, fields: dict[str, Any]
    ) -> dict[str, Any] | None: ...
    async def upsert_defaults(self, academy_id: str) -> dict[str, Any]: ...


class UpdateAcademyFeesUseCase:
    def __init__(
        self,
        academy_repo: AcademyWriteRepo,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._repo = academy_repo
        self._now = clock

    async def execute(self, academy_id: str, fields: dict[str, Any]) -> GetAcademyFeesOutput:
        # Nest under "fees" subdocument using dot-notation for $set.
        patch = {f"fees.{k}": v for k, v in fields.items() if v is not None}
        if not patch:
            doc = await self._repo.upsert_defaults(academy_id)
        else:
            if await self._turns_late_fee_on(academy_id, fields.get("late_fee_cents")):
                # Owner decision (2026-09-25): a late fee applies from the day
                # it is switched on. The pass reads this date and leaves alone
                # every invoice that was already past its grace period.
                patch["fees.late_fee_effective_from"] = self._now()
            doc = await self._repo.update_by_id(academy_id, patch)
        if not doc:
            raise LookupError(f"academy {academy_id} not found")
        return fees_from_academy_doc(doc)

    async def _turns_late_fee_on(self, academy_id: str, new_fee: Any) -> bool:
        if new_fee is None or int(new_fee) <= 0:
            return False
        current = await self._repo.find_by_id(academy_id)
        stored = fees_from_academy_doc(current or {}).late_fee_cents
        return not stored or int(stored) <= 0
