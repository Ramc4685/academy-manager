"""Application-layer ports for the finance context (Wave 5A).

The finance context never imports from coaching, billing, or enrollment.
Anything it needs from those contexts is reshaped into a local DTO at the
composition layer and exposed here as a ``Protocol``.

Two families of ports:

1. **Storage** — ``PayoutPeriodRepository`` for the persisted payout
   periods + lines (Stream J), plus snapshot repositories for the
   reporting read models (Stream M).
2. **External read models** — ``PayoutCalculator``, ``BillingLedgerReader``,
   ``SessionOccurrenceReader`` and ``AttendanceReader`` — these are
   implemented by adapters in the composition layer that translate from
   their owning context's types to local DTOs.

Keeping these as Protocols means tests can supply fakes without dragging
in Mongo or other contexts.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from backend.v2.contexts.finance.domain.payout_audit import PayoutAuditEntry
from backend.v2.contexts.finance.domain.payout_period import (
    PayoutPeriod,
    PayoutWarning,
    PersistedPayoutLine,
)
from backend.v2.contexts.finance.domain.reporting_snapshots import (
    AcademyRevenueSnapshot,
    CoachPayoutSnapshot,
    SessionAttendanceSnapshot,
)

# ---------------------------------------------------------------------------
# Storage ports
# ---------------------------------------------------------------------------


class PayoutPeriodRepository(Protocol):
    """Storage port for ``PayoutPeriod`` aggregates.

    Uniqueness is enforced on the natural key
    ``(academy_id, coach_id, period_start, period_end)`` — see migration
    ``0103_payout_period_indexes.py``.
    """

    async def find_by_window(
        self,
        *,
        coach_id: str,
        period_start: datetime,
        period_end: datetime,
    ) -> PayoutPeriod | None: ...

    async def find_by_id(self, period_id: str) -> PayoutPeriod | None: ...

    async def save(self, period: PayoutPeriod) -> PayoutPeriod:
        """Insert the period and its lines atomically.

        If a period with the same natural key already exists, return it
        unchanged (idempotent — supports retried generation).
        """
        ...

    async def replace(self, period: PayoutPeriod) -> PayoutPeriod:
        """Replace an existing period (state-machine update).

        Raises ``LookupError`` if no period matches ``period.period_id``.
        """
        ...

    async def replace_with_lines(self, period: PayoutPeriod) -> PayoutPeriod:
        """Replace an existing period AND rewrite its lines.

        Used by recompute and line-override flows where the line set
        itself changes. Raises ``LookupError`` if the period is missing.
        """
        ...

    async def list_for_window(
        self,
        *,
        academy_id: str,
        period_start: datetime,
        period_end: datetime,
    ) -> list[PayoutPeriod]:
        """All periods for this academy whose window exactly matches [period_start, period_end)."""
        ...


class PayoutAuditLog(Protocol):
    """Append-only audit trail of payout-period mutations."""

    async def append(self, entry: PayoutAuditEntry) -> None: ...

    async def list_for_period(self, period_id: str) -> list[PayoutAuditEntry]: ...


class AcademyRevenueSnapshotRepository(Protocol):
    async def find(self, *, academy_id: str, period: str) -> AcademyRevenueSnapshot | None: ...

    async def upsert(self, snapshot: AcademyRevenueSnapshot) -> AcademyRevenueSnapshot: ...


class SessionAttendanceSnapshotRepository(Protocol):
    async def find(
        self, *, academy_id: str, session_id: str, period: str
    ) -> SessionAttendanceSnapshot | None: ...

    async def upsert(self, snapshot: SessionAttendanceSnapshot) -> SessionAttendanceSnapshot: ...


class CoachPayoutSnapshotRepository(Protocol):
    async def find(
        self, *, academy_id: str, coach_id: str, period: str
    ) -> CoachPayoutSnapshot | None: ...

    async def upsert(self, snapshot: CoachPayoutSnapshot) -> CoachPayoutSnapshot: ...


# ---------------------------------------------------------------------------
# External read-model ports (implemented by composition-layer adapters)
# ---------------------------------------------------------------------------


class PayoutCalculation(Protocol):
    """The shape of a payout calculation result, locally typed."""

    @property
    def coach_id(self) -> str: ...
    @property
    def academy_id(self) -> str: ...
    @property
    def period_start(self) -> datetime: ...
    @property
    def period_end(self) -> datetime: ...
    @property
    def currency(self) -> str: ...
    @property
    def total_minor(self) -> int: ...
    @property
    def lines(self) -> list[PersistedPayoutLine]: ...
    @property
    def unpaid_occurrence_ids(self) -> list[str]: ...
    @property
    def payout_warnings(self) -> list[PayoutWarning]: ...


class PayoutCalculator(Protocol):
    """Composition-layer adapter that wraps ``ComputeCoachPayout`` and
    translates ``coaching.PayoutLine`` into ``PersistedPayoutLine``."""

    async def calculate(
        self,
        *,
        coach_id: str,
        academy_id: str,
        period_start: datetime,
        period_end: datetime,
    ) -> PayoutCalculation: ...


class BillingLedgerReader(Protocol):
    """Aggregated billing facts for a reporting period.

    Implemented by a composition-layer adapter over the billing context's
    repositories. ``period`` is an opaque string like ``2026-05`` —
    semantics belong to the caller.
    """

    async def revenue_for_period(
        self, *, academy_id: str, period_start: datetime, period_end: datetime
    ) -> BillingPeriodTotals: ...


class BillingPeriodTotals(Protocol):
    @property
    def gross_minor(self) -> int: ...
    @property
    def refunded_minor(self) -> int: ...
    @property
    def outstanding_minor(self) -> int: ...
    @property
    def currency(self) -> str: ...


class SessionOccurrenceReader(Protocol):
    """Counts session occurrences in a window.

    Implemented by a composition-layer adapter over enrollment.
    """

    async def counts_for_session(
        self,
        *,
        academy_id: str,
        session_id: str,
        period_start: datetime,
        period_end: datetime,
    ) -> SessionOccurrenceCounts: ...


class SessionOccurrenceCounts(Protocol):
    @property
    def scheduled_count(self) -> int: ...
    @property
    def completed_count(self) -> int: ...
    @property
    def no_show_count(self) -> int: ...


class ApplicationFunnelReader(Protocol):
    """Read application funnel counts from the onboarding store.

    The implementor queries the ``onboarding_applications`` collection
    and groups raw documents by their ``status`` field.  The finance
    context never imports from the onboarding context directly — this
    port is the boundary.

    Returns a mapping of ``{status: count}`` for all statuses that have
    at least one document matching the query.  An empty collection
    returns an empty dict.
    """

    async def get_funnel_counts(self, academy_id: str, period: str | None) -> dict[str, int]: ...


class AttendanceSnapshotReader(Protocol):
    """Read ``SessionAttendanceSnapshot`` records for a set of periods.

    The implementor queries the ``session_attendance_snapshots`` collection
    and returns all snapshot documents that match the given academy and
    periods.  The finance context uses this to build trend reports without
    knowing Mongo internals.

    Returns all matching snapshots (one per session per period).  An
    unknown period or an academy with no data returns an empty list.
    """

    async def list_snapshots_for_periods(
        self, *, academy_id: str, periods: list[str]
    ) -> list[SessionAttendanceSnapshot]: ...


class CoachMonthOccurrences(Protocol):
    """Shape of one row returned by MonthlyCoachOccurrenceReader."""

    @property
    def coach_id(self) -> str: ...

    @property
    def session_count(self) -> int: ...


class MonthlyCoachOccurrenceReader(Protocol):
    """Coaches with payable, non-cancelled occurrences in a month window.

    Paying coach = actual_coach_id when set, else scheduled_coach_id.
    Clock-derived completion: end_at < now OR status == 'completed'.
    Never filters on stored status == 'completed' alone.
    """

    async def coaches_with_occurrences(
        self, *, academy_id: str, period_start: datetime, period_end: datetime
    ) -> list[CoachMonthOccurrences]: ...


class CoachPayoutSnapshotReader(Protocol):
    """Read ``CoachPayoutSnapshot`` records for a set of periods.

    The implementor queries the ``coach_payout_snapshots`` collection
    and returns all snapshot documents that match the given academy and
    periods.  The finance context uses this to build utilization reports
    without knowing Mongo internals.

    Returns all matching snapshots (one per coach per period).  An
    unknown period or an academy with no data returns an empty list.
    """

    async def list_snapshots_for_periods(
        self, *, academy_id: str, periods: list[str]
    ) -> list[CoachPayoutSnapshot]: ...


__all__ = [
    "AcademyRevenueSnapshotRepository",
    "ApplicationFunnelReader",
    "AttendanceSnapshotReader",
    "BillingLedgerReader",
    "BillingPeriodTotals",
    "CoachMonthOccurrences",
    "CoachPayoutSnapshotReader",
    "CoachPayoutSnapshotRepository",
    "MonthlyCoachOccurrenceReader",
    "PayoutAuditLog",
    "PayoutCalculation",
    "PayoutCalculator",
    "PayoutPeriodRepository",
    "SessionAttendanceSnapshotRepository",
    "SessionOccurrenceCounts",
    "SessionOccurrenceReader",
]
