"""Checkout hold — the lock that stops autopay charging an invoice a parent is already paying.

Nothing else marks an invoice "a human is paying this right now". Invoice status only
moves when the success webhook drains, and that drain is not prompt: a 60s scheduler
tick, 25 events per academy, with backoff up to an hour. The hourly dunning tick reads
the invoice in that gap, sees ``open``, and fires an off-session PaymentIntent under a
fresh ``retry_scope`` idempotency key — so Stripe's own idempotency does not dedupe it.
The parent is charged twice.

The hold closes that gap. ``SendInvoice`` stamps it on every invoice behind a freshly
minted Checkout Session; ``ChargeInvoiceViaAutopay`` refuses to charge while it is live;
the webhook handler clears it the moment the session completes, expires, or fails.

Release is event-driven — ``CHECKOUT_HOLD_WINDOW`` is only the backstop for a webhook
that never arrives at all (parent abandoned the tab AND ``checkout.session.expired`` was
lost). 90 minutes covers the documented worst case (up to an hour of webhook backoff,
plus the tick and per-academy drain) with margin. Stalling is close to free on the other
side: the dunning ladder's rungs are days apart (``DUNNING_SCHEDULE_DAYS``), and a parked
attempt is re-claimed on the next hourly tick without consuming a retry, so a held
invoice loses at most one tick — never a rung.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from backend.v2.contexts.billing.domain.ledger import LedgerInvoice

# Backstop only; see module docstring. Not a timeout the happy path ever reaches.
CHECKOUT_HOLD_WINDOW = timedelta(minutes=90)

# decline_code / dunning park reason for "a checkout session is already open".
CHECKOUT_HOLD_DECLINE_CODE = "checkout_session_open"


def place_checkout_hold(
    invoice: LedgerInvoice,
    *,
    checkout_session_id: str,
    now: datetime,
) -> LedgerInvoice:
    """Stamp an open Checkout Session on the invoice.

    A newer session always replaces an older one: the parent re-opening the pay link
    mints a fresh session, and it is that session we are now waiting on.
    """
    return invoice.model_copy(
        update={
            "checkout_hold_session_id": checkout_session_id,
            "checkout_hold_started_at": now,
            "updated_at": now,
        }
    )


def release_checkout_hold(
    invoice: LedgerInvoice,
    *,
    now: datetime,
    checkout_session_id: str | None = None,
) -> LedgerInvoice | None:
    """Clear the hold. Returns None when there was nothing to clear.

    When ``checkout_session_id`` is given, only a hold for *that* session is released.
    A late webhook for a superseded session must not unlock the invoice while a newer
    session is still open — that would re-open the very race this guards.
    """
    if invoice.checkout_hold_session_id is None and invoice.checkout_hold_started_at is None:
        return None
    if checkout_session_id is not None and invoice.checkout_hold_session_id != checkout_session_id:
        return None
    return invoice.model_copy(
        update={
            "checkout_hold_session_id": None,
            "checkout_hold_started_at": None,
            "updated_at": now,
        }
    )


def active_checkout_hold(invoice: LedgerInvoice, *, now: datetime) -> str | None:
    """Return the held session id when a hold is live, else None.

    A hold with no timestamp is treated as expired rather than as an eternal lock:
    failing open here only costs a duplicate-charge *risk* window, but failing closed
    on malformed data would stall collection forever with no way out.
    """
    started_at = invoice.checkout_hold_started_at
    if started_at is None:
        return None
    if now - started_at >= CHECKOUT_HOLD_WINDOW:
        return None
    return invoice.checkout_hold_session_id or ""
