"""SetEnrollmentBilling: validation and the edges the real-Mongo test skips."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from backend.v2.contexts.billing.application.use_cases.enrollment_not_billed import (
    EnrollmentNotFound,
    NotBilledValidationError,
    SetEnrollmentBilling,
    SetEnrollmentBillingCommand,
)
from backend.v2.contexts.billing.application.use_cases.money_setting_audit import (
    RecordMoneySettingChange,
)

pytestmark = pytest.mark.asyncio
NOW = datetime(2026, 11, 16, tzinfo=UTC)


class _Store:
    def __init__(self, doc: dict[str, Any] | None) -> None:
        self.doc = doc
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def get(self, enrollment_id: str) -> dict[str, Any] | None:
        return self.doc

    async def mark_not_billed(self, enrollment_id: str, **kwargs: Any) -> None:
        self.calls.append(("mark", kwargs))

    async def start_billing(self, enrollment_id: str, **kwargs: Any) -> None:
        self.calls.append(("start", kwargs))


class _Audit:
    def __init__(self) -> None:
        self.entries: list[Any] = []

    async def append(self, entry: Any) -> None:
        self.entries.append(entry)


class _Invoices:
    def __init__(self, invoices: list[Any]) -> None:
        self.invoices = invoices

    async def list_invoices_for_enrollment(self, enrollment_id: str) -> list[Any]:
        return self.invoices


class _Month:
    async def current_period(self) -> str:
        return "2026-11"


def _use_case(
    store: _Store, audit: _Audit, invoices: list[Any] | None = None, voided: list[str] | None = None
) -> SetEnrollmentBilling:
    async def void(*, invoice_id: str, reason: str, actor_id: str | None = None) -> None:
        (voided if voided is not None else []).append(invoice_id)

    return SetEnrollmentBilling(
        store=store,
        invoices=_Invoices(invoices or []),
        void_invoice=void,
        billing_month=_Month(),
        audit=RecordMoneySettingChange(audit=audit, now=lambda: NOW),  # type: ignore[arg-type]
        clock=lambda: NOW,
    )


def _cmd(**kwargs: Any) -> SetEnrollmentBillingCommand:
    return SetEnrollmentBillingCommand(enrollment_id="enr-1", actor_id="owner-1", **kwargs)


@pytest.mark.parametrize(
    ("reason", "note", "field"),
    [
        (None, None, "reason"),
        ("cousin", None, "reason"),
        ("other", "   ", "note"),
        ("scholarship", "x" * 501, "note"),
    ],
)
async def test_rejects_a_missing_reason_or_note(reason: Any, note: Any, field: str) -> None:
    store = _Store({"enrollment_id": "enr-1"})
    with pytest.raises(NotBilledValidationError) as err:
        await _use_case(store, _Audit()).execute(
            "acad", _cmd(not_billed=True, reason=reason, note=note)
        )
    assert err.value.field == field
    assert store.calls == []


async def test_unknown_enrollment_is_not_found() -> None:
    with pytest.raises(EnrollmentNotFound):
        await _use_case(_Store(None), _Audit()).execute(
            "acad", _cmd(not_billed=True, reason="owner_child")
        )


async def test_marking_again_keeps_the_type_recorded_first() -> None:
    store = _Store({"enrollment_id": "enr-1", "billing_type": "NoCharge"})
    await _use_case(store, _Audit()).execute("acad", _cmd(not_billed=True, reason="scholarship"))
    assert store.calls[0][1]["previous_billing_type"] is None


async def test_start_billing_a_billed_row_is_a_silent_no_op() -> None:
    store, audit = _Store({"enrollment_id": "enr-1", "billing_type": "Standard"}), _Audit()
    result = await _use_case(store, audit).execute("acad", _cmd(not_billed=False))
    assert result.not_billed is False
    assert store.calls == []
    assert audit.entries == []


async def test_start_billing_cannot_void() -> None:
    with pytest.raises(NotBilledValidationError):
        await _use_case(_Store({"billing_type": "NoCharge"}), _Audit()).execute(
            "acad", _cmd(not_billed=False, void_open_invoices=True)
        )


async def test_start_billing_restores_standard_when_nothing_was_recorded() -> None:
    store = _Store({"enrollment_id": "enr-1", "billing_type": "nocharge"})
    result = await _use_case(store, _Audit()).execute("acad", _cmd(not_billed=False))
    assert result.billing_type == "standard"
    assert store.calls == [
        (
            "start",
            {
                "billing_type": "standard",
                "skip_period": "2026-11",
                "actor_id": "owner-1",
                "at": NOW,
            },
        )
    ]


async def test_void_takes_unpaid_draft_and_open_only() -> None:
    def inv(invoice_id: str, status: str, balance: int = 100) -> SimpleNamespace:
        return SimpleNamespace(
            invoice_id=invoice_id, status=status, total_cents=100, balance_due_cents=balance
        )

    voided: list[str] = []
    result = await _use_case(
        _Store({"enrollment_id": "enr-1"}),
        _Audit(),
        [
            inv("d", "draft"),
            inv("o", "open"),
            inv("p", "open", 40),
            inv("v", "void"),
            inv("paid", "paid", 0),
        ],
        voided,
    ).execute("acad", _cmd(not_billed=True, reason="owner_child", void_open_invoices=True))

    assert voided == ["d", "o"]
    assert result.voided_invoice_ids == ["d", "o"]
    assert result.kept_invoice_ids == ["p"]


async def test_a_failed_void_is_kept_and_the_change_still_audited() -> None:
    async def boom(*, invoice_id: str, reason: str, actor_id: str | None = None) -> None:
        raise ValueError("money landed")

    audit = _Audit()
    use_case = _use_case(_Store({"enrollment_id": "enr-1"}), audit)
    use_case._void = boom  # type: ignore[method-assign]
    invoice = SimpleNamespace(invoice_id="o", status="open", total_cents=100, balance_due_cents=100)
    use_case._invoices = _Invoices([invoice])  # type: ignore[assignment]

    result = await use_case.execute(
        "acad", _cmd(not_billed=True, reason="coach_child", void_open_invoices=True)
    )

    assert result.kept_invoice_ids == ["o"]
    assert result.voided_invoice_ids == []
    assert len(audit.entries) == 1
