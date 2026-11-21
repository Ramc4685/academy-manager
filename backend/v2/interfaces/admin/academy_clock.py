"""Today on the academy's own clock, for admin BFF routes.

"Today" on an admin screen means the academy's calendar date, never the
server's (UTC on Fly): after about 6 PM Central the UTC date is already
tomorrow, which used to put tomorrow's classes on the dashboard.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from backend.v2.interfaces.admin.deps import AdminUseCases
from backend.v2.shared.time.academy_timezone import (
    LEGACY_FALLBACK_TIMEZONE,
    resolve_academy_clock_timezone,
)


def _now() -> datetime:
    return datetime.now(UTC)


async def academy_zone(use_cases: AdminUseCases, academy_id: str) -> str:
    """The academy's clock timezone (legacy zone when none is configured)."""
    reader = getattr(use_cases, "get_academy_timezone", None)
    if reader is None:
        return LEGACY_FALLBACK_TIMEZONE
    return await resolve_academy_clock_timezone(reader, academy_id)


async def academy_today(use_cases: AdminUseCases, academy_id: str) -> date:
    """The academy-local calendar date (legacy zone when none is configured)."""
    zone = await academy_zone(use_cases, academy_id)
    return _now().astimezone(ZoneInfo(zone)).date()
