"""The admin waiver report counts each live waiver against its own students."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from backend.v2.contexts.onboarding.application.use_cases.admin_waivers import (
    AdminWaiverAcceptance,
    AdminWaiverData,
    AdminWaiverDocument,
    AdminWaiverStudent,
    ListAdminWaivers,
)


class _Query:
    def __init__(self, data: AdminWaiverData) -> None:
        self.data = data

    async def load_admin_waiver_data(self) -> AdminWaiverData:
        return self.data


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=UTC)


def _student(student_id: str) -> AdminWaiverStudent:
    return AdminWaiverStudent(student_id=student_id, full_name=student_id.title(), parent_id="p")


def _accept(student_id: str, template_id: str, version: str, digest: str) -> AdminWaiverAcceptance:
    return AdminWaiverAcceptance(
        student_id=student_id,
        parent_id="p",
        waiver_template_id=template_id,
        waiver_version=version,
        content_hash=digest,
        accepted_at=_dt("2026-09-01T10:00:00"),
    )


LIABILITY = AdminWaiverDocument(
    waiver_id="wt-liability",
    version="2",
    title="Liability",
    content_hash="h-liab-2",
    lineage_key="legacy",
    required=True,
    scope="all",
)
PHOTO = AdminWaiverDocument(
    waiver_id="wt-photo",
    version="1",
    title="Photo consent",
    content_hash="h-photo-1",
    lineage_key="photo",
    required=True,
    scope="programs",
    program_ids=["prog-juniors"],
)
UNASSIGNED = AdminWaiverDocument(
    waiver_id="wt-trip",
    version="1",
    title="Trip release",
    content_hash="h-trip",
    lineage_key="trip",
    required=False,
)


@pytest.mark.asyncio
async def test_each_waiver_counts_only_the_students_it_applies_to() -> None:
    data = AdminWaiverData(
        students=[_student("ann"), _student("bo"), _student("cy")],
        live_waivers=[PHOTO, LIABILITY, UNASSIGNED],
        program_ids_by_student={"ann": {"prog-juniors"}, "bo": {"prog-adults"}, "cy": set()},
        acceptances_by_lineage={
            ("ann", "legacy"): _accept("ann", "wt-liability", "2", "h-liab-2"),
            ("bo", "legacy"): _accept("bo", "wt-old", "1", "h-liab-1"),
            ("ann", "photo"): _accept("ann", "wt-photo", "1", "h-photo-1"),
        },
    )

    report = await ListAdminWaivers(_Query(data)).execute()

    by_key = {lineage.waiver.lineage_key: lineage for lineage in report.lineages}
    liability = by_key["legacy"]
    assert liability.summary.total_students == 3
    assert (liability.summary.current_count, liability.summary.outdated_count) == (1, 1)
    assert liability.summary.pending_count == 1
    photo = by_key["photo"]
    # Only ann sits in the Juniors program.
    assert [row.student_id for row in photo.rows] == ["ann"]
    assert photo.summary.current_count == 1
    assert photo.summary.pending_count == 0
    # A live waiver nobody is asked to sign counts nobody.
    assert by_key["trip"].summary.total_students == 0
    assert by_key["trip"].rows == []
    assert len(report.live_waivers) == 3


@pytest.mark.asyncio
async def test_signing_one_waiver_does_not_count_for_another() -> None:
    data = AdminWaiverData(
        students=[_student("ann")],
        live_waivers=[LIABILITY, PHOTO.model_copy(update={"scope": "all", "program_ids": []})],
        acceptances_by_lineage={
            ("ann", "photo"): _accept("ann", "wt-photo", "1", "h-photo-1"),
        },
    )

    report = await ListAdminWaivers(_Query(data)).execute()

    by_key = {lineage.waiver.lineage_key: lineage for lineage in report.lineages}
    assert by_key["legacy"].rows[0].status == "pending"
    assert by_key["photo"].rows[0].status == "current"


@pytest.mark.asyncio
async def test_top_level_report_is_the_all_family_waiver_first() -> None:
    data = AdminWaiverData(
        students=[_student("ann")],
        live_waivers=[PHOTO, LIABILITY],
        program_ids_by_student={"ann": {"prog-juniors"}},
        acceptances_by_lineage={
            ("ann", "legacy"): _accept("ann", "wt-liability", "2", "h-liab-2"),
        },
    )

    report = await ListAdminWaivers(_Query(data)).execute()

    assert report.active_waiver is not None
    assert report.active_waiver.waiver_id == "wt-liability"
    assert report.summary.current_count == 1
    assert [row.status for row in report.rows] == ["current"]


@pytest.mark.asyncio
async def test_single_all_family_waiver_reads_as_the_old_single_waiver_report() -> None:
    students = [_student("ann"), _student("bo"), _student("cy")]
    acceptances = {
        "ann": _accept("ann", "wt-liability", "2", "h-liab-2"),
        "bo": _accept("bo", "wt-old", "1", "h-liab-1"),
    }
    old_style = await ListAdminWaivers(
        _Query(
            AdminWaiverData(
                active_waiver=LIABILITY, students=students, acceptances_by_student=acceptances
            )
        )
    ).execute()
    per_waiver = await ListAdminWaivers(
        _Query(
            AdminWaiverData(
                students=students,
                live_waivers=[LIABILITY],
                acceptances_by_lineage={
                    ("ann", "legacy"): acceptances["ann"],
                    ("bo", "legacy"): acceptances["bo"],
                },
            )
        )
    ).execute()

    assert per_waiver.summary == old_style.summary
    assert [row.status for row in per_waiver.rows] == [row.status for row in old_style.rows]
    assert [row.status for row in per_waiver.rows] == ["current", "outdated", "pending"]
    assert len(per_waiver.lineages) == 1
