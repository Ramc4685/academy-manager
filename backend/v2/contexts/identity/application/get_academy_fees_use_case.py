"""Get academy fee settings."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


class AcademyRepo(Protocol):
    async def find_by_id(self, academy_id: str) -> dict[str, Any] | None: ...
    async def upsert_defaults(self, academy_id: str) -> dict[str, Any]: ...


@dataclass(frozen=True)
class GetAcademyFeesOutput:
    late_fee_cents: int | None = None
    grace_days: int | None = None


class GetAcademyFeesUseCase:
    def __init__(self, academy_repo: AcademyRepo) -> None:
        self._repo = academy_repo

    async def execute(self, academy_id: str) -> GetAcademyFeesOutput:
        doc = await self._repo.find_by_id(academy_id)
        if not doc:
            doc = await self._repo.upsert_defaults(academy_id)
        fees = doc.get("fees") or doc  # fees may be nested or flat
        # `or` would collapse a stored 0 to the legacy alias and then to None,
        # so "no late fee" could never be read back: the Billing rules panel
        # showed the field blank after saving 0 and re-audited the same change
        # on every save. Fall through only when the value is genuinely absent.
        late_fee_cents = fees.get("late_fee_cents")
        if late_fee_cents is None:
            late_fee_cents = fees.get("late_cancellation_fee_cents")
        return GetAcademyFeesOutput(
            late_fee_cents=late_fee_cents,
            grace_days=fees.get("grace_days"),
        )
