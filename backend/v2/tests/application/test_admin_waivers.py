"""Admin waiver report use-case tests."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from backend.v2.contexts.onboarding.application.use_cases.admin_waivers import (
    AdminWaiverAcceptance,
    AdminWaiverData,
    AdminWaiverDocument,
    AdminWaiverStudent,
    ListAdminWaivers,
)


class FakeWaiverQuery:
    def __init__(self, data: AdminWaiverData) -> None:
        self.data = data

    async def load_admin_waiver_data(self) -> AdminWaiverData:
        return self.data


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_list_admin_waivers_classifies_supported_statuses() -> None:
    active = AdminWaiverDocument(
        waiver_id="wv-current",
        version="2026.1",
        content_hash="hash-current",
        effective_from=_dt("2026-01-01T00:00:00"),
    )
    data = AdminWaiverData(
        active_waiver=active,
        students=[
            AdminWaiverStudent(
                student_id="st-current",
                full_name="Current Student",
                parent_id="p1",
                parent_name="Parent One",
                parent_email="p1@example.com",
            ),
            AdminWaiverStudent(
                student_id="st-old",
                full_name="Old Student",
                parent_id="p2",
            ),
            AdminWaiverStudent(
                student_id="st-pending",
                full_name="Pending Student",
                parent_id="p3",
            ),
        ],
        acceptances_by_student={
            "st-current": AdminWaiverAcceptance(
                student_id="st-current",
                parent_id="p1",
                accepted_by_user_id="p1",
                waiver_version="2026.1",
                content_hash="hash-current",
                accepted_at=_dt("2026-05-01T12:00:00"),
            ),
            "st-old": AdminWaiverAcceptance(
                student_id="st-old",
                parent_id="p2",
                accepted_by_user_id="p2",
                waiver_version="2025.1",
                content_hash="hash-old",
                accepted_at=_dt("2026-04-01T12:00:00"),
            ),
        },
    )

    report = await ListAdminWaivers(FakeWaiverQuery(data)).execute()

    assert report.summary.total_students == 3
    assert report.summary.signed_count == 2
    assert report.summary.current_count == 1
    assert report.summary.pending_count == 1
    assert report.summary.outdated_count == 1
    assert [row.status for row in report.rows] == ["current", "outdated", "pending"]
    assert report.rows[0].signed_at == _dt("2026-05-01T12:00:00")
    assert report.rows[1].waiver_version == "2025.1"
    assert report.rows[2].signed_at is None


@pytest.mark.asyncio
async def test_list_admin_waivers_reports_signed_when_no_active_waiver_to_compare() -> None:
    data = AdminWaiverData(
        active_waiver=None,
        students=[
            AdminWaiverStudent(
                student_id="st-signed",
                full_name="Signed Student",
                parent_id="p1",
            )
        ],
        acceptances_by_student={
            "st-signed": AdminWaiverAcceptance(
                student_id="st-signed",
                parent_id="p1",
                accepted_by_user_id="p1",
                waiver_version="legacy",
                content_hash=None,
                accepted_at=_dt("2026-05-01T12:00:00"),
            )
        },
    )

    report = await ListAdminWaivers(FakeWaiverQuery(data)).execute()

    assert report.summary.signed_count == 1
    assert report.summary.current_count == 0
    assert report.summary.outdated_count == 0
    assert report.rows[0].status == "signed"
