"""Repair session rows stamped with the admin form's ``timezone: "UTC"`` default.

Background (2026-09-01 production defect)
-----------------------------------------
The admin create/edit session form seeds its timezone field from
``DEFAULT_TIMEZONE = "UTC"`` (``frontend/app/(admin)/admin/sessions/page.tsx``)
and only patches it once ``GET /api/v2/admin/academy`` resolves. Whenever that
patch did not land — the academy query had not resolved before submit, or the
``academies`` doc carries no ``timezone`` at all (``GetAcademyUseCase`` also
falls back to ``"UTC"``) — the client sent ``timezone="UTC"``.

``CreateSession.execute`` then built the stored instants correctly *for the
timezone it was given*::

    datetime.combine(local_date, start_time, tzinfo=ZoneInfo("UTC")).astimezone(UTC)

so a 6:00 PM America/Chicago class was persisted as ``18:00Z`` — 1:00 PM
Chicago. The arithmetic was never wrong; the timezone was.

This is not a display-only bug. Both occurrence generators key off
``doc["timezone"]``:

- ``backend/v2/contexts/billing/infrastructure/mongo_monthly_billing.py``
  ``_session_occurrences`` (billing / proration / payroll expectations)
- ``backend/v2/contexts/enrollment/infrastructure/mongo_session_repo.py``
  ``synthesize_recurring_session_docs`` (parent + admin catalog)

and ``QuoteEnrollment`` derives the whole ``BillingPeriod`` from the session's
timezone, so an affected session prices its first month on a UTC clock.

What this migration repairs
---------------------------
Only rows it can *prove* were mis-defaulted, because corrupting a genuinely-UTC
row is the dominant risk here. Every one of these must hold:

1. ``sessions.timezone == "UTC"`` exactly (a missing/empty timezone is a
   different bug — readers fall back to ``America/Chicago`` — and is left
   alone).
2. The owning academy's ``academies.timezone`` is present and is **not**
   ``"UTC"``. If the academy is itself UTC, or has no timezone, the row is
   indeterminate: the form could legitimately have produced ``"UTC"``. Those
   rows are skipped and reported for a human decision, never guessed at.
   (Note ``MongoAcademyRepository.upsert_defaults`` seeds new academies with
   ``timezone: "UTC"``, so an academy reading UTC is not proof of intent.)
3. The row is a recurring template — ``days_of_week`` + ``start_time`` +
   ``end_time`` are all present — so ``start_at``/``end_at`` are *derived*
   values that can be recomputed. Dated one-off sessions carry a client-supplied
   instant that this migration cannot re-derive; they are reported only.
4. The stored ``start_at``/``end_at`` are still consistent with the UTC-default
   hypothesis: read as UTC they land exactly on ``start_time``/``end_time`` on a
   weekday listed in ``days_of_week``. Anything else was written by some other
   path and is left untouched.

Recomputation re-derives the instants from ``start_time``/``end_time`` in the
correct zone on the row's own calendar date — never a fixed offset shift, so
DST is handled per-date by ``ZoneInfo``. The calendar date is preserved (the
UTC-default bug never moved it: with ``tzinfo=UTC`` the stored UTC date *is*
the intended local date), which also makes the repair stable across re-runs.

Materialised ``session_occurrences`` rows are repaired the same way, but only
where they are clean and in the future — mirroring
``composition/admin.py::_is_clean_future_occurrence``. Past, attended, or
already-paid occurrences are history: the class happened at some real wall
clock and the coach was paid for it. Those are reported, not rewritten.
``occurrence_id`` embeds the local date and the literal ``start_time``, neither
of which this repair changes, so ids stay stable and the update is in place.

Execution model
---------------
``up()`` is **report-only by default**. Setting ``SESSION_TZ_REPAIR_APPLY=1``
makes it write. This is deliberate: the boot runner would otherwise apply a
financially-material data rewrite on the next deploy with nobody watching. The
sanctioned path is ``scripts/prod/repair_session_timezones.py``, which calls
``repair()`` directly and works regardless of what the ``v2_migrations``
registry already records.

``repair()`` is idempotent: after a successful pass the consistency guard in
(4) no longer matches, so a re-run reports zero changes.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from motor.motor_asyncio import AsyncIOMotorDatabase

version = "0160_session_timezone_utc_default_repair"

log = logging.getLogger(__name__)

#: The literal value the admin form's ``DEFAULT_TIMEZONE`` sends. Only this
#: exact string is treated as a suspected mis-default.
WRONG_DEFAULT = "UTC"

APPLY_ENV_VAR = "SESSION_TZ_REPAIR_APPLY"

_DOW_INDEX = {
    "mon": 0,
    "tue": 1,
    "wed": 2,
    "thu": 3,
    "fri": 4,
    "sat": 5,
    "sun": 6,
}


@dataclass
class RowChange:
    """One repaired (or repairable) document, with before/after instants."""

    collection: str
    academy_id: str
    doc_key: str
    old_timezone: str | None
    new_timezone: str
    old_start_at: datetime
    new_start_at: datetime
    old_end_at: datetime | None
    new_end_at: datetime | None

    def describe(self) -> str:
        return (
            f"{self.collection}[{self.doc_key}] academy={self.academy_id} "
            f"tz {self.old_timezone!r} -> {self.new_timezone!r} "
            f"start_at {_iso(self.old_start_at)} -> {_iso(self.new_start_at)} "
            f"end_at {_iso(self.old_end_at)} -> {_iso(self.new_end_at)}"
        )


@dataclass
class RepairReport:
    dry_run: bool = True
    sessions_scanned: int = 0
    sessions_changed: list[RowChange] = field(default_factory=list)
    occurrences_changed: list[RowChange] = field(default_factory=list)
    #: reason -> list of human-readable row identifiers that were left alone.
    skipped: dict[str, list[str]] = field(default_factory=dict)

    def skip(self, reason: str, detail: str) -> None:
        self.skipped.setdefault(reason, []).append(detail)

    @property
    def skipped_total(self) -> int:
        return sum(len(rows) for rows in self.skipped.values())

    def summary(self) -> str:
        parts = [
            f"mode={'DRY-RUN' if self.dry_run else 'APPLY'}",
            f"sessions_scanned={self.sessions_scanned}",
            f"sessions_repaired={len(self.sessions_changed)}",
            f"occurrences_repaired={len(self.occurrences_changed)}",
            f"skipped={self.skipped_total}",
        ]
        for reason, rows in sorted(self.skipped.items()):
            parts.append(f"{reason}={len(rows)}")
        return " ".join(parts)


def _iso(value: datetime | None) -> str:
    if value is None:
        return "-"
    return _as_utc(value).isoformat()


def _as_utc(value: datetime) -> datetime:
    """Mongo hands back naive datetimes; they are always UTC instants."""
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _weekday_indexes(days_of_week: Any) -> set[int]:
    out: set[int] = set()
    if not isinstance(days_of_week, (list, tuple)):
        return out
    for day in days_of_week:
        key = str(day).strip()[:3].casefold()
        if key in _DOW_INDEX:
            out.add(_DOW_INDEX[key])
    return out


def _parse_clock(value: object) -> time | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return time.fromisoformat(text)
    except ValueError:
        return None


def _local_interval_utc(
    local_date: date,
    start_time: time,
    end_time: time,
    tz: ZoneInfo,
    *,
    roll_over_midnight: bool,
) -> tuple[datetime, datetime]:
    """Re-derive the UTC instants for one local date in ``tz``.

    ``datetime.combine(..., tzinfo=ZoneInfo(...))`` resolves the offset for
    *that* date, so this is DST-correct across the year — unlike shifting the
    stored instant by a fixed offset.

    ``roll_over_midnight`` mirrors the two writers this repair has to stay
    byte-compatible with, which disagree on the past-midnight case:

    - ``session_occurrences`` (``composition/admin.py::_local_interval_utc``)
      pushes ``end`` to the next day when it lands at or before ``start``.
    - ``sessions`` (``admin_writes.py::_representative_series_datetimes``)
      does not, and stores an ``end_at`` before its ``start_at``.

    Reproducing each writer exactly is what keeps the repair a pure timezone
    correction rather than a silent second change.
    """
    start = datetime.combine(local_date, start_time, tzinfo=tz)
    end = datetime.combine(local_date, end_time, tzinfo=tz)
    if roll_over_midnight and end <= start:
        end += timedelta(days=1)
    return start.astimezone(UTC), end.astimezone(UTC)


def _matches_utc_default_hypothesis(
    *,
    start_at: datetime,
    end_at: datetime | None,
    start_time: time,
    end_time: time,
    weekdays: set[int],
    roll_over_midnight: bool,
) -> bool:
    """True when the stored instants are exactly what ``tz="UTC"`` would write.

    This is the guard that keeps the repair off rows some other code path
    wrote — and, just as importantly, off rows this migration already fixed.
    Under the bug the stored value is literally
    ``combine(local_date, start_time, tzinfo=UTC)``, so read back in UTC it
    lands on the wall clock the admin typed, on one of the series' weekdays.
    Once repaired to a non-UTC zone the wall clock no longer matches, so a
    re-run skips the row: that is what makes ``repair()`` idempotent.
    """
    start_utc = _as_utc(start_at)
    if start_utc.time() != start_time:
        return False
    if start_utc.weekday() not in weekdays:
        return False
    if end_at is None:
        return False
    end_utc = _as_utc(end_at)
    if end_utc.time() != end_time:
        return False
    expected_start, expected_end = _local_interval_utc(
        start_utc.date(),
        start_time,
        end_time,
        ZoneInfo("UTC"),
        roll_over_midnight=roll_over_midnight,
    )
    return start_utc == expected_start and end_utc == expected_end


async def _load_academy_timezones(db: AsyncIOMotorDatabase[Any]) -> dict[str, str | None]:
    """academy_id -> its own ``academies.timezone`` (``None`` when unset).

    ``academies`` is the source of truth the admin form reads through
    ``GetAcademyUseCase``; ``academy_settings.timezone`` is a separate document
    that can and does disagree, so it is deliberately not consulted here.
    """
    out: dict[str, str | None] = {}
    async for doc in db["academies"].find({}, {"academy_id": 1, "timezone": 1}):
        academy_id = str(doc.get("academy_id") or "")
        if not academy_id:
            continue
        timezone_name = str(doc.get("timezone") or "").strip()
        out[academy_id] = timezone_name or None
    return out


async def _occurrence_is_clean_future(
    db: AsyncIOMotorDatabase[Any],
    doc: dict[str, Any],
    *,
    now: datetime,
) -> bool:
    """Mirror of ``composition/admin.py::_is_clean_future_occurrence``."""
    start_at = doc.get("start_at")
    if not isinstance(start_at, datetime) or _as_utc(start_at) < now:
        return False
    if str(doc.get("status") or "scheduled") != "scheduled":
        return False
    if doc.get("actual_coach_id") or doc.get("substitute_coach_id"):
        return False
    academy_id = str(doc.get("academy_id") or "")
    occurrence_id = str(doc.get("occurrence_id") or "")
    for collection in ("attendance", "coach_attendance", "payout_period_lines"):
        if await db[collection].count_documents(
            {"academy_id": academy_id, "occurrence_id": occurrence_id}, limit=1
        ):
            return False
    return True


async def _repair_occurrences_for_session(
    db: AsyncIOMotorDatabase[Any],
    *,
    academy_id: str,
    session_id: str,
    tz: ZoneInfo,
    timezone_name: str,
    start_time: time,
    end_time: time,
    weekdays: set[int],
    report: RepairReport,
    dry_run: bool,
    now: datetime,
) -> None:
    cursor = db["session_occurrences"].find(
        {
            "academy_id": academy_id,
            "$or": [
                {"session_id": session_id},
                {"template_session_id": session_id},
            ],
        }
    )
    async for doc in cursor:
        occurrence_id = str(doc.get("occurrence_id") or "")
        start_at = doc.get("start_at")
        end_at = doc.get("end_at")
        if not isinstance(start_at, datetime):
            report.skip("occurrence_missing_start_at", f"{academy_id}/{occurrence_id}")
            continue
        if not _matches_utc_default_hypothesis(
            start_at=start_at,
            end_at=end_at if isinstance(end_at, datetime) else None,
            start_time=start_time,
            end_time=end_time,
            weekdays=weekdays,
            roll_over_midnight=True,
        ):
            # Already repaired, or written by a path this migration does not
            # model. Either way: not provably wrong, so not touched.
            report.skip("occurrence_not_utc_default_shaped", f"{academy_id}/{occurrence_id}")
            continue
        if not await _occurrence_is_clean_future(db, doc, now=now):
            # The class already happened (or has attendance / payout attached).
            # Rewriting its instant would rewrite history and could move a
            # coach's paid hours; report it for the human instead.
            report.skip("occurrence_past_or_settled", f"{academy_id}/{occurrence_id}")
            continue

        local_date = _as_utc(start_at).date()
        new_start, new_end = _local_interval_utc(
            local_date, start_time, end_time, tz, roll_over_midnight=True
        )
        change = RowChange(
            collection="session_occurrences",
            academy_id=academy_id,
            doc_key=occurrence_id,
            old_timezone=str(doc.get("timezone") or "") or None,
            new_timezone=timezone_name,
            old_start_at=_as_utc(start_at),
            new_start_at=new_start,
            old_end_at=_as_utc(end_at) if isinstance(end_at, datetime) else None,
            new_end_at=new_end,
        )
        log.warning("0160 %s: %s", "would repair" if dry_run else "repairing", change.describe())
        if not dry_run:
            await db["session_occurrences"].update_one(
                {"academy_id": academy_id, "occurrence_id": occurrence_id},
                {"$set": {"start_at": new_start, "end_at": new_end, "updated_at": now}},
            )
        report.occurrences_changed.append(change)


async def repair(
    db: AsyncIOMotorDatabase[Any],
    *,
    dry_run: bool = True,
    now: datetime | None = None,
) -> RepairReport:
    """Repair (or, when ``dry_run``, report) mis-defaulted session timezones."""
    report = RepairReport(dry_run=dry_run)
    moment = now or datetime.now(UTC)
    academy_timezones = await _load_academy_timezones(db)

    async for doc in db["sessions"].find({"timezone": WRONG_DEFAULT}):
        report.sessions_scanned += 1
        academy_id = str(doc.get("academy_id") or "")
        session_id = str(doc.get("session_id") or doc.get("_id") or "")
        row_key = f"{academy_id}/{session_id}"

        if not academy_id or not session_id:
            report.skip("session_missing_identity", row_key)
            continue

        if academy_id not in academy_timezones:
            report.skip("academy_not_found", row_key)
            continue
        academy_tz_name = academy_timezones[academy_id]
        if academy_tz_name is None:
            # Needs a decision, not a guess: with no academy timezone the form
            # would have sent "UTC" legitimately.
            report.skip("academy_timezone_missing", row_key)
            continue
        if academy_tz_name == WRONG_DEFAULT:
            # Indeterminate — the academy may genuinely be UTC, or may just be
            # carrying upsert_defaults' seeded value.
            report.skip("academy_timezone_is_utc", row_key)
            continue
        try:
            tz = ZoneInfo(academy_tz_name)
        except (KeyError, ValueError):
            report.skip("academy_timezone_invalid", f"{row_key} tz={academy_tz_name!r}")
            continue

        start_time = _parse_clock(doc.get("start_time"))
        end_time = _parse_clock(doc.get("end_time"))
        weekdays = _weekday_indexes(doc.get("days_of_week"))
        if start_time is None or end_time is None or not weekdays:
            # A dated one-off: start_at came from the client as an instant and
            # cannot be re-derived here. Reported so the human can see it.
            report.skip("session_not_recurring", row_key)
            continue

        start_at = doc.get("start_at")
        end_at = doc.get("end_at")
        if not isinstance(start_at, datetime):
            report.skip("session_missing_start_at", row_key)
            continue
        if not _matches_utc_default_hypothesis(
            start_at=start_at,
            end_at=end_at if isinstance(end_at, datetime) else None,
            start_time=start_time,
            end_time=end_time,
            weekdays=weekdays,
            roll_over_midnight=False,
        ):
            report.skip("session_not_utc_default_shaped", row_key)
            continue

        local_date = _as_utc(start_at).date()
        new_start, new_end = _local_interval_utc(
            local_date, start_time, end_time, tz, roll_over_midnight=False
        )
        change = RowChange(
            collection="sessions",
            academy_id=academy_id,
            doc_key=session_id,
            old_timezone=WRONG_DEFAULT,
            new_timezone=academy_tz_name,
            old_start_at=_as_utc(start_at),
            new_start_at=new_start,
            old_end_at=_as_utc(end_at) if isinstance(end_at, datetime) else None,
            new_end_at=new_end,
        )
        log.warning("0160 %s: %s", "would repair" if dry_run else "repairing", change.describe())
        if not dry_run:
            await db["sessions"].update_one(
                {"academy_id": academy_id, "session_id": session_id},
                {
                    "$set": {
                        "timezone": academy_tz_name,
                        "start_at": new_start,
                        "end_at": new_end,
                        "updated_at": moment,
                    }
                },
            )
        report.sessions_changed.append(change)

        await _repair_occurrences_for_session(
            db,
            academy_id=academy_id,
            session_id=session_id,
            tz=tz,
            timezone_name=academy_tz_name,
            start_time=start_time,
            end_time=end_time,
            weekdays=weekdays,
            report=report,
            dry_run=dry_run,
            now=moment,
        )

    log.warning("0160 session timezone repair: %s", report.summary())
    for reason, rows in sorted(report.skipped.items()):
        log.warning("0160 skipped[%s] (%d): %s", reason, len(rows), ", ".join(rows[:50]))
    return report


async def up(db: AsyncIOMotorDatabase[Any]) -> None:
    """Report-only unless ``SESSION_TZ_REPAIR_APPLY=1``.

    A financially-material rewrite must not ride in silently on a deploy; see
    the module docstring. Use ``scripts/prod/repair_session_timezones.py`` for
    the reviewed run.
    """
    apply = os.environ.get(APPLY_ENV_VAR, "").strip().lower() in {"1", "true", "yes"}
    if not apply:
        report = await repair(db, dry_run=True)
        if report.sessions_changed or report.occurrences_changed:
            log.warning(
                "0160: %d session(s) and %d occurrence(s) need a timezone repair but "
                "%s is not set — nothing was written. Run "
                "scripts/prod/repair_session_timezones.py --apply after review.",
                len(report.sessions_changed),
                len(report.occurrences_changed),
                APPLY_ENV_VAR,
            )
        return
    await repair(db, dry_run=False)
