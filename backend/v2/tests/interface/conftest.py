"""Interface-test fixtures.

Builds a FastAPI app with the coach router and an in-memory test
composition so we never spin up Mongo. Auth is injected via FastAPI's
dependency override.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.v2.contexts.coaching.application.ports import OccurrenceDetails
from backend.v2.contexts.coaching.application.use_cases.mark_attendance import MarkAttendance
from backend.v2.contexts.coaching.application.use_cases.session_notes import (
    CreateLessonPlan,
    CreateProgressNote,
    ListLessonPlans,
    ListProgressNotes,
)
from backend.v2.contexts.enrollment.application.use_cases.get_session_roster import (
    GetSessionRoster,
)
from backend.v2.contexts.enrollment.application.use_cases.list_coach_sessions_for_date import (
    ListCoachSessionsForDate,
)
from backend.v2.contexts.enrollment.domain.models import Enrollment, Session, Student
from backend.v2.interfaces.coach.deps import CoachUseCases, get_coach_use_cases
from backend.v2.interfaces.coach.router import router as coach_router
from backend.v2.shared.auth.claims import AuthClaims, get_auth_claims
from backend.v2.shared.http import register_exception_handlers

# --- in-memory fakes ---


class FakeSessionQuery:
    def __init__(self, sessions: list[Session]) -> None:
        self._sessions = sessions

    async def for_coach_on_date(self, coach_id: str, on_date: date) -> list[Session]:
        return [
            s for s in self._sessions if s.coach_id == coach_id and s.start_at.date() == on_date
        ]

    async def get(self, session_id: str) -> Session | None:
        for s in self._sessions:
            if s.session_id == session_id:
                return s
        return None


class FakeEnrollmentQuery:
    def __init__(self, enrollments: list[Enrollment]) -> None:
        self._enrollments = enrollments

    async def active_for_session(self, session_id: str) -> list[Enrollment]:
        return [e for e in self._enrollments if e.session_id == session_id and e.status == "active"]

    async def is_active(self, session_id: str, student_id: str) -> bool:
        return any(
            e.session_id == session_id and e.student_id == student_id and e.status == "active"
            for e in self._enrollments
        )


class FakeStudentQuery:
    def __init__(self, students: list[Student]) -> None:
        self._by_id = {s.student_id: s for s in students}

    async def by_ids(self, student_ids: list[str]) -> list[Student]:
        return [self._by_id[s] for s in student_ids if s in self._by_id]


class FakeAttendanceRepo:
    def __init__(self) -> None:
        self.saved: list = []

    async def save(self, attendance) -> None:
        self.saved.append(attendance)

    async def find_existing(self, occurrence_id, student_id):
        for a in self.saved:
            if a.occurrence_id == occurrence_id and a.student_id == student_id:
                return a
        return None

    async def find_by_attendance_id(self, attendance_id):
        for a in self.saved:
            if a.attendance_id == attendance_id:
                return a
        return None


class FakeCoachingNotesRepo:
    def __init__(self) -> None:
        self.plans: list = []
        self.notes: list = []

    async def add_lesson_plan(self, plan):
        self.plans.append(plan)

    async def list_lesson_plans(self, session_id, coach_id):
        return [p for p in self.plans if p.session_id == session_id and p.coach_id == coach_id]

    async def add_progress_note(self, note):
        self.notes.append(note)

    async def list_progress_notes(self, session_id, coach_id):
        return [n for n in self.notes if n.session_id == session_id and n.coach_id == coach_id]

    async def find_by_attendance_id(self, attendance_id):
        for a in self.saved:
            if a.attendance_id == attendance_id:
                return a
        return None


class FakeOutbox:
    def __init__(self) -> None:
        self.appended: list = []

    async def append(self, event, *, session=None) -> None:
        self.appended.append(event)

    async def pull_unprocessed(self, limit: int = 100):
        return []

    async def mark_processed(self, event_id: str) -> None:
        pass


class FakeIdempotencyStore:
    def __init__(self) -> None:
        self.data: dict = {}

    async def get(self, key: str):
        return self.data.get(key)

    async def put(self, key: str, value) -> None:
        self.data[key] = value


# --- seed data ---


def _now() -> datetime:
    return datetime(2026, 5, 16, 9, 0, tzinfo=UTC)


@pytest.fixture()
def seed():
    sessions = [
        Session(
            session_id="s-today-1",
            academy_id="test-academy",
            coach_id="coach-1",
            title="Junior A",
            location="Court 1",
            start_at=datetime(2026, 5, 16, 9, 0, tzinfo=UTC),
            end_at=datetime(2026, 5, 16, 10, 30, tzinfo=UTC),
            capacity=8,
            status="scheduled",
        ),
        Session(
            session_id="s-today-2",
            academy_id="test-academy",
            coach_id="coach-1",
            title="Adult B",
            location="Court 2",
            start_at=datetime(2026, 5, 16, 18, 0, tzinfo=UTC),
            end_at=datetime(2026, 5, 16, 19, 30, tzinfo=UTC),
            capacity=10,
            status="scheduled",
        ),
        Session(
            session_id="s-other-coach",
            academy_id="test-academy",
            coach_id="coach-2",
            title="Not mine",
            location="Court 3",
            start_at=datetime(2026, 5, 16, 12, 0, tzinfo=UTC),
            end_at=datetime(2026, 5, 16, 13, 0, tzinfo=UTC),
            capacity=4,
            status="scheduled",
        ),
    ]
    enrollments = [
        Enrollment(
            enrollment_id="e1",
            academy_id="test-academy",
            session_id="s-today-1",
            student_id="st1",
            status="active",
        ),
        Enrollment(
            enrollment_id="e2",
            academy_id="test-academy",
            session_id="s-today-1",
            student_id="st2",
            status="active",
        ),
    ]
    students = [
        Student(student_id="st1", academy_id="test-academy", parent_id="p1", full_name="Alice"),
        Student(student_id="st2", academy_id="test-academy", parent_id="p2", full_name="Bob"),
    ]
    return {
        "sessions": sessions,
        "enrollments": enrollments,
        "students": students,
    }


def _coach_claims() -> AuthClaims:
    return AuthClaims(
        user_id="coach-1",
        email="coach1@example.com",
        academy_id="test-academy",
        roles=("coach",),
    )


def _parent_claims() -> AuthClaims:
    return AuthClaims(
        user_id="p1",
        email="parent@example.com",
        academy_id="test-academy",
        roles=("parent",),
    )


def _admin_claims() -> AuthClaims:
    return AuthClaims(
        user_id="adm",
        email="admin@example.com",
        academy_id="test-academy",
        roles=("admin",),
    )


def _build_use_cases(seed_data) -> CoachUseCases:
    sessions = FakeSessionQuery(seed_data["sessions"])
    enrollments = FakeEnrollmentQuery(seed_data["enrollments"])
    students = FakeStudentQuery(seed_data["students"])

    # Adapters wiring coach lookups to enrollment queries.
    class _SL:
        async def is_coach_assigned(self, coach_id, sid, on_date=None):
            s = await sessions.get(sid)
            if s is None or s.coach_id != coach_id:
                return False
            return on_date is None or s.start_at.date() == on_date

        async def is_cancelled(self, sid):
            s = await sessions.get(sid)
            return s is not None and s.status == "cancelled"

        async def session_date(self, sid):
            s = await sessions.get(sid)
            return s.start_at.date() if s else None

    class _OL:
        async def get(self, occurrence_id):
            session_id = occurrence_id.split(":", 1)[0]
            s = await sessions.get(session_id)
            if s is None:
                return None
            return OccurrenceDetails(
                occurrence_id=occurrence_id,
                session_id=s.session_id,
                starts_at=s.start_at,
                status=s.status,
                scheduled_coach_id=s.coach_id,
            )

    class _EL:
        async def is_active(self, sid, student_id):
            return await enrollments.is_active(sid, student_id)

    async def _dashboard(_coach_id):
        return {
            "active_student_count": 2,
            "sessions_today": 2,
            "attendance_percentage": 0.0,
            "expected_cut_cents": 0,
            "marked_attendance_count": 0,
        }

    notes = FakeCoachingNotesRepo()
    session_lookup = _SL()
    return CoachUseCases(
        list_today=ListCoachSessionsForDate(sessions=sessions),
        get_roster=GetSessionRoster(enrollments=enrollments, students=students),
        mark_attendance=MarkAttendance(
            attendance_repo=FakeAttendanceRepo(),
            occurrence_lookup=_OL(),
            enrollment_lookup=_EL(),
            outbox=FakeOutbox(),
            idempotency_store=FakeIdempotencyStore(),
            academy_id="test-academy",
            clock=_now,
        ),
        get_dashboard_metrics=_dashboard,
        create_lesson_plan=CreateLessonPlan(notes=notes, sessions=session_lookup),
        list_lesson_plans=ListLessonPlans(notes=notes, sessions=session_lookup),
        create_progress_note=CreateProgressNote(
            notes=notes,
            sessions=session_lookup,
            enrollments=enrollments,
        ),
        list_progress_notes=ListProgressNotes(notes=notes, sessions=session_lookup),
    )


def _make_app(claims: AuthClaims, use_cases: CoachUseCases) -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(coach_router, prefix="/api/v2")

    async def _override_claims():
        return claims

    def _override_use_cases():
        return use_cases

    app.dependency_overrides[get_auth_claims] = _override_claims
    app.dependency_overrides[get_coach_use_cases] = _override_use_cases
    return app


@pytest.fixture()
def coach_client(seed) -> Iterator[TestClient]:
    use_cases = _build_use_cases(seed)
    app = _make_app(_coach_claims(), use_cases)
    with TestClient(app) as client:
        client.coach_use_cases = use_cases  # type: ignore[attr-defined]
        yield client


@pytest.fixture()
def parent_client(seed) -> Iterator[TestClient]:
    """Same routes mounted, but token represents a parent — wrong persona."""
    use_cases = _build_use_cases(seed)
    app = _make_app(_parent_claims(), use_cases)
    with TestClient(app) as client:
        yield client


@pytest.fixture()
def admin_client(seed) -> Iterator[TestClient]:
    use_cases = _build_use_cases(seed)
    app = _make_app(_admin_claims(), use_cases)
    with TestClient(app) as client:
        yield client


@pytest.fixture()
def anon_client(seed) -> Iterator[TestClient]:
    """No auth claims; the dependency raises 401."""
    use_cases = _build_use_cases(seed)
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(coach_router, prefix="/api/v2")
    app.dependency_overrides[get_coach_use_cases] = lambda: use_cases
    # Do NOT override get_auth_claims; the default raises 401.
    with TestClient(app) as client:
        yield client


# ====================================================================
# Admin BFF fixtures (Wave 3)
# ====================================================================


from dataclasses import dataclass, field
from typing import Any

import pytest

from backend.v2.contexts.billing.application.use_cases.admin_payment_ops import (
    ApplyPaymentDiscount,
    GenerateMonthlyPayments,
    GenerateMonthlyPaymentsResult,
    MarkPaymentPaid,
    UndoPaymentPaid,
)
from backend.v2.contexts.billing.application.use_cases.finance import (
    AcademyRevenueQuery,
    Expense,
    Payout,
    RecordExpense,
)
from backend.v2.contexts.billing.application.use_cases.issue_refund import IssueRefund
from backend.v2.contexts.billing.application.use_cases.withdrawal_credit import (
    ApproveWithdrawalCreditResult,
    WithdrawalCreditPreviewResult,
)
from backend.v2.contexts.billing.domain.errors import (
    PaymentNotFound,
    PaymentOperationNotAllowed,
)
from backend.v2.contexts.billing.domain.models import Payment
from backend.v2.contexts.billing.domain.proration import BillingCalculationSnapshot
from backend.v2.contexts.billing.infrastructure.fake_stripe_gateway import (
    FakeStripeGateway,
)
from backend.v2.contexts.enrollment.application.use_cases.admin_directory import (
    AdminStudentPage,
    AdminStudentSummary,
    decode_student_cursor,
    encode_student_cursor,
    full_name_key,
)
from backend.v2.contexts.enrollment.application.use_cases.admin_writes import (
    CancelEnrollment,
    CancelSession,
    CreateSession,
    EditRosterAdd,
    JoinWaitlist,
    PauseEnrollment,
    RemoveFromWaitlist,
    ResumeEnrollment,
    SkipFromWaitlist,
    TransferEnrollment,
)
from backend.v2.contexts.enrollment.application.use_cases.pause_requests import (
    ApprovePauseRequest,
    DeclinePauseRequest,
    ListAdminPauseRequests,
    PauseRequest,
)
from backend.v2.contexts.enrollment.application.use_cases.promote_from_waitlist import (
    PromoteFromWaitlist,
)
from backend.v2.contexts.enrollment.domain.models_extra import WaitlistEntry
from backend.v2.contexts.identity.application.use_cases.admin_directory import (
    AdminUserSummary,
)
from backend.v2.contexts.onboarding.application.use_cases.admin_waivers import (
    AdminWaiverReport,
    AdminWaiverSummary,
)
from backend.v2.interfaces.admin.deps import AdminUseCases, get_admin_use_cases
from backend.v2.interfaces.admin.router import router as admin_router
from backend.v2.shared.comms import CommsService, Message

# --- in-memory port fakes ---


@dataclass
class _AdminFakeOutbox:
    events: list[Any] = field(default_factory=list)

    async def append(self, event, *, session=None):
        self.events.append(event)

    async def pull_unprocessed(self, limit=100):
        return []

    async def mark_processed(self, _):
        pass


@dataclass
class _AdminFakeIdempotencyStore:
    data: dict[str, Any] = field(default_factory=dict)

    async def get(self, key):
        return self.data.get(key)

    async def put(self, key, value):
        self.data[key] = value


@dataclass
class FakeSessionWriter:
    """Implements SessionWriter + minimal SessionQuery for the admin reads."""

    sessions: dict[str, Session] = field(default_factory=dict)
    reserved: dict[str, int] = field(default_factory=dict)

    async def try_reserve_seat(self, session_id):
        s = self.sessions.get(session_id)
        if s is None or s.status != "scheduled":
            return False
        if self.reserved.get(session_id, 0) >= s.capacity:
            return False
        self.reserved[session_id] = self.reserved.get(session_id, 0) + 1
        return True

    async def release_seat(self, session_id):
        self.reserved[session_id] = max(0, self.reserved.get(session_id, 0) - 1)

    async def update_status(self, session_id, status):
        s = self.sessions[session_id]
        self.sessions[session_id] = s.model_copy(update={"status": status})

    async def create(self, session):
        self.sessions[session.session_id] = session

    async def update(self, session):
        self.sessions[session.session_id] = session


@dataclass
class FakeEnrollmentWriter:
    rows: dict[str, Any] = field(default_factory=dict)
    move_history: list[dict[str, str]] = field(default_factory=list)

    async def create(self, enrollment):
        self.rows[enrollment.enrollment_id] = enrollment

    async def update_status(self, enrollment_id, status):
        e = self.rows.get(enrollment_id)
        if e is not None:
            self.rows[enrollment_id] = e.model_copy(update={"status": status})

    async def update_session(self, enrollment_id, session_id):
        e = self.rows.get(enrollment_id)
        if e is not None:
            self.move_history.append(
                {
                    "enrollment_id": enrollment_id,
                    "from_session_id": e.session_id,
                    "to_session_id": session_id,
                }
            )
            self.rows[enrollment_id] = e.model_copy(update={"session_id": session_id})

    async def get(self, enrollment_id):
        return self.rows.get(enrollment_id)


@dataclass
class _AdminFakeEnrollmentQuery:
    rows: dict[str, Any] = field(default_factory=dict)

    async def active_for_session(self, session_id):
        return [
            e for e in self.rows.values() if e.session_id == session_id and e.status == "active"
        ]

    async def is_active(self, session_id, student_id):
        return any(
            e.session_id == session_id and e.student_id == student_id and e.status == "active"
            for e in self.rows.values()
        )


@dataclass
class FakeStudentWriter:
    students: dict[str, Any] = field(default_factory=dict)
    admin_status: dict[str, str] = field(default_factory=dict)

    async def upsert(self, student):
        self.students[student.student_id] = student


@dataclass
class FakeWaitlistRepo:
    entries: dict[str, WaitlistEntry] = field(default_factory=dict)

    async def add(self, entry):
        self.entries[entry.waitlist_id] = entry

    async def next_waiting(self, session_id):
        waiting = sorted(
            (
                e
                for e in self.entries.values()
                if e.session_id == session_id and e.status == "waiting"
            ),
            key=lambda e: e.joined_at,
        )
        return waiting[0] if waiting else None

    async def update_status(self, waitlist_id, status):
        e = self.entries.get(waitlist_id)
        if e is not None:
            self.entries[waitlist_id] = e.model_copy(update={"status": status})


@dataclass
class FakePauseRequestRepo:
    rows: dict[str, PauseRequest] = field(default_factory=dict)

    async def add(self, request):
        self.rows[request.pause_request_id] = request

    async def get(self, pause_request_id):
        return self.rows.get(pause_request_id)

    async def list_for_parent(self, parent_id):
        return [r for r in self.rows.values() if r.parent_id == parent_id]

    async def list_pending(self):
        return [r for r in self.rows.values() if r.status == "pending"]

    async def approve(self, pause_request_id, *, admin_id):
        row = self.rows[pause_request_id].model_copy(
            update={"status": "approved", "decided_by": admin_id}
        )
        self.rows[pause_request_id] = row
        return row

    async def decline(self, pause_request_id, *, admin_id):
        row = self.rows[pause_request_id].model_copy(
            update={"status": "declined", "decided_by": admin_id}
        )
        self.rows[pause_request_id] = row
        return row

    async def enrollment_belongs_to_parent(self, _enrollment_id, _parent_id):
        return True


@dataclass
class FakePaymentRepo:
    rows: dict[str, Payment] = field(default_factory=dict)
    discounts: dict[str, int] = field(default_factory=dict)
    generated_periods: list[str] = field(default_factory=list)

    async def save(self, p):
        self.rows[p.payment_id] = p

    async def get(self, payment_id):
        return self.rows.get(payment_id)

    async def get_by_stripe_pi(self, _):
        return None

    async def get_by_checkout_session(self, _):
        return None

    async def list_for_parent(self, parent_id):
        return [p for p in self.rows.values() if p.parent_id == parent_id]

    async def list_all(self):
        return list(self.rows.values())

    async def generate_monthly_payments(self, period):
        self.generated_periods.append(period)
        return GenerateMonthlyPaymentsResult(created=1, skipped_existing=0)

    async def mark_payment_paid(self, payment_id, *, payment_method, notes):
        p = self.rows.get(payment_id)
        if p is None:
            raise PaymentNotFound("no such payment", payment_id=payment_id)
        if p.status not in ("pending", "failed"):
            raise PaymentOperationNotAllowed("only pending payments can be marked paid")
        self.rows[payment_id] = p.model_copy(update={"status": "succeeded"})

    async def apply_payment_discount(self, payment_id, discount_cents):
        p = self.rows.get(payment_id)
        if p is None:
            raise PaymentNotFound("no such payment", payment_id=payment_id)
        if p.status != "pending":
            raise PaymentOperationNotAllowed("only pending payments can be discounted")
        if discount_cents > p.amount_cents:
            raise PaymentOperationNotAllowed("discount cannot exceed payment amount")
        self.discounts[payment_id] = discount_cents

    async def undo_payment_paid(self, payment_id):
        p = self.rows.get(payment_id)
        if p is None:
            raise PaymentNotFound("no such payment", payment_id=payment_id)
        if p.stripe_payment_intent_id:
            raise PaymentOperationNotAllowed("Stripe-linked payments must be refunded")
        if p.status != "succeeded":
            raise PaymentOperationNotAllowed("only paid payments can be undone")
        self.rows[payment_id] = p.model_copy(update={"status": "pending"})


class _FakePreviewWithdrawalCredit:
    async def execute(self, cmd):
        _ = cmd
        return WithdrawalCreditPreviewResult(
            credit_amount_cents=3750,
            paid_tuition_cents=10_000,
            refunded_tuition_cents=0,
            net_paid_tuition_cents=10_000,
            unused_eligible_classes=3,
            paid_period_eligible_classes=8,
            formula="max(10000 - 0, 0) * 3 / 8",
        )


class _FakeApproveWithdrawalCredit:
    async def execute(self, cmd):
        _ = cmd
        return ApproveWithdrawalCreditResult(
            status="APPROVED",
            credit_amount_cents=3750,
            credit_balance_cents=3750,
            credit_id="credit-1",
        )


@dataclass
class FakeExpenseRepo:
    rows: dict[str, Expense] = field(default_factory=dict)

    async def add(self, e):
        self.rows[e.expense_id] = e

    async def list_recent(self, limit: int = 200):
        return sorted(self.rows.values(), key=lambda e: e.incurred_on, reverse=True)[:limit]


@dataclass
class FakePayoutRepo:
    rows: dict[str, Payout] = field(default_factory=dict)

    async def list_all(self):
        return sorted(self.rows.values(), key=lambda p: p.period_start, reverse=True)

    async def list_for_coach(self, coach_id):
        return [p for p in self.rows.values() if p.coach_id == coach_id]


@dataclass
class FakeMessageRepo:
    rows: dict[str, Message] = field(default_factory=dict)

    async def insert(self, m):
        self.rows[m.message_id] = m

    async def for_recipient(self, recipient_id):
        return sorted(
            (
                m
                for m in self.rows.values()
                if m.recipient_id == recipient_id or m.kind == "announcement"
            ),
            key=lambda m: m.created_at,
            reverse=True,
        )

    async def list_announcements(self):
        return [m for m in self.rows.values() if m.kind == "announcement"]


@dataclass
class FakeAdminWaivers:
    report: AdminWaiverReport = field(
        default_factory=lambda: AdminWaiverReport(
            summary=AdminWaiverSummary(
                total_students=0,
                signed_count=0,
                current_count=0,
                pending_count=0,
                outdated_count=0,
            ),
            active_waiver=None,
            rows=[],
        )
    )

    async def execute(self) -> AdminWaiverReport:
        return self.report


# --- seed data ---


def _now() -> datetime:
    return datetime(2026, 5, 16, 9, 0, tzinfo=UTC)


@pytest.fixture
def admin_seed():
    sessions = FakeSessionWriter()
    sessions.sessions["sess-1"] = Session(
        session_id="sess-1",
        academy_id="acad",
        coach_id="coach-1",
        title="Junior A",
        location="Court 1",
        start_at=datetime(2026, 5, 16, 9, 0, tzinfo=UTC),
        end_at=datetime(2026, 5, 16, 10, 30, tzinfo=UTC),
        capacity=8,
        status="scheduled",
    )
    return {
        "sessions": sessions,
        "enrollments": FakeEnrollmentWriter(),
        "enrollment_query": _AdminFakeEnrollmentQuery(),
        "students": FakeStudentWriter(),
        "waitlist": FakeWaitlistRepo(),
        "pause_requests": FakePauseRequestRepo(),
        "payments": FakePaymentRepo(),
        "expenses": FakeExpenseRepo(),
        "payouts": FakePayoutRepo(),
        "messages": FakeMessageRepo(),
        "waivers": FakeAdminWaivers(),
        "outbox": _AdminFakeOutbox(),
        "idempotency": _AdminFakeIdempotencyStore(),
        "stripe": FakeStripeGateway(),
    }


def _build_admin_use_cases(seed) -> AdminUseCases:
    sessions = seed["sessions"]
    enrollments_w = seed["enrollments"]
    enrollments_q = seed["enrollment_query"]
    students = seed["students"]
    waitlist = seed["waitlist"]
    pause_requests = seed["pause_requests"]
    payments = seed["payments"]
    outbox = seed["outbox"]
    idem = seed["idempotency"]
    stripe = seed["stripe"]
    expenses = seed["expenses"]
    payouts = seed["payouts"]
    messages = seed["messages"]
    waivers = seed["waivers"]
    comms = CommsService(messages=messages, academy_id="acad")  # type: ignore[arg-type]

    create_session = CreateSession(sessions=sessions, academy_id="acad")
    cancel_session = CancelSession(
        sessions=sessions,
        enrollments_query=enrollments_q,
        enrollments_writer=enrollments_w,
        outbox=outbox,
        academy_id="acad",
    )
    edit_roster_add = EditRosterAdd(
        sessions=sessions,
        enrollments=enrollments_w,
        students=students,
        academy_id="acad",
    )
    cancel_enrollment = CancelEnrollment(
        enrollments=enrollments_w,
        sessions=sessions,
        outbox=outbox,
        academy_id="acad",
    )
    transfer_enrollment = TransferEnrollment(enrollments=enrollments_w, sessions=sessions)
    pause_enrollment = PauseEnrollment(enrollments=enrollments_w)
    resume_enrollment = ResumeEnrollment(enrollments=enrollments_w)
    join_waitlist = JoinWaitlist(waitlist=waitlist, academy_id="acad")
    promote = PromoteFromWaitlist(waitlist=waitlist, outbox=outbox, academy_id="acad")
    skip = SkipFromWaitlist(waitlist=waitlist)
    remove = RemoveFromWaitlist(waitlist=waitlist)
    list_admin_pause_requests = ListAdminPauseRequests(pause_requests=pause_requests)
    approve_pause_request = ApprovePauseRequest(pause_requests=pause_requests)
    decline_pause_request = DeclinePauseRequest(pause_requests=pause_requests)
    issue_refund = IssueRefund(
        payment_repo=payments, stripe=stripe, outbox=outbox, idempotency_store=idem
    )
    generate_monthly_payments = GenerateMonthlyPayments(payments=payments)
    mark_payment_paid = MarkPaymentPaid(payments=payments)
    apply_payment_discount = ApplyPaymentDiscount(payments=payments)
    undo_payment_paid = UndoPaymentPaid(payments=payments)
    record_expense = RecordExpense(expenses=expenses, academy_id="acad")  # type: ignore[arg-type]
    revenue_query = AcademyRevenueQuery(payments=payments)

    async def list_admin_sessions(on_date, *, window=None):
        if window == "upcoming":
            today = _now().date()
            return [s for s in sessions.sessions.values() if s.start_at.date() >= today]
        if on_date is None:
            on_date = _now().date()
        return [s for s in sessions.sessions.values() if s.start_at.date() == on_date]

    async def list_admin_enrollments_for_session(session_id):
        active = await enrollments_q.active_for_session(session_id)
        out = []
        for e in active:
            st = students.students.get(e.student_id)
            out.append(
                {
                    "enrollment_id": e.enrollment_id,
                    "session_id": e.session_id,
                    "student_id": e.student_id,
                    "student_name": st.full_name if st else "(unknown)",
                    "parent_id": st.parent_id if st else "",
                    "status": e.status,
                }
            )
        return out

    async def list_waitlist_for_session(session_id):
        return [e for e in waitlist.entries.values() if e.session_id == session_id]

    async def list_payments_recent():
        return list(payments.rows.values())

    async def quote_enrollment(*, session_id, student_id=None, start_date=None):
        _ = (session_id, student_id, start_date)
        return BillingCalculationSnapshot(
            snapshot_id="snap-1",
            monthly_price_cents=10_000,
            billing_period_start=datetime(2026, 5, 1, tzinfo=UTC),
            billing_period_end=datetime(2026, 6, 1, tzinfo=UTC),
            billing_period_label="2026-05",
            timezone="America/Chicago",
            total_eligible_classes=8,
            billable_remaining_classes=3,
            proration_ratio="3/8",
            final_amount_cents=3_750,
            included_occurrence_ids=["class-6", "class-7", "class-8"],
            excluded_occurrences={"class-1": "ELAPSED_BEFORE_ENROLLMENT"},
            calculated_at=datetime(2026, 5, 16, tzinfo=UTC),
            calculated_by="admin",
        )

    async def list_audit_logs():
        return []

    async def list_dues_followup():
        return []

    async def send_dues_reminders():
        return {"sent": 0, "blocked": True, "reason": "test safety block"}

    async def export_report_csv(report_name):
        return f"name\n{report_name}\n"

    class _ListAdminUsers:
        async def execute(self, role=None, academy_id=None):
            _ = academy_id
            users = [
                AdminUserSummary(
                    user_id="coach-1",
                    email="coach@example.com",
                    display_name="Coach One",
                    role="coach",
                    status="active",
                ),
                AdminUserSummary(
                    user_id="p-1",
                    email="parent@example.com",
                    display_name="Parent One",
                    role="parent",
                    status="active",
                ),
                AdminUserSummary(
                    user_id="adm",
                    email="admin@example.com",
                    display_name="Admin One",
                    role="admin",
                    status="active",
                ),
            ]
            return [u for u in users if role is None or u.role == role]

    class _ListAdminStudents:
        async def execute(self, search=None, status=None, limit=50, cursor=None):
            rows = []
            search_key = full_name_key(search or "") if search else None
            for s in students.students.values():
                row_status = students.admin_status.get(s.student_id, "active")
                if status and row_status != status:
                    continue
                parent_name = "Parent One" if s.parent_id == "p-1" else None
                parent_email = "parent@example.com" if s.parent_id == "p-1" else None
                haystack = " ".join(
                    full_name_key(value)
                    for value in (s.full_name, parent_name or "", parent_email or "")
                )
                if search_key and search_key not in haystack:
                    continue
                rows.append(
                    {
                        "summary": AdminStudentSummary(
                            student_id=s.student_id,
                            full_name=s.full_name,
                            parent_id=s.parent_id,
                            parent_name=parent_name,
                            parent_email=parent_email,
                            status=row_status,
                            active_session_count=1,
                            attendance_rate=None,
                            dues_status="current",
                        ),
                        "full_name_key": full_name_key(s.full_name),
                    }
                )
            rows.sort(key=lambda row: (row["full_name_key"], row["summary"].student_id))
            if cursor:
                decoded = decode_student_cursor(cursor)
                rows = [
                    row
                    for row in rows
                    if (row["full_name_key"], row["summary"].student_id)
                    > (decoded.full_name_key, decoded.student_id)
                ]
            page_rows = rows[: limit + 1]
            has_next = len(page_rows) > limit
            page_rows = page_rows[:limit]
            next_cursor = None
            if has_next and page_rows:
                last = page_rows[-1]
                next_cursor = encode_student_cursor(
                    last["full_name_key"],
                    last["summary"].student_id,
                )
            return AdminStudentPage(
                students=[row["summary"] for row in page_rows],
                next_cursor=next_cursor,
            )

    return AdminUseCases(
        list_admin_users=_ListAdminUsers(),  # type: ignore[arg-type]
        list_admin_students=_ListAdminStudents(),  # type: ignore[arg-type]
        create_session=create_session,
        cancel_session=cancel_session,
        edit_roster_add=edit_roster_add,
        cancel_enrollment=cancel_enrollment,
        transfer_enrollment=transfer_enrollment,
        pause_enrollment=pause_enrollment,
        resume_enrollment=resume_enrollment,
        join_waitlist=join_waitlist,
        promote_from_waitlist=promote,
        skip_from_waitlist=skip,
        remove_from_waitlist=remove,
        list_admin_pause_requests=list_admin_pause_requests,
        approve_pause_request=approve_pause_request,
        decline_pause_request=decline_pause_request,
        issue_refund=issue_refund,
        quote_enrollment=quote_enrollment,
        preview_withdrawal_credit=_FakePreviewWithdrawalCredit(),  # type: ignore[arg-type]
        approve_withdrawal_credit=_FakeApproveWithdrawalCredit(),  # type: ignore[arg-type]
        list_payments_recent=list_payments_recent,
        generate_monthly_payments=generate_monthly_payments,
        mark_payment_paid=mark_payment_paid,
        apply_payment_discount=apply_payment_discount,
        undo_payment_paid=undo_payment_paid,
        record_expense=record_expense,
        expenses=expenses,  # type: ignore[arg-type]
        payouts=payouts,  # type: ignore[arg-type]
        revenue_query=revenue_query,
        list_admin_sessions=list_admin_sessions,
        list_admin_enrollments_for_session=list_admin_enrollments_for_session,
        list_waitlist_for_session=list_waitlist_for_session,
        list_audit_logs=list_audit_logs,
        list_dues_followup=list_dues_followup,
        send_dues_reminders=send_dues_reminders,
        export_report_csv=export_report_csv,
        get_reports_kpis=AsyncMock(return_value={"active_students": 0, "attendance_rate_30d": 0.0, "dues_collected_mtd_cents": 0, "pending_waivers": 0}),
        list_enrollment_events=AsyncMock(return_value=[]),
        list_billing_invoices=AsyncMock(return_value=[]),
        comms=comms,
        list_admin_waivers=waivers,  # type: ignore[arg-type]
        get_academy_use_case=AsyncMock(),
        update_academy_use_case=AsyncMock(),
        get_academy_fees_use_case=AsyncMock(),
        update_academy_fees_use_case=AsyncMock(),
        get_academy_notifications_use_case=AsyncMock(),
        update_academy_notifications_use_case=AsyncMock(),
        get_academy_gateway_use_case=AsyncMock(),
        change_user_role=AsyncMock(),
    )


def _claims(role: str) -> AuthClaims:
    return AuthClaims(
        user_id=f"u-{role}",
        email=f"{role}@example.com",
        academy_id="acad",
        roles=(role,),  # type: ignore[arg-type]
    )


def _make_admin_app(claims: AuthClaims, use_cases: AdminUseCases) -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(admin_router, prefix="/api/v2")
    app.dependency_overrides[get_auth_claims] = lambda: claims
    app.dependency_overrides[get_admin_use_cases] = lambda: use_cases
    return app


@pytest.fixture
def admin_client(admin_seed) -> Iterator[TestClient]:  # noqa: F811
    uc = _build_admin_use_cases(admin_seed)
    app = _make_admin_app(_claims("admin"), uc)
    with TestClient(app) as client:
        client.seed = admin_seed  # type: ignore[attr-defined]
        client.use_cases = uc  # type: ignore[attr-defined]
        yield client


@pytest.fixture
def coach_on_admin_client(admin_seed) -> Iterator[TestClient]:
    """Coach token hitting admin routes → must 404."""
    uc = _build_admin_use_cases(admin_seed)
    app = _make_admin_app(_claims("coach"), uc)
    with TestClient(app) as client:
        yield client


@pytest.fixture
def parent_on_admin_client(admin_seed) -> Iterator[TestClient]:
    """Parent token hitting admin routes → must 404."""
    uc = _build_admin_use_cases(admin_seed)
    app = _make_admin_app(_claims("parent"), uc)
    with TestClient(app) as client:
        yield client
