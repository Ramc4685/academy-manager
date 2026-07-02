"""Shared invoice-number allocation for application use cases."""

from __future__ import annotations

from typing import Any

from backend.v2.contexts.billing.domain.ledger import format_invoice_number


async def mint_invoice_number(
    *,
    billing_counters: Any | None,
    billing_settings: Any | None,
    academy_id: str,
    period: str,
) -> str | None:
    """Mint a human-facing invoice number, or ``None`` when not wired."""

    if billing_counters is None or billing_settings is None:
        return None
    yyyymm = period.replace("-", "")
    settings = await billing_settings.get()
    seq = await billing_counters.next_value(scope=f"invoice:{academy_id}:{yyyymm}")
    return format_invoice_number(prefix=settings.invoice_number_prefix, yyyymm=yyyymm, seq=seq)
