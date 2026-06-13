"""Update academy notification settings."""

from __future__ import annotations

from typing import Any, Protocol

from .get_academy_notifications_use_case import (
    GetAcademyNotificationsOutput,
    _notifications_output,
)


class AcademyWriteRepo(Protocol):
    async def update_by_id(
        self, academy_id: str, fields: dict[str, Any]
    ) -> dict[str, Any] | None: ...
    async def upsert_defaults(self, academy_id: str) -> dict[str, Any]: ...


class UpdateAcademyNotificationsUseCase:
    def __init__(self, academy_repo: AcademyWriteRepo) -> None:
        self._repo = academy_repo

    async def execute(
        self, academy_id: str, fields: dict[str, Any]
    ) -> GetAcademyNotificationsOutput:
        if "coach_digest_hour" in fields and fields["coach_digest_hour"] is not None:
            hour = fields["coach_digest_hour"]
            if not isinstance(hour, int) or isinstance(hour, bool) or not (0 <= hour <= 23):
                raise ValueError("coach_digest_hour must be an integer between 0 and 23")
        # Nest under "notifications" subdocument.
        patch = {f"notifications.{k}": v for k, v in fields.items() if v is not None}
        if not patch:
            doc = await self._repo.upsert_defaults(academy_id)
        else:
            doc = await self._repo.update_by_id(academy_id, patch)
        if not doc:
            raise LookupError(f"academy {academy_id} not found")
        notifs = doc.get("notifications") or doc
        return _notifications_output(notifs)
