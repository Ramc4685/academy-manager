"""The offline (manual) payment methods an academy records against invoices.

Stored on the academy record as ``academies.manual_methods``. Until the owner
saves a choice in Settings -> Billing rules, the stored list is not a choice:
the only writers before this setting existed were ``upsert_defaults``
(``["cash", "check"]``) and local seed scripts, while the admin payment dialogs
always offered all six methods. So a list counts only when
``manual_methods_updated_at`` is set, which only the owner's save writes;
every other academy reads all six, in the order the dialogs have always used
(BLNO's behaviour today). No backfill is needed.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any, Final

from backend.v2.contexts.identity.domain.errors import InvalidManualPaymentMethods

#: Canonical set and order. Mirrors billing's ``ManualPaymentMethod`` Literal
#: (``tests/structural/test_manual_payment_methods_parity.py`` holds them equal)
#: and ``frontend/lib/payment-methods.ts``.
MANUAL_PAYMENT_METHODS: Final[tuple[str, ...]] = (
    "cash",
    "check",
    "zelle",
    "venmo",
    "bank_transfer",
    "other",
)

MANUAL_METHODS_FIELD: Final = "manual_methods"
#: Written only by the owner's save; marks the stored list as a real choice.
MANUAL_METHODS_UPDATED_AT_FIELD: Final = "manual_methods_updated_at"
MANUAL_METHODS_UPDATED_BY_FIELD: Final = "manual_methods_updated_by"


def effective_manual_methods(doc: Mapping[str, Any] | None) -> list[str]:
    """The methods the payment dialogs offer, in canonical order."""
    if not doc or doc.get(MANUAL_METHODS_UPDATED_AT_FIELD) is None:
        return list(MANUAL_PAYMENT_METHODS)
    stored = doc.get(MANUAL_METHODS_FIELD)
    if not isinstance(stored, list):
        return list(MANUAL_PAYMENT_METHODS)
    chosen = [method for method in MANUAL_PAYMENT_METHODS if method in stored]
    # Never offer nothing: an empty or all-unknown stored list reads as all six.
    return chosen or list(MANUAL_PAYMENT_METHODS)


def normalize_manual_methods(values: Iterable[Any]) -> list[str]:
    """Validate an owner's choice: known methods only, at least one.

    Returns the choice de-duplicated and in canonical order.
    """
    raw = list(values)
    unknown = sorted({str(v) for v in raw if v not in MANUAL_PAYMENT_METHODS})
    if unknown:
        raise InvalidManualPaymentMethods(
            f"Unknown payment method: {', '.join(unknown)}.",
        )
    chosen = [method for method in MANUAL_PAYMENT_METHODS if method in raw]
    if not chosen:
        raise InvalidManualPaymentMethods("Keep at least one offline payment method.")
    return chosen
