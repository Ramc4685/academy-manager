"""Whether a class has a price yet (S10).

A class fee of ``None`` means nobody priced it: billing has nothing to charge
and staff must be told. ``0`` is an explicit choice (a free clinic) and is
priced. Every surface that warns about an unpriced class reads this one rule.
"""

from __future__ import annotations


def is_unpriced(amount_cents: int | None) -> bool:
    """True when the class fee was never set (``None``), not when it is free."""
    return amount_cents is None
