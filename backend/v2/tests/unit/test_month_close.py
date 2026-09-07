"""Unit tests for the pure Month close shaping (spec §4.3, §9).

No Mongo, no clock: every case is a hand-built ``InvoiceFacts`` set, which is
the point of keeping the rules out of the read model.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from backend.v2.contexts.billing.application.month_close import (
    MAX_ODD_ITEMS,
    InvoiceFacts,
    MonthCloseFacts,
    build_autopay_run_section,
    build_invoices_section,
    build_money_section,
    build_month_close_view,
    build_odd_section,
)

TODAY = date(2026, 9, 20)
CHARGE_ON = date(2026, 9, 8)
GENERATED_AT = datetime(2026, 9, 20, 15, 0, tzinfo=UTC)


def inv(invoice_id: str = "inv-1", **kwargs: object) -> InvoiceFacts:
    defaults: dict[str, object] = {
        "status": "open",
        "total_cents": 10_000,
        "paid_cents": 0,
        "outstanding_cents": 10_000,
        "due_date": CHARGE_ON,
        "parent_id": "par-1",
        "parent_name": "Parent One",
        "enrollment_id": "enr-1",
        "enrollment_status": "active",
        "has_card": True,
        "connected_account_ready": True,
    }
    defaults.update(kwargs)
    return InvoiceFacts(invoice_id=invoice_id, **defaults)  # type: ignore[arg-type]


def odd(rows: list[dict[str, object]], code: str) -> dict[str, object]:
    return next(row for row in rows if row["code"] == code)


# --------------------------------------------------------------------- invoices


def test_generated_excludes_drafts_but_counts_voids() -> None:
    section = build_invoices_section([inv("a"), inv("b", status="draft"), inv("c", status="void")])

    assert section["generated"] == 2


def test_the_emailed_notice_split_comes_from_current_autopay_status() -> None:
    """The message kind is not persisted, so it is re-derived (§4.3 note)."""
    section = build_invoices_section(
        [
            inv("a", delivery_status="sent", autopay_enrollment_status="active"),
            inv("b", delivery_status="sent", autopay_enrollment_status="paused"),
            inv("c", delivery_status="sent", autopay_enrollment_status=None),
        ]
    )

    assert section["autopay_notices"] == 1
    assert section["emailed"] == 2
    assert section["emailed"] + section["autopay_notices"] == 3


def test_not_sent_counts_failures_too_and_ignores_drafts() -> None:
    section = build_invoices_section(
        [
            inv("a", delivery_status="not_sent"),
            inv("b", delivery_status="delivery_failed"),
            inv("c", delivery_status="sent"),
            inv("d", status="draft", delivery_status="not_sent"),
        ]
    )

    assert section["not_sent"] == 2


def test_void_reasons_are_grouped_so_a_void_count_is_always_explainable() -> None:
    section = build_invoices_section(
        [
            inv("a", status="void", void_reason="duplicate", total_cents=5_000),
            inv("b", status="void", void_reason="duplicate", total_cents=5_000),
            inv("c", status="void", void_reason="withdrawn", total_cents=1_000),
            inv("d", status="void", void_reason=None, total_cents=100),
        ]
    )

    assert section["voided"] == 4
    assert section["voided_cents"] == 11_100
    assert section["void_reasons"] == [
        {"reason": "duplicate", "count": 2},
        {"reason": "unspecified", "count": 1},
        {"reason": "withdrawn", "count": 1},
    ]


# ------------------------------------------------------------------------ money


def test_billed_and_outstanding_skip_voided_invoices() -> None:
    section = build_money_section(
        [
            inv("a", paid_cents=4_000, outstanding_cents=6_000),
            inv("b", status="void", paid_cents=0, outstanding_cents=9_000),
        ],
        collected_cents=4_000,
    )

    assert section["billed_cents"] == 10_000
    assert section["outstanding_cents"] == 6_000
    assert section["collection_rate"] == 0.4


def test_collection_rate_is_null_not_zero_when_nothing_was_billed() -> None:
    section = build_money_section([], collected_cents=0)

    assert section["billed_cents"] == 0
    assert section["collection_rate"] is None


def test_collection_rate_is_capped_at_one() -> None:
    section = build_money_section(
        [inv("a", paid_cents=10_000, outstanding_cents=0)], collected_cents=25_000
    )

    assert section["collection_rate"] == 1.0


# ------------------------------------------------------------------ autopay run


def test_before_the_charge_date_the_run_has_not_happened() -> None:
    section = build_autopay_run_section(
        [inv("a", autopay_enrollment_status="active")], today=date(2026, 9, 1)
    )

    assert section["has_run"] is False
    assert section["charge_on"] == "2026-09-08"
    assert section["pending"] == {"count": 1, "cents": 10_000}
    assert section["scheduled"] == {"count": 1, "cents": 10_000}
    assert section["succeeded"]["count"] == 0
    assert section["failed"]["count"] == 0


def test_after_the_charge_date_the_three_tallies_partition_the_run() -> None:
    section = build_autopay_run_section(
        [
            inv(
                "ok",
                autopay_enrollment_status="active",
                status="paid",
                paid_cents=10_000,
                outstanding_cents=0,
                has_charge_attempt=True,
                has_succeeded_attempt=True,
            ),
            inv(
                "bad",
                autopay_enrollment_status="active",
                has_charge_attempt=True,
                dunning_status="active",
                dunning_attempt_count=2,
            ),
            inv("todo", autopay_enrollment_status="active"),
            # Not autopay — never part of the run.
            inv("manual", autopay_enrollment_status="paused"),
        ],
        today=TODAY,
    )

    assert section["has_run"] is True
    assert section["succeeded"] == {"count": 1, "cents": 10_000}
    assert section["failed"] == {"count": 1, "cents": 10_000}
    assert section["pending"] == {"count": 1, "cents": 10_000}
    assert section["scheduled"] == {"count": 3, "cents": 30_000}


def test_a_dunned_ladder_counts_as_failed_even_with_no_attempt_count() -> None:
    section = build_autopay_run_section(
        [inv("a", autopay_enrollment_status="active", dunning_status="dunned")], today=TODAY
    )

    assert section["failed"]["count"] == 1


def test_a_resolved_ladder_is_not_a_failure() -> None:
    section = build_autopay_run_section(
        [
            inv(
                "a",
                autopay_enrollment_status="active",
                dunning_status="resolved",
                dunning_attempt_count=1,
                has_charge_attempt=True,
                has_succeeded_attempt=True,
                paid_cents=10_000,
                outstanding_cents=0,
                status="paid",
            )
        ],
        today=TODAY,
    )

    assert section["failed"]["count"] == 0
    assert section["succeeded"]["count"] == 1


def test_pending_never_promises_a_charge_the_worker_would_skip() -> None:
    """No card on file → not eligible → not pending, even with autopay on."""
    section = build_autopay_run_section(
        [inv("a", autopay_enrollment_status="active", has_card=False)], today=date(2026, 9, 1)
    )

    assert section["pending"]["count"] == 0
    assert section["scheduled"]["count"] == 0


def test_mixed_due_dates_report_the_earliest_and_flag_the_rest() -> None:
    section = build_autopay_run_section(
        [
            inv("a", autopay_enrollment_status="active"),
            inv("b", autopay_enrollment_status="active", due_date=date(2026, 9, 22)),
        ],
        today=TODAY,
    )

    assert section["charge_on"] == "2026-09-08"
    assert section["charge_on_varies"] is True
    # Tallies span every autopay invoice, later due date included.
    assert section["scheduled"]["count"] == 2


def test_a_period_with_no_invoices_has_no_charge_date() -> None:
    section = build_autopay_run_section([], today=TODAY)

    assert section["charge_on"] is None
    assert section["has_run"] is False
    assert section["scheduled"] == {"count": 0, "cents": 0}


# -------------------------------------------------------------------------- odd


def test_all_four_checks_render_even_when_everything_is_fine() -> None:
    rows = build_odd_section([inv("a")])

    assert [row["code"] for row in rows] == [
        "invoice_without_enrollment",
        "paused_family_invoiced",
        "autopay_no_card",
        "autopay_on_dead_enrollment",
    ]
    assert all(row["count"] == 0 for row in rows)


def test_invoice_without_enrollment_catches_missing_and_dangling_ids() -> None:
    rows = build_odd_section(
        [
            inv("none", enrollment_id=None),
            inv("dangling", enrollment_id="enr-gone", enrollment_found=False),
            inv("fine"),
        ]
    )
    row = odd(rows, "invoice_without_enrollment")

    assert row["count"] == 2
    assert {item["id"] for item in row["items"]} == {"none", "dangling"}
    assert row["items"][0]["kind"] == "invoice"
    assert row["items"][0]["href"] == "/admin/families/par-1"


def test_a_voided_invoice_is_never_odd() -> None:
    rows = build_odd_section([inv("a", status="void", enrollment_id=None)])

    assert odd(rows, "invoice_without_enrollment")["count"] == 0


def test_paused_family_invoiced_needs_a_balance() -> None:
    rows = build_odd_section(
        [
            inv("owing", enrollment_status="paused"),
            inv(
                "settled",
                invoice_number=None,
                enrollment_status="paused",
                parent_id="par-2",
                outstanding_cents=0,
                paid_cents=10_000,
                status="paid",
            ),
        ]
    )
    row = odd(rows, "paused_family_invoiced")

    assert row["count"] == 1
    assert row["items"][0]["kind"] == "family"
    assert row["items"][0]["label"] == "Parent One"


def test_autopay_no_card_fires_only_when_the_card_state_is_known() -> None:
    facts = [inv("a", autopay_enrollment_status="active", has_card=False)]

    assert odd(build_odd_section(facts), "autopay_no_card")["count"] == 1
    assert odd(build_odd_section(facts, card_state_known=False), "autopay_no_card")["count"] == 0


def test_autopay_no_card_ignores_an_unknown_card_on_a_single_family() -> None:
    rows = build_odd_section([inv("a", autopay_enrollment_status="active", has_card=None)])

    assert odd(rows, "autopay_no_card")["count"] == 0


def test_autopay_on_dead_enrollment_covers_cancelled_and_withdrawn() -> None:
    rows = build_odd_section(
        [
            inv("a", autopay_enrollment_status="active", enrollment_status="cancelled"),
            inv(
                "b",
                autopay_enrollment_status="active",
                enrollment_status="withdrawn",
                parent_id="par-2",
                parent_name="Parent Two",
            ),
            inv(
                "c",
                autopay_enrollment_status="active",
                enrollment_status="active",
                parent_id="par-3",
            ),
            inv(
                "d",
                autopay_enrollment_status="paused",
                enrollment_status="cancelled",
                parent_id="par-4",
            ),
        ]
    )
    row = odd(rows, "autopay_on_dead_enrollment")

    assert row["count"] == 2
    assert {item["label"] for item in row["items"]} == {"Parent One", "Parent Two"}


def test_a_family_with_two_bad_invoices_is_listed_once() -> None:
    rows = build_odd_section(
        [
            inv("a", enrollment_status="paused"),
            inv("b", enrollment_status="paused"),
        ]
    )

    assert odd(rows, "paused_family_invoiced")["count"] == 1


def test_items_truncate_at_twenty_but_the_count_stays_true() -> None:
    rows = build_odd_section(
        [inv(f"inv-{n}", enrollment_id=None) for n in range(MAX_ODD_ITEMS + 5)]
    )
    row = odd(rows, "invoice_without_enrollment")

    assert row["count"] == MAX_ODD_ITEMS + 5
    assert len(row["items"]) == MAX_ODD_ITEMS


# ------------------------------------------------------------------- whole view


def test_the_view_carries_every_section_and_its_warnings() -> None:
    view = build_month_close_view(
        MonthCloseFacts(
            period="2026-09",
            today=TODAY,
            timezone="America/Chicago",
            generated_at=GENERATED_AT,
            invoices=(inv("a"),),
            collected_cents=2_500,
            tuition_discounts={"gross_cents": 10_000, "discount_cents": 0, "net_cents": 10_000},
            warnings=("attempts_unavailable",),
        )
    )

    assert view["period"] == "2026-09"
    assert view["timezone"] == "America/Chicago"
    assert view["generated_at"] == GENERATED_AT.isoformat()
    assert view["money"]["collected_cents"] == 2_500
    assert view["invoices"]["generated"] == 1
    assert view["autopay_run"]["charge_on"] == "2026-09-08"
    assert len(view["odd"]) == 4
    assert view["tuition_discounts"]["net_cents"] == 10_000
    assert view["warnings"] == ["attempts_unavailable"]


def test_an_empty_period_is_zeros_a_null_rate_and_four_zero_checks() -> None:
    view = build_month_close_view(
        MonthCloseFacts(
            period="2026-09",
            today=TODAY,
            timezone="UTC",
            generated_at=GENERATED_AT,
        )
    )

    assert view["money"] == {
        "billed_cents": 0,
        "collected_cents": 0,
        "outstanding_cents": 0,
        "collection_rate": None,
    }
    assert view["invoices"]["generated"] == 0
    assert [row["count"] for row in view["odd"]] == [0, 0, 0, 0]
    assert view["tuition_discounts"] is None
    assert view["warnings"] == []
