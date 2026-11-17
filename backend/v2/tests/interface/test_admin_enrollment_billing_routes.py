"""PUT /admin/enrollments/{id}/billing: the owner's errors map to 404 / 422.

The admin-without-owner 404 is walked by ``test_money_owner_only.py``.
"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from backend.v2.contexts.billing.application.use_cases.enrollment_not_billed import (
    EnrollmentBillingResult,
    EnrollmentNotFound,
    NotBilledValidationError,
    SetEnrollmentBillingCommand,
)
from backend.v2.interfaces.admin.enrollment_billing_routes import get_admin_enrollment_billing

_URL = "/api/v2/admin/enrollments/enr-1/billing"


class _Setter:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.seen: list[tuple[str, SetEnrollmentBillingCommand]] = []

    async def execute(self, academy_id: str, cmd: SetEnrollmentBillingCommand) -> Any:
        self.seen.append((academy_id, cmd))
        if self.error:
            raise self.error
        return EnrollmentBillingResult(
            enrollment_id=cmd.enrollment_id,
            not_billed=True,
            billing_type="NoCharge",
            not_billed_reason=cmd.reason,
        )


def _with(client: TestClient, setter: _Setter) -> TestClient:
    client.app.dependency_overrides[get_admin_enrollment_billing] = lambda: setter  # type: ignore[attr-defined]
    return client


def test_the_owner_marks_an_enrollment_not_billed(admin_client: TestClient) -> None:
    setter = _Setter()
    response = _with(admin_client, setter).put(
        _URL, json={"not_billed": True, "reason": "owner_child"}
    )

    assert response.status_code == 200, response.text
    assert response.json()["not_billed_reason"] == "owner_child"
    assert setter.seen[0][1].enrollment_id == "enr-1"
    assert setter.seen[0][1].actor_id


def test_validation_and_missing_rows_map_to_422_and_404(admin_client: TestClient) -> None:
    invalid = _with(admin_client, _Setter(NotBilledValidationError("note", "add a note"))).put(
        _URL, json={"not_billed": True, "reason": "other"}
    )
    missing = _with(admin_client, _Setter(EnrollmentNotFound("enr-1"))).put(
        _URL, json={"not_billed": False}
    )
    unknown_reason = admin_client.put(_URL, json={"not_billed": True, "reason": "cousin"})

    assert invalid.status_code == 422
    assert invalid.json()["detail"] == {"field": "note", "message": "add a note"}
    assert missing.status_code == 404
    assert unknown_reason.status_code == 422
