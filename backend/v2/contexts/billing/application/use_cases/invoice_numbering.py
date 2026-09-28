"""Shared invoice-number allocation for application use cases."""

from __future__ import annotations

import logging
from typing import Any

from backend.v2.contexts.billing.domain.ledger import format_invoice_number

log = logging.getLogger(__name__)


async def mint_invoice_number(
    *,
    billing_counters: Any | None,
    billing_settings: Any | None,
    academy_id: str,
    period: str,
) -> str | None:
    """Mint a human-facing invoice number, or ``None`` when it cannot be minted.

    ``None`` when the counters/settings were not wired, or when the academy
    has no invoice prefix. There is deliberately no fallback prefix: the old
    hardcoded "BLNO" default would have given another academy BLNO-numbered
    invoices, and a prefix guessed here would skip the platform's uniqueness
    check and then be locked in by the first number issued. A missing prefix
    is logged at ERROR (it means the academy was created without one or the
    0206 migration did not run), no counter value is consumed, and the invoice
    is created unnumbered, the state every pre-numbering invoice is already
    in. The display path (``composition.invoice_naming``) numbers it on first
    show or send once the prefix is set. Numbering is presentation; it must
    never block the money.
    """

    if billing_counters is None or billing_settings is None:
        return None
    yyyymm = period.replace("-", "")
    settings = await billing_settings.get()
    prefix = getattr(settings, "invoice_number_prefix", None)
    if not prefix:
        log.error(
            "invoice_prefix_not_configured academy_id=%s period=%s; invoice left unnumbered",
            academy_id,
            period,
        )
        return None
    seq = await billing_counters.next_value(scope=f"invoice:{academy_id}:{yyyymm}")
    return format_invoice_number(prefix=prefix, yyyymm=yyyymm, seq=seq)
