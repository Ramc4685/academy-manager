"""Admin operational detail routes for waivers, messages, and reports."""

from __future__ import annotations

from datetime import UTC, datetime

from backend.v2.contexts.onboarding.application.use_cases.admin_waivers import (
    AdminWaiverDocument,
    AdminWaiverReport,
    AdminWaiverStudentRow,
    AdminWaiverSummary,
)


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=UTC)


def _seed_waiver_report(admin_client) -> None:
    admin_client.seed["waivers"].report = AdminWaiverReport(
        active_waiver=AdminWaiverDocument(
            waiver_id="wt-2026",
            title="Annual waiver",
            version="2026.1",
            body="Release text",
            content_hash="hash-current",
            effective_from=_dt("2026-01-01T00:00:00"),
        ),
        summary=AdminWaiverSummary(
            total_students=1,
            signed_count=1,
            current_count=1,
            pending_count=0,
            outdated_count=0,
        ),
        rows=[
            AdminWaiverStudentRow(
                signature_id="ws-1",
                student_id="st-current",
                student_name="Current Student",
                parent_id="p-1",
                parent_name="Parent One",
                parent_email="parent@example.com",
                status="current",
                waiver_template_id="wt-2026",
                waiver_version="2026.1",
                current_waiver_version="2026.1",
                content_hash="hash-current",
                signed_at=_dt("2026-05-01T12:00:00"),
                signed_by_user_id="p-1",
            )
        ],
    )


def test_admin_can_open_waiver_template_detail(admin_client):
    _seed_waiver_report(admin_client)

    response = admin_client.get("/api/v2/admin/waivers/wt-2026")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["title"] == "Annual waiver"
    assert body["version"] == "2026.1"
    assert body["body"] == "Release text"
    assert body["artifact_status"] == "unavailable"
    assert body["share_status"] == "unavailable"


def test_admin_can_open_signed_waiver_detail(admin_client):
    _seed_waiver_report(admin_client)

    response = admin_client.get("/api/v2/admin/waivers/signatures/ws-1")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["student_name"] == "Current Student"
    assert body["parent_name"] == "Parent One"
    assert body["signed_at"] == "2026-05-01T12:00:00Z"
    assert body["waiver_version"] == "2026.1"
    assert body["template_reference"] == "wt-2026"
    assert body["artifact_status"] == "unavailable"
    assert body["share_status"] == "unavailable"


def test_waiver_template_detail_wrong_persona_404(
    coach_on_admin_client, parent_on_admin_client
):
    assert coach_on_admin_client.get("/api/v2/admin/waivers/wt-2026").status_code == 404
    assert parent_on_admin_client.get("/api/v2/admin/waivers/wt-2026").status_code == 404


def test_signed_waiver_detail_wrong_persona_404(coach_on_admin_client, parent_on_admin_client):
    assert (
        coach_on_admin_client.get("/api/v2/admin/waivers/signatures/ws-1").status_code == 404
    )
    assert (
        parent_on_admin_client.get("/api/v2/admin/waivers/signatures/ws-1").status_code == 404
    )


def test_admin_message_broadcast_response_includes_scope(admin_client):
    response = admin_client.post(
        "/api/v2/admin/messages/broadcast",
        json={
            "body": "Schedule update",
            "scope_type": "academy",
            "scope_label": "Whole academy announcement",
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["kind"] == "announcement"
    assert body["is_broadcast"] is True
    assert body["scope_type"] == "academy"
    assert body["scope_label"] == "Whole academy announcement"
    assert body["recipient_count"] is None
    assert body["delivery_status"] == "recorded"


def test_admin_reports_kpis_are_available_as_dashboard_data(admin_client):
    response = admin_client.get("/api/v2/admin/reports/kpis")

    assert response.status_code == 200, response.text
    assert response.json() == {
        "active_students": 0,
        "attendance_rate_30d": 0.0,
        "dues_collected_mtd_cents": 0,
        "pending_waivers": 0,
    }
