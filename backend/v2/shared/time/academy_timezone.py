"""Resolve a tenant's IANA timezone from its academy record.

`academies.timezone` is the single source of truth for "what wall clock does
this tenant run on". Deliberately returns ``None`` — never ``"UTC"`` — when the
field is unset, so each caller decides whether to fail closed (writes) or fall
back visibly (reads). Inventing ``"UTC"`` here is exactly the defect that made
a 6:00 PM class render as 1:00 PM to paying parents.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Mapping
from typing import Any
from zoneinfo import ZoneInfo

log = logging.getLogger(__name__)

UTC_NAME = "UTC"

#: Last-resort zone for LEGACY rows that carry neither their own ``timezone``
#: nor a resolvable academy zone. It is the single-tenant guess every site used
#: to hardcode (BLNO's zone), kept so reads never raise and BLNO's output never
#: moves. This is the ONLY place the literal may live
#: (tests/structural/test_no_chicago_literal.py); reaching it is logged.
LEGACY_FALLBACK_TIMEZONE = "America/Chicago"

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


def academy_clock_timezone(academy_tz: str | None) -> str:
    """The wall clock an academy's scheduled jobs and digests run on.

    The academy's own zone when it is a real IANA name, else
    ``LEGACY_FALLBACK_TIMEZONE`` (never UTC): before Settings Phase 4 every
    scheduled job ran on the scheduler zone, which is BLNO's zone in
    production, so an academy with no zone keeps exactly those times.
    """
    name = str(academy_tz or "").strip()
    if name:
        try:
            ZoneInfo(name)
        except Exception:
            log.warning(
                "unknown academy timezone %r, scheduling on %s", name, LEGACY_FALLBACK_TIMEZONE
            )
        else:
            return name
    return LEGACY_FALLBACK_TIMEZONE


async def resolve_academy_clock_timezone(reader: AcademyTimezoneReader, academy_id: str) -> str:
    """``academy_clock_timezone`` for an academy id, never raising."""
    try:
        name = await reader(academy_id)
    except Exception:
        log.warning(
            "academy timezone lookup failed for %r, scheduling on %s",
            academy_id,
            LEGACY_FALLBACK_TIMEZONE,
            exc_info=True,
        )
        return LEGACY_FALLBACK_TIMEZONE
    return academy_clock_timezone(name)


def resolve_session_timezone(session_tz: str | None, academy_tz: str | None) -> str:
    """The wall clock a session runs on: session zone -> academy zone -> legacy.

    A non-empty session zone is returned verbatim: sessions are validated at
    write time, and money/write paths build their own ``ZoneInfo`` and fail on
    a bad name exactly as they always did. The academy rung is skipped when
    unset or not a real IANA name. The legacy rung never raises but logs, since
    it is a single-tenant guess rather than the tenant's own clock.
    """
    session_name = str(session_tz or "").strip()
    if session_name:
        return session_name
    academy_name = str(academy_tz or "").strip()
    if academy_name:
        try:
            ZoneInfo(academy_name)
        except Exception:
            log.warning(
                "unknown academy timezone %r, falling back to %s",
                academy_name,
                LEGACY_FALLBACK_TIMEZONE,
            )
        else:
            return academy_name
    log.warning(
        "session has no timezone and no academy timezone; falling back to %s",
        LEGACY_FALLBACK_TIMEZONE,
    )
    return LEGACY_FALLBACK_TIMEZONE


async def resolve_session_doc_timezone(
    reader: AcademyTimezoneReader, doc: Mapping[str, Any]
) -> str:
    """``resolve_session_timezone`` for a raw ``sessions`` document.

    The academy zone is read from the doc's OWN ``academy_id`` (the row is
    already tenant-scoped), and only when the doc carries no zone, so the
    common case costs no extra read. A failed lookup degrades to the legacy
    rung instead of raising.
    """
    session_name = str(doc.get("timezone") or "").strip()
    if session_name:
        return session_name
    try:
        academy_name = await reader(str(doc.get("academy_id") or ""))
    except Exception:
        log.warning("academy timezone lookup failed for session doc", exc_info=True)
        academy_name = None
    return resolve_session_timezone(None, academy_name)
