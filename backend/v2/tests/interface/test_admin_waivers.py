"""Admin waivers BFF route."""

from __future__ import annotations

from datetime import UTC, datetime

from backend.v2.contexts.onboarding.application.use_cases.admin_waivers import (
    AdminWaiverDocument,
    AdminWaiverLineageReport,
    AdminWaiverReport,
    AdminWaiverStudentRow,
    AdminWaiverSummary,
)


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=UTC)


def test_admin_lists_waiver_summary_and_student_rows(admin_client):
    admin_client.seed["waivers"].report = AdminWaiverReport(
        active_waiver=AdminWaiverDocument(
            waiver_id="wv-current",
            version="2026.1",
            content_hash="hash-current",
            effective_from=_dt("2026-01-01T00:00:00"),
        ),
        summary=AdminWaiverSummary(
            total_students=2,
            signed_count=1,
            current_count=1,
            pending_count=1,
            outdated_count=0,
        ),
        rows=[
            AdminWaiverStudentRow(
                student_id="st-current",
                student_name="Current Student",
                parent_id="p-1",
                parent_name="Parent One",
                parent_email="parent@example.com",
                status="current",
                waiver_version="2026.1",
                current_waiver_version="2026.1",
                content_hash="hash-current",
                signed_at=_dt("2026-05-01T12:00:00"),
                signed_by_user_id="p-1",
            ),
            AdminWaiverStudentRow(
                student_id="st-pending",
                student_name="Pending Student",
                parent_id="p-2",
                status="pending",
                current_waiver_version="2026.1",
            ),
        ],
    )

    r = admin_client.get("/api/v2/admin/waivers")

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["summary"] == {
        "signed_current": 1,
        "pending_signature": 1,
        "expiring_30d": 0,
        "outdated_version": 0,
        "active_students": 2,
        "adoption_rate": 0.5,
    }
    assert body["current_waiver"]["version"] == "2026.1"
    assert body["current_waiver"]["signed_count"] == 1
    assert body["current_waiver"]["total_count"] == 2
    assert [row["status"] for row in body["waivers"]] == ["signed", "pending"]
    assert body["waivers"][0]["student_name"] == "Current Student"
    assert body["waivers"][0]["version"] == "2026.1"
    assert body["waivers"][0]["method"] == "online"
    assert body["waivers"][0]["signed_at"] == "2026-05-01T12:00:00Z"
    assert body["waivers"][1]["signed_at"] is None


def test_admin_waivers_wrong_persona_404(coach_on_admin_client, parent_on_admin_client):
    assert coach_on_admin_client.get("/api/v2/admin/waivers").status_code == 404
    assert parent_on_admin_client.get("/api/v2/admin/waivers").status_code == 404


def test_admin_waiver_list_carries_one_entry_per_live_waiver(admin_client):
    liability = AdminWaiverDocument(waiver_id="wt-liab", version="2", title="Liability")
    photo = AdminWaiverDocument(
        waiver_id="wt-photo",
        version="1",
        title="Photo consent",
        lineage_key="photo",
        scope="programs",
        program_ids=["prog-juniors"],
    )
    liability_summary = AdminWaiverSummary(
        total_students=3, signed_count=2, current_count=2, pending_count=1, outdated_count=0
    )
    photo_summary = AdminWaiverSummary(
        total_students=1, signed_count=0, current_count=0, pending_count=1, outdated_count=0
    )
    pending = AdminWaiverStudentRow(
        student_id="st-a",
        student_name="Ann",
        parent_id="p-1",
        status="pending",
        current_waiver_version="1",
    )
    admin_client.seed["waivers"].report = AdminWaiverReport(
        active_waiver=liability,
        summary=liability_summary,
        rows=[],
        lineages=[
            AdminWaiverLineageReport(waiver=liability, summary=liability_summary, rows=[]),
            AdminWaiverLineageReport(waiver=photo, summary=photo_summary, rows=[pending]),
        ],
        live_waivers=[liability, photo],
    )

    body = admin_client.get("/api/v2/admin/waivers").json()

    assert body["summary"]["signed_current"] == 2
    assert [lineage["lineage_key"] for lineage in body["lineages"]] == ["legacy", "photo"]
    photo_view = body["lineages"][1]
    assert photo_view["scope"] == "programs"
    assert photo_view["program_ids"] == ["prog-juniors"]
    assert photo_view["summary"]["pending_signature"] == 1
    assert photo_view["waiver"]["title"] == "Photo consent"
    assert [row["status"] for row in photo_view["waivers"]] == ["pending"]
