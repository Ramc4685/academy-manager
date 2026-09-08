"""Autopay-facing composition helpers (issue #651), split out of
``composition/admin.py`` to keep that file inside its line budget.

- ``build_send_autopay_notice``: the pre-charge notice sent when a monthly
  invoice is generated for an autopay family, recording delivery on the
  invoice so the daily tick never sends it twice.
- ``build_dunning_worker``: the hourly autopay/dunning worker factory.
- ``autopay_active_enrollment_ids``: which of these enrollments will be
  auto-charged (used to keep "pay now" reminders away from autopay families).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from backend.v2.composition.email_adapters import InvoiceEmailAdapter
from backend.v2.contexts.billing.application.use_cases.charge_invoice_via_autopay import (
    ChargeInvoiceViaAutopay,
)
from backend.v2.contexts.billing.application.use_cases.process_dunning_retries import (
    ProcessDunningRetries,
)
from backend.v2.contexts.billing.domain.ledger import record_delivery
from backend.v2.shared.tenancy import current_academy_id
from backend.v2.shared.tenancy.academy_url import academy_frontend_url


def build_send_autopay_notice(
    *,
    ledger: Any,
    email_port: Callable[[], InvoiceEmailAdapter | None],
    academy_repo: Any,
    frontend_url: str,
) -> Callable[[str], Awaitable[dict[str, Any]]]:
    async def send_autopay_notice(invoice_id: str) -> dict[str, Any]:
        """Pre-charge notice for an autopay invoice (issue #651); marks delivery."""
        invoice = await ledger.get_invoice(invoice_id)
        if invoice is None:
            raise ValueError("invoice not found")
        port = email_port()
        if port is None:
            raise ValueError("email delivery is not enabled")
        academy_doc = await academy_repo.find_by_id(current_academy_id())
        academy_slug = str(academy_doc.get("slug") or "") if academy_doc else ""
        base = academy_frontend_url(frontend_url=frontend_url, academy_slug=academy_slug)
        provider_message_id = await port.send_autopay_notice(
            parent_id=invoice.parent_id,
            invoice_id=invoice.invoice_id,
            period=invoice.period,
            amount_cents=invoice.balance_due_cents,
            currency=invoice.currency,
            charge_on=invoice.due_date,
            portal_url=f"{base}/parent/payments" if base else None,
        )
        delivered = record_delivery(
            invoice, outcome="sent", now=datetime.now(UTC), provider_message_id=provider_message_id
        )
        await ledger.save_invoice(delivered)
        return {"invoice_id": invoice_id, "delivery_status": delivered.delivery_status}

    return send_autopay_notice


def build_dunning_worker(
    *,
    stripe: Any,
    dunning: Any,
    ledger: Any,
    enrollment_autopay: Any,
    settings: Any,
    connected_accounts: Any,
    email_port: Callable[[], InvoiceEmailAdapter | None],
    outbox: Any,
) -> Callable[[], ProcessDunningRetries]:
    def _dunning_worker() -> ProcessDunningRetries:
        required = ("get_default_payment_method", "create_off_session_payment_intent")
        if not all(hasattr(stripe, name) for name in required):
            raise RuntimeError("Stripe autopay not configured")
        return ProcessDunningRetries(
            dunning=dunning,
            charge_invoice=ChargeInvoiceViaAutopay(
                ledger=ledger,
                stripe=stripe,
                enrollment_autopay=enrollment_autopay,
                settings=settings,
                connected_accounts=connected_accounts,
            ),
            notifier=email_port(),
            enrollment_autopay=enrollment_autopay,
            # Issue #435: the failure notice goes through the outbox, so a
            # transient Resend error is retried by the dispatcher instead of
            # being logged once and losing the parent's only warning.
            outbox=outbox,
        )

    return _dunning_worker


async def autopay_active_enrollment_ids(
    db: Any, *, academy_id: str, enrollment_ids: list[str]
) -> set[str]:
    """Enrollments among ``enrollment_ids`` whose card will be auto-charged."""
    if not enrollment_ids:
        return set()
    found: set[str] = set()
    async for doc in db["student_billing_enrollments"].find(
        {
            "academy_id": academy_id,
            "enrollment_id": {"$in": enrollment_ids},
            "autopay_enrollment_status": "active",
        },
        {"enrollment_id": 1},
    ):
        found.add(str(doc.get("enrollment_id") or ""))
    return found
