"""Get academy payment gateway settings."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


class AcademyRepo(Protocol):
    async def find_by_id(self, academy_id: str) -> dict[str, Any] | None: ...

    async def upsert_defaults(self, academy_id: str) -> dict[str, Any]: ...


@dataclass(frozen=True)
class GetAcademyGatewayOutput:
    stripe_connected: bool
    stripe_account_id_masked: str | None
    manual_methods: list[str]


def _mask_account_id(account_id: str | None) -> str | None:
    if not account_id:
        return None
    if len(account_id) <= 8:
        return account_id
    return f"{account_id[:4]}...{account_id[-4:]}"


class GetAcademyGatewayUseCase:
    def __init__(self, academy_repo: AcademyRepo) -> None:
        self._repo = academy_repo

    async def execute(self, academy_id: str) -> GetAcademyGatewayOutput:
        doc = await self._repo.find_by_id(academy_id)
        if not doc:
            doc = await self._repo.upsert_defaults(academy_id)
        stripe_account_id = doc.get("stripe_account_id")
        manual_methods = doc.get("manual_methods")
        if not isinstance(manual_methods, list) or not manual_methods:
            manual_methods = ["cash", "check"]
        return GetAcademyGatewayOutput(
            stripe_connected=bool(stripe_account_id),
            stripe_account_id_masked=_mask_account_id(
                str(stripe_account_id) if stripe_account_id else None
            ),
            manual_methods=[str(method) for method in manual_methods],
        )
