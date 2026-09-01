"""QuoteEnrollment application use case.

Applies FirstMonthProrationPolicy and persists an OPEN snapshot.
Repos and BFFs must not call FirstMonthProrationPolicy directly;
they delegate here instead.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

from backend.v2.contexts.billing.application.ports import (
    OccurrenceCatalog,
    SessionLoader,
    SnapshotWriter,
)
from backend.v2.contexts.billing.domain.errors import PaymentNotFound
from backend.v2.contexts.billing.domain.proration import (
    BillingCalculationSnapshot,
    BillingPeriod,
    FirstMonthProrationPolicy,
)


@dataclass(frozen=True)
class QuoteEnrollmentCommand:
    session_id: str
    billing_start_at: datetime
    calculated_by: str
    parent_id: str | None = None
    student_id: str | None = None
    enrollment_id: str | None = None
    ttl_minutes: int = 15
    #: A caller-chosen *calendar* start date, when the caller has one. It is
    #: resolved to local midnight of the session's own timezone inside
    #: ``execute`` — a calendar date has no meaning until you know whose clock
    #: it is on, and only the use case has the session doc (#541). When set it
    #: supersedes ``billing_start_at``, which then only carries the "no start
    #: date given, start now" fallback.
    billing_start_date: date | None = None


class QuoteEnrollment:
    """Compute a first-month proration quote and store it as an OPEN snapshot."""

    def __init__(
        self,
        *,
        sessions: SessionLoader,
        snapshots: SnapshotWriter,
        occurrences: OccurrenceCatalog,
        clock=lambda: datetime.now(UTC),
    ) -> None:
        self._sessions = sessions
        self._snapshots = snapshots
        self._occurrences = occurrences
        self._clock = clock

    async def execute(self, cmd: QuoteEnrollmentCommand) -> BillingCalculationSnapshot:
        session_doc = await self._sessions.get_by_id(cmd.session_id)
        if session_doc is None:
            raise PaymentNotFound("session not found", payment_id=cmd.session_id)

        now = self._clock()
        timezone_name = str(session_doc.get("timezone") or "America/Chicago")
        billing_start_at = _resolve_billing_start(
            instant=cmd.billing_start_at,
            start_date=cmd.billing_start_date,
            timezone_name=timezone_name,
        )
        period = BillingPeriod.from_label(
            _period_label(billing_start_at, timezone_name),
            timezone_name=timezone_name,
        )
        occ_list = await self._occurrences.list_for_session(session_doc, period)

        snapshot = FirstMonthProrationPolicy().quote(
            monthly_price_cents=_session_amount_cents(session_doc),
            discount_cents=0,
            period=period,
            occurrences=occ_list,
            billing_start_at=billing_start_at,
            calculated_at=now,
            calculated_by=cmd.calculated_by,
        )

        stored = await self._snapshots.persist_open(
            snapshot=snapshot,
            session_id=cmd.session_id,
            parent_id=cmd.parent_id,
            student_id=cmd.student_id,
            enrollment_id=cmd.enrollment_id,
            ttl_minutes=cmd.ttl_minutes,
            now=now,
        )
        return stored


def _zone(timezone_name: str) -> ZoneInfo:
    """The session's timezone, falling back to UTC on an unknown name.

    Follows the local-bucketing pattern from the #510 fix (commit 118f4622).
    Swallowing the bad name here changes nothing observable: every caller
    hands the same name to ``BillingPeriod.from_label`` a line later, which
    constructs its own ``ZoneInfo`` and raises exactly as it did before.
    """
    try:
        return ZoneInfo(timezone_name)
    except (KeyError, ValueError):
        return ZoneInfo("UTC")


def _resolve_billing_start(
    *,
    instant: datetime,
    start_date: date | None,
    timezone_name: str,
) -> datetime:
    """Pin the billing start to the session's own clock.

    A caller-chosen ``start_date`` is a calendar date, not an instant: "start
    on September 1st" means local midnight *for that session*. The composition
    layer cannot resolve it, because only the use case has loaded the session
    doc and therefore its timezone.

    This matters because ``_period_label`` now reads the instant in the
    session's zone. Converting a date at some *other* zone's midnight (the
    composition helpers hardcoded ``America/Chicago``) lands on the previous
    day for any session west of it — 2026-09-01 Chicago midnight is
    2026-08-31 22:00 in Los Angeles — which would silently label, price and
    persist the wrong month (#541).
    """
    if start_date is None:
        return instant
    return datetime.combine(start_date, time.min, tzinfo=_zone(timezone_name))


def _period_label(instant: datetime, timezone_name: str) -> str:
    """``YYYY-MM`` label of ``instant`` in the session's own timezone.

    ``BillingPeriod.from_label`` builds the period bounds from *local* month
    boundaries, so the label has to be local too. Deriving it from a UTC
    instant labels the next month for a US evening near month-end — 8pm
    Chicago on Aug 31 is 01:00 UTC Sep 1 — which skips current-month
    proration and misaligns the zero-amount skip period (#541).

    Naive datetimes are treated as UTC instants, since that is what Mongo
    hands back after dropping tzinfo.
    """
    moment = instant if instant.tzinfo is not None else instant.replace(tzinfo=UTC)
    return moment.astimezone(_zone(timezone_name)).strftime("%Y-%m")


def _session_amount_cents(doc: dict) -> int:
    if doc.get("amount_cents") is not None:
        return int(doc["amount_cents"])
    if doc.get("monthly_price_cents") is not None:
        return int(doc["monthly_price_cents"])
    if doc.get("monthly_price") is not None:
        return round(float(doc["monthly_price"]) * 100)
    return 0
