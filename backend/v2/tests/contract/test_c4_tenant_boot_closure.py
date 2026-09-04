"""C4 — boot-time academy_id closures are gone (parent reads + coach/parent writes).

Three guarantees per converted path, with boot academy A and request academy B:

- Writes land in B: use cases stamp the ContextVar tenant at execute time.
- Reads return only B rows: parent inline reads re-resolve per request.
- No-context fallback: without a tenant scope, composition providers fall
  back to the boot academy so single-academy / outbox callers are unchanged.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from backend.v2.contexts.coaching.application.use_cases.bulk_mark_attendance import (
    BulkAttendanceEntry,
    BulkMarkAttendance,
    BulkMarkAttendanceCommand,
)
from backend.v2.contexts.coaching.application.use_cases.mark_attendance import (
    MarkAttendance,
    MarkAttendanceCommand,
)
from backend.v2.contexts.enrollment.application.use_cases.coach_roster_writes import (
    CoachAddStudentToRoster,
    CoachAddStudentToRosterCommand,
)
from backend.v2.contexts.enrollment.application.use_cases.confirm_enrollment import (
    ConfirmEnrollment,
    ConfirmEnrollmentCommand,
)
from backend.v2.contexts.enrollment.application.use_cases.promote_from_waitlist import (
    PromoteFromWaitlist,
)
from backend.v2.contexts.enrollment.domain.models_extra import WaitlistEntry
from backend.v2.contexts.onboarding.application.use_cases.admin_waiver_templates import (
    AdminWaiverTemplateRecord,
)
from backend.v2.contexts.onboarding.application.use_cases.manage_application import (
    StartApplication,
    StartApplicationCommand,
)
from backend.v2.contexts.onboarding.application.use_cases.parent_student_waivers import (
    AcceptParentWaiver,
    ParentWaiverStudent,
)
from backend.v2.shared.tenancy import TenantContextUnset, current_academy_id, tenant_scope

BOOT = "academy-a"
REQUEST = "academy-b"
FIXED_NOW = datetime(2026, 7, 20, 9, 30, tzinfo=UTC)


def _boot_fallback_provider(boot: str = BOOT):
    """Mirror of the composition-level request_academy_id helpers."""

    def _provider() -> str:
        try:
            return current_academy_id()
        except TenantContextUnset:
            return boot

    return _provider


# --- shared fakes -----------------------------------------------------------


class InMemoryIdempotency:
    def __init__(self) -> None:
        self.data: dict[str, dict[str, Any]] = {}

    async def get(self, key: str) -> dict[str, Any] | None:
        return self.data.get(key)

    async def put(self, key: str, value: dict[str, Any]) -> None:
        self.data[key] = value


class FakeOutbox:
    def __init__(self) -> None:
        self.appended: list[Any] = []

    async def append(self, event, *, session=None) -> None:
        self.appended.append(event)


class FakeAttendanceRepo:
    def __init__(self) -> None:
        self.saved: list[Any] = []

    async def save(self, attendance) -> None:
        self.saved.append(attendance)

    async def find_existing(self, occurrence_id: str, student_id: str):
        return None


class FakeOccurrenceLookup:
    async def get(self, occurrence_id: str):
        from backend.v2.contexts.coaching.application.ports import OccurrenceDetails

        return OccurrenceDetails(
            occurrence_id=occurrence_id,
            session_id="sess-1",
            starts_at=FIXED_NOW,
            status="scheduled",
            scheduled_coach_id="coach-1",
            actual_coach_id=None,
            substitute_coach_id=None,
        )


class FakeEnrollmentLookup:
    async def is_active(self, session_id: str, student_id: str) -> bool:
        return True


class FakeSessionWriter:
    async def get(self, session_id: str):
        return None

    async def try_reserve_seat(self, session_id: str) -> bool:
        return True


class FakeEnrollmentWriter:
    def __init__(self) -> None:
        self.created: list[Any] = []

    async def create(self, enrollment) -> None:
        self.created.append(enrollment)

    async def find_for_session_student(self, session_id: str, student_id: str):
        return None

    async def update_status(self, enrollment_id: str, status: str) -> None:
        pass


class FakeStudentWriter:
    def __init__(self) -> None:
        self.upserted: list[Any] = []
        self.ensured: list[Any] = []

    async def upsert(self, student) -> None:
        self.upserted.append(student)

    async def ensure_exists(self, student) -> bool:
        self.ensured.append(student)
        return True


class FakeEnrollmentQuery:
    async def count_active_for_session(self, session_id: str) -> int:
        return 0


# --- writes land in the request tenant --------------------------------------


@pytest.mark.asyncio
async def test_mark_attendance_writes_land_in_request_tenant() -> None:
    repo = FakeAttendanceRepo()
    uc = MarkAttendance(
        attendance_repo=repo,
        occurrence_lookup=FakeOccurrenceLookup(),
        enrollment_lookup=FakeEnrollmentLookup(),
        outbox=FakeOutbox(),
        idempotency_store=InMemoryIdempotency(),
        academy_id=_boot_fallback_provider(),
        clock=lambda: FIXED_NOW,
    )
    cmd = MarkAttendanceCommand(
        mutation_id="mut-1",
        occurrence_id="occ-1",
        session_id="sess-1",
        student_id="st-1",
        status="present",
    )
    with tenant_scope(REQUEST):
        await uc.execute(cmd, "coach-1")
    assert repo.saved[0].academy_id == REQUEST


@pytest.mark.asyncio
async def test_mark_attendance_without_context_falls_back_to_boot_academy() -> None:
    repo = FakeAttendanceRepo()
    uc = MarkAttendance(
        attendance_repo=repo,
        occurrence_lookup=FakeOccurrenceLookup(),
        enrollment_lookup=FakeEnrollmentLookup(),
        outbox=FakeOutbox(),
        idempotency_store=InMemoryIdempotency(),
        academy_id=_boot_fallback_provider(),
        clock=lambda: FIXED_NOW,
    )
    cmd = MarkAttendanceCommand(
        mutation_id="mut-2",
        occurrence_id="occ-1",
        session_id="sess-1",
        student_id="st-1",
        status="present",
    )
    await uc.execute(cmd, "coach-1")
    assert repo.saved[0].academy_id == BOOT


@pytest.mark.asyncio
async def test_bulk_mark_attendance_writes_land_in_request_tenant() -> None:
    repo = FakeAttendanceRepo()
    uc = BulkMarkAttendance(
        attendance_repo=repo,
        occurrence_lookup=FakeOccurrenceLookup(),
        enrollment_lookup=FakeEnrollmentLookup(),
        outbox=FakeOutbox(),
        idempotency_store=InMemoryIdempotency(),
        academy_id=_boot_fallback_provider(),
        clock=lambda: FIXED_NOW,
    )
    cmd = BulkMarkAttendanceCommand(
        mutation_id="bulk-1",
        occurrence_id="occ-1",
        session_id="sess-1",
        entries=[
            BulkAttendanceEntry(student_id="st-1", status="present"),
            BulkAttendanceEntry(student_id="st-2", status="absent"),
        ],
    )
    with tenant_scope(REQUEST):
        await uc.execute(cmd, "coach-1")
    assert {a.academy_id for a in repo.saved} == {REQUEST}


class _AlwaysAssigned:
    async def is_coach_assigned(self, coach_id: str, session_id: str) -> bool:
        return True


@pytest.mark.asyncio
async def test_coach_add_student_to_roster_writes_land_in_request_tenant() -> None:
    enrollments = FakeEnrollmentWriter()
    students = FakeStudentWriter()
    uc = CoachAddStudentToRoster(
        sessions=FakeSessionWriter(),
        enrollments=enrollments,
        students=students,
        assigned_sessions=_AlwaysAssigned(),
        academy_id=_boot_fallback_provider(),
    )
    cmd = CoachAddStudentToRosterCommand(
        coach_id="coach-1",
        session_id="sess-1",
        student_id="st-1",
        parent_id="par-1",
        full_name="Kid One",
    )
    with tenant_scope(REQUEST):
        enrollment = await uc.execute(cmd)
    assert enrollment.academy_id == REQUEST
    assert students.ensured[0].academy_id == REQUEST
    assert enrollments.created[0].academy_id == REQUEST


@pytest.mark.asyncio
async def test_confirm_enrollment_writes_land_in_request_tenant() -> None:
    enrollments = FakeEnrollmentWriter()
    students = FakeStudentWriter()
    uc = ConfirmEnrollment(
        sessions=FakeSessionWriter(),
        enrollments=enrollments,
        enrollment_query=FakeEnrollmentQuery(),
        students=students,
        outbox=FakeOutbox(),
        idempotency_store=InMemoryIdempotency(),
        academy_id=_boot_fallback_provider(),
    )
    cmd = ConfirmEnrollmentCommand(
        payment_id="pay-1",
        parent_id="par-1",
        session_id="sess-1",
        student_first_name="Kid",
        student_last_name="One",
    )
    with tenant_scope(REQUEST):
        await uc.execute(cmd)
    assert students.upserted[0].academy_id == REQUEST
    assert enrollments.created[0].academy_id == REQUEST


@pytest.mark.asyncio
async def test_confirm_enrollment_without_context_falls_back_to_boot_academy() -> None:
    # Outbox event handlers run outside HTTP tenant scope — the boot fallback
    # keeps today's single-academy behavior byte-identical.
    enrollments = FakeEnrollmentWriter()
    uc = ConfirmEnrollment(
        sessions=FakeSessionWriter(),
        enrollments=enrollments,
        enrollment_query=FakeEnrollmentQuery(),
        students=FakeStudentWriter(),
        outbox=FakeOutbox(),
        idempotency_store=InMemoryIdempotency(),
        academy_id=_boot_fallback_provider(),
    )
    cmd = ConfirmEnrollmentCommand(
        payment_id="pay-2",
        parent_id="par-1",
        session_id="sess-1",
        student_first_name="Kid",
        student_last_name="Two",
    )
    await uc.execute(cmd)
    assert enrollments.created[0].academy_id == BOOT


class FakeWaitlist:
    def __init__(self) -> None:
        self.entry = WaitlistEntry(
            waitlist_id="wl-1",
            academy_id=REQUEST,
            session_id="sess-1",
            student_id="st-1",
            parent_id="par-1",
            joined_at=FIXED_NOW,
        )

    async def next_waiting(self, session_id: str):
        return self.entry

    async def update_status(self, waitlist_id: str, status: str) -> None:
        pass


@pytest.mark.asyncio
async def test_promote_from_waitlist_writes_land_in_request_tenant() -> None:
    enrollments = FakeEnrollmentWriter()
    uc = PromoteFromWaitlist(
        waitlist=FakeWaitlist(),
        sessions=FakeSessionWriter(),
        enrollments=enrollments,
        outbox=FakeOutbox(),
        academy_id=_boot_fallback_provider(),
        clock=lambda: FIXED_NOW,
    )
    with tenant_scope(REQUEST):
        promoted = await uc.execute("sess-1")
    assert promoted == "wl-1"
    assert enrollments.created[0].academy_id == REQUEST


class FakeParentWaivers:
    def __init__(self) -> None:
        self.signatures: list[Any] = []
        self.template = AdminWaiverTemplateRecord(
            waiver_template_id="wt-1",
            title="Liability",
            body="...",
            status="active",
            version="v1",
            content_hash="hash-1",
            updated_at=FIXED_NOW,
        )

    async def get_required_template(self):
        return self.template

    async def list_active_students_for_parent(self, parent_id: str):
        return [ParentWaiverStudent(student_id="st-1", student_name="Kid One")]

    async def latest_signatures_for_students(self, student_ids):
        return {}

    async def save_signature(self, signature) -> None:
        self.signatures.append(signature)


@pytest.mark.asyncio
async def test_accept_parent_waiver_writes_land_in_request_tenant() -> None:
    waivers = FakeParentWaivers()
    uc = AcceptParentWaiver(waivers=waivers, academy_id=_boot_fallback_provider())
    with tenant_scope(REQUEST):
        await uc.execute(
            parent_id="par-1",
            signer_name="Pat Parent",
            signer_email="pat@example.com",
            ip_address=None,
            user_agent=None,
        )
    assert waivers.signatures[0].academy_id == REQUEST


class FakeAppRepo:
    def __init__(self) -> None:
        self.saved: list[Any] = []

    async def latest_for_parent(self, parent_user_id: str):
        return None

    async def save(self, app) -> None:
        self.saved.append(app)


@pytest.mark.asyncio
async def test_start_application_writes_land_in_request_tenant() -> None:
    repo = FakeAppRepo()
    uc = StartApplication(apps=repo, academy_id=_boot_fallback_provider())
    with tenant_scope(REQUEST):
        await uc.execute(
            StartApplicationCommand(parent_user_id="par-1", parent_email="pat@example.com")
        )
    assert repo.saved[0].academy_id == REQUEST


# --- parent reads return only the request tenant's rows ----------------------


def _compose_parent(db):
    from backend.v2.composition.parent import compose_parent

    return compose_parent(
        db,
        outbox=FakeOutbox(),  # type: ignore[arg-type]
        idempotency_store=InMemoryIdempotency(),  # type: ignore[arg-type]
        stripe=object(),  # type: ignore[arg-type]
        academy_id=BOOT,
    )


@pytest.mark.asyncio
async def test_list_payments_returns_only_request_tenant_rows(db) -> None:
    now = FIXED_NOW
    await db["ledger_payments"].insert_many(
        [
            {
                "academy_id": BOOT,
                "payment_id": "pay-a",
                "parent_id": "par-1",
                "amount_cents": 5_000,
                "currency": "usd",
                "status": "succeeded",
                "created_at": now,
            },
            {
                "academy_id": REQUEST,
                "payment_id": "pay-b",
                "parent_id": "par-1",
                "amount_cents": 6_000,
                "currency": "usd",
                "status": "succeeded",
                "created_at": now,
            },
        ]
    )
    parent = _compose_parent(db)
    with tenant_scope(REQUEST):
        rows = await parent.list_payments_for_parent("par-1")
    assert [row.payment_id for row in rows] == ["pay-b"]


@pytest.mark.asyncio
async def test_list_children_returns_only_request_tenant_rows(db) -> None:
    await db["students"].insert_many(
        [
            {
                "academy_id": BOOT,
                "student_id": "st-a",
                "parent_id": "par-1",
                "full_name": "Boot Kid",
                "status": "active",
            },
            {
                "academy_id": REQUEST,
                "student_id": "st-b",
                "parent_id": "par-1",
                "full_name": "Request Kid",
                "status": "active",
            },
        ]
    )
    parent = _compose_parent(db)
    with tenant_scope(REQUEST):
        rows = await parent.list_children_for_parent("par-1")
    assert [row["student_id"] for row in rows] == ["st-b"]


@pytest.mark.asyncio
async def test_list_enrollments_returns_only_request_tenant_rows(db) -> None:
    await db["students"].insert_one(
        {
            "academy_id": REQUEST,
            "student_id": "st-b",
            "parent_id": "par-1",
            "full_name": "Request Kid",
            "status": "active",
        }
    )
    await db["enrollments"].insert_many(
        [
            {
                "academy_id": BOOT,
                "enrollment_id": "enr-a",
                "student_id": "st-b",
                "session_id": "sess-1",
                "status": "active",
                "created_at": FIXED_NOW,
            },
            {
                "academy_id": REQUEST,
                "enrollment_id": "enr-b",
                "student_id": "st-b",
                "session_id": "sess-1",
                "status": "active",
                "created_at": FIXED_NOW,
            },
        ]
    )
    parent = _compose_parent(db)
    with tenant_scope(REQUEST):
        rows = await parent.list_enrollments_for_parent("par-1")
    assert [row["enrollment_id"] for row in rows] == ["enr-b"]


# --- reads fail closed without tenant context --------------------------------


@pytest.mark.asyncio
async def test_list_payments_without_context_raises(db) -> None:
    parent = _compose_parent(db)
    with pytest.raises(TenantContextUnset):
        await parent.list_payments_for_parent("par-1")


# --- composition wiring: providers resolve request-time; fallback is mode-aware


def test_compose_parent_providers_resolve_request_tenant(db) -> None:
    parent = _compose_parent(db)
    for provider in (
        parent.start_application._academy_id,
        parent.accept_parent_waiver._academy_id,
    ):
        assert callable(provider)
        with tenant_scope(REQUEST):
            assert provider() == REQUEST
        # Default test settings run multi_academy: no context must fail closed.
        with pytest.raises(TenantContextUnset):
            provider()


def test_compose_parent_provider_falls_back_to_boot_in_single_academy_mode(
    db, monkeypatch: pytest.MonkeyPatch
) -> None:
    from backend.v2.shared.config import get_settings

    monkeypatch.setenv("V2_TENANCY_MODE", "single_academy")
    monkeypatch.setenv("V2_PRIMARY_ACADEMY_ID", BOOT)
    get_settings.cache_clear()
    try:
        parent = _compose_parent(db)
        assert parent.start_application._academy_id() == BOOT
        with tenant_scope(REQUEST):
            assert parent.start_application._academy_id() == REQUEST
    finally:
        get_settings.cache_clear()


def test_compose_coach_providers_resolve_request_tenant(db) -> None:
    from backend.v2.composition.coach import compose_coach

    coach = compose_coach(
        db,
        outbox=FakeOutbox(),  # type: ignore[arg-type]
        idempotency_store=InMemoryIdempotency(),  # type: ignore[arg-type]
        stripe=object(),  # type: ignore[arg-type]
    )
    for provider in (
        coach.mark_attendance._academy_id,
        coach.bulk_mark_attendance._academy_id,
        coach.add_student_to_roster._academy_id,
    ):
        assert callable(provider)
        with tenant_scope(REQUEST):
            assert provider() == REQUEST
        # Default test settings run multi_academy: no context must fail closed.
        with pytest.raises(TenantContextUnset):
            provider()
