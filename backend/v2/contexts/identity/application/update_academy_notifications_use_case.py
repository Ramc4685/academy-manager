"""Update academy notification settings."""

from __future__ import annotations

from typing import Any, Optional, Protocol

from .get_academy_notifications_use_case import GetAcademyNotificationsOutput


class AcademyWriteRepo(Protocol):
    async def update_by_id(self, academy_id: str, fields: dict[str, Any]) -> Optional[dict[str, Any]]: ...
    async def upsert_defaults(self, academy_id: str) -> dict[str, Any]: ...


class UpdateAcademyNotificationsUseCase:
    def __init__(self, academy_repo: AcademyWriteRepo) -> None:
        self._repo = academy_repo

    async def execute(self, academy_id: str, fields: dict[str, Any]) -> GetAcademyNotificationsOutput:
        # Nest under "notifications" subdocument.
        patch = {f"notifications.{k}": v for k, v in fields.items() if v is not None}
        if not patch:
            doc = await self._repo.upsert_defaults(academy_id)
        else:
            doc = await self._repo.update_by_id(academy_id, patch)
        if not doc:
            raise LookupError(f"academy {academy_id} not found")
        notifs = doc.get("notifications") or doc
        return GetAcademyNotificationsOutput(
            dues_reminders=bool(notifs.get("dues_reminders", False)),
            attendance_alerts=bool(notifs.get("attendance_alerts", False)),
            daily_digest_to_admin=bool(notifs.get("daily_digest_to_admin", False)),
        )
