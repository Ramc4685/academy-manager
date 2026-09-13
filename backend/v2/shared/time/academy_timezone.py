"""Resolve a tenant's IANA timezone from its academy record.

`academies.timezone` is the single source of truth for "what wall clock does
this tenant run on". Deliberately returns ``None`` — never ``"UTC"`` — when the
field is unset, so each caller decides whether to fail closed (writes) or fall
back visibly (reads). Inventing ``"UTC"`` here is exactly the defect that made
a 6:00 PM class render as 1:00 PM to paying parents.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any
from zoneinfo import ZoneInfo

log = logging.getLogger(__name__)

UTC_NAME = "UTC"

AcademyTimezoneReader = Callable[[str], Awaitable[str | None]]


def academy_timezone_lookup(db: Any) -> AcademyTimezoneReader:
    """Timezone name for an academy, or None when unset (#510)."""
    academies = db["academies"]

    async def get_academy_timezone(academy_id: str) -> str | None:
        doc = await academies.find_one({"academy_id": academy_id}, {"timezone": 1})
        if not doc:
            return None
        timezone_name = doc.get("timezone")
        if not timezone_name:
            return None
        text = str(timezone_name).strip()
        return text or None

    return get_academy_timezone


def request_scoped_academy_timezone(
    db: Any, resolve_academy_id: Callable[[], str]
) -> AcademyTimezoneReader:
    """A reader that always resolves the tenant serving the CURRENT request.

    Composition roots capture a boot-time academy id that is only a
    single-tenant fallback. Resolving a session's zone against that id would
    read the wrong tenant's record under multi-academy hosting, so the passed
    academy id is deliberately ignored in favour of request-scoped context.
    """
    lookup = academy_timezone_lookup(db)

    async def get_academy_timezone(_academy_id: str = "") -> str | None:
        return await lookup(resolve_academy_id())

    return get_academy_timezone


async def resolve_reporting_timezone(reader: AcademyTimezoneReader, academy_id: str) -> str:
    """The zone a read model should bucket in, never raising.

    Reads must render something, so an unset, unreadable or nonsense
    ``academies.timezone`` degrades to UTC (the behaviour every report had
    before #608) instead of 500-ing the page. Writes keep failing closed by
    using the raw reader.
    """
    try:
        name = await reader(academy_id)
    except Exception:
        log.warning("academy timezone lookup failed for %r, using UTC", academy_id, exc_info=True)
        return UTC_NAME
    if not name:
        return UTC_NAME
    try:
        ZoneInfo(name)
    except Exception:
        log.warning("unknown academy timezone %r, using UTC", name)
        return UTC_NAME
    return name
