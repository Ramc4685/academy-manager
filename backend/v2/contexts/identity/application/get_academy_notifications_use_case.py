"""Get academy notification settings."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, Protocol


class AcademyRepo(Protocol):
    async def find_by_id(self, academy_id: str) -> Optional[dict[str, Any]]: ...
    async def upsert_defaults(self, academy_id: str) -> dict[str, Any]: ...


@dataclass(frozen=True)
class GetAcademyNotificationsOutput:
    dues_reminders: bool = False
    attendance_alerts: bool = False
    daily_digest_to_admin: bool = False


class GetAcademyNotificationsUseCase:
    def __init__(self, academy_repo: AcademyRepo) -> None:
        self._repo = academy_repo

    async def execute(self, academy_id: str) -> GetAcademyNotificationsOutput:
        doc = await self._repo.find_by_id(academy_id)
        if not doc:
            doc = await self._repo.upsert_defaults(academy_id)
        notifs = doc.get("notifications") or doc
        return GetAcademyNotificationsOutput(
            dues_reminders=bool(notifs.get("dues_reminders", False)),
            attendance_alerts=bool(notifs.get("attendance_alerts", False)),
            daily_digest_to_admin=bool(notifs.get("daily_digest_to_admin", False)),
        )
