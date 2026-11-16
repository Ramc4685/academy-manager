"""The autopay date-change notice is preview-only (L8, owner decision).

Nothing may send it to parents: no job, no outbox event, no send use case.
The route renders the email and lists the autopay families it is meant for.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from backend.v2.composition import admin as admin_composition
from backend.v2.tests.interface.test_admin_sessions import _mongo_admin_app

ROUTE = "/api/v2/admin/billing/ach-notice/preview"


class _SenderSpy:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def send(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        raise AssertionError("the ACH notice preview must never send")


async def _seed(db) -> None:
    await db.academies.insert_one(
        {"academy_id": "academy-b", "display_name": "Preview Club", "slug": "preview"}
    )
    await db.billing_settings.insert_one(
        {
            "academy_id": "academy-b",
            "billing_day": 1,
            "schedule_change": {
                "effective_from": "2027-01-01",
                "invoice_due_days": 4,
                "autopay_charge_offset_days": 0,
                "reminder_days": [0, 3, 7],
            },
        }
    )
    for enrollment_id, parent_id, status in (
        ("enr-1", "parent-auto", "active"),
        ("enr-2", "parent-auto", "active"),
        ("enr-3", "parent-manual", None),
    ):
        await db.student_billing_enrollments.insert_one(
            {
                "academy_id": "academy-b",
                "enrollment_id": enrollment_id,
                "parent_id": parent_id,
                "autopay_enrollment_status": status,
            }
        )
    await db.parent_billing_customers.insert_one(
        {
            "academy_id": "academy-b",
            "parent_id": "parent-auto",
            "payment_method_label": "Bank",
            "payment_method_last4": "6789",
        }
    )


@pytest.mark.asyncio
async def test_preview_renders_the_notice_and_lists_autopay_families_without_sending(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mongomock_motor = pytest.importorskip("mongomock_motor")
    db = mongomock_motor.AsyncMongoMockClient()["ach-notice-preview"]
    await _seed(db)
    spy = _SenderSpy()
    monkeypatch.setattr(admin_composition, "_build_email_sender", lambda *_a, **_k: spy)

    with TestClient(_mongo_admin_app(db)) as client:
        response = client.get(ROUTE)
        other = client.get(ROUTE, params={"parent_id": "parent-manual"})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["subject"] == "Your autopay date is changing to the 1st of the month"
    assert "Starting January 1, 2027" in body["html"]
    assert "your usual monthly tuition" in body["html"]
    assert body["recipients"] == [
        {
            "parent_id": "parent-auto",
            "name": None,
            "payment_method": "Bank ending 6789",
            "expected_amount_cents": None,
        }
    ]
    assert other.status_code == 404
    assert spy.calls == []
    assert "outbox" not in await db.list_collection_names()


def test_preview_refuses_a_non_admin(coach_on_admin_client) -> None:
    assert coach_on_admin_client.get(ROUTE).status_code == 404
