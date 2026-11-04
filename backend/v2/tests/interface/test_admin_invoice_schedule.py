"""Admin routes for the automated monthly-invoicing schedule (issue #288).

``PUT`` (the write side) was retired in the Settings overhaul (Lane D, PR 7):
nothing called it — the Billing rules panel writes through
``POST /admin/billing/rules`` instead, which reuses the same
``SetInvoiceScheduleCommand`` use case underneath. ``GET`` stays: the family
billing tab still reads it.
"""

from __future__ import annotations

from backend.v2.contexts.billing.application.use_cases.billing_settings_admin import (
    InvoiceScheduleResult,
)

ROUTE = "/api/v2/admin/billing/settings/invoice-schedule"


class _FakeGetInvoiceSchedule:
    def __init__(self, billing_day: int = 1, invoice_due_days: int = 7) -> None:
        self._result = InvoiceScheduleResult(
            billing_day=billing_day, invoice_due_days=invoice_due_days
        )

    async def execute(self) -> InvoiceScheduleResult:
        return self._result


def test_get_invoice_schedule_returns_current_values(admin_client):
    admin_client.use_cases.get_invoice_schedule = _FakeGetInvoiceSchedule(
        billing_day=5, invoice_due_days=10
    )

    r = admin_client.get(ROUTE)

    assert r.status_code == 200, r.text
    assert r.json() == {"billing_day": 5, "invoice_due_days": 10}


def test_get_invoice_schedule_wrong_persona_404(coach_on_admin_client):
    assert coach_on_admin_client.get(ROUTE).status_code == 404


def test_put_invoice_schedule_retired(admin_client):
    r = admin_client.put(ROUTE, json={"billing_day": 5, "invoice_due_days": 10})
    assert r.status_code in (404, 405), r.text
