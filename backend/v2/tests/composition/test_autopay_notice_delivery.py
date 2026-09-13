"""The autopay pre-charge notice records WHICH message it sent (issue #692).

Month close and the family timeline used to re-derive "invoice email" vs
"autopay notice" from the enrollment's *current* autopay status, so a family
that changed autopay after the send silently moved between columns. The
notice hook now stamps the kind on the invoice at send time.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

import pytest
from backend.v2.composition.autopay_comms import build_send_autopay_notice
from backend.v2.contexts.billing.domain.ledger import LedgerInvoice
from backend.v2.shared.tenancy import tenant_scope

pytestmark = pytest.mark.asyncio

NOW = datetime(2026, 9, 1, 6, 5, tzinfo=UTC)


def _invoice() -> LedgerInvoice:
    return LedgerInvoice(
        invoice_id="inv-1",
        academy_id="acad-1",
        parent_id="parent-1",
        student_id="s-1",
        enrollment_id="e-1",
        period="2026-09",
        status="open",
        subtotal_cents=7_000,
        discount_cents=0,
        total_cents=7_000,
        balance_due_cents=7_000,
        currency="usd",
        due_date=date(2026, 9, 8),
        created_at=NOW,
        updated_at=NOW,
    )


class _FakeLedger:
    def __init__(self) -> None:
        self.invoice = _invoice()
        self.saved: list[LedgerInvoice] = []

    async def get_invoice(self, invoice_id: str) -> LedgerInvoice | None:
        return self.invoice if invoice_id == self.invoice.invoice_id else None

    async def save_invoice(self, invoice: LedgerInvoice) -> LedgerInvoice:
        self.saved.append(invoice)
        self.invoice = invoice
        return invoice


class _FakePort:
    async def send_autopay_notice(self, **kwargs: Any) -> str:
        return "re_notice_1"


class _FakeAcademyRepo:
    async def find_by_id(self, academy_id: str) -> dict[str, Any]:
        return {"slug": "blno"}


async def test_autopay_notice_stamps_the_autopay_notice_kind() -> None:
    ledger = _FakeLedger()
    send = build_send_autopay_notice(
        ledger=ledger,
        email_port=lambda: _FakePort(),
        academy_repo=_FakeAcademyRepo(),
        frontend_url="https://app.test",
    )

    with tenant_scope("acad-1"):
        result = await send("inv-1")

    assert result["delivery_status"] == "sent"
    assert ledger.saved[-1].delivery_kind == "autopay_notice"
    assert ledger.saved[-1].email_provider_message_id == "re_notice_1"
