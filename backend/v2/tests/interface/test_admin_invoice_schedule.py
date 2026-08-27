"""Admin routes for the automated monthly-invoicing schedule (issue #288)."""

from __future__ import annotations

from typing import Any

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


class _FakeSetInvoiceSchedule:
    def __init__(self) -> None:
        self.commands: list[Any] = []

    async def execute(self, cmd: Any) -> InvoiceScheduleResult:
        self.commands.append(cmd)
        return InvoiceScheduleResult(
            billing_day=cmd.billing_day, invoice_due_days=cmd.invoice_due_days
        )


def test_get_invoice_schedule_returns_current_values(admin_client):
    admin_client.use_cases.get_invoice_schedule = _FakeGetInvoiceSchedule(
        billing_day=5, invoice_due_days=10
    )

    r = admin_client.get(ROUTE)

    assert r.status_code == 200, r.text
    assert r.json() == {"billing_day": 5, "invoice_due_days": 10}


def test_set_invoice_schedule_passes_actor_and_reason_to_the_use_case(admin_client):
    """The audit trail is only as good as the actor the route forwards, so the
    caller's identity must come from the verified claims, never the body."""
    use_case = _FakeSetInvoiceSchedule()
    admin_client.use_cases.set_invoice_schedule = use_case

    r = admin_client.put(
        ROUTE,
        json={"billing_day": 5, "invoice_due_days": 10, "reason": "align with payroll"},
    )

    assert r.status_code == 200, r.text
    assert r.json() == {"billing_day": 5, "invoice_due_days": 10}
    cmd = use_case.commands[0]
    assert (cmd.billing_day, cmd.invoice_due_days) == (5, 10)
    assert cmd.reason == "align with payroll"
    assert cmd.actor_id


def test_set_invoice_schedule_rejects_day_that_does_not_exist_in_february(admin_client):
    use_case = _FakeSetInvoiceSchedule()
    admin_client.use_cases.set_invoice_schedule = use_case

    r = admin_client.put(ROUTE, json={"billing_day": 31, "invoice_due_days": 7})

    assert r.status_code == 422, r.text
    assert use_case.commands == []


def test_set_invoice_schedule_rejects_negative_grace_window(admin_client):
    use_case = _FakeSetInvoiceSchedule()
    admin_client.use_cases.set_invoice_schedule = use_case

    r = admin_client.put(ROUTE, json={"billing_day": 1, "invoice_due_days": -1})

    assert r.status_code == 422, r.text
    assert use_case.commands == []


def test_get_invoice_schedule_wrong_persona_404(coach_on_admin_client):
    assert coach_on_admin_client.get(ROUTE).status_code == 404


def test_set_invoice_schedule_wrong_persona_404(coach_on_admin_client):
    r = coach_on_admin_client.put(ROUTE, json={"billing_day": 5, "invoice_due_days": 10})
    assert r.status_code == 404
