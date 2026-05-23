"""Admin waiver detail read-model tests."""

from __future__ import annotations

from datetime import UTC, datetime

from backend.v2.contexts.onboarding.application.use_cases.admin_waivers import (
    AdminWaiverData,
    AdminWaiverDocument,
    AdminWaiverSignatureDetail,
    AdminWaiverStudent,
    AdminWaiverTemplateDetail,
    ListAdminWaivers,
)


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=UTC)


class FakeWaiverQuery:
    async def load_admin_waiver_data(self) -> AdminWaiverData:
        return AdminWaiverData(
            active_waiver=AdminWaiverDocument(
                waiver_id="wt-2026",
                title="Annual waiver",
                version="2026.1",
                body="Release text",
                content_hash="hash-2026",
                effective_from=_dt("2026-01-01T00:00:00"),
            ),
            students=[
                AdminWaiverStudent(
                    student_id="st-1",
                    full_name="Ava Player",
                    parent_id="p-1",
                    parent_name="Priya Parent",
                    parent_email="parent@example.com",
                )
            ],
            acceptances_by_student={},
        )

    async def get_template_detail(self, waiver_id: str) -> AdminWaiverTemplateDetail | None:
        if waiver_id != "wt-2026":
            return None
        return AdminWaiverTemplateDetail(
            waiver_id="wt-2026",
            title="Annual waiver",
            version="2026.1",
            body="Release text",
            content_hash="hash-2026",
            effective_from=_dt("2026-01-01T00:00:00"),
        )

    async def get_signature_detail(self, signature_id: str) -> AdminWaiverSignatureDetail | None:
        if signature_id != "ws-1":
            return None
        return AdminWaiverSignatureDetail(
            signature_id="ws-1",
            student_id="st-1",
            student_name="Ava Player",
            parent_id="p-1",
            parent_name="Priya Parent",
            parent_email="parent@example.com",
            signed_at=_dt("2026-05-01T12:00:00"),
            signer_name="Priya Parent",
            signer_email="parent@example.com",
            waiver_template_id="wt-2026",
            waiver_title="Annual waiver",
            waiver_version="2026.1",
            content_hash="hash-2026",
        )


async def test_template_detail_returns_stored_template_text_and_truthful_gap() -> None:
    use_case = ListAdminWaivers(FakeWaiverQuery())

    detail = await use_case.template_detail("wt-2026")

    assert detail is not None
    assert detail.title == "Annual waiver"
    assert detail.body == "Release text"
    assert detail.artifact_status == "unavailable"
    assert detail.share_status == "unavailable"
    assert "not implemented yet" in detail.gap_note


async def test_signature_detail_returns_student_signed_date_and_template_reference() -> None:
    use_case = ListAdminWaivers(FakeWaiverQuery())

    detail = await use_case.signature_detail("ws-1")

    assert detail is not None
    assert detail.student_name == "Ava Player"
    assert detail.signed_at == _dt("2026-05-01T12:00:00")
    assert detail.waiver_template_id == "wt-2026"
    assert detail.waiver_version == "2026.1"
    assert detail.artifact_status == "unavailable"
    assert detail.share_status == "unavailable"
