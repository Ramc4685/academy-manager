# backend/v2/tests/unit/test_draft_invoice_owes_nothing.py
"""One rule, four surfaces: an unsent draft owes nothing and was never billed.

A draft is the manual-invoicing working state (#722): the owner adds a charge
line, the ledger recomputes ``balance_due_cents``, and nothing is owed until
Send flips the invoice to ``open``. Month close, the Payments buckets, the
admin money helpers and the family page each derive "owed" separately, so this
test pins the same draft through all four and asserts they agree (#736).
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from backend.v2.contexts.billing.application import collections_buckets as buckets
from backend.v2.contexts.billing.application import family_billing as family
from backend.v2.contexts.billing.application.admin_money import invoice_outstanding_cents
from backend.v2.contexts.billing.application.month_close import (
    InvoiceFacts as MonthCloseInvoiceFacts,
)
from backend.v2.contexts.billing.application.month_close import (
    MonthCloseFacts,
    build_month_close_view,
)

PERIOD = "2026-09"
TODAY = date(2026, 9, 20)
DUE = date(2026, 9, 8)
NOW = datetime(2026, 9, 20, 15, 0, tzinfo=UTC)
CHARGE_CENTS = 5_000


def test_month_close_does_not_bill_or_chase_an_unsent_draft() -> None:
    view = build_month_close_view(
        MonthCloseFacts(
            period=PERIOD,
            today=TODAY,
            timezone="America/Chicago",
            generated_at=NOW,
            invoices=(
                MonthCloseInvoiceFacts(
                    invoice_id="inv-draft",
                    status="draft",
                    total_cents=CHARGE_CENTS,
                    paid_cents=0,
                    outstanding_cents=CHARGE_CENTS,
                    due_date=DUE,
                    parent_id="par-1",
                    parent_name="Priya Rao",
                    enrollment_id="enr-1",
                    # Paused + autopay-active: every odd check the draft could
                    # trip is armed, and none of them may fire on unsent money.
                    enrollment_status="paused",
                    autopay_enrollment_status="active",
                    has_card=False,
                    connected_account_ready=True,
                ),
            ),
            collected_cents=0,
        )
    )

    assert view["money"]["billed_cents"] == 0
    assert view["money"]["outstanding_cents"] == 0
    assert view["money"]["collection_rate"] is None
    assert {row["code"]: row["count"] for row in view["odd"]} == {
        row["code"]: 0 for row in view["odd"]
    }
    # A draft's due date must not pull the autopay run's charge date forward.
    assert view["autopay_run"]["charge_on"] is None
    assert view["autopay_run"]["has_run"] is False
    # The generation counts still see it: a draft exists, it was just not sent.
    assert view["invoices"]["generated"] == 0


def test_payments_buckets_do_not_chase_an_unsent_draft() -> None:
    row = buckets.classify_family(
        buckets.FamilyFacts(
            parent_id="par-1",
            parent_name="Priya Rao",
            parent_email="priya@example.com",
            students=(
                buckets.StudentFacts(
                    student_id="stu-1", name="Asha Rao", session_title="Juniors Tue/Thu"
                ),
            ),
            invoices=(
                buckets.InvoiceFacts(
                    invoice_id="inv-draft",
                    invoice_number="INV-0001",
                    period=PERIOD,
                    status="draft",
                    total_cents=CHARGE_CENTS,
                    balance_due_cents=CHARGE_CENTS,
                    due_date=DUE,
                    delivery_status="not_sent",
                    last_sent_at=None,
                    enrollment_id="enr-1",
                    student_id="stu-1",
                    autopay_enrollment_status="active",
                    dunning_status=None,
                    dunning_attempt_count=0,
                    dunning_next_attempt_at=None,
                    latest_attempt_status=None,
                    latest_attempt_reason=None,
                    paid_cents=0,
                    paid_method=None,
                    paid_at=None,
                ),
            ),
            leftover_balance_cents=0,
            paused=(),
            has_payment_method=True,
            card_last4="4242",
            connected_account_ready=True,
        ),
        today=TODAY,
    )

    assert row is not None
    assert row.bucket not in {"past_due", "awaiting", "failed_autopay", "autopay_scheduled"}
    assert row.payload["balance_cents"] == 0


def test_admin_money_reports_no_outstanding_on_a_draft() -> None:
    assert invoice_outstanding_cents({"status": "draft", "balance_due_cents": CHARGE_CENTS}) == 0


def test_family_page_reports_no_balance_on_a_draft() -> None:
    """The surface that already got it right — pinned so it stays the rule."""
    view = family.build_family_billing_view(
        family.FamilyFacts(
            parent=family.ParentFacts(
                parent_id="par-1", name="Priya Rao", email="priya@example.com", phone=None
            ),
            students=(
                family.StudentFacts(
                    student_id="stu-1",
                    name="Asha",
                    status="active",
                    enrollments=(
                        family.EnrollmentFacts(
                            enrollment_id="enr-1",
                            student_id="stu-1",
                            session_id="sess-1",
                            session_title="Juniors Tue/Thu",
                            schedule="Tue 18:15",
                            status="active",
                            monthly_price_cents=7000,
                            override_price_cents=None,
                            autopay_status="active",
                            recurring_discount=None,
                            resume_on=None,
                        ),
                    ),
                ),
            ),
            invoices=(
                family.InvoiceFacts(
                    invoice_id="inv-draft",
                    invoice_number="INV-0001",
                    period=PERIOD,
                    student_id="stu-1",
                    student_name="Asha",
                    enrollment_id="enr-1",
                    status="draft",
                    total_cents=CHARGE_CENTS,
                    balance_due_cents=CHARGE_CENTS,
                    due_date=DUE,
                    created_at=datetime(2026, 9, 1, 6, 0, tzinfo=UTC),
                    paid_at=None,
                    voided_at=None,
                    void_reason=None,
                    delivery_status="not_sent",
                    last_sent_at=None,
                    autopay_status="active",
                    allocations=(),
                    credits=(),
                ),
            ),
            attempts=(),
            dunning=(),
            audit=(),
            events=(),
            customer=family.CustomerFacts(
                has_card=True,
                card_last4="4242",
                card_label="Visa",
                last_invited_at=None,
                has_login_account=True,
            ),
            available_credit_cents=0,
            connected_account_ready=True,
            warnings=(),
        ),
        timezone="America/Chicago",
        generated_at=NOW,
        today=TODAY,
    )

    assert view["header"]["balance_cents"] == 0
    assert view["header"]["open_invoice_count"] == 0
