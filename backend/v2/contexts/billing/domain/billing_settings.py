"""BillingSettings — academy-scoped cash-discount configuration.

Pure domain model. No infra imports. Defaults are fail-safe: discounts are
off unless an academy admin explicitly opts in.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class BillingSettings(BaseModel):
    """Academy-scoped billing configuration (cash/ACH discount + invoice numbering)."""

    model_config = ConfigDict(frozen=True)

    academy_id: str
    ach_discount_enabled: bool = False
    ach_discount_percent: float = 0
    ach_discount_label: str = "ACH autopay discount"
    max_ach_discount_percent: float = 3.0
    disclosure_text: str | None = None
    disclosure_version: str | None = None
    effective_at: datetime | None = None
    invoice_number_prefix: str = "BLNO"

    @classmethod
    def default(cls, academy_id: str) -> BillingSettings:
        """Fail-safe defaults: all discounts off."""
        return cls(academy_id=academy_id)
