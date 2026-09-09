"""Pure shaping for the admin Month close page.

Spec: ``docs/superpowers/specs/2026-09-07-month-close-design.md`` §4.

Everything here works on plain fact dataclasses — no Mongo, no clock, no
network — exactly like :mod:`collections_buckets` and :mod:`family_billing`.
The infrastructure read model gathers the facts in a fixed number of batched
queries and calls :func:`build_month_close_view`; the interface layer
serialises the returned dict verbatim.

Two rules are deliberately not re-derived here:

* the Failed-autopay predicate is the ladder predicate the Payments Failed
  bucket uses, so the tile and the bucket can never disagree; and
* autopay eligibility comes from :mod:`autopay_eligibility`, the same
  predicates the dunning worker runs, so "pending" never promises a charge the
  worker would skip.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Literal

from backend.v2.contexts.billing.application.autopay_eligibility import (
    AUTOPAY_ACTIVE_STATUS,
    autopay_eligibility,
    invoice_is_chargeable,
)

#: Odd-list checks are capped so one bad month cannot return thousands of rows.
#: The count beside the list is always the true count (spec §4.3).
MAX_ODD_ITEMS = 20

#: Every check renders even at zero, so the owner learns the shape of the box.
ODD_CHECKS: tuple[tuple[str, str], ...] = (
    ("invoice_without_enrollment", "Invoice with no enrollment"),
    ("paused_family_invoiced", "Paused family still invoiced"),
    ("autopay_no_card", "Autopay on with no card on file"),
    ("autopay_on_dead_enrollment", "Autopay on a cancelled or withdrawn enrollment"),
)

_VOID_STATUS = "void"
_DRAFT_STATUS = "draft"
_SENT_DELIVERY = "sent"
_UNSENT_DELIVERY: frozenset[str] = frozenset({"not_sent", "delivery_failed"})
_PAUSED_ENROLLMENT = "paused"
#: Terminal ("dead") enrollment statuses, in BOTH the legacy and #699
#: canonical spellings ("withdrawn"->"dropped", "cancelled"->"deleted").
#: Billing cannot import contexts.enrollment.domain.models.canonical_status
#: (Rule 5, no cross-context imports — enforced by
#: tests/structural/test_layering.py::test_no_cross_context_imports), so the
#: dual-spelling set is duplicated here rather than normalized through a
#: shared function. Before this widened, a dropped/deleted enrollment
#: written by #699-migrated code matched neither "cancelled" nor "withdrawn",
#: so an autopay left on over a dropped child never tripped
#: "autopay_on_dead_enrollment" and month close silently missed it.
_DEAD_ENROLLMENT_STATUSES: frozenset[str] = frozenset(
    {"cancelled", "deleted", "withdrawn", "dropped"}
)

#: Same as ``collections_buckets._FAILED_LADDER_STATUSES`` / ``_DUNNED_STATUS``:
#: a ladder that has actually tried and failed, or one that gave up.
_FAILED_LADDER_STATUSES: frozenset[str] = frozenset({"active", "processing"})
_DUNNED_STATUS = "dunned"

Warning = Literal[
    "attempts_unavailable",
    "dunning_unavailable",
    "discounts_unavailable",
    # The card-on-file read failed, so ``autopay_no_card`` is suppressed rather
    # than guessed. Without this code the page rendered a zero for a check that
    # never ran, which reads as "nothing wrong" (spec §8).
    "card_state_unavailable",
]


@dataclass(frozen=True)
class InvoiceFacts:
    """One invoice of the period, plus everything joined onto it.

    ``enrollment_found`` is False when ``enrollment_id`` points at a row the
    ``enrollments`` query did not return — a dangling reference, which is a
    different defect from having no ``enrollment_id`` at all but produces the
    same odd row.
    """

    invoice_id: str
    invoice_number: str | None = None
    status: str = ""
    total_cents: int = 0
    paid_cents: int = 0
    outstanding_cents: int = 0
    due_date: date | None = None
    delivery_status: str = "not_sent"
    void_reason: str | None = None
    parent_id: str | None = None
    parent_name: str | None = None
    enrollment_id: str | None = None
    enrollment_found: bool = True
    enrollment_status: str | None = None
    autopay_enrollment_status: str | None = None
    has_card: bool | None = None
    connected_account_ready: bool | None = None
    #: A charge attempt of any status exists for this invoice in the period.
    has_charge_attempt: bool = False
    #: A *succeeded* charge attempt exists for this invoice in the period.
    has_succeeded_attempt: bool = False
    dunning_status: str | None = None
    dunning_attempt_count: int = 0

    @property
    def is_void(self) -> bool:
        return self.status == _VOID_STATUS

    @property
    def is_draft(self) -> bool:
        return self.status == _DRAFT_STATUS

    @property
    def autopay_active(self) -> bool:
        return self.autopay_enrollment_status == AUTOPAY_ACTIVE_STATUS


@dataclass(frozen=True)
class MonthCloseFacts:
    period: str
    today: date
    timezone: str
    generated_at: datetime
    invoices: tuple[InvoiceFacts, ...] = ()
    #: ``cash_received_in_period(...).net_cents`` — the one "collected" (§3.2).
    collected_cents: int = 0
    #: ``GET /admin/finance/tuition-discounts`` verbatim, or ``None`` when the
    #: use case was unavailable (which also raises ``discounts_unavailable``).
    tuition_discounts: dict[str, Any] | None = None
    #: True when the card lookup succeeded. False suppresses ``autopay_no_card``
    #: rather than guessing at it (spec §8).
    card_state_known: bool = True
    warnings: tuple[str, ...] = field(default_factory=tuple)


# --------------------------------------------------------------------------- helpers


def _iso(value: date | datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _live(invoices: Iterable[InvoiceFacts]) -> list[InvoiceFacts]:
    """Non-void invoices — what "billed" and every odd check are about."""
    return [inv for inv in invoices if not inv.is_void]


def _family_href(parent_id: str | None) -> str:
    return f"/admin/families/{parent_id}" if parent_id else "/admin/payments"


def _family_label(inv: InvoiceFacts) -> str:
    return inv.parent_name or inv.parent_id or "Unknown family"


def _has_failed_ladder(inv: InvoiceFacts) -> bool:
    """The Failed autopay bucket's predicate, not a second opinion on it.

    The chargeable-and-owing half matters as much as the ladder half. A dunning
    row is only suppressed the next time the worker claims that state, so an
    invoice paid by hand after a failed charge keeps its ``active`` ladder row
    until ``next_attempt_at``. Without this guard the tile counted that invoice
    as failed and sent the owner to a Failed autopay bucket that had already
    dropped it — the tile and the bucket disagreeing is exactly what this page
    exists to stop.
    """
    if not invoice_is_chargeable(inv.status, inv.outstanding_cents):
        return False
    if inv.dunning_status == _DUNNED_STATUS:
        return True
    return inv.dunning_status in _FAILED_LADDER_STATUSES and inv.dunning_attempt_count >= 1


def _is_autopay_eligible(inv: InvoiceFacts) -> bool:
    return autopay_eligibility(
        invoice_status=inv.status,
        balance_due_cents=inv.outstanding_cents,
        enrollment_id=inv.enrollment_id,
        autopay_enrollment_status=inv.autopay_enrollment_status,
        has_payment_method=inv.has_card,
        connected_account_ready=inv.connected_account_ready,
    ).eligible


# --------------------------------------------------------------------------- sections


def build_invoices_section(invoices: Iterable[InvoiceFacts]) -> dict[str, Any]:
    """Counts of what the generation and send runs produced.

    The delivery split is over *generated* (non-draft) invoices: a draft was
    never meant to be sent, so counting it as ``not_sent`` would report a
    failure that never happened.

    The kind of email is not persisted — ``record_delivery`` writes the same
    ``delivery_status`` for an invoice email and an autopay notice — so the
    split is re-derived from the enrollment's *current* autopay status, exactly
    as the family timeline does. ``emailed + autopay_notices`` is always the
    true sent count, which is the number that matters for close (§4.3).
    """
    generated = [inv for inv in invoices if not inv.is_draft]
    sent = [inv for inv in generated if inv.delivery_status == _SENT_DELIVERY]
    voided = [inv for inv in invoices if inv.is_void]
    reasons = Counter(inv.void_reason or "unspecified" for inv in voided)
    return {
        "generated": len(generated),
        "emailed": sum(1 for inv in sent if not inv.autopay_active),
        "autopay_notices": sum(1 for inv in sent if inv.autopay_active),
        "not_sent": sum(1 for inv in generated if inv.delivery_status in _UNSENT_DELIVERY),
        "voided": len(voided),
        "voided_cents": sum(inv.total_cents for inv in voided),
        "void_reasons": [
            {"reason": reason, "count": count}
            for reason, count in sorted(reasons.items(), key=lambda item: (-item[1], item[0]))
        ],
    }


def build_money_section(
    invoices: Iterable[InvoiceFacts], *, collected_cents: int
) -> dict[str, Any]:
    """``billed`` and ``outstanding`` keep the dashboard's definitions; the
    collection rate is ``None`` — rendered "—" — on an empty month, so a month
    with nothing billed never reads as a total collection failure."""
    live = _live(invoices)
    billed_cents = sum(inv.paid_cents + inv.outstanding_cents for inv in live)
    return {
        "billed_cents": billed_cents,
        "collected_cents": collected_cents,
        "outstanding_cents": sum(inv.outstanding_cents for inv in live),
        "collection_rate": (
            round(min(collected_cents / billed_cents, 1.0), 4) if billed_cents > 0 else None
        ),
    }


def build_autopay_run_section(invoices: Iterable[InvoiceFacts], *, today: date) -> dict[str, Any]:
    """The autopay run's four tallies over every autopay-active invoice.

    ``charge_on`` is the earliest due date in the period. The generator
    normally stamps one due date per run, but a late-added enrollment gets a
    later one, so ``charge_on_varies`` tells the page to append "and later".
    The tallies span every autopay-active invoice regardless of its due date.

    The three tallies are a partition, evaluated in this order: a failed ladder
    first (matching the Failed autopay bucket, so the tile and the bucket can
    never disagree), then a succeeded charge, then anything still eligible with
    no attempt yet. ``scheduled`` is their sum — what the worker had to do.
    """
    live = _live(invoices)
    due_dates = sorted({inv.due_date for inv in live if inv.due_date is not None})
    autopay = [inv for inv in live if inv.autopay_active]

    failed = [inv for inv in autopay if _has_failed_ladder(inv)]
    failed_ids = {inv.invoice_id for inv in failed}
    remaining = [inv for inv in autopay if inv.invoice_id not in failed_ids]
    succeeded = [inv for inv in remaining if inv.has_succeeded_attempt]
    pending = [
        inv
        for inv in remaining
        if not inv.has_succeeded_attempt
        and not inv.has_charge_attempt
        and _is_autopay_eligible(inv)
    ]

    def tally(rows: list[InvoiceFacts], *, paid: bool = False) -> dict[str, int]:
        return {
            "count": len(rows),
            "cents": sum(inv.paid_cents if paid else inv.outstanding_cents for inv in rows),
        }

    charge_on = due_dates[0] if due_dates else None
    succeeded_tally = tally(succeeded, paid=True)
    failed_tally = tally(failed)
    pending_tally = tally(pending)
    return {
        "charge_on": _iso(charge_on),
        "charge_on_varies": len(due_dates) > 1,
        "has_run": charge_on is not None and today >= charge_on,
        "scheduled": {
            "count": succeeded_tally["count"] + failed_tally["count"] + pending_tally["count"],
            "cents": succeeded_tally["cents"] + failed_tally["cents"] + pending_tally["cents"],
        },
        "succeeded": succeeded_tally,
        "failed": failed_tally,
        "pending": pending_tally,
    }


def _invoice_item(inv: InvoiceFacts) -> dict[str, Any]:
    return {
        "kind": "invoice",
        "id": inv.invoice_id,
        "label": inv.invoice_number or inv.invoice_id,
        "href": _family_href(inv.parent_id),
    }


def _family_item(inv: InvoiceFacts) -> dict[str, Any]:
    return {
        "kind": "family",
        "id": inv.parent_id or inv.invoice_id,
        "label": _family_label(inv),
        "href": _family_href(inv.parent_id),
    }


def build_odd_section(
    invoices: Iterable[InvoiceFacts], *, card_state_known: bool = True
) -> list[dict[str, Any]]:
    """The four "anything odd" checks (spec §4.3), all from facts already loaded.

    ``autopay_no_card`` is suppressed — reported as zero — when the card
    lookup failed, because the read model never reports an odd count it cannot
    stand behind (§8). The companion ``warnings`` entry says why.
    """
    live = _live(invoices)

    hits: dict[str, list[dict[str, Any]]] = {code: [] for code, _ in ODD_CHECKS}
    seen_families: dict[str, set[str]] = {code: set() for code, _ in ODD_CHECKS}

    def add_family(code: str, inv: InvoiceFacts) -> None:
        key = inv.parent_id or inv.invoice_id
        if key in seen_families[code]:
            return
        seen_families[code].add(key)
        hits[code].append(_family_item(inv))

    for inv in live:
        if not inv.enrollment_id or not inv.enrollment_found:
            hits["invoice_without_enrollment"].append(_invoice_item(inv))
        if inv.outstanding_cents > 0 and inv.enrollment_status == _PAUSED_ENROLLMENT:
            add_family("paused_family_invoiced", inv)
        if inv.autopay_active and card_state_known and inv.has_card is False:
            add_family("autopay_no_card", inv)
        if inv.autopay_active and inv.enrollment_status in _DEAD_ENROLLMENT_STATUSES:
            add_family("autopay_on_dead_enrollment", inv)

    return [
        {
            "code": code,
            "label": label,
            "count": len(hits[code]),
            "items": hits[code][:MAX_ODD_ITEMS],
        }
        for code, label in ODD_CHECKS
    ]


def build_month_close_view(facts: MonthCloseFacts) -> dict[str, Any]:
    """The whole ``AdminMonthCloseView`` payload (spec §4.2)."""
    return {
        "generated_at": facts.generated_at.isoformat(),
        "timezone": facts.timezone,
        "period": facts.period,
        "invoices": build_invoices_section(facts.invoices),
        "money": build_money_section(facts.invoices, collected_cents=facts.collected_cents),
        "autopay_run": build_autopay_run_section(facts.invoices, today=facts.today),
        "odd": build_odd_section(facts.invoices, card_state_known=facts.card_state_known),
        "tuition_discounts": facts.tuition_discounts,
        "warnings": list(facts.warnings),
    }
