"""Admin management of the coach rate sheet.

Rates are versioned, never edited in place: setting a new pay rate
supersedes the currently active one (its ``effective_until`` is closed at
the new rate's ``effective_from``) and inserts a new active row. History
is preserved so already-generated payout periods keep pointing at the
rate that was in effect when their occurrences happened.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from itertools import pairwise
from typing import Protocol

from pydantic import BaseModel, Field

from backend.v2.contexts.coaching.domain.payout import (
    CoachRate,
    CoachRateBillingUnit,
    CoachRateTimelineDiagnostics,
    CoachRateTimelineIssue,
)
from backend.v2.shared.ids import new_ulid
from backend.v2.shared.tenancy.context import current_academy_id


class CoachRateWriter(Protocol):
    async def list_for_coach(self, coach_id: str) -> list[CoachRate]: ...

    async def find_active(self, coach_id: str) -> CoachRate | None: ...

    async def supersede(self, rate_id: str, *, effective_until: datetime) -> None: ...

    async def insert(self, rate: CoachRate) -> None: ...


class CoachRateAuditWriter(Protocol):
    async def append(self, entry: CoachRateAuditEntry) -> None: ...


class SetCoachPayRateCommand(BaseModel):
    model_config = {"frozen": True}

    coach_id: str
    billing_unit: CoachRateBillingUnit
    amount_minor: int = Field(default=0, ge=0)
    percent_bps: int | None = Field(default=None, ge=0, le=10000)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    effective_from: datetime | None = None
    actor_id: str | None = None


class RepairCoachRateWindowCommand(BaseModel):
    model_config = {"frozen": True}

    coach_id: str
    billing_unit: CoachRateBillingUnit
    amount_minor: int = Field(default=0, ge=0)
    percent_bps: int | None = Field(default=None, ge=0, le=10000)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    effective_from: datetime
    effective_until: datetime
    reason: str = Field(min_length=1, max_length=1000)
    actor_id: str = Field(min_length=1)


class CoachRateAuditEntry(BaseModel):
    model_config = {"frozen": True}

    audit_id: str
    academy_id: str
    coach_id: str
    rate_id: str | None = None
    action: str
    actor_id: str | None = None
    at: datetime
    reason: str | None = None
    before: dict | None = None
    after: dict | None = None


def normalize_effective_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _rate_window(rate: CoachRate) -> tuple[datetime, datetime | None]:
    return (
        normalize_effective_datetime(rate.effective_from),
        None
        if rate.effective_until is None
        else normalize_effective_datetime(rate.effective_until),
    )


def diagnose_rate_timeline(coach_id: str, rates: list[CoachRate]) -> CoachRateTimelineDiagnostics:
    issues: list[CoachRateTimelineIssue] = []
    ordered = sorted(rates, key=lambda r: _rate_window(r)[0])

    starts: dict[datetime, list[CoachRate]] = {}
    active = [r for r in ordered if r.status == "active"]
    open_ended = [r for r in ordered if r.effective_until is None]
    for rate in ordered:
        start, until = _rate_window(rate)
        starts.setdefault(start, []).append(rate)
        if until is not None and until <= start:
            issues.append(
                CoachRateTimelineIssue(
                    issue_type="invalid_window",
                    message="Rate window ends before or at its effective start.",
                    rate_ids=[rate.rate_id],
                    starts_at=start,
                    ends_at=until,
                )
            )
        if rate.status == "active" and until is not None:
            issues.append(
                CoachRateTimelineIssue(
                    issue_type="malformed_history",
                    message="Active rate has a closed effective_until.",
                    rate_ids=[rate.rate_id],
                    starts_at=start,
                    ends_at=until,
                )
            )
        if rate.status == "superseded" and until is None:
            issues.append(
                CoachRateTimelineIssue(
                    issue_type="malformed_history",
                    message="Superseded rate is open-ended.",
                    rate_ids=[rate.rate_id],
                    starts_at=start,
                )
            )

    for start, duplicates in starts.items():
        if len(duplicates) > 1:
            issues.append(
                CoachRateTimelineIssue(
                    issue_type="duplicate_effective_from",
                    message="Multiple rate rows share the same effective_from.",
                    rate_ids=[r.rate_id for r in duplicates],
                    starts_at=start,
                )
            )

    if len(active) > 1:
        issues.append(
            CoachRateTimelineIssue(
                issue_type="duplicate_active_rows",
                message="Multiple active coach-rate rows exist.",
                rate_ids=[r.rate_id for r in active],
            )
        )
    if len(open_ended) > 1:
        issues.append(
            CoachRateTimelineIssue(
                issue_type="multiple_open_ended_rows",
                message="Multiple open-ended coach-rate rows exist.",
                rate_ids=[r.rate_id for r in open_ended],
            )
        )

    for prev, current in pairwise(ordered):
        _prev_start, prev_until = _rate_window(prev)
        current_start, _ = _rate_window(current)
        if prev_until is None:
            issues.append(
                CoachRateTimelineIssue(
                    issue_type="overlap",
                    message="Open-ended rate overlaps a later rate.",
                    rate_ids=[prev.rate_id, current.rate_id],
                    starts_at=current_start,
                )
            )
            continue
        if prev_until < current_start:
            issues.append(
                CoachRateTimelineIssue(
                    issue_type="gap",
                    message="Rate history has an uncovered gap.",
                    rate_ids=[prev.rate_id, current.rate_id],
                    starts_at=prev_until,
                    ends_at=current_start,
                )
            )
        elif prev_until > current_start:
            issues.append(
                CoachRateTimelineIssue(
                    issue_type="overlap",
                    message="Rate windows overlap.",
                    rate_ids=[prev.rate_id, current.rate_id],
                    starts_at=current_start,
                    ends_at=prev_until,
                )
            )

    return CoachRateTimelineDiagnostics(coach_id=coach_id, issues=issues)


def _blocking_for_normal_set(
    diagnostics: CoachRateTimelineDiagnostics,
) -> list[CoachRateTimelineIssue]:
    return [
        issue
        for issue in diagnostics.issues
        if issue.issue_type
        in {
            "overlap",
            "duplicate_effective_from",
            "duplicate_active_rows",
            "multiple_open_ended_rows",
            "invalid_window",
            "malformed_history",
        }
    ]


class SetCoachPayRate:
    def __init__(
        self,
        *,
        rates: CoachRateWriter,
        audit: CoachRateAuditWriter | None = None,
        clock: Callable[[], datetime] | None = None,
        id_factory: Callable[[], str] | None = None,
        audit_id_factory: Callable[[], str] | None = None,
    ) -> None:
        self._rates = rates
        self._audit = audit
        self._clock = clock or (lambda: datetime.now(UTC))
        self._id = id_factory or (lambda: str(new_ulid()))
        self._audit_id = audit_id_factory or (lambda: str(new_ulid()))

    async def execute(self, command: SetCoachPayRateCommand) -> CoachRate:
        if command.billing_unit == "percent_of_revenue":
            if command.percent_bps is None:
                raise ValueError("percent is required for percent_of_revenue rates")
        elif command.amount_minor <= 0:
            raise ValueError("amount must be positive for per_session/per_hour rates")

        effective_from = normalize_effective_datetime(command.effective_from or self._clock())

        diagnostics = diagnose_rate_timeline(
            command.coach_id, await self._rates.list_for_coach(command.coach_id)
        )
        if _blocking_for_normal_set(diagnostics):
            raise ValueError("coach rate timeline is malformed; use the repair workflow")

        active = await self._rates.find_active(command.coach_id)
        if active is not None:
            active_start = normalize_effective_datetime(active.effective_from)
            if effective_from <= active_start:
                raise ValueError(
                    "effective_from must be after the current rate's effective_from "
                    f"({active_start.isoformat()})"
                )
            await self._rates.supersede(active.rate_id, effective_until=effective_from)
            await self._record(
                command.coach_id,
                rate_id=active.rate_id,
                action="rate_superseded",
                actor_id=command.actor_id,
                before={"effective_until": _iso(active.effective_until), "status": active.status},
                after={"effective_until": effective_from.isoformat(), "status": "superseded"},
            )

        rate = CoachRate(
            rate_id=self._id(),
            academy_id=current_academy_id(),
            coach_id=command.coach_id,
            billing_unit=command.billing_unit,
            amount_minor=command.amount_minor,
            percent_bps=(
                command.percent_bps if command.billing_unit == "percent_of_revenue" else None
            ),
            currency=command.currency.upper(),
            effective_from=effective_from,
            effective_until=None,
            status="active",
        )
        await self._rates.insert(rate)
        await self._record(
            command.coach_id,
            rate_id=rate.rate_id,
            action="rate_created",
            actor_id=command.actor_id,
            after=_rate_audit_snapshot(rate),
        )
        return rate

    async def _record(
        self,
        coach_id: str,
        *,
        rate_id: str | None,
        action: str,
        actor_id: str | None,
        reason: str | None = None,
        before: dict | None = None,
        after: dict | None = None,
    ) -> None:
        if self._audit is None:
            return
        await self._audit.append(
            CoachRateAuditEntry(
                audit_id=self._audit_id(),
                academy_id=current_academy_id(),
                coach_id=coach_id,
                rate_id=rate_id,
                action=action,
                actor_id=actor_id,
                at=self._clock(),
                reason=reason,
                before=before,
                after=after,
            )
        )


class RepairCoachRateWindow:
    def __init__(
        self,
        *,
        rates: CoachRateWriter,
        audit: CoachRateAuditWriter,
        clock: Callable[[], datetime] | None = None,
        id_factory: Callable[[], str] | None = None,
        audit_id_factory: Callable[[], str] | None = None,
    ) -> None:
        self._rates = rates
        self._audit = audit
        self._clock = clock or (lambda: datetime.now(UTC))
        self._id = id_factory or (lambda: str(new_ulid()))
        self._audit_id = audit_id_factory or (lambda: str(new_ulid()))

    async def execute(self, command: RepairCoachRateWindowCommand) -> CoachRate:
        if not command.reason.strip():
            raise ValueError("reason is required to repair a coach rate window")
        if command.billing_unit == "percent_of_revenue":
            if command.percent_bps is None:
                raise ValueError("percent is required for percent_of_revenue rates")
        elif command.amount_minor <= 0:
            raise ValueError("amount must be positive for per_session/per_hour rates")

        start = normalize_effective_datetime(command.effective_from)
        until = normalize_effective_datetime(command.effective_until)
        if until <= start:
            raise ValueError("effective_until must be after effective_from")

        existing = await self._rates.list_for_coach(command.coach_id)
        for rate in existing:
            existing_start, existing_until = _rate_window(rate)
            if (
                start < (existing_until or datetime.max.replace(tzinfo=UTC))
                and until > existing_start
            ):
                raise ValueError("repair window overlaps an existing coach rate")

        rate = CoachRate(
            rate_id=self._id(),
            academy_id=current_academy_id(),
            coach_id=command.coach_id,
            billing_unit=command.billing_unit,
            amount_minor=command.amount_minor,
            percent_bps=(
                command.percent_bps if command.billing_unit == "percent_of_revenue" else None
            ),
            currency=command.currency.upper(),
            effective_from=start,
            effective_until=until,
            status="superseded",
        )
        await self._rates.insert(rate)
        await self._audit.append(
            CoachRateAuditEntry(
                audit_id=self._audit_id(),
                academy_id=current_academy_id(),
                coach_id=command.coach_id,
                rate_id=rate.rate_id,
                action="rate_repaired",
                actor_id=command.actor_id,
                at=self._clock(),
                reason=command.reason,
                before={
                    "issue_types": [
                        issue.issue_type
                        for issue in diagnose_rate_timeline(command.coach_id, existing).issues
                    ]
                },
                after=_rate_audit_snapshot(rate),
            )
        )
        return rate


class DiagnoseCoachRateTimeline:
    def __init__(self, *, rates: CoachRateWriter) -> None:
        self._rates = rates

    async def execute(self, *, coach_id: str) -> CoachRateTimelineDiagnostics:
        return diagnose_rate_timeline(coach_id, await self._rates.list_for_coach(coach_id))


class ListCoachPayRates:
    def __init__(self, *, rates: CoachRateWriter) -> None:
        self._rates = rates

    async def execute(self, *, coach_id: str) -> list[CoachRate]:
        rates = await self._rates.list_for_coach(coach_id)
        return sorted(rates, key=lambda r: r.effective_from, reverse=True)


def _iso(value: datetime | None) -> str | None:
    return None if value is None else normalize_effective_datetime(value).isoformat()


def _rate_audit_snapshot(rate: CoachRate) -> dict:
    return {
        "rate_id": rate.rate_id,
        "billing_unit": rate.billing_unit,
        "amount_minor": rate.amount_minor,
        "percent_bps": rate.percent_bps,
        "currency": rate.currency,
        "effective_from": _iso(rate.effective_from),
        "effective_until": _iso(rate.effective_until),
        "status": rate.status,
    }
