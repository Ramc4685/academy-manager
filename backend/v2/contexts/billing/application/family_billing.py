"""Pure rules for the admin Family billing view.

Spec: ``docs/superpowers/specs/2026-09-05-family-billing-design.md`` §3.3 (autopay
state), §3.4 (actions), §4 (timeline). No Mongo, no clock: the infrastructure read
model gathers :class:`FamilyFacts` in a fixed number of batched queries and calls
:func:`build_family_billing_view`; the interface layer strips owner-only actions
for non-owners with :func:`strip_owner_actions` and serialises the dict.

Chargeability is never re-derived here — it comes from :mod:`autopay_eligibility`,
the predicates the dunning worker runs.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, tzinfo
from typing import Any
from zoneinfo import ZoneInfo

from backend.v2.contexts.billing.application.autopay_eligibility import (
    AUTOPAY_ACTIVE_STATUS,
    CHARGEABLE_INVOICE_STATUSES,
    Eligibility,
    autopay_eligibility,
)

TIMELINE_CAP = 200

OWNER_ONLY_ACTIONS: frozenset[str] = frozenset(
    {"void", "refund", "discount_once", "recurring_discount"}
)

# Charge-outcome attempt statuses that mean "the charge did not take money".
FAILURE_ATTEMPT_STATUSES: frozenset[str] = frozenset(
    {"failed", "declined", "requires_action", "error", "canceled", "cancelled"}
)

_PAUSED = "paused"
_CANCELLED_ENROLLMENT_STATUSES: frozenset[str] = frozenset({"cancelled", "withdrawn"})
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
_EPOCH = datetime.min.replace(tzinfo=UTC)


# --------------------------------------------------------------------------- facts


@dataclass(frozen=True)
class ParentFacts:
    parent_id: str
    name: str | None
    email: str | None
    phone: str | None


@dataclass(frozen=True)
class EnrollmentFacts:
    enrollment_id: str
    student_id: str
    session_id: str | None
    session_title: str | None
    schedule: str | None
    status: str
    monthly_price_cents: int | None
    override_price_cents: int | None
    autopay_status: str | None
    recurring_discount: dict[str, Any] | None
    resume_on: date | None


@dataclass(frozen=True)
class StudentFacts:
    student_id: str
    name: str
    status: str | None
    enrollments: tuple[EnrollmentFacts, ...]


@dataclass(frozen=True)
class AllocationFacts:
    payment_id: str
    amount_cents: int
    method: str | None
    paid_at: datetime | None
    stripe_payment_intent_id: str | None


@dataclass(frozen=True)
class CreditFacts:
    credit_id: str
    amount_cents: int


@dataclass(frozen=True)
class InvoiceFacts:
    invoice_id: str
    invoice_number: str | None
    period: str
    student_id: str | None
    student_name: str | None
    enrollment_id: str | None
    status: str
    total_cents: int
    balance_due_cents: int
    due_date: date | None
    created_at: datetime | None
    paid_at: datetime | None
    voided_at: datetime | None
    void_reason: str | None
    delivery_status: str
    last_sent_at: datetime | None
    autopay_status: str | None  # the enrollment's autopay status (labels the send)
    allocations: tuple[AllocationFacts, ...]
    credits: tuple[CreditFacts, ...]


@dataclass(frozen=True)
class AttemptFacts:
    attempt_id: str
    invoice_id: str
    status: str
    failure_message: str | None
    amount_cents: int
    created_at: datetime | None


@dataclass(frozen=True)
class DunningFacts:
    invoice_id: str
    status: str | None
    attempt_count: int
    autopay_disabled_at: datetime | None
    last_notification_at: datetime | None


@dataclass(frozen=True)
class AuditFacts:
    audit_id: str
    action: str
    actor_id: str
    at: datetime
    invoice_id: str | None
    payment_id: str | None
    reason: str | None
    before: dict[str, Any] | None
    after: dict[str, Any] | None


@dataclass(frozen=True)
class EventFacts:
    event_id: str
    event_type: str
    enrollment_id: str
    student_name: str | None
    occurred_at: datetime
    actor_id: str | None
    reason: str | None
    effective_at: datetime | None


@dataclass(frozen=True)
class CustomerFacts:
    has_card: bool | None  # None = lookup failed (unknown)
    card_last4: str | None
    card_label: str | None
    last_invited_at: datetime | None
    has_login_account: bool


@dataclass(frozen=True)
class FamilyFacts:
    parent: ParentFacts
    students: tuple[StudentFacts, ...]
    invoices: tuple[InvoiceFacts, ...]  # newest first
    attempts: tuple[AttemptFacts, ...]
    dunning: tuple[DunningFacts, ...]
    audit: tuple[AuditFacts, ...]
    events: tuple[EventFacts, ...]
    customer: CustomerFacts
    available_credit_cents: int
    connected_account_ready: bool | None
    warnings: tuple[str, ...]


# --------------------------------------------------------------------------- helpers


def _iso(value: date | datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _local_day(value: date | datetime | None, zone: tzinfo) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return _as_utc(value).astimezone(zone).date()
    return value


def _money(cents: int) -> str:
    sign = "-" if cents < 0 else ""
    cents = abs(cents)
    if cents % 100 == 0:
        return f"{sign}${cents // 100:,}"
    return f"{sign}${cents // 100:,}.{cents % 100:02d}"


def _period_label(period: str) -> str:
    try:
        year, month = period.split("-")
        return f"{_MONTHS[int(month) - 1]} {year}"
    except (ValueError, IndexError):
        return period


def _day_label(value: date | datetime | None, zone: tzinfo) -> str | None:
    day = _local_day(value, zone)
    if day is None:
        return None
    return f"{_MONTHS[day.month - 1]} {day.day}"


def _method_label(method: str | None, card_last4: str | None = None) -> str:
    if method in (None, "", "card", "stripe") and card_last4:
        return f"card ••{card_last4}"
    return (method or "payment").replace("_", " ")


def _live(enrollments: Iterable[EnrollmentFacts]) -> list[EnrollmentFacts]:
    return [e for e in enrollments if e.status not in _CANCELLED_ENROLLMENT_STATUSES]


def _all_enrollments(facts: FamilyFacts) -> list[EnrollmentFacts]:
    return [e for s in facts.students for e in s.enrollments]


def _stripe_paid_cents(inv: InvoiceFacts) -> int:
    return sum(a.amount_cents for a in inv.allocations if a.stripe_payment_intent_id)


# --------------------------------------------------------------------------- rules


def autopay_state(enrollments: Iterable[EnrollmentFacts]) -> str:
    """Spec §3.3 over the parent's non-cancelled enrollments."""
    statuses = [e.autopay_status for e in _live(enrollments)]
    active = sum(1 for s in statuses if s == AUTOPAY_ACTIVE_STATUS)
    if statuses and active == len(statuses):
        return "on"
    if active:
        return "partial"
    if any(s == _PAUSED for s in statuses):
        return "off"
    return "needs_consent"


def invoice_actions(inv: InvoiceFacts, *, eligibility: Eligibility) -> list[str]:
    """Spec §3.4 per-invoice table. Order is the button order on the page."""
    actions: list[str] = []
    if inv.status in CHARGEABLE_INVOICE_STATUSES:
        actions.append("send")
        if inv.balance_due_cents > 0:
            actions.append("record_payment")
            if eligibility.eligible:
                actions.append("charge_card")
        if not inv.allocations:
            actions.append("void")
    if inv.status in {"paid", "partially_paid"} and _stripe_paid_cents(inv) > 0:
        actions.append("refund")
    if inv.status == "open" and inv.balance_due_cents > 0:
        actions.append("discount_once")
    return actions


def family_actions(
    *, state: str, has_card: bool | None, invoices: Sequence[InvoiceFacts]
) -> list[str]:
    actions: list[str] = []
    if not has_card:
        actions.append("send_invite")
    if state in {"off", "partial"}:
        actions.append("autopay_on")
    if state in {"on", "partial"}:
        actions.append("autopay_off")
    open_invoices = [i for i in invoices if i.status in CHARGEABLE_INVOICE_STATUSES]
    if open_invoices:
        actions.append("send_invoice")
    if any(i.balance_due_cents > 0 for i in open_invoices):
        actions.append("record_payment")
    return actions


def strip_owner_actions(view: dict[str, Any]) -> dict[str, Any]:
    """Remove owner-only actions for a non-owner caller (interface layer)."""
    out = dict(view)
    out["invoices"] = [
        {**inv, "actions": [a for a in inv["actions"] if a not in OWNER_ONLY_ACTIONS]}
        for inv in view["invoices"]
    ]
    out["students"] = [
        {
            **student,
            "enrollments": [
                {**e, "actions": [a for a in e["actions"] if a not in OWNER_ONLY_ACTIONS]}
                for e in student["enrollments"]
            ],
        }
        for student in view["students"]
    ]
    out["actions"] = [a for a in view["actions"] if a not in OWNER_ONLY_ACTIONS]
    return out


# --------------------------------------------------------------------------- timeline


def _entry(
    *,
    at: datetime,
    kind: str,
    code: str,
    summary: str,
    invoice_id: str | None = None,
    enrollment_id: str | None = None,
    student_name: str | None = None,
    actor_id: str | None = None,
    reason: str | None = None,
    amount_cents: int | None = None,
    invoice_ids: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "at": _as_utc(at),
        "kind": kind,
        "code": code,
        "summary": summary,
        "invoice_id": invoice_id,
        "invoice_ids": invoice_ids or ([invoice_id] if invoice_id else []),
        "enrollment_id": enrollment_id,
        "student_name": student_name,
        "actor_id": actor_id,
        "reason": reason,
        "amount_cents": amount_cents,
        "muted": kind == "comms",
    }


_AUDIT_SUMMARIES: dict[str, str] = {
    "manual_payment_recorded": "Payment recorded by admin",
    "refund_issued": "Refund issued",
    "admin_charge_initiated": "Card charged by admin",
    "autopay_resumed": "Autopay turned on",
    "autopay_paused": "Autopay turned off",
    "invoice_voided": "Invoice voided by admin",
    "invoice_line_added": "Charge added to invoice",
    "invoice_line_removed": "Charge removed from invoice",
    "discount_set": "Discount set",
    "discount_removed": "Discount removed",
    "platform_fallback_toggled": "Charge routing changed",
    "invoice_schedule_changed": "Invoice schedule changed",
}

_EVENT_SUMMARIES: dict[str, str] = {
    "created": "enrolled",
    "paused": "paused",
    "resumed": "resumed",
    "cancelled": "cancelled",
    "withdrawn": "withdrawn",
    "moved": "moved to another class",
    "promoted": "promoted from waitlist",
    "waitlisted": "waitlisted",
}


def _invoice_entries(facts: FamilyFacts) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for inv in facts.invoices:
        label = _period_label(inv.period)
        who = f" · {inv.student_name}" if inv.student_name else ""
        if inv.created_at is not None:
            entries.append(
                _entry(
                    at=inv.created_at,
                    kind="money",
                    code="invoice_generated",
                    summary=f"{label} invoice generated{who} · {_money(inv.total_cents)}",
                    invoice_id=inv.invoice_id,
                    student_name=inv.student_name,
                    amount_cents=inv.total_cents,
                )
            )
        if inv.voided_at is not None:
            why = f" · {inv.void_reason}" if inv.void_reason else ""
            entries.append(
                _entry(
                    at=inv.voided_at,
                    kind="money",
                    code="invoice_voided",
                    summary=f"{label} invoice voided{who}{why}",
                    invoice_id=inv.invoice_id,
                    student_name=inv.student_name,
                    reason=inv.void_reason,
                )
            )
        if inv.last_sent_at is not None:
            notice = inv.autopay_status == AUTOPAY_ACTIVE_STATUS
            entries.append(
                _entry(
                    at=inv.last_sent_at,
                    kind="comms",
                    code="autopay_notice_emailed" if notice else "invoice_emailed",
                    summary=(
                        f"Autopay notice emailed · {label}{who}"
                        if notice
                        else f"{label} invoice emailed{who}"
                    ),
                    invoice_id=inv.invoice_id,
                    student_name=inv.student_name,
                )
            )
    return entries


def _payment_entries(facts: FamilyFacts) -> list[dict[str, Any]]:
    """One entry per payment, listing every invoice it settled (PR #645 invariant)."""
    payments: dict[str, dict[str, Any]] = {}
    for inv in facts.invoices:
        for alloc in inv.allocations:
            slot = payments.setdefault(
                alloc.payment_id,
                {
                    "amount_cents": 0,
                    "invoice_ids": [],
                    "method": alloc.method,
                    "paid_at": alloc.paid_at,
                },
            )
            slot["amount_cents"] += alloc.amount_cents
            slot["invoice_ids"].append(inv.invoice_id)
            if slot["paid_at"] is None:
                slot["paid_at"] = alloc.paid_at
    entries: list[dict[str, Any]] = []
    for payment_id, slot in payments.items():
        if slot["paid_at"] is None:
            continue
        method = _method_label(slot["method"], facts.customer.card_last4)
        entries.append(
            _entry(
                at=slot["paid_at"],
                kind="money",
                code="payment_received",
                summary=f"{_money(slot['amount_cents'])} received · {method}",
                invoice_ids=sorted(slot["invoice_ids"]),
                amount_cents=slot["amount_cents"],
                reason=payment_id,
            )
        )
    return entries


def _attempt_entries(facts: FamilyFacts) -> list[dict[str, Any]]:
    invoice_by_id = {inv.invoice_id: inv for inv in facts.invoices}
    failed_by_invoice: dict[str, int] = {}
    entries: list[dict[str, Any]] = []
    ordered = sorted(
        facts.attempts,
        key=lambda a: (_as_utc(a.created_at) if a.created_at else _EPOCH, a.attempt_id),
    )
    for attempt in ordered:
        if attempt.status not in FAILURE_ATTEMPT_STATUSES or attempt.created_at is None:
            continue
        n = failed_by_invoice.get(attempt.invoice_id, 0) + 1
        failed_by_invoice[attempt.invoice_id] = n
        inv = invoice_by_id.get(attempt.invoice_id)
        detail = f" · {attempt.failure_message}" if attempt.failure_message else ""
        entries.append(
            _entry(
                at=attempt.created_at,
                kind="money",
                code="charge_failed",
                summary=f"Card declined · {_money(attempt.amount_cents)} · attempt {n}{detail}",
                invoice_id=attempt.invoice_id,
                student_name=inv.student_name if inv else None,
                amount_cents=attempt.amount_cents,
            )
        )
    return entries


def _dunning_entries(facts: FamilyFacts) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for d in facts.dunning:
        if d.autopay_disabled_at is not None:
            entries.append(
                _entry(
                    at=d.autopay_disabled_at,
                    kind="money",
                    code="autopay_disabled_by_ladder",
                    summary=f"Autopay disabled after {d.attempt_count} failed attempts",
                    invoice_id=d.invoice_id,
                )
            )
        if d.last_notification_at is not None:
            entries.append(
                _entry(
                    at=d.last_notification_at,
                    kind="comms",
                    code="failure_notice_emailed",
                    summary="Payment failure notice emailed",
                    invoice_id=d.invoice_id,
                )
            )
    return entries


def _audit_entries(facts: FamilyFacts) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for a in facts.audit:
        base = _AUDIT_SUMMARIES.get(a.action, a.action.replace("_", " ").capitalize())
        why = f" · {a.reason}" if a.reason else ""
        entries.append(
            _entry(
                at=a.at,
                kind="admin",
                code=f"audit:{a.action}",
                summary=f"{base}{why}",
                invoice_id=a.invoice_id,
                actor_id=a.actor_id,
                reason=a.reason,
            )
        )
    return entries


def _event_entries(facts: FamilyFacts, zone: tzinfo) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for ev in facts.events:
        verb = _EVENT_SUMMARIES.get(ev.event_type, ev.event_type)
        who = ev.student_name or "Student"
        tail = ""
        if ev.event_type == "paused" and ev.effective_at is not None:
            tail = f" · resumes {_day_label(ev.effective_at, zone)}"
        elif ev.reason:
            tail = f" · {ev.reason}"
        entries.append(
            _entry(
                at=ev.occurred_at,
                kind="lifecycle",
                code=f"enrollment:{ev.event_type}",
                summary=f"{who} {verb}{tail}",
                enrollment_id=ev.enrollment_id,
                student_name=ev.student_name,
                actor_id=ev.actor_id,
                reason=ev.reason,
            )
        )
    return entries


def build_timeline(facts: FamilyFacts, *, zone: tzinfo) -> list[dict[str, Any]]:
    """Spec §4: one merged list, newest first (ties by code), capped, comms muted."""
    entries = [
        *_invoice_entries(facts),
        *_payment_entries(facts),
        *_attempt_entries(facts),
        *_dunning_entries(facts),
        *_audit_entries(facts),
        *_event_entries(facts, zone),
    ]
    # Two stable sorts: ascending code as the tiebreak, then newest first.
    entries.sort(key=lambda e: e["code"])
    entries.sort(key=lambda e: e["at"], reverse=True)
    for e in entries:
        e["at"] = _iso(e["at"])
    return entries[:TIMELINE_CAP]


# --------------------------------------------------------------------------- view


def _enrollment_payload(e: EnrollmentFacts) -> dict[str, Any]:
    live = e.status not in _CANCELLED_ENROLLMENT_STATUSES
    return {
        "enrollment_id": e.enrollment_id,
        "session_id": e.session_id,
        "session_title": e.session_title,
        "schedule": e.schedule,
        "status": e.status,
        "monthly_price_cents": e.monthly_price_cents,
        "override_price_cents": e.override_price_cents,
        "autopay_status": e.autopay_status,
        "recurring_discount": e.recurring_discount,
        "resume_on": _iso(e.resume_on),
        "actions": ["recurring_discount"] if live else [],
    }


def _invoice_payload(inv: InvoiceFacts, *, eligibility: Eligibility) -> dict[str, Any]:
    allocated = sum(a.amount_cents for a in inv.allocations)
    # Invoices settled before payment_allocations existed carry no rows; report
    # total - balance and flag the row (spec §3.2).
    unlinked = inv.status == "paid" and not inv.allocations
    paid_cents = inv.total_cents - inv.balance_due_cents if unlinked else allocated
    notice = inv.autopay_status == AUTOPAY_ACTIVE_STATUS
    return {
        "invoice_id": inv.invoice_id,
        "invoice_number": inv.invoice_number,
        "period": inv.period,
        "student_id": inv.student_id,
        "student_name": inv.student_name,
        "enrollment_id": inv.enrollment_id,
        "status": inv.status,
        "total_cents": inv.total_cents,
        "paid_cents": paid_cents,
        "balance_due_cents": inv.balance_due_cents,
        "due_date": _iso(inv.due_date),
        "created_at": _iso(inv.created_at),
        "paid_at": _iso(inv.paid_at),
        "voided_at": _iso(inv.voided_at),
        "void_reason": inv.void_reason,
        "settlement_unlinked": unlinked,
        "delivery": {
            "status": inv.delivery_status,
            "last_sent_at": _iso(inv.last_sent_at),
            "kind": "autopay_notice" if notice else "invoice",
        },
        "allocations": [
            {
                "payment_id": a.payment_id,
                "amount_cents": a.amount_cents,
                "method": a.method,
                "paid_at": _iso(a.paid_at),
                "stripe_payment_intent_id": a.stripe_payment_intent_id,
            }
            for a in inv.allocations
        ],
        "credits": [
            {"credit_id": c.credit_id, "amount_cents": c.amount_cents} for c in inv.credits
        ],
        "chargeable": eligibility.eligible,
        "actions": invoice_actions(inv, eligibility=eligibility),
    }


def _last_payment(facts: FamilyFacts) -> dict[str, Any] | None:
    newest: tuple[datetime, str] | None = None
    for inv in facts.invoices:
        for a in inv.allocations:
            if a.paid_at is None:
                continue
            candidate = (_as_utc(a.paid_at), a.payment_id)
            if newest is None or candidate[0] > newest[0]:
                newest = candidate
    if newest is None:
        return None
    paid_at, pid = newest
    settled = [inv for inv in facts.invoices if any(a.payment_id == pid for a in inv.allocations)]
    allocs = [a for inv in settled for a in inv.allocations if a.payment_id == pid]
    return {
        "amount_cents": sum(a.amount_cents for a in allocs),
        "method": allocs[0].method if allocs else None,
        "paid_at": _iso(paid_at),
        "invoice_ids": [inv.invoice_id for inv in settled],
    }


def _last_failure(facts: FamilyFacts) -> dict[str, Any] | None:
    newest: tuple[datetime, str] | None = None
    for attempt in facts.attempts:
        if attempt.status not in FAILURE_ATTEMPT_STATUSES or attempt.created_at is None:
            continue
        at = _as_utc(attempt.created_at)
        if newest is None or at > newest[0]:
            newest = (at, attempt.failure_message or attempt.status)
    if newest is None:
        return None
    return {"code": newest[1], "at": _iso(newest[0])}


def build_family_billing_view(
    facts: FamilyFacts,
    *,
    timezone: str,
    generated_at: datetime,
    today: date,
) -> dict[str, Any]:
    zone = ZoneInfo(timezone)
    enrollments = _all_enrollments(facts)
    live = _live(enrollments)
    state = autopay_state(enrollments)
    autopay_by_enrollment = {e.enrollment_id: e.autopay_status for e in enrollments}

    invoice_rows: list[dict[str, Any]] = []
    next_charge: tuple[date, str] | None = None
    for inv in facts.invoices:
        elig = autopay_eligibility(
            invoice_status=inv.status,
            balance_due_cents=inv.balance_due_cents,
            enrollment_id=inv.enrollment_id,
            autopay_enrollment_status=autopay_by_enrollment.get(
                inv.enrollment_id or "", inv.autopay_status
            ),
            has_payment_method=facts.customer.has_card,
            connected_account_ready=facts.connected_account_ready,
        )
        invoice_rows.append(_invoice_payload(inv, eligibility=elig))
        if elig.eligible and inv.due_date is not None:
            candidate = (inv.due_date, inv.invoice_id)
            if next_charge is None or candidate < next_charge:
                next_charge = candidate

    open_rows = [inv for inv in facts.invoices if inv.status in CHARGEABLE_INVOICE_STATUSES]

    if facts.customer.has_card:
        registration = "registered"
    elif facts.customer.last_invited_at is not None:
        registration = "invited"
    else:
        registration = "not_invited"

    return {
        "generated_at": _iso(generated_at),
        "timezone": timezone,
        "today": today.isoformat(),
        "parent": {
            "parent_id": facts.parent.parent_id,
            "name": facts.parent.name,
            "email": facts.parent.email,
            "phone": facts.parent.phone,
        },
        "header": {
            "balance_cents": sum(inv.balance_due_cents for inv in open_rows),
            "open_invoice_count": len(open_rows),
            "available_credit_cents": facts.available_credit_cents,
            "last_payment": _last_payment(facts),
            "autopay": {
                "state": state,
                "active_count": sum(1 for e in live if e.autopay_status == AUTOPAY_ACTIVE_STATUS),
                "total_count": len(live),
                "card_last4": facts.customer.card_last4,
                "card_label": facts.customer.card_label,
                "next_charge_on": _iso(next_charge[0]) if next_charge else None,
                "next_charge_invoice_id": next_charge[1] if next_charge else None,
                "last_failure": _last_failure(facts),
            },
            "registration": {
                "state": registration,
                "card_on_file": bool(facts.customer.has_card),
                "last_invited_at": _iso(facts.customer.last_invited_at),
            },
            "enrollment_counts": {
                "active": sum(1 for e in enrollments if e.status == "active"),
                "paused": sum(1 for e in enrollments if e.status == _PAUSED),
                "cancelled": sum(
                    1 for e in enrollments if e.status in _CANCELLED_ENROLLMENT_STATUSES
                ),
            },
        },
        "students": [
            {
                "student_id": s.student_id,
                "name": s.name,
                "status": s.status,
                "enrollments": [_enrollment_payload(e) for e in s.enrollments],
            }
            for s in facts.students
        ],
        "invoices": invoice_rows,
        "timeline": build_timeline(facts, zone=zone),
        "actions": family_actions(
            state=state, has_card=facts.customer.has_card, invoices=facts.invoices
        ),
        "warnings": list(facts.warnings),
    }
