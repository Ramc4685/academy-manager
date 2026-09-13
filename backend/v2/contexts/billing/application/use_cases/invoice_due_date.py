"""Where an invoice's due date comes from when the caller did not pick one.

The monthly generator dates every invoice it raises ``invoice_due_days`` out
(``MongoMonthlyBilling._load_invoice_due_days``), which is also when the dunning
ladder makes its first autopay attempt. Anything created by hand — the family
page's "Create invoice" and "Bill this month", the enrollment-move top-up — has
to read the same Billing rule, or one month carries two due dates for one family
and month close reports ``charge_on_varies`` (#739).
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any, Protocol

from backend.v2.contexts.billing.domain.billing_settings import BillingSettings

log = logging.getLogger(__name__)

#: Used when this academy has no billing_settings doc, the doc cannot be read, or
#: the field is explicitly null. Settings are advisory for invoicing: an
#: unreadable doc must never block a hand-billed invoice.
DEFAULT_INVOICE_DUE_DAYS = BillingSettings.default("").invoice_due_days


class BillingSettingsReader(Protocol):
    async def get(self) -> Any: ...


async def invoice_due_days(settings: BillingSettingsReader | None) -> int:
    """This academy's grace window, degrading to the model default."""
    if settings is None:
        return DEFAULT_INVOICE_DUE_DAYS
    try:
        current = await settings.get()
    except Exception:
        log.exception("invoice_due_days_settings_unreadable")
        return DEFAULT_INVOICE_DUE_DAYS
    # Only ``None`` falls back. ``int(value or 0)`` would turn an explicit null
    # (the field is optional on older docs) into "due today" and the dunning
    # ladder would chase a charge the parent has not seen yet; ``value or
    # DEFAULT`` would discard a deliberately configured 0.
    value = getattr(current, "invoice_due_days", None)
    return DEFAULT_INVOICE_DUE_DAYS if value is None else int(value)


async def resolve_invoice_due_date(
    settings: BillingSettingsReader | None,
    *,
    due_date: date | None,
    today: date,
) -> date:
    """The caller's own due date when it picked one, else today + the configured window."""
    if due_date is not None:
        return due_date
    return today + timedelta(days=await invoice_due_days(settings))
