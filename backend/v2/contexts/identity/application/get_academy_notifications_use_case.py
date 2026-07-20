"""Get academy notification settings."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


class AcademyRepo(Protocol):
    async def find_by_id(self, academy_id: str) -> dict[str, Any] | None: ...
    async def upsert_defaults(self, academy_id: str) -> dict[str, Any]: ...


@dataclass(frozen=True)
class GetAcademyNotificationsOutput:
    dues_reminders: bool = False
    attendance_alerts: bool = False
    daily_digest_to_admin: bool = False
    # Per-academy override for the coach teaching-plan digest. ``coach_digest_hour``
    # is interpreted in the scheduler timezone (see scheduler refactor in main.py),
    # not the academy's local timezone.
    coach_digest_enabled: bool = False
    coach_digest_hour: int = 6
    # Per-academy override for the parent daily digest. ``parent_digest_hour`` is
    # interpreted in the scheduler timezone (see scheduler refactor in main.py),
    # not the academy's local timezone.
    parent_digest_enabled: bool = False
    parent_digest_hour: int = 6


def _coerce_hour(value: Any, default: int = 6) -> int:
    """Clamp a stored hour into 0-23; fall back to ``default`` on bad data."""
    try:
        hour = int(value)
    except (TypeError, ValueError):
        return default
    return hour if 0 <= hour <= 23 else default


def _notifications_output(
    notifs: dict[str, Any],
    *,
    default_coach_digest_enabled: bool = False,
    default_coach_digest_hour: int = 6,
    default_parent_digest_enabled: bool = False,
    default_parent_digest_hour: int = 6,
) -> GetAcademyNotificationsOutput:
    return GetAcademyNotificationsOutput(
        dues_reminders=bool(notifs.get("dues_reminders", False)),
        attendance_alerts=bool(notifs.get("attendance_alerts", False)),
        daily_digest_to_admin=bool(notifs.get("daily_digest_to_admin", False)),
        coach_digest_enabled=bool(notifs.get("coach_digest_enabled", default_coach_digest_enabled)),
        coach_digest_hour=_coerce_hour(
            notifs.get("coach_digest_hour", default_coach_digest_hour),
            default=default_coach_digest_hour,
        ),
        parent_digest_enabled=bool(
            notifs.get("parent_digest_enabled", default_parent_digest_enabled)
        ),
        parent_digest_hour=_coerce_hour(
            notifs.get("parent_digest_hour", default_parent_digest_hour),
            default=default_parent_digest_hour,
        ),
    )


class GetAcademyNotificationsUseCase:
    def __init__(
        self,
        academy_repo: AcademyRepo,
        *,
        default_coach_digest_enabled: bool = False,
        default_coach_digest_hour: int = 6,
        default_parent_digest_enabled: bool = False,
        default_parent_digest_hour: int = 6,
    ) -> None:
        self._repo = academy_repo
        self._default_coach_digest_enabled = default_coach_digest_enabled
        self._default_coach_digest_hour = default_coach_digest_hour
        self._default_parent_digest_enabled = default_parent_digest_enabled
        self._default_parent_digest_hour = default_parent_digest_hour

    async def execute(self, academy_id: str) -> GetAcademyNotificationsOutput:
        doc = await self._repo.find_by_id(academy_id)
        if not doc:
            doc = await self._repo.upsert_defaults(academy_id)
        notifs = doc.get("notifications") or doc
        return _notifications_output(
            notifs,
            default_coach_digest_enabled=self._default_coach_digest_enabled,
            default_coach_digest_hour=self._default_coach_digest_hour,
            default_parent_digest_enabled=self._default_parent_digest_enabled,
            default_parent_digest_hour=self._default_parent_digest_hour,
        )
