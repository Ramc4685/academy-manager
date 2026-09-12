"""Shared enrollment/hold fakes for issue #697's test suite.

These fakes are part of the contract, not test scaffolding (see the
departures design contract §6.1): a permissive fake with an overwriting
``put`` and a non-deduping audit append hid two P1 money bugs on #664 AND
made the review's verifiers refute a correct finding. No test file in this
suite may write its own copy of these — a second, laxer fake is how the
first one gets bypassed.

Every fake here enforces the SAME constraint the real Mongo store does:

* ``FakeSessionWriter.try_reserve_seat`` really checks
  ``reserved_seats < capacity`` AND ``status in {scheduled,active,open}``.
* ``FakeSessionWriter.release_seat`` floors at zero AND appends to
  ``release_calls`` — because the real one floors, a double-release is
  invisible in the final count; tests must assert the call COUNT.
* ``FakeEnrollmentWriter``'s CAS methods are true compare-and-set: they
  return the pre-image on the first winning call and ``None`` on every
  later call against the same row — never an unconditional overwrite.
* ``FakeHoldRepository.claim_longest_held`` applies the real sort
  ``(hold_started_at ASC, enrollment_id ASC)``, flips the row to
  ``reclaim_pending`` atomically, and never returns the same document twice.
* ``FakeBillingSync`` records every ``(enrollment_id, transition,
  effective_at)`` tuple — tests assert EXACT multiplicity, never membership.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from backend.v2.contexts.enrollment.domain.models import SEAT_HOLDING, Enrollment, Session


def make_enrollment(
    enrollment_id: str = "enr-1",
    *,
    academy_id: str = "acad",
    session_id: str = "sess-1",
    student_id: str = "stu-1",
    status: str = "active",
    **extra: Any,
) -> Enrollment:
    return Enrollment(
        enrollment_id=enrollment_id,
        academy_id=academy_id,
        session_id=session_id,
        student_id=student_id,
        status=status,  # type: ignore[arg-type]
        **extra,
    )


def make_session(
    session_id: str = "sess-1",
    *,
    academy_id: str = "acad",
    capacity: int = 1,
    status: str = "scheduled",
    coach_id: str = "coach-1",
    amount_cents: int | None = None,
) -> Session:
    from datetime import timedelta

    now = datetime(2026, 1, 1, tzinfo=UTC)
    return Session(
        session_id=session_id,
        academy_id=academy_id,
        coach_id=coach_id,
        title="Test class",
        location="Court 1",
        start_at=now,
        end_at=now + timedelta(hours=1),
        capacity=capacity,
        status=status,  # type: ignore[arg-type]
        amount_cents=amount_cents,
    )


@dataclass
class FakeSessionWriter:
    """Real capacity + status enforcement — never a rubber stamp."""

    sessions: dict[str, Session] = field(default_factory=dict)
    reserved_seats: dict[str, int] = field(default_factory=dict)
    release_calls: list[str] = field(default_factory=list)
    reserve_calls: list[str] = field(default_factory=list)

    _ENROLLABLE = frozenset({"scheduled", "active", "open"})

    async def get(self, session_id: str) -> Session | None:
        return self.sessions.get(session_id)

    async def try_reserve_seat(self, session_id: str) -> bool:
        self.reserve_calls.append(session_id)
        session = self.sessions.get(session_id)
        if session is None or session.status not in self._ENROLLABLE:
            return False
        current = self.reserved_seats.get(session_id, 0)
        if current >= session.capacity:
            return False
        self.reserved_seats[session_id] = current + 1
        return True

    async def release_seat(self, session_id: str) -> None:
        self.release_calls.append(session_id)
        current = self.reserved_seats.get(session_id, 0)
        self.reserved_seats[session_id] = max(0, current - 1)

    async def update_status(self, session_id: str, status: str) -> None:
        s = self.sessions.get(session_id)
        if s is not None:
            self.sessions[session_id] = s.model_copy(update={"status": status})


@dataclass
class FakeEnrollmentWriter:
    """True compare-and-set on every CAS method — never an unconditional write."""

    rows: dict[str, Enrollment] = field(default_factory=dict)

    async def get(self, enrollment_id: str) -> Enrollment | None:
        return self.rows.get(enrollment_id)

    async def create(self, enrollment: Enrollment) -> None:
        self.rows[enrollment.enrollment_id] = enrollment

    async def update_status(self, enrollment_id: str, status: str) -> None:
        self.rows[enrollment_id] = self.rows[enrollment_id].model_copy(update={"status": status})

    async def update_session(self, enrollment_id: str, session_id: str) -> None:
        self.rows[enrollment_id] = self.rows[enrollment_id].model_copy(
            update={"session_id": session_id}
        )

    async def find_for_session_student(self, session_id: str, student_id: str) -> Enrollment | None:
        return next(
            (
                e
                for e in self.rows.values()
                if e.session_id == session_id and e.student_id == student_id
            ),
            None,
        )

    async def mark_withdrawn_if_open(
        self, enrollment_id: str, *, withdrawal_date: datetime
    ) -> Enrollment | None:
        # Issue #699: writes the canonical "dropped" spelling, matching
        # MongoEnrollmentWriter.mark_withdrawn_if_open (was "withdrawn").
        before = self.rows.get(enrollment_id)
        if before is None or before.status not in {"active", "paused", "held"}:
            return None
        self.rows[enrollment_id] = before.model_copy(
            update={"status": "dropped", "withdrawal_date": withdrawal_date}
        )
        return before

    async def mark_held_if_active(
        self,
        enrollment_id: str,
        *,
        started_at: datetime,
        return_on: Any,
        expires_at: datetime,
        reason: str | None,
    ) -> Enrollment | None:
        before = self.rows.get(enrollment_id)
        if before is None or before.status != "active":
            return None
        self.rows[enrollment_id] = before.model_copy(
            update={
                "status": "held",
                "hold_started_at": started_at,
                "hold_return_on": return_on,
                "hold_expires_at": expires_at,
                "hold_reason": reason,
                "hold_seq": before.hold_seq + 1,
                "hold_reclaim_claimed_at": None,
                "hold_reclaim_for": None,
            }
        )
        return before

    async def mark_active_if_held(self, enrollment_id: str) -> Enrollment | None:
        before = self.rows.get(enrollment_id)
        if before is None or before.status != "held":
            return None
        self.rows[enrollment_id] = before.model_copy(
            update={
                "status": "active",
                "hold_started_at": None,
                "hold_return_on": None,
                "hold_expires_at": None,
                "hold_reason": None,
            }
        )
        return before

    async def mark_pending_cancellation_by_parent(
        self,
        enrollment_id: str,
        *,
        cancellation_reason: str,
        cancellation_policy_snapshot: dict[str, Any],
        pending_cancellation_at: datetime,
        requested_at: datetime,
    ) -> Enrollment | None:
        before = self.rows.get(enrollment_id)
        if (
            before is None
            or before.status != "active"
            or before.pending_cancellation_at is not None
        ):
            return None
        self.rows[enrollment_id] = before.model_copy(
            update={
                "cancellation_reason": cancellation_reason,
                "cancellation_policy_snapshot": cancellation_policy_snapshot,
                "pending_cancellation_at": pending_cancellation_at,
                "pending_cancellation_requested_at": requested_at,
            }
        )
        return self.rows[enrollment_id]

    async def complete_pending_cancellation(
        self, enrollment_id: str, *, cancelled_at: datetime
    ) -> Enrollment | None:
        """Mirrors ``MongoEnrollmentWriter.complete_pending_cancellation``:
        CAS on "still pending, not yet ended" — active, paused, OR held (a
        hold keeps the seat AND the pending marker; see the departures
        follow-up on issue #675/#697)."""
        before = self.rows.get(enrollment_id)
        if (
            before is None
            or before.status not in {"active", "paused", "held"}
            or before.pending_cancellation_at is None
        ):
            return None
        self.rows[enrollment_id] = before.model_copy(
            update={
                "status": "cancelled",
                "cancelled_by": "parent",
                "cancelled_at": cancelled_at,
                "pending_cancellation_at": None,
            }
        )
        return before

    async def delete_if_status(
        self, enrollment_id: str, *, allowed: frozenset[str]
    ) -> Enrollment | None:
        before = self.rows.get(enrollment_id)
        if before is None or before.status not in allowed:
            return None
        del self.rows[enrollment_id]
        return before

    async def count_active_for_session(self, session_id: str) -> int:
        return sum(
            1 for e in self.rows.values() if e.session_id == session_id and e.status in SEAT_HOLDING
        )


@dataclass
class FakeHoldRepository:
    """Real sort + real single-claim CAS — mirrors MongoHoldRepository exactly."""

    enrollments: FakeEnrollmentWriter
    claimed_ids: list[str] = field(default_factory=list)

    async def claim_longest_held(
        self, *, session_id: str, now: datetime, requested_by: str
    ) -> Enrollment | None:
        candidates = [
            e
            for e in self.enrollments.rows.values()
            if e.session_id == session_id
            and e.status == "held"
            and e.hold_reclaim_claimed_at is None
        ]
        if not candidates:
            return None
        candidates.sort(key=lambda e: (e.hold_started_at or now, e.enrollment_id))
        victim = candidates[0]
        # Atomic in the real store; here we just flip it before returning —
        # a second call in the SAME tick will not see it again because the
        # filter above excludes claimed rows.
        self.enrollments.rows[victim.enrollment_id] = victim.model_copy(
            update={
                "status": "reclaim_pending",
                "hold_reclaim_claimed_at": now,
                "hold_reclaim_for": requested_by,
            }
        )
        self.claimed_ids.append(victim.enrollment_id)
        return victim

    async def claim_expired(
        self, *, enrollment_id: str, now: datetime, requested_by: str
    ) -> Enrollment | None:
        before = self.enrollments.rows.get(enrollment_id)
        if (
            before is None
            or before.status != "held"
            or before.hold_reclaim_claimed_at is not None
            # Mirrors the real CAS filter's `hold_expires_at: {"$lte": now}`:
            # a row that returned and was re-Held between list_expired's
            # snapshot and this claim has a fresh, later hold_expires_at and
            # must NOT be claimable as expired.
            or before.hold_expires_at is None
            or before.hold_expires_at > now
        ):
            return None
        self.enrollments.rows[enrollment_id] = before.model_copy(
            update={
                "status": "reclaim_pending",
                "hold_reclaim_claimed_at": now,
                "hold_reclaim_for": requested_by,
            }
        )
        self.claimed_ids.append(enrollment_id)
        return before

    async def finalize_reclaim(
        self, enrollment_id: str, *, withdrawal_date: datetime
    ) -> Enrollment | None:
        # Issue #699: writes the canonical "dropped" spelling, matching
        # MongoHoldRepository.finalize_reclaim (was "withdrawn").
        before = self.enrollments.rows.get(enrollment_id)
        if before is None or before.status != "reclaim_pending":
            return None
        self.enrollments.rows[enrollment_id] = before.model_copy(
            update={"status": "dropped", "withdrawal_date": withdrawal_date}
        )
        return before

    async def mark_reclaim_orphaned(self, enrollment_id: str, *, now: datetime) -> None:
        before = self.enrollments.rows.get(enrollment_id)
        if before is None or before.status != "reclaim_pending":
            return
        self.enrollments.rows[enrollment_id] = before.model_copy(
            update={"hold_reclaim_failed_at": now}
        )

    async def list_stalled(self, *, older_than: datetime) -> list[Enrollment]:
        return [
            e
            for e in self.enrollments.rows.values()
            if e.status == "reclaim_pending"
            and e.hold_reclaim_claimed_at is not None
            and e.hold_reclaim_claimed_at < older_than
        ]

    async def list_due_for_reminder(self) -> list[Enrollment]:
        return [e for e in self.enrollments.rows.values() if e.status == "held"]

    async def list_expired(self, *, now: datetime) -> list[Enrollment]:
        return [
            e
            for e in self.enrollments.rows.values()
            if e.status == "held" and e.hold_expires_at is not None and e.hold_expires_at <= now
        ]


@dataclass
class FakeDeparturePolicyRepo:
    policy: Any = None

    async def get_or_default(self) -> Any:
        if self.policy is not None:
            return self.policy
        from backend.v2.contexts.enrollment.domain.departure_policy import (
            EnrollmentDeparturePolicy,
        )

        return EnrollmentDeparturePolicy.default("acad")

    async def save(self, policy: Any) -> None:
        self.policy = policy


@dataclass
class FakeBillingSync:
    """Records every (enrollment_id, transition, effective_at) call — tests
    assert EXACT multiplicity, never membership."""

    calls: list[dict[str, Any]] = field(default_factory=list)
    result: dict[str, Any] = field(default_factory=lambda: {"billing_result": "ok"})

    async def apply(
        self,
        *,
        enrollment_id: str,
        transition: str,
        effective_at: datetime,
        reason: str,
        actor_id: str | None,
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "enrollment_id": enrollment_id,
                "transition": transition,
                "effective_at": effective_at,
                "reason": reason,
                "actor_id": actor_id,
            }
        )
        return dict(self.result)


@dataclass
class FakeHoldNotifier:
    started_calls: list[dict[str, Any]] = field(default_factory=list)
    reclaimed_calls: list[dict[str, Any]] = field(default_factory=list)
    reminder_calls: list[dict[str, Any]] = field(default_factory=list)
    dropped_calls: list[dict[str, Any]] = field(default_factory=list)
    returned_calls: list[dict[str, Any]] = field(default_factory=list)

    async def hold_started(self, **kwargs: Any) -> None:
        self.started_calls.append(kwargs)

    async def hold_reclaimed(self, **kwargs: Any) -> None:
        self.reclaimed_calls.append(kwargs)

    async def hold_reminder(self, **kwargs: Any) -> None:
        self.reminder_calls.append(kwargs)

    async def enrollment_dropped(self, **kwargs: Any) -> None:
        self.dropped_calls.append(kwargs)

    async def enrollment_returned(self, **kwargs: Any) -> None:
        self.returned_calls.append(kwargs)


@dataclass
class FakeEnrollmentEvents:
    rows: list[Any] = field(default_factory=list)

    async def record(self, event: Any) -> None:
        self.rows.append(event)

    async def list_for_enrollment(self, enrollment_id: str) -> list[Any]:
        return [e for e in self.rows if e.enrollment_id == enrollment_id]

    async def list_in_range(
        self, *, start: datetime, end: datetime, event_types: frozenset[str]
    ) -> list[Any]:
        """Issue #698's leaving report read. Mirrors the real Mongo repo's
        range-scan filter."""
        return [
            e for e in self.rows if e.event_type in event_types and start <= e.occurred_at < end
        ]


@dataclass
class FakeHoldNoticeSendRepo:
    """Real claim rule, not an append: dedupe on
    ``(academy_id, enrollment_id, notice_key)``; sent/skipped never
    re-claimable."""

    sends: dict[tuple[str, str, str], dict[str, Any]] = field(default_factory=dict)
    max_attempts: int = 3

    async def try_claim(
        self, *, academy_id: str, enrollment_id: str, notice_key: str
    ) -> dict[str, Any] | None:
        key = (academy_id, enrollment_id, notice_key)
        existing = self.sends.get(key)
        if existing is None:
            row = {"send_id": f"send-{len(self.sends) + 1}", "status": "queued", "attempts": 1}
            self.sends[key] = row
            return dict(row)
        if existing["status"] in {"sent", "skipped"}:
            return None
        if existing.get("retryable") is False:
            return None
        if existing["status"] == "failed" and existing["attempts"] < self.max_attempts:
            existing["status"] = "queued"
            existing["attempts"] += 1
            return dict(existing)
        return None

    async def mark_sent(self, send_id: str) -> None:
        for row in self.sends.values():
            if row["send_id"] == send_id:
                row["status"] = "sent"

    async def mark_failed(self, send_id: str, reason: str, *, retryable: bool = True) -> None:
        for row in self.sends.values():
            if row["send_id"] == send_id:
                row["status"] = "failed"
                row["retryable"] = retryable
