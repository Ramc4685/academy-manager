"""S40: class created, waiver published and invoice run each leave an audit row.

The row is best effort: the action has already committed, so a failing audit
write is logged and never fails the action.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from mongomock_motor import AsyncMongoMockClient

from backend.v2.contexts.billing.application.use_cases.admin_payment_ops import (
    GenerateMonthlyPayments,
    GenerateMonthlyPaymentsCommand,
    GenerateMonthlyPaymentsResult,
)
from backend.v2.contexts.enrollment.application.use_cases.admin_writes import (
    CreateSession,
    CreateSessionCommand,
)
from backend.v2.contexts.identity.infrastructure.mongo_audit_trail import MongoAuditTrail
from backend.v2.contexts.onboarding.application.use_cases.admin_waiver_templates import (
    AdminWaiverTemplateRecord,
    ManageAdminWaiverTemplates,
    PublishWaiverTemplateCommand,
)
from backend.v2.shared.tenancy import tenant_scope
from backend.v2.tests.application.test_admin_waiver_template_management import (
    FakeTemplateRepo,
)
from backend.v2.tests.unit.test_create_session_timezone_persistence import (
    _StubSessionWriter,
)

pytestmark = pytest.mark.asyncio


class _Trail:
    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []

    async def append(self, **row: Any) -> None:
        self.rows.append(row)


class _BrokenTrail:
    async def append(self, **_: Any) -> None:
        raise RuntimeError("mongo is down")


class _Payments:
    def __init__(self, created: int) -> None:
        self._created = created

    async def generate_monthly_payments(self, period: str) -> GenerateMonthlyPaymentsResult:
        return GenerateMonthlyPaymentsResult(created=self._created)


async def _tz(_academy_id: str) -> str:
    return "America/Chicago"


def _create_session(trail: Any) -> CreateSession:
    return CreateSession(
        sessions=_StubSessionWriter(),  # type: ignore[arg-type]
        academy_id="acad-1",
        get_academy_timezone=_tz,
        audit=trail,
    )


def _session_cmd() -> CreateSessionCommand:
    return CreateSessionCommand(
        coach_id="coach-1",
        title="Thursday Juniors",
        location="Court 1",
        capacity=10,
        days_of_week=["Thu"],
        start_time="18:00",
        end_time="18:45",
        actor_id="u-owner",
    )


def _waivers(trail: Any) -> ManageAdminWaiverTemplates:
    at = datetime(2026, 11, 1, tzinfo=UTC)
    repo = FakeTemplateRepo(
        rows={
            "wt-1": AdminWaiverTemplateRecord(
                waiver_template_id="wt-1",
                title="Liability",
                body="Body",
                status="draft",
                updated_at=at,
            )
        }
    )
    return ManageAdminWaiverTemplates(repo, clock=lambda: at, audit=trail)


async def test_class_created_appends_a_row() -> None:
    trail = _Trail()
    session = await _create_session(trail).execute(_session_cmd())
    assert trail.rows == [
        {
            "actor_id": "u-owner",
            "action": "class_created",
            "entity_type": "session",
            "entity_id": session.session_id,
            "metadata": {"title": "Thursday Juniors"},
        }
    ]


async def test_waiver_published_appends_a_row() -> None:
    trail = _Trail()
    published = await _waivers(trail).publish(
        PublishWaiverTemplateCommand(waiver_template_id="wt-1", actor_id="u-owner")
    )
    assert [r["action"] for r in trail.rows] == ["waiver_published"]
    assert trail.rows[0]["entity_id"] == "wt-1"
    assert trail.rows[0]["metadata"] == {"title": "Liability", "version": published.version}


async def test_invoice_run_appends_a_row_for_staff_and_busy_scheduler_runs_only() -> None:
    trail = _Trail()
    await GenerateMonthlyPayments(payments=_Payments(0), audit=trail).execute(
        GenerateMonthlyPaymentsCommand(period="2026-11", actor_id="u-owner")
    )
    # Unattended run that billed nothing: no row.
    await GenerateMonthlyPayments(payments=_Payments(0), audit=trail).execute(
        GenerateMonthlyPaymentsCommand(period="2026-11")
    )
    await GenerateMonthlyPayments(payments=_Payments(4), audit=trail).execute(
        GenerateMonthlyPaymentsCommand(period="2026-12")
    )
    assert [(r["actor_id"], r["entity_id"]) for r in trail.rows] == [
        ("u-owner", "2026-11"),
        (None, "2026-12"),
    ]
    assert trail.rows[1]["metadata"]["created"] == 4


async def test_a_failing_audit_write_never_fails_the_action() -> None:
    broken = _BrokenTrail()
    session = await _create_session(broken).execute(_session_cmd())
    assert session.title == "Thursday Juniors"
    published = await _waivers(broken).publish(
        PublishWaiverTemplateCommand(waiver_template_id="wt-1", actor_id="u-owner")
    )
    assert published.status == "active"
    result = await GenerateMonthlyPayments(payments=_Payments(2), audit=broken).execute(
        GenerateMonthlyPaymentsCommand(period="2026-11", actor_id="u-owner")
    )
    assert result.created == 2


async def test_mongo_trail_writes_a_tenant_scoped_audit_logs_row() -> None:
    db = AsyncMongoMockClient()["s40"]
    with tenant_scope("acad-1"):
        await MongoAuditTrail(db).append(
            actor_id="u-owner",
            action="class_created",
            entity_type="session",
            entity_id="s-1",
            metadata={"title": "Juniors"},
        )
    row = await db["audit_logs"].find_one({})
    assert row is not None
    assert row["academy_id"] == "acad-1"
    assert row["action"] == "class_created"
    assert row["audit_id"].startswith("audit_")
