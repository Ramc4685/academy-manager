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

# Only money actually received settles an invoice. A pending, failed or expired
# attempt that references an invoice must NOT stamp paid_at / method / Stripe
# ids onto it, otherwise an unpaid invoice renders as "Stripe linked".
SETTLED_STATUSES: frozenset[str] = frozenset(
    {"succeeded", "paid", "partially_refunded", "refunded"}
)

# Placeholder methods stamped on rows that have not yet learned how they were
# settled. A real settlement method always replaces these. NOTE: "stripe" is
# NOT a placeholder — the Stripe webhook writes it as a real ledger method
# (alongside stripe_checkout / stripe_autopay / stripe_subscription), so an
# older settlement must not overwrite it.
_PLACEHOLDER_METHODS: frozenset[str] = frozenset({"", "invoice"})


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


def is_settled(doc: dict[str, Any]) -> bool:
    return str(doc.get("status") or "") in SETTLED_STATUSES


def apply_settlement(row: dict[str, Any], doc: dict[str, Any]) -> bool:
    """Merge ``doc``'s settlement facts into ``row`` in place.

    Returns False (and touches nothing) unless ``doc`` is money received.

    - ``paid_at`` takes the latest settlement timestamp seen.
    - Stripe ids fill in whatever the row lacks; ``stripe_linked`` becomes true
      when any Stripe id is present.
    - ``payment_method`` is replaced when the row still holds a placeholder or
      when this document settled at or after the row's current ``paid_at``.
    """

    if not is_settled(doc):
        return False
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
    if method is not None:
        current = str(row.get("payment_method") or "")
        if current in _PLACEHOLDER_METHODS or newer:
            row["payment_method"] = method
    return True


def settle_matching_rows(
    rows_by_key: dict[str, dict[str, Any]],
    keys: set[str],
    doc: dict[str, Any],
) -> int:
    """Apply ``doc``'s settlement to every distinct row reachable from ``keys``.

    ``rows_by_key`` maps provider keys (invoice_id, invoice_number, Stripe ids)
    to invoice rows; one row may be reachable through several keys and one
    payment may settle several invoices (balance checkouts write one ledger
    payment with one allocation per invoice). Returns the number of rows
    settled.
    """

    matched: list[dict[str, Any]] = []
    for key in keys:
        row = rows_by_key.get(key)
        if row is not None and not any(r is row for r in matched):
            matched.append(row)
    settled = 0
    for row in matched:
        if apply_settlement(row, doc):
            settled += 1
    return settled
