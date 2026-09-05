"""Pure bucket classification for the admin Payments collections view.

Spec: ``docs/superpowers/specs/2026-09-05-payments-buckets-design.md`` §2.

Everything here works on plain fact dataclasses — no Mongo, no clock. The
infrastructure read model gathers the facts in a fixed number of batched
queries and hands each family to :func:`classify_family`; the interface layer
serialises the dict returned by :func:`build_collections_view` verbatim.

Autopay eligibility is never re-derived here: it comes from
:mod:`autopay_eligibility`, the same predicates the dunning worker runs, so the
page never promises a charge the worker would skip.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import date, datetime
from typing import Any

from backend.v2.contexts.billing.application.autopay_eligibility import (
    AUTOPAY_ACTIVE_STATUS,
    CHARGEABLE_INVOICE_STATUSES,
    Eligibility,
    autopay_eligibility,
)

BUCKET_ORDER: tuple[str, ...] = (
    "failed_autopay",
    "past_due",
    "awaiting",
    "autopay_scheduled",
    "paused",
    "paid",
)

BUCKET_ACTIONS: dict[str, list[str]] = {
    "failed_autopay": ["message", "record_payment"],
    "past_due": ["send_reminder", "record_payment"],
    "awaiting": ["send_reminder", "record_payment"],
    "autopay_scheduled": ["skip_month"],
    "paused": ["resume"],
    "paid": [],
}

MAX_AUTOPAY_ATTEMPTS = 4

# A ladder that has actually tried (and failed) at least once, or one that ran
# out of retries and disabled autopay. ``resolved`` / ``suppressed`` never count.
_FAILED_LADDER_STATUSES: frozenset[str] = frozenset({"active", "processing"})
_DUNNED_STATUS = "dunned"

# ``draft`` invoices with a balance are owed money but the worker will never
# charge them; they count for the reminder buckets (2/3) only.
_OWING_STATUSES: frozenset[str] = CHARGEABLE_INVOICE_STATUSES | {"draft"}

# The read model already excludes voids; the classifier ignores them anyway so a
# stray void can never put a family in the Paid bucket (spec §2).
_VOID_STATUS = "void"


@dataclass(frozen=True)
class InvoiceFacts:
    invoice_id: str
    invoice_number: str | None
    period: str
    status: str
    total_cents: int
    balance_due_cents: int
    due_date: date
    delivery_status: str
    last_sent_at: datetime | None
    enrollment_id: str | None
    student_id: str | None
    autopay_enrollment_status: str | None  # from student_billing_enrollments
    dunning_status: str | None  # dunning_states.status
    dunning_attempt_count: int
    dunning_next_attempt_at: datetime | None
    latest_attempt_status: str | None
    latest_attempt_reason: str | None
    paid_cents: int  # from allocations
    paid_method: str | None
    paid_at: datetime | None


@dataclass(frozen=True)
class StudentFacts:
    student_id: str
    name: str
    session_title: str | None


@dataclass(frozen=True)
class PauseFacts:
    enrollment_id: str
    student_name: str
    session_title: str | None
    resume_on: date | None
    review_on: date | None


@dataclass(frozen=True)
class FamilyFacts:
    parent_id: str
    parent_name: str | None
    parent_email: str | None
    students: tuple[StudentFacts, ...]
    invoices: tuple[InvoiceFacts, ...]  # this period, non-void
    leftover_balance_cents: int
    paused: tuple[PauseFacts, ...]
    has_payment_method: bool | None
    card_last4: str | None
    connected_account_ready: bool | None


@dataclass(frozen=True)
class FamilyRow:
    bucket: str
    payload: dict[str, Any]  # payload == spec §3 family JSON


# --------------------------------------------------------------------------- helpers


def _iso(value: date | datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _date_iso(value: date | datetime | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    return value.isoformat()


def _is_owing(invoice: InvoiceFacts) -> bool:
    return invoice.status in _OWING_STATUSES and invoice.balance_due_cents > 0


def _is_chargeable_owing(invoice: InvoiceFacts) -> bool:
    return invoice.status in CHARGEABLE_INVOICE_STATUSES and invoice.balance_due_cents > 0


def _eligibility(family: FamilyFacts, invoice: InvoiceFacts) -> Eligibility:
    return autopay_eligibility(
        invoice_status=invoice.status,
        balance_due_cents=invoice.balance_due_cents,
        enrollment_id=invoice.enrollment_id,
        autopay_enrollment_status=invoice.autopay_enrollment_status,
        has_payment_method=family.has_payment_method,
        connected_account_ready=family.connected_account_ready,
    )


def _has_failed_attempt(invoice: InvoiceFacts) -> bool:
    if invoice.dunning_status == _DUNNED_STATUS:
        return True
    return invoice.dunning_status in _FAILED_LADDER_STATUSES and invoice.dunning_attempt_count >= 1


def _by_due_date(invoices: Iterable[InvoiceFacts]) -> list[InvoiceFacts]:
    return sorted(invoices, key=lambda inv: (inv.due_date, inv.invoice_id))


# --------------------------------------------------------------------------- classification


def _pick_bucket(
    family: FamilyFacts,
    owing: list[InvoiceFacts],
    eligibility: dict[str, Eligibility],
    *,
    today: date,
) -> tuple[str | None, InvoiceFacts | None]:
    """Spec §2 rules, top to bottom. Returns (bucket, triggering invoice)."""
    for inv in owing:
        if _is_chargeable_owing(inv) and _has_failed_attempt(inv):
            return "failed_autopay", inv
    for inv in owing:
        if not eligibility[inv.invoice_id].eligible and inv.due_date < today:
            return "past_due", inv
    for inv in owing:
        if not eligibility[inv.invoice_id].eligible and inv.due_date >= today:
            return "awaiting", inv
    for inv in owing:
        if eligibility[inv.invoice_id].eligible:
            return "autopay_scheduled", inv
    if family.paused:
        return "paused", None
    if family.invoices:
        return "paid", None
    return None, None


def _autopay_payload(
    family: FamilyFacts,
    bucket: str,
    owing: list[InvoiceFacts],
    eligibility: dict[str, Eligibility],
) -> dict[str, Any] | None:
    if not owing:
        return None
    earliest = owing[0]
    if bucket == "autopay_scheduled":
        return {
            "status": "eligible",
            "card_last4": family.card_last4,
            "charge_on": earliest.due_date.isoformat(),
            "notice_sent_at": _iso(earliest.last_sent_at),
        }
    if bucket not in {"past_due", "awaiting"}:
        return None
    # Autopay is switched on but the worker would not charge: surface the
    # reason ("no_card_on_file", "card_state_unknown", ...) so the admin can act.
    for inv in owing:
        elig = eligibility[inv.invoice_id]
        if inv.autopay_enrollment_status == AUTOPAY_ACTIVE_STATUS and not elig.eligible:
            return {
                "status": elig.reason or elig.status,
                "card_last4": family.card_last4,
                "charge_on": inv.due_date.isoformat(),
                "notice_sent_at": _iso(inv.last_sent_at),
            }
    return None


def _failure_payload(trigger: InvoiceFacts) -> dict[str, Any]:
    return {
        "reason": trigger.latest_attempt_reason,
        "attempt_count": trigger.dunning_attempt_count,
        "max_attempts": MAX_AUTOPAY_ATTEMPTS,
        "next_retry_on": _date_iso(trigger.dunning_next_attempt_at),
        "disabled": trigger.dunning_status == _DUNNED_STATUS,
    }


def _pause_payload(family: FamilyFacts) -> dict[str, Any] | None:
    if not family.paused:
        return None
    first = family.paused[0]
    return {
        "enrollment_id": first.enrollment_id,
        "resume_on": _iso(first.resume_on),
        "review_on": _iso(first.review_on),
        "session_title": first.session_title,
        "student_name": first.student_name,
    }


def _paid_payload(family: FamilyFacts, bucket: str) -> dict[str, Any] | None:
    with_payments = [inv for inv in family.invoices if inv.paid_cents > 0]
    if with_payments:
        latest = max(
            with_payments,
            key=lambda inv: (inv.paid_at is not None, inv.paid_at or datetime.min),
        )
        return {
            "amount_cents": sum(inv.paid_cents for inv in with_payments),
            "method": latest.paid_method,
            "paid_at": _iso(latest.paid_at),
        }
    if bucket == "paid":
        return {
            "amount_cents": sum(
                max(inv.total_cents - inv.balance_due_cents, 0) for inv in family.invoices
            ),
            "method": None,
            "paid_at": None,
        }
    return None


def _last_reminder_at(owing: list[InvoiceFacts]) -> str | None:
    sent = [inv.last_sent_at for inv in owing if inv.last_sent_at is not None]
    return _iso(max(sent)) if sent else None


def _invoice_payload(inv: InvoiceFacts) -> dict[str, Any]:
    return {
        "invoice_id": inv.invoice_id,
        "invoice_number": inv.invoice_number,
        "period": inv.period,
        "status": inv.status,
        "total_cents": inv.total_cents,
        "balance_due_cents": inv.balance_due_cents,
        "due_date": inv.due_date.isoformat(),
        "delivery_status": inv.delivery_status,
    }


def classify_family(family: FamilyFacts, *, today: date) -> FamilyRow | None:
    """Place one family in the first matching spec §2 bucket, or ``None``."""
    invoices = tuple(inv for inv in family.invoices if inv.status != _VOID_STATUS)
    if len(invoices) != len(family.invoices):
        family = replace(family, invoices=invoices)
    owing = _by_due_date(inv for inv in invoices if _is_owing(inv))
    eligibility = {inv.invoice_id: _eligibility(family, inv) for inv in owing}

    bucket, trigger = _pick_bucket(family, owing, eligibility, today=today)
    if bucket is None:
        return None

    payload: dict[str, Any] = {
        "parent_id": family.parent_id,
        "parent_name": family.parent_name,
        "parent_email": family.parent_email,
        "students": [
            {
                "student_id": s.student_id,
                "name": s.name,
                "session_title": s.session_title,
            }
            for s in family.students
        ],
        "invoices": [_invoice_payload(inv) for inv in family.invoices],
        "balance_cents": sum(inv.balance_due_cents for inv in owing),
        "leftover_balance_cents": family.leftover_balance_cents,
        "autopay": _autopay_payload(family, bucket, owing, eligibility),
        "failure": (
            _failure_payload(trigger)
            if bucket == "failed_autopay" and trigger is not None
            else None
        ),
        "pause": _pause_payload(family) if bucket == "paused" else None,
        "paid": _paid_payload(family, bucket),
        "last_reminder_at": _last_reminder_at(owing),
        "actions": list(BUCKET_ACTIONS[bucket]),
    }
    return FamilyRow(bucket=bucket, payload=payload)


# --------------------------------------------------------------------------- view


def _bucket_total(bucket: str, rows: list[FamilyRow]) -> int:
    if bucket == "paused":
        return sum(r.payload["leftover_balance_cents"] for r in rows)
    if bucket == "paid":
        return sum((r.payload["paid"] or {}).get("amount_cents", 0) for r in rows)
    return sum(r.payload["balance_cents"] for r in rows)


def build_collections_view(
    families: Iterable[FamilyFacts],
    *,
    period: str,
    today: date,
    timezone: str,
    generated_at: datetime,
    unclassified: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Spec §3 ``AdminCollectionsView`` as a plain dict, buckets in ``BUCKET_ORDER``."""
    grouped: dict[str, list[FamilyRow]] = {key: [] for key in BUCKET_ORDER}
    for family in families:
        row = classify_family(family, today=today)
        if row is not None:
            grouped[row.bucket].append(row)

    buckets = [
        {
            "key": key,
            "count": len(rows),
            "total_cents": _bucket_total(key, rows),
            "families": [row.payload for row in rows],
        }
        for key, rows in ((key, grouped[key]) for key in BUCKET_ORDER)
    ]

    owed_cents = sum(
        r.payload["balance_cents"]
        for key in ("failed_autopay", "past_due", "awaiting")
        for r in grouped[key]
    )
    collected_cents = sum(
        r.payload["paid"]["amount_cents"]
        for rows in grouped.values()
        for r in rows
        if r.payload["paid"] is not None
    )

    view: dict[str, Any] = {
        "period": period,
        "generated_at": generated_at.isoformat(),
        "timezone": timezone,
        "totals": {
            "owed_cents": owed_cents,
            "autopay_scheduled_cents": _bucket_total(
                "autopay_scheduled", grouped["autopay_scheduled"]
            ),
            "autopay_scheduled_count": len(grouped["autopay_scheduled"]),
            "needs_action_count": len(grouped["failed_autopay"]) + len(grouped["past_due"]),
            "collected_cents": collected_cents,
        },
        "buckets": buckets,
    }
    if unclassified is not None:
        view["unclassified"] = unclassified
    return view
