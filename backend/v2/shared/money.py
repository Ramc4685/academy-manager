"""Minor-unit money helpers shared across contexts.

Rounding a Decimal to whole minor units is not billing-specific — the coach
payout read models need exactly the same rule — and contexts may not import
one another (``tests/structural/test_layering.py``), so the helper lives here.
``contexts.billing.application.admin_money`` re-exports it.
"""

from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Decimal


def round_money_minor(value: Decimal) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_EVEN))
