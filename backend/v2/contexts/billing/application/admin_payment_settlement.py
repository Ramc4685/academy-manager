"""Fold settlement facts from payment documents into admin payment rows.

The admin payment list is invoice-centric: when a ledger or legacy payment
settles an invoice, the invoice row stays and the payment row is dropped.
Before this module the drop lost the payment's ``paid_at``, its real
``payment_method`` (``stripe_checkout``, ``zelle`` ...) and its Stripe ids, so
Stripe-paid invoices rendered as method "invoice" with no paid date.

``apply_settlement`` copies those facts onto the invoice row instead.
"""

from __future__ import annotations

from typing import Any

from backend.v2.contexts.billing.application.admin_money import coerce_report_datetime

STRIPE_ID_KEYS: tuple[str, ...] = (
    "stripe_payment_intent_id",
    "stripe_invoice_id",
    "stripe_checkout_session_id",
    "stripe_subscription_id",
)

# Placeholder methods stamped on rows that have not yet learned how they were
# settled. A real settlement method always replaces these.
_PLACEHOLDER_METHODS: frozenset[str] = frozenset({"", "invoice", "stripe"})


def has_stripe_ids(doc: dict[str, Any]) -> bool:
    return any(doc.get(key) for key in STRIPE_ID_KEYS)


def settlement_method(doc: dict[str, Any]) -> str | None:
    """Return the payment method a document settled with.

    Stripe-originated documents sometimes carry no ``payment_method``; treat any
    document with a Stripe id as a checkout so the UI can label it "Stripe".
    """

    method = str(doc.get("payment_method") or "").strip()
    if method:
        return method
    if has_stripe_ids(doc):
        return "stripe_checkout"
    return None


def apply_settlement(row: dict[str, Any], doc: dict[str, Any]) -> None:
    """Merge ``doc``'s settlement facts into ``row`` in place.

    - ``paid_at`` takes the latest settlement timestamp seen.
    - Stripe ids fill in whatever the row lacks; ``stripe_linked`` becomes true
      when any Stripe id is present.
    - ``payment_method`` is replaced when the row still holds a placeholder or
      when this document settled at or after the row's current ``paid_at``.
    """

    doc_paid_at = coerce_report_datetime(doc.get("paid_at") or doc.get("payment_date"))
    row_paid_at = coerce_report_datetime(row.get("paid_at") or row.get("payment_date"))
    newer = doc_paid_at is not None and (row_paid_at is None or doc_paid_at >= row_paid_at)
    if newer:
        row["paid_at"] = doc_paid_at

    for key in STRIPE_ID_KEYS:
        if not row.get(key) and doc.get(key):
            row[key] = doc[key]
    if has_stripe_ids(doc):
        row["stripe_linked"] = True

    method = settlement_method(doc)
    if method is None:
        return
    current = str(row.get("payment_method") or "")
    if current in _PLACEHOLDER_METHODS or newer:
        row["payment_method"] = method
