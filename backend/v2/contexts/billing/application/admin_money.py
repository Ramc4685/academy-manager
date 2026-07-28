"""Admin billing money math: cents/dollar conversions and payment/invoice amount
semantics used by the admin reports and payments composition.

Pure functions only — no I/O. Extracted from ``composition/admin.py`` (MT1
Phase A) so this business logic lives in the billing application layer
instead of the composition root.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any


def month_bounds(period: str) -> tuple[datetime, datetime]:
    year_str, month_str = period.split("-", 1)
    year = int(year_str)
    month = int(month_str)
    start = datetime(year, month, 1, tzinfo=UTC)
    if month == 12:
        end = datetime(year + 1, 1, 1, tzinfo=UTC)
    else:
        end = datetime(year, month + 1, 1, tzinfo=UTC)
    return start, end


def money_to_cents(value: Any) -> int:
    if value is None:
        return 0
    return round(float(value) * 100)


def payment_discount_cents(payment: dict[str, Any]) -> int:
    value = payment.get("discount_cents")
    if value is not None:
        return int(value)
    return money_to_cents(payment.get("discount"))


def payment_received_cents(payment: dict[str, Any]) -> int | None:
    for key in ("paid_amount_cents", "amount_received_cents"):
        value = payment.get(key)
        if value is not None:
            return int(value)
    for key in ("paid_amount", "amount_received"):
        value = payment.get(key)
        if value is not None:
            return money_to_cents(value)
    return None


def payment_final_amount_cents(payment: dict[str, Any]) -> int:
    for key in ("final_amount_cents", "final_amount"):
        value = payment.get(key)
        if value is not None:
            if key.endswith("_cents"):
                return int(value)
            return money_to_cents(value)
    for key in ("amount_cents", "gross_amount_cents"):
        value = payment.get(key)
        if value is not None:
            return max(int(value) - payment_discount_cents(payment), 0)
    for key in ("amount", "gross_amount"):
        value = payment.get(key)
        if value is not None:
            return max(money_to_cents(value) - payment_discount_cents(payment), 0)
    return 0


def payment_collected_cents(payment: dict[str, Any]) -> int:
    status = str(payment.get("status") or "")
    if status in {"partially_paid", "pending", "failed"}:
        return max(payment_received_cents(payment) or 0, 0)
    if status in {"succeeded", "paid", "partially_refunded", "refunded"}:
        paid = payment_received_cents(payment)
        if paid is None:
            paid = payment_final_amount_cents(payment)
        return max(paid - int(payment.get("refunded_cents") or 0), 0)
    return 0


def payment_outstanding_cents(payment: dict[str, Any]) -> int:
    status = str(payment.get("status") or "")
    if status not in {"pending", "failed", "partially_paid"}:
        return 0
    balance = payment.get("balance_due_cents")
    if balance is not None:
        return max(int(balance), 0)
    return max(payment_final_amount_cents(payment) - payment_collected_cents(payment), 0)


def invoice_status_for_admin(invoice: dict[str, Any]) -> str:
    status = str(invoice.get("status") or "open")
    if status in {"open", "draft"}:
        return "pending"
    if status == "void":
        return "waived"
    return status


def invoice_amount_cents(invoice: dict[str, Any]) -> int:
    subtotal = invoice.get("subtotal_cents")
    if subtotal is not None:
        return int(subtotal)
    total = int(invoice.get("total_cents") or 0)
    return total + int(invoice.get("discount_cents") or 0)


def invoice_final_amount_cents(invoice: dict[str, Any]) -> int:
    return int(invoice.get("total_cents") or invoice_amount_cents(invoice))


def invoice_paid_cents(invoice: dict[str, Any]) -> int:
    total = invoice_final_amount_cents(invoice)
    balance = max(int(invoice.get("balance_due_cents") or 0), 0)
    return max(total - balance, 0)


def invoice_outstanding_cents(invoice: dict[str, Any]) -> int:
    if str(invoice.get("status") or "") in {"paid", "void", "waived", "cancelled"}:
        return 0
    return max(int(invoice.get("balance_due_cents") or 0), 0)


def invoice_provider_keys(invoice: dict[str, Any]) -> set[str]:
    return {
        str(value)
        for value in (
            invoice.get("invoice_id"),
            invoice.get("invoice_number"),
            invoice.get("stripe_invoice_id"),
            invoice.get("stripe_payment_intent_id"),
        )
        if value
    }


def payment_provider_keys(payment: dict[str, Any]) -> set[str]:
    return {
        str(value)
        for value in (
            payment.get("payment_id"),
            payment.get("invoice_id"),
            payment.get("invoice_number"),
            payment.get("stripe_invoice_id"),
            payment.get("stripe_payment_intent_id"),
            payment.get("stripe_checkout_session_id"),
        )
        if value
    }


def payment_revenue_net_cents(payment: dict[str, Any]) -> int:
    paid = payment_received_cents(payment)
    if paid is None:
        paid = payment_final_amount_cents(payment)
    return max(paid - int(payment.get("refunded_cents") or 0), 0)


def invoice_to_admin_payment_row(invoice: dict[str, Any]) -> dict[str, Any]:
    total = invoice_final_amount_cents(invoice)
    paid = invoice_paid_cents(invoice)
    stripe_invoice_id = invoice.get("stripe_invoice_id")
    stripe_payment_intent_id = invoice.get("stripe_payment_intent_id")
    stripe_checkout_session_id = invoice.get("stripe_checkout_session_id")
    stripe_subscription_id = invoice.get("stripe_subscription_id")
    stripe_linked = any(
        value
        for value in (
            stripe_invoice_id,
            stripe_payment_intent_id,
            stripe_checkout_session_id,
            stripe_subscription_id,
        )
    )
    return {
        "payment_id": str(invoice.get("invoice_id") or invoice.get("_id") or ""),
        "invoice_id": str(invoice.get("invoice_id") or "") or None,
        "parent_id": str(invoice.get("parent_id") or invoice.get("parent_user_id") or ""),
        "parent_name": None,
        "student_id": str(invoice.get("student_id") or "") or None,
        "student_name": None,
        "enrollment_id": str(invoice.get("enrollment_id") or "") or None,
        "session_id": str(invoice.get("session_id") or "") or None,
        "period": str(invoice.get("period") or "") or None,
        "amount_cents": invoice_amount_cents(invoice),
        "discount_cents": int(invoice.get("discount_cents") or 0),
        "final_amount_cents": total,
        "amount_received_cents": paid,
        "paid_amount_cents": paid,
        "balance_due_cents": max(int(invoice.get("balance_due_cents") or 0), 0),
        # surfaced from APPROVED OVERPAYMENT credits, batch-enriched onto the doc by the
        # list builder (no longer hardcoded 0)
        "overpayment_credit_cents": int(invoice.get("overpayment_credit_cents") or 0),
        "currency": str(invoice.get("currency") or "usd"),
        "status": invoice_status_for_admin(invoice),
        "refunded_cents": int(invoice.get("refunded_cents") or 0),
        "invoice_number": invoice.get("invoice_number") or invoice.get("invoice_id"),
        "payment_method": "stripe" if stripe_linked else "invoice",
        "stripe_linked": stripe_linked,
        "stripe_customer_id": invoice.get("stripe_customer_id"),
        "stripe_checkout_session_id": stripe_checkout_session_id,
        "stripe_subscription_id": stripe_subscription_id,
        "stripe_invoice_id": stripe_invoice_id,
        "stripe_payment_intent_id": stripe_payment_intent_id,
        "reconciliation_status": invoice.get("reconciliation_status"),
        "created_at": invoice.get("created_at") or datetime.now(UTC),
    }


def coerce_report_date(value: object) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def coerce_report_datetime(value: object) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.astimezone(UTC) if value.tzinfo is not None else value.replace(tzinfo=UTC)
    if isinstance(value, date):
        return datetime.combine(value, time.min, tzinfo=UTC)
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return None
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            try:
                parsed_date = date.fromisoformat(raw[:10])
            except ValueError:
                return None
            return datetime.combine(parsed_date, time.min, tzinfo=UTC)
        return parsed.astimezone(UTC) if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
    return None


def period_start_datetime(period: object) -> datetime | None:
    if not isinstance(period, str) or not period:
        return None
    try:
        start, _ = month_bounds(period)
    except (TypeError, ValueError):
        return None
    return start


def payment_effective_at(payment: dict[str, Any]) -> datetime | None:
    for key in ("paid_at", "payment_date", "created_at"):
        parsed = coerce_report_datetime(payment.get(key))
        if parsed is not None:
            return parsed
    return period_start_datetime(payment.get("period"))


def payment_effective_month(payment: dict[str, Any]) -> str:
    effective_at = payment_effective_at(payment)
    return effective_at.strftime("%Y-%m") if effective_at is not None else ""


def ledger_payment_effective_at(payment: dict[str, Any]) -> datetime | None:
    for key in ("paid_at", "created_at"):
        parsed = coerce_report_datetime(payment.get(key))
        if parsed is not None:
            return parsed
    return None


def ledger_payment_effective_month(payment: dict[str, Any]) -> str:
    effective_at = ledger_payment_effective_at(payment)
    return effective_at.strftime("%Y-%m") if effective_at is not None else ""


def missing_or_empty_field(field: str) -> dict[str, Any]:
    return {"$or": [{field: None}, {field: ""}]}


def field_window_or(field: str, start: datetime, end: datetime) -> list[dict[str, Any]]:
    return [
        {field: {"$gte": start, "$lt": end}},
        {
            field: {
                "$gte": start.date().isoformat(),
                "$lt": end.date().isoformat(),
            }
        },
    ]


def ledger_payment_effective_window_query(start: datetime, end: datetime) -> dict[str, Any]:
    paid_at_missing = missing_or_empty_field("paid_at")
    return {
        "$or": [
            *field_window_or("paid_at", start, end),
            {
                "$and": [
                    paid_at_missing,
                    {"$or": field_window_or("created_at", start, end)},
                ]
            },
        ]
    }


def payment_effective_window_or(start: datetime, end: datetime) -> list[dict[str, Any]]:
    paid_at_missing = missing_or_empty_field("paid_at")
    payment_date_missing = missing_or_empty_field("payment_date")
    return [
        *field_window_or("paid_at", start, end),
        {
            "$and": [
                paid_at_missing,
                {"$or": field_window_or("payment_date", start, end)},
            ]
        },
        {
            "$and": [
                paid_at_missing,
                payment_date_missing,
                {"$or": field_window_or("created_at", start, end)},
            ]
        },
    ]


def legacy_payment_cash_candidate_query(
    academy_id: str, period: str, start: datetime, end: datetime
) -> dict[str, Any]:
    return {
        "academy_id": academy_id,
        "is_deleted": {"$ne": True},
        "$or": [
            *payment_effective_window_or(start, end),
            {"period": period},
        ],
    }


def payment_due_date(payment: dict[str, Any], fallback: date) -> date:
    for key in ("due_date", "due_at", "created_at"):
        parsed = coerce_report_date(payment.get(key))
        if parsed is not None:
            return parsed
    return fallback


def invoice_due_date(invoice: dict[str, Any], fallback: date) -> date:
    for key in ("due_date", "due_at", "created_at"):
        parsed = coerce_report_date(invoice.get(key))
        if parsed is not None:
            return parsed
    return fallback


def aging_label(days_late: int) -> str:
    if days_late <= 0:
        return "Current"
    if days_late <= 30:
        return "1-30"
    if days_late <= 60:
        return "31-60"
    return "60+"


def cents_to_dollars(cents: int) -> str:
    return f"{cents / 100:.2f}"


def round_money_minor(value: Decimal) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_EVEN))
