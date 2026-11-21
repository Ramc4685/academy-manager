"""A negative owner adjustment reads as a discount on the family timeline (#1035)."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from backend.v2.contexts.billing.application.family_billing import AuditFacts, _audit_entries


def _added(amount_cents: int) -> AuditFacts:
    return AuditFacts(
        audit_id=f"baud-{amount_cents}",
        action="invoice_line_added",
        actor_id="owner-1",
        at=datetime(2026, 9, 1, tzinfo=UTC),
        invoice_id="inv-1",
        payment_id=None,
        reason="Coach child",
        before=None,
        after={"amount_cents": amount_cents},
    )


def test_negative_adjustment_is_a_discount_and_a_positive_one_a_charge() -> None:
    facts = SimpleNamespace(audit=(_added(-2_000), _added(1_500)))

    summaries = [entry["summary"] for entry in _audit_entries(facts)]  # type: ignore[arg-type]

    assert summaries == [
        "Discount added to invoice · Coach child",
        "Charge added to invoice · Coach child",
    ]
