from __future__ import annotations

from datetime import UTC, date, datetime

from backend.v2.contexts.billing.application.collections_buckets import (
    BUCKET_ACTIONS,
    BUCKET_ORDER,
    MAX_AUTOPAY_ATTEMPTS,
    FamilyFacts,
    FamilyRow,
    InvoiceFacts,
    PauseFacts,
    StudentFacts,
    build_collections_view,
    classify_family,
)

TODAY = date(2026, 9, 15)
PERIOD = "2026-09"
GENERATED_AT = datetime(2026, 9, 15, 14, 0, tzinfo=UTC)


def _invoice(**overrides) -> InvoiceFacts:
    kwargs = dict(
        invoice_id="inv-1",
        invoice_number="INV-0001",
        period=PERIOD,
        status="open",
        total_cents=12000,
        balance_due_cents=12000,
        due_date=date(2026, 9, 20),
        delivery_status="sent",
        last_sent_at=datetime(2026, 9, 1, 9, 0, tzinfo=UTC),
        enrollment_id="enr-1",
        student_id="stu-1",
        autopay_enrollment_status=None,
        dunning_status=None,
        dunning_attempt_count=0,
        dunning_next_attempt_at=None,
        latest_attempt_status=None,
        latest_attempt_reason=None,
        paid_cents=0,
        paid_method=None,
        paid_at=None,
    )
    kwargs.update(overrides)
    return InvoiceFacts(**kwargs)


def _student(student_id: str = "stu-1", name: str = "Asha Rao") -> StudentFacts:
    return StudentFacts(student_id=student_id, name=name, session_title="Juniors Tue/Thu")


def _family(**overrides) -> FamilyFacts:
    kwargs = dict(
        parent_id="par-1",
        parent_name="Priya Rao",
        parent_email="priya@example.com",
        students=(_student(),),
        invoices=(_invoice(),),
        leftover_balance_cents=0,
        paused=(),
        has_payment_method=True,
        card_last4="4242",
        connected_account_ready=True,
    )
    kwargs.update(overrides)
    return FamilyFacts(**kwargs)


def _autopay_invoice(**overrides) -> InvoiceFacts:
    return _invoice(autopay_enrollment_status="active", **overrides)


# --------------------------------------------------------------------------- constants


def test_bucket_order_and_actions_match_spec() -> None:
    assert BUCKET_ORDER == (
        "failed_autopay",
        "past_due",
        "awaiting",
        "autopay_scheduled",
        "paused",
        "paid",
    )
    assert BUCKET_ACTIONS == {
        "failed_autopay": ["message", "record_payment"],
        "past_due": ["send_reminder", "record_payment"],
        "awaiting": ["send_reminder", "record_payment"],
        "autopay_scheduled": ["skip_month"],
        "paused": ["resume"],
        "paid": [],
    }
    assert MAX_AUTOPAY_ATTEMPTS == 4


# --------------------------------------------------------------------------- one family per bucket


def test_failed_autopay_bucket_carries_failure_payload() -> None:
    family = _family(
        invoices=(
            _autopay_invoice(
                dunning_status="active",
                dunning_attempt_count=2,
                dunning_next_attempt_at=datetime(2026, 9, 18, 9, 0, tzinfo=UTC),
                latest_attempt_status="failed",
                latest_attempt_reason="card_declined",
            ),
        )
    )
    row = classify_family(family, today=TODAY)
    assert isinstance(row, FamilyRow)
    assert row.bucket == "failed_autopay"
    assert row.payload["failure"] == {
        "reason": "card_declined",
        "attempt_count": 2,
        "max_attempts": 4,
        "next_retry_on": "2026-09-18",
        "disabled": False,
    }
    assert row.payload["actions"] == ["message", "record_payment"]
    assert row.payload["balance_cents"] == 12000
    assert row.payload["parent_id"] == "par-1"
    assert row.payload["parent_name"] == "Priya Rao"
    assert row.payload["parent_email"] == "priya@example.com"


def test_dunned_family_is_failed_autopay_with_disabled_flag() -> None:
    family = _family(
        invoices=(
            _autopay_invoice(
                dunning_status="dunned",
                dunning_attempt_count=4,
                latest_attempt_reason="insufficient_funds",
            ),
        )
    )
    row = classify_family(family, today=TODAY)
    assert row is not None
    assert row.bucket == "failed_autopay"
    assert row.payload["failure"]["disabled"] is True
    assert row.payload["failure"]["next_retry_on"] is None
    assert row.payload["failure"]["attempt_count"] == 4


def test_past_due_bucket_when_not_eligible_and_due_date_passed() -> None:
    family = _family(
        invoices=(
            _invoice(
                due_date=date(2026, 9, 5),
                last_sent_at=datetime(2026, 9, 10, 9, 0, tzinfo=UTC),
            ),
        )
    )
    row = classify_family(family, today=TODAY)
    assert row is not None
    assert row.bucket == "past_due"
    assert row.payload["actions"] == ["send_reminder", "record_payment"]
    # days late are computed by the caller from the row's due_date
    assert row.payload["invoices"][0]["due_date"] == "2026-09-05"
    assert row.payload["last_reminder_at"] == "2026-09-10T09:00:00+00:00"
    assert row.payload["autopay"] is None
    assert row.payload["failure"] is None
    assert row.payload["paid"] is None


def test_awaiting_bucket_when_not_eligible_and_due_today_or_later() -> None:
    family = _family(invoices=(_invoice(due_date=TODAY),))
    row = classify_family(family, today=TODAY)
    assert row is not None
    assert row.bucket == "awaiting"
    assert row.payload["actions"] == ["send_reminder", "record_payment"]
    assert row.payload["invoices"][0]["delivery_status"] == "sent"


def test_autopay_scheduled_bucket_carries_autopay_payload() -> None:
    family = _family(
        invoices=(
            _autopay_invoice(
                invoice_id="inv-late",
                due_date=date(2026, 9, 25),
                last_sent_at=None,
            ),
            _autopay_invoice(
                invoice_id="inv-early",
                due_date=date(2026, 9, 20),
                last_sent_at=datetime(2026, 9, 2, 9, 0, tzinfo=UTC),
            ),
        )
    )
    row = classify_family(family, today=TODAY)
    assert row is not None
    assert row.bucket == "autopay_scheduled"
    assert row.payload["autopay"] == {
        "status": "eligible",
        "card_last4": "4242",
        "charge_on": "2026-09-20",
        "notice_sent_at": "2026-09-02T09:00:00+00:00",
    }
    assert row.payload["actions"] == ["skip_month"]
    assert row.payload["balance_cents"] == 24000


def test_paused_family_with_leftover_balance() -> None:
    family = _family(
        invoices=(),
        leftover_balance_cents=4500,
        paused=(
            PauseFacts(
                enrollment_id="enr-9",
                student_name="Asha Rao",
                session_title="Juniors Tue/Thu",
                resume_on=date(2026, 10, 1),
                review_on=None,
            ),
        ),
    )
    row = classify_family(family, today=TODAY)
    assert row is not None
    assert row.bucket == "paused"
    assert row.payload["pause"] == {
        "enrollment_id": "enr-9",
        "resume_on": "2026-10-01",
        "review_on": None,
        "session_title": "Juniors Tue/Thu",
        "student_name": "Asha Rao",
    }
    assert row.payload["leftover_balance_cents"] == 4500
    assert row.payload["balance_cents"] == 0
    assert row.payload["actions"] == ["resume"]


def test_paid_bucket_uses_allocation_facts_when_present() -> None:
    family = _family(
        invoices=(
            _invoice(
                status="paid",
                balance_due_cents=0,
                paid_cents=12000,
                paid_method="card",
                paid_at=datetime(2026, 9, 3, 15, 0, tzinfo=UTC),
            ),
        )
    )
    row = classify_family(family, today=TODAY)
    assert row is not None
    assert row.bucket == "paid"
    assert row.payload["paid"] == {
        "amount_cents": 12000,
        "method": "card",
        "paid_at": "2026-09-03T15:00:00+00:00",
    }
    assert row.payload["actions"] == []


def test_paid_bucket_falls_back_to_total_minus_balance_without_allocations() -> None:
    family = _family(invoices=(_invoice(status="paid", balance_due_cents=0),))
    row = classify_family(family, today=TODAY)
    assert row is not None
    assert row.bucket == "paid"
    assert row.payload["paid"] == {"amount_cents": 12000, "method": None, "paid_at": None}


# --------------------------------------------------------------------------- precedence and edge cases


def test_failed_attempt_beats_autopay_scheduled() -> None:
    family = _family(
        invoices=(
            _autopay_invoice(invoice_id="inv-ok", due_date=date(2026, 9, 25)),
            _autopay_invoice(
                invoice_id="inv-failed",
                dunning_status="processing",
                dunning_attempt_count=1,
                latest_attempt_reason="card_declined",
            ),
        )
    )
    row = classify_family(family, today=TODAY)
    assert row is not None
    assert row.bucket == "failed_autopay"
    assert row.payload["failure"]["reason"] == "card_declined"


def test_active_ladder_with_no_attempt_yet_is_not_a_failure() -> None:
    family = _family(invoices=(_autopay_invoice(dunning_status="active", dunning_attempt_count=0),))
    row = classify_family(family, today=TODAY)
    assert row is not None
    assert row.bucket == "autopay_scheduled"


def test_two_students_produce_one_family_row() -> None:
    family = _family(
        students=(_student("stu-1", "Asha Rao"), _student("stu-2", "Dev Rao")),
        invoices=(
            _invoice(invoice_id="inv-1", student_id="stu-1", due_date=date(2026, 9, 5)),
            _invoice(
                invoice_id="inv-2",
                student_id="stu-2",
                balance_due_cents=8000,
                total_cents=8000,
                due_date=date(2026, 9, 25),
            ),
        ),
    )
    row = classify_family(family, today=TODAY)
    assert row is not None
    assert row.bucket == "past_due"
    assert [s["student_id"] for s in row.payload["students"]] == ["stu-1", "stu-2"]
    assert [i["invoice_id"] for i in row.payload["invoices"]] == ["inv-1", "inv-2"]
    assert row.payload["balance_cents"] == 20000


def test_family_with_only_a_void_invoice_has_no_bucket() -> None:
    family = _family(invoices=(_invoice(status="void", balance_due_cents=0),))
    assert classify_family(family, today=TODAY) is None


def test_family_with_nothing_has_no_bucket() -> None:
    assert classify_family(_family(invoices=()), today=TODAY) is None


def test_paused_beats_paid_when_family_has_paid_invoice_and_pause() -> None:
    family = _family(
        invoices=(_invoice(status="paid", balance_due_cents=0),),
        paused=(
            PauseFacts(
                enrollment_id="enr-9",
                student_name="Asha Rao",
                session_title=None,
                resume_on=None,
                review_on=date(2026, 9, 30),
            ),
        ),
    )
    row = classify_family(family, today=TODAY)
    assert row is not None
    assert row.bucket == "paused"


def test_draft_with_balance_counts_for_awaiting_but_never_failed_autopay() -> None:
    family = _family(
        invoices=(
            _autopay_invoice(
                status="draft",
                dunning_status="active",
                dunning_attempt_count=2,
                latest_attempt_reason="card_declined",
            ),
        )
    )
    row = classify_family(family, today=TODAY)
    assert row is not None
    assert row.bucket == "awaiting"


def test_autopay_active_but_no_card_is_awaiting_with_flag() -> None:
    family = _family(has_payment_method=False, card_last4=None, invoices=(_autopay_invoice(),))
    row = classify_family(family, today=TODAY)
    assert row is not None
    assert row.bucket == "awaiting"
    assert row.payload["autopay"] == {
        "status": "no_card_on_file",
        "card_last4": None,
        "charge_on": "2026-09-20",
        "notice_sent_at": "2026-09-01T09:00:00+00:00",
    }


def test_autopay_active_but_unknown_card_state_is_awaiting_with_flag() -> None:
    family = _family(has_payment_method=None, card_last4=None, invoices=(_autopay_invoice(),))
    row = classify_family(family, today=TODAY)
    assert row is not None
    assert row.bucket == "awaiting"
    assert row.payload["autopay"]["status"] == "card_state_unknown"


def test_autopay_active_but_no_card_and_overdue_is_past_due_with_flag() -> None:
    family = _family(
        has_payment_method=False,
        invoices=(_autopay_invoice(due_date=date(2026, 9, 1)),),
    )
    row = classify_family(family, today=TODAY)
    assert row is not None
    assert row.bucket == "past_due"
    assert row.payload["autopay"]["status"] == "no_card_on_file"


def test_owing_row_without_autopay_enrollment_has_no_autopay_payload() -> None:
    row = classify_family(_family(), today=TODAY)
    assert row is not None
    assert row.payload["autopay"] is None


def test_partial_payment_in_owing_bucket_still_reports_paid_facts() -> None:
    family = _family(
        invoices=(
            _invoice(
                status="partially_paid",
                balance_due_cents=7000,
                paid_cents=5000,
                paid_method="cash",
                paid_at=datetime(2026, 9, 4, 12, 0, tzinfo=UTC),
            ),
        )
    )
    row = classify_family(family, today=TODAY)
    assert row is not None
    assert row.bucket == "awaiting"
    assert row.payload["balance_cents"] == 7000
    assert row.payload["paid"] == {
        "amount_cents": 5000,
        "method": "cash",
        "paid_at": "2026-09-04T12:00:00+00:00",
    }


# --------------------------------------------------------------------------- build_collections_view


def _families_one_per_bucket() -> list[FamilyFacts]:
    return [
        _family(
            parent_id="p-failed",
            invoices=(
                _autopay_invoice(
                    dunning_status="active",
                    dunning_attempt_count=1,
                    latest_attempt_reason="card_declined",
                    balance_due_cents=1000,
                    total_cents=1000,
                ),
            ),
        ),
        _family(
            parent_id="p-past",
            invoices=(
                _invoice(due_date=date(2026, 9, 1), balance_due_cents=2000, total_cents=2000),
            ),
        ),
        _family(
            parent_id="p-await",
            invoices=(_invoice(balance_due_cents=3000, total_cents=3000),),
        ),
        _family(
            parent_id="p-auto",
            invoices=(_autopay_invoice(balance_due_cents=4000, total_cents=4000),),
        ),
        _family(
            parent_id="p-paused",
            invoices=(),
            leftover_balance_cents=500,
            paused=(
                PauseFacts(
                    enrollment_id="enr-p",
                    student_name="Asha Rao",
                    session_title=None,
                    resume_on=None,
                    review_on=None,
                ),
            ),
        ),
        _family(
            parent_id="p-paid",
            invoices=(
                _invoice(
                    status="paid",
                    balance_due_cents=0,
                    total_cents=6000,
                    paid_cents=6000,
                    paid_method="card",
                    paid_at=datetime(2026, 9, 2, tzinfo=UTC),
                ),
            ),
        ),
    ]


def test_build_view_orders_buckets_and_computes_totals() -> None:
    view = build_collections_view(
        _families_one_per_bucket(),
        period=PERIOD,
        today=TODAY,
        timezone="America/Chicago",
        generated_at=GENERATED_AT,
    )
    assert view["period"] == PERIOD
    assert view["timezone"] == "America/Chicago"
    assert view["generated_at"] == GENERATED_AT.isoformat()
    assert [b["key"] for b in view["buckets"]] == list(BUCKET_ORDER)
    by_key = {b["key"]: b for b in view["buckets"]}
    assert by_key["failed_autopay"]["count"] == 1
    assert by_key["failed_autopay"]["total_cents"] == 1000
    assert by_key["past_due"]["total_cents"] == 2000
    assert by_key["awaiting"]["total_cents"] == 3000
    assert by_key["autopay_scheduled"]["total_cents"] == 4000
    assert by_key["paused"]["families"][0]["parent_id"] == "p-paused"
    assert by_key["paid"]["families"][0]["paid"]["amount_cents"] == 6000
    assert view["totals"] == {
        "owed_cents": 6000,
        "autopay_scheduled_cents": 4000,
        "autopay_scheduled_count": 1,
        "needs_action_count": 2,
        "collected_cents": 6000,
    }
    assert "unclassified" not in view


def test_build_view_includes_empty_buckets_with_zero_count() -> None:
    view = build_collections_view(
        [], period=PERIOD, today=TODAY, timezone="UTC", generated_at=GENERATED_AT
    )
    assert [b["key"] for b in view["buckets"]] == list(BUCKET_ORDER)
    for bucket in view["buckets"]:
        assert bucket["count"] == 0
        assert bucket["total_cents"] == 0
        assert bucket["families"] == []
    assert view["totals"] == {
        "owed_cents": 0,
        "autopay_scheduled_cents": 0,
        "autopay_scheduled_count": 0,
        "needs_action_count": 0,
        "collected_cents": 0,
    }


def test_build_view_skips_unbucketed_families() -> None:
    view = build_collections_view(
        [_family(invoices=())],
        period=PERIOD,
        today=TODAY,
        timezone="UTC",
        generated_at=GENERATED_AT,
    )
    assert all(b["count"] == 0 for b in view["buckets"])


def test_build_view_collected_counts_partial_payments_in_owing_buckets() -> None:
    family = _family(
        invoices=(
            _invoice(
                status="partially_paid",
                balance_due_cents=7000,
                paid_cents=5000,
                paid_method="cash",
                paid_at=datetime(2026, 9, 4, tzinfo=UTC),
            ),
        )
    )
    view = build_collections_view(
        [family], period=PERIOD, today=TODAY, timezone="UTC", generated_at=GENERATED_AT
    )
    assert view["totals"]["owed_cents"] == 7000
    assert view["totals"]["collected_cents"] == 5000


def test_build_view_only_includes_unclassified_when_passed() -> None:
    unclassified = [{"parent_id": "p-x", "reason": "no_parent_doc"}]
    view = build_collections_view(
        [],
        period=PERIOD,
        today=TODAY,
        timezone="UTC",
        generated_at=GENERATED_AT,
        unclassified=unclassified,
    )
    assert view["unclassified"] == unclassified

    view_empty_list = build_collections_view(
        [],
        period=PERIOD,
        today=TODAY,
        timezone="UTC",
        generated_at=GENERATED_AT,
        unclassified=[],
    )
    assert view_empty_list["unclassified"] == []
