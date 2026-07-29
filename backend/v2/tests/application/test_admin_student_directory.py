"""Admin student directory use-case behavior."""

from __future__ import annotations

import pytest

from backend.v2.contexts.enrollment.application.use_cases.admin_directory import (
    AdminStudentPage,
    AdminStudentSummary,
    ListAdminStudents,
)


class FakeStudentDirectory:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def list_admin_students(
        self,
        *,
        search: str | None,
        status: str | None,
        limit: int,
        cursor: str | None,
        missing: tuple[str, ...] = (),
    ) -> AdminStudentPage:
        self.calls.append(
            {
                "search": search,
                "status": status,
                "limit": limit,
                "cursor": cursor,
                "missing": missing,
            }
        )
        return AdminStudentPage(
            students=[
                AdminStudentSummary(
                    student_id="st-1",
                    full_name="Alice Chen",
                    parent_id="p-1",
                    status="active",
                    active_session_count=1,
                    attendance_rate=0.75,
                    dues_status="due",
                )
            ],
            next_cursor=None,
        )


@pytest.mark.asyncio
async def test_list_admin_students_forwards_filters_to_query():
    query = FakeStudentDirectory()
    use_case = ListAdminStudents(query)

    page = await use_case.execute(
        search="alice",
        status="active",
        limit=25,
        cursor="opaque",
    )

    assert query.calls == [
        {
            "search": "alice",
            "status": "active",
            "limit": 25,
            "cursor": "opaque",
            "missing": (),
        }
    ]
    assert page.students[0].attendance_rate == 0.75
    assert page.students[0].dues_status == "due"


@pytest.mark.asyncio
async def test_list_admin_students_forwards_missing_filter():
    query = FakeStudentDirectory()
    use_case = ListAdminStudents(query)

    await use_case.execute(missing=("date_of_birth", "emergency_contact_name"))

    assert query.calls[0]["missing"] == ("date_of_birth", "emergency_contact_name")
