# backend/v2/tests/unit/test_family_billing.py
"""Pure rules for the Family billing view (spec 2026-09-05-family-billing §3.3, §3.4, §4)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from backend.v2.contexts.billing.application.autopay_eligibility import (
    ELIGIBLE,
    Eligibility,
)
from backend.v2.contexts.billing.application.family_billing import (
    AllocationFacts,
    AttemptFacts,
    AuditFacts,
    CustomerFacts,
    DunningFacts,
    EnrollmentFacts,
    EventFacts,
    FamilyFacts,
    InvoiceFacts,
    ParentFacts,
    StudentFacts,
    autopay_state,
    build_family_billing_view,
    build_timeline,
    family_actions,
    invoice_actions,
    strip_owner_actions,
)

ZONE = ZoneInfo("America/Chicago")
NOW = datetime(2026, 9, 10, 15, 0, tzinfo=UTC)
TODAY = date(2026, 9, 10)


def _enrollment(eid="e-1", autopay="active", status="active", **kw) -> EnrollmentFacts:
    base = dict(
        enrollment_id=eid,
        student_id="s-1",
        session_id="sess-1",
        session_title="Wed 6:15 Intermediate",
        schedule="Wed 18:15",
        status=status,
        monthly_price_cents=7000,
        override_price_cents=None,
        autopay_status=autopay,
        recurring_discount=None,
        resume_on=None,
    )
    base.update(kw)
    return EnrollmentFacts(**base)


def _invoice(iid="inv-1", status="open", balance=6000, allocations=(), **kw) -> InvoiceFacts:
    base = dict(
        invoice_id=iid,
        invoice_number=f"INV-{iid}",
        period="2026-09",
        student_id="s-1",
        student_name="Arjun",
        enrollment_id="e-1",
        status=status,
        total_cents=6000,
        balance_due_cents=balance,
        due_date=date(2026, 9, 8),
        created_at=datetime(2026, 9, 1, 6, 0, tzinfo=UTC),
        paid_at=None,
        voided_at=None,
        void_reason=None,
        delivery_status="sent",
        last_sent_at=datetime(2026, 9, 1, 6, 5, tzinfo=UTC),
        autopay_status="active",
        allocations=tuple(allocations),
        credits=(),
    )
    base.update(kw)
    return InvoiceFacts(**base)


def _alloc(payment_id="pay-1", stripe=True, method="card", amount=6000) -> AllocationFacts:
    return AllocationFacts(
        payment_id=payment_id,
        amount_cents=amount,
        method=method,
        paid_at=datetime(2026, 8, 4, 14, 0, tzinfo=UTC),
        stripe_payment_intent_id="pi_1" if stripe else None,
    )


def _facts(**kw) -> FamilyFacts:
    base = dict(
        parent=ParentFacts(
            parent_id="p-1", name="Sahaya Vinodh", email="s@example.com", phone=None
        ),
        students=(
            StudentFacts(
                student_id="s-1", name="Arjun", status="active", enrollments=(_enrollment(),)
            ),
        ),
        invoices=(_invoice(),),
        attempts=(),
        dunning=(),
        audit=(),
        events=(),
        customer=CustomerFacts(
            has_card=True,
            card_last4="4242",
            card_label="Visa",
            last_invited_at=None,
            has_login_account=True,
        ),
        available_credit_cents=0,
        connected_account_ready=True,
        warnings=(),
    )
    base.update(kw)
    return FamilyFacts(**base)


# ------------------------------------------------------------ autopay state


def test_autopay_state_on_partial_off_needs_consent() -> None:
    assert autopay_state([_enrollment(autopay="active")]) == "on"
    assert (
        autopay_state([_enrollment(autopay="active"), _enrollment("e-2", autopay="paused")])
        == "partial"
    )
    assert autopay_state([_enrollment(autopay="paused")]) == "off"
    assert (
        autopay_state([_enrollment(autopay="offered"), _enrollment("e-2", autopay="disabled")])
        == "needs_consent"
    )
    assert autopay_state([]) == "needs_consent"


def test_autopay_state_ignores_cancelled_enrollments() -> None:
    assert (
        autopay_state(
            [
                _enrollment(autopay="active"),
                _enrollment("e-2", autopay="paused", status="cancelled"),
            ]
        )
        == "on"
    )


# ------------------------------------------------------------ actions


def test_open_invoice_actions_with_eligible_card() -> None:
    assert invoice_actions(_invoice(), eligibility=ELIGIBLE) == [
        "send",
        "record_payment",
        "charge_card",
        "void",
        "discount_once",
    ]


def test_open_invoice_without_eligibility_has_no_charge_card() -> None:
    acts = invoice_actions(_invoice(), eligibility=Eligibility("ineligible", "no_card_on_file"))
    assert "charge_card" not in acts
    assert "void" in acts


def test_partially_paid_invoice_with_stripe_allocation_refunds_not_void() -> None:
    inv = _invoice(status="partially_paid", balance=1000, allocations=[_alloc(amount=5000)])
    acts = invoice_actions(inv, eligibility=ELIGIBLE)
    assert "refund" in acts
    assert "void" not in acts
    assert "record_payment" in acts


def test_paid_invoice_with_manual_allocation_has_no_refund() -> None:
    inv = _invoice(status="paid", balance=0, allocations=[_alloc(stripe=False, method="zelle")])
    assert (
        invoice_actions(inv, eligibility=Eligibility("ineligible", "invoice_not_chargeable")) == []
    )


def test_void_and_draft_invoices_have_no_actions() -> None:
    assert invoice_actions(_invoice(status="void", balance=0), eligibility=ELIGIBLE) == []
    assert invoice_actions(_invoice(status="draft"), eligibility=ELIGIBLE) == []


def test_family_actions() -> None:
    assert family_actions(state="on", has_card=True, invoices=[_invoice()]) == [
        "autopay_off",
        "send_invoice",
        "record_payment",
    ]
    assert family_actions(state="off", has_card=True, invoices=[]) == ["autopay_on"]
    assert family_actions(state="needs_consent", has_card=False, invoices=[]) == ["send_invite"]
    assert family_actions(state="partial", has_card=True, invoices=[_invoice()]) == [
        "autopay_on",
        "autopay_off",
        "send_invoice",
        "record_payment",
    ]


def test_strip_owner_actions_removes_void_refund_discount_everywhere() -> None:
    view = build_family_billing_view(
        _facts(), timezone="America/Chicago", generated_at=NOW, today=TODAY
    )
    assert "void" in view["invoices"][0]["actions"]
    stripped = strip_owner_actions(view)
    assert stripped["invoices"][0]["actions"] == ["send", "record_payment", "charge_card"]
    assert stripped["students"][0]["enrollments"][0]["actions"] == []
    assert view["students"][0]["enrollments"][0]["actions"] == ["recurring_discount"]


# ------------------------------------------------------------ timeline


def test_timeline_merges_sources_newest_first_and_mutes_comms() -> None:
    paid = _invoice(
        "inv-aug",
        status="paid",
        balance=0,
        period="2026-08",
        created_at=datetime(2026, 8, 1, 6, 0, tzinfo=UTC),
        paid_at=datetime(2026, 8, 4, 14, 0, tzinfo=UTC),
        allocations=[_alloc()],
        last_sent_at=datetime(2026, 8, 1, 6, 5, tzinfo=UTC),
    )
    void = _invoice(
        "inv-void",
        status="void",
        balance=0,
        student_name="Hannah",
        voided_at=datetime(2026, 9, 4, 20, 0, tzinfo=UTC),
        void_reason="enrollment paused",
        last_sent_at=None,
    )
    facts = _facts(
        invoices=(_invoice(), paid, void),
        attempts=(
            AttemptFacts(
                attempt_id="at-1",
                invoice_id="inv-1",
                status="declined",
                failure_message="Your card was declined.",
                amount_cents=6000,
                created_at=datetime(2026, 9, 8, 14, 0, tzinfo=UTC),
            ),
        ),
        dunning=(
            DunningFacts(
                invoice_id="inv-1",
                status="dunned",
                attempt_count=4,
                autopay_disabled_at=datetime(2026, 9, 9, 14, 0, tzinfo=UTC),
                last_notification_at=datetime(2026, 9, 8, 14, 1, tzinfo=UTC),
            ),
        ),
        audit=(
            AuditFacts(
                audit_id="a-1",
                action="autopay_paused",
                actor_id="admin-1",
                at=datetime(2026, 9, 4, 20, 1, tzinfo=UTC),
                invoice_id=None,
                payment_id=None,
                reason="parent asked",
                before=None,
                after=None,
            ),
        ),
        events=(
            EventFacts(
                event_id="ev-1",
                event_type="paused",
                enrollment_id="e-1",
                student_name="Hannah",
                occurred_at=datetime(2026, 9, 4, 19, 59, tzinfo=UTC),
                actor_id="admin-1",
                reason="travel",
                effective_at=datetime(2026, 10, 1, 5, 0, tzinfo=UTC),
            ),
        ),
    )

    timeline = build_timeline(facts, zone=ZONE)

    codes = [e["code"] for e in timeline]
    assert codes == [
        "autopay_disabled_by_ladder",
        "failure_notice_emailed",
        "charge_failed",
        "audit:autopay_paused",
        "invoice_voided",
        "enrollment:paused",
        "autopay_notice_emailed",  # inv-1 sent Sep 1 06:05
        "invoice_generated",  # inv-1 and inv-void both generated Sep 1 06:00
        "invoice_generated",
        "payment_received",  # Aug 4
        "autopay_notice_emailed",  # inv-aug sent Aug 1 06:05 (autopay active → notice)
        "invoice_generated",  # inv-aug generated Aug 1 06:00
    ]
    by_code = {e["code"]: e for e in timeline}
    assert (
        by_code["charge_failed"]["summary"]
        == "Card declined · $60 · attempt 1 · Your card was declined."
    )
    assert by_code["payment_received"]["summary"] == "$60 received · card ••4242"
    assert by_code["payment_received"]["kind"] == "money"
    assert by_code["autopay_notice_emailed"]["muted"] is True
    assert by_code["audit:autopay_paused"]["reason"] == "parent asked"
    assert by_code["audit:autopay_paused"]["kind"] == "admin"
    assert (
        by_code["invoice_voided"]["summary"]
        == "Sep 2026 invoice voided · Hannah · enrollment paused"
    )
    assert by_code["enrollment:paused"]["summary"] == "Hannah paused · resumes Oct 1"


def test_timeline_one_entry_per_payment_even_when_it_settles_two_invoices() -> None:
    a = _invoice("inv-a", status="paid", balance=0, allocations=[_alloc(amount=3000)])
    b = _invoice("inv-b", status="paid", balance=0, allocations=[_alloc(amount=3000)])
    timeline = build_timeline(_facts(invoices=(a, b)), zone=ZONE)
    received = [e for e in timeline if e["code"] == "payment_received"]
    assert len(received) == 1
    assert received[0]["amount_cents"] == 6000
    assert sorted(received[0]["invoice_ids"]) == ["inv-a", "inv-b"]


def test_timeline_is_capped() -> None:
    invoices = tuple(_invoice(f"inv-{i}", last_sent_at=None) for i in range(250))
    assert len(build_timeline(_facts(invoices=invoices), zone=ZONE)) == 200


# ------------------------------------------------------------ view


def test_view_header_next_charge_and_paid_cents() -> None:
    aug = _invoice("inv-aug", status="paid", balance=0, period="2026-08", allocations=[_alloc()])
    view = build_family_billing_view(
        _facts(invoices=(_invoice(), aug)),
        timezone="America/Chicago",
        generated_at=NOW,
        today=TODAY,
    )
    header = view["header"]
    assert header["balance_cents"] == 6000
    assert header["open_invoice_count"] == 1
    assert header["autopay"] == {
        "state": "on",
        "active_count": 1,
        "total_count": 1,
        "card_last4": "4242",
        "card_label": "Visa",
        "next_charge_on": "2026-09-08",
        "next_charge_invoice_id": "inv-1",
        "last_failure": None,
    }
    assert header["last_payment"] == {
        "amount_cents": 6000,
        "method": "card",
        "paid_at": "2026-08-04T14:00:00+00:00",
        "invoice_ids": ["inv-aug"],
    }
    assert header["registration"] == {
        "state": "registered",
        "card_on_file": True,
        "last_invited_at": None,
    }
    paid_row = next(i for i in view["invoices"] if i["invoice_id"] == "inv-aug")
    assert paid_row["paid_cents"] == 6000
    assert paid_row["settlement_unlinked"] is False
    assert view["actions"] == ["autopay_off", "send_invoice", "record_payment"]
    assert view["warnings"] == []


def test_view_unlinked_paid_invoice_reports_total_minus_balance() -> None:
    legacy = _invoice("inv-legacy", status="paid", balance=0, allocations=[])
    view = build_family_billing_view(
        _facts(invoices=(legacy,)), timezone="UTC", generated_at=NOW, today=TODAY
    )
    row = view["invoices"][0]
    assert row["paid_cents"] == 6000
    assert row["settlement_unlinked"] is True


def test_view_no_card_means_no_next_charge_and_invite_offered() -> None:
    facts = _facts(
        customer=CustomerFacts(
            has_card=False,
            card_last4=None,
            card_label=None,
            last_invited_at=None,
            has_login_account=False,
        )
    )
    view = build_family_billing_view(facts, timezone="UTC", generated_at=NOW, today=TODAY)
    assert view["header"]["autopay"]["next_charge_on"] is None
    assert view["header"]["registration"]["state"] == "not_invited"
    assert "send_invite" in view["actions"]
    assert "charge_card" not in view["invoices"][0]["actions"]
