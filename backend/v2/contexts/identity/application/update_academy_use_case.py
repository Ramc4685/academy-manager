"""Update academy profile settings."""

from __future__ import annotations

from typing import Any, Protocol

from .get_academy_use_case import GetAcademyOutput


class AcademyWriteRepo(Protocol):
    async def update_by_id(
        self, academy_id: str, fields: dict[str, Any]
    ) -> dict[str, Any] | None: ...
    async def upsert_defaults(self, academy_id: str) -> dict[str, Any]: ...


class UpdateAcademyUseCase:
    def __init__(self, academy_repo: AcademyWriteRepo) -> None:
        self._repo = academy_repo

    async def execute(self, academy_id: str, fields: dict[str, Any]) -> GetAcademyOutput:
        if not fields:
            # No changes — ensure doc exists and return current state.
            doc = await self._repo.upsert_defaults(academy_id)
        else:
            doc = await self._repo.update_by_id(academy_id, fields)
        if not doc:
            raise LookupError(f"academy {academy_id} not found")
        return GetAcademyOutput(
            academy_id=str(doc.get("academy_id") or doc.get("_id", academy_id)),
            display_name=doc.get("display_name") or academy_id,
            timezone=doc.get("timezone") or "UTC",
            contact_email=doc.get("contact_email"),
            contact_phone=doc.get("contact_phone"),
            hours_text=doc.get("hours_text"),
            address=doc.get("address"),
            logo_url=doc.get("logo_url"),
            brand_color=doc.get("brand_color"),
        )
