"""Payment-attempt status vocabulary shared by application and infrastructure.

The ``payment_attempts`` collection was built for **charge outcomes** — an
autopay/off-session PaymentIntent that succeeded, declined, or needs action.
Issue #426 added a second, structurally different kind of row: a Stripe Checkout
*pay link* that we tried and failed to create ("mint"). Recording those on the
same collection is what makes them visible to operators without new
infrastructure, but they are NOT charge outcomes and must never be read as one.

Three consumers key off charge statuses and would misread a mint failure:

* ``MongoDunningStateRepository._latest_payment_attempt_status`` — a mint
  failure written after a genuine ``succeeded`` row would stop dunning from
  resolving an invoice that just paid, and keep escalating it (terminal rung:
  autopay disabled).
* ``MongoBillingLedgerRepository.list_open_failed_attempts`` — the admin
  billing-health "failed payments" list, whose Retry button fires an
  off-session card charge.
* The admin revenue reports' ``failed_payment_count``.

So mint failures get their own status value, and the charge-outcome readers
filter them out explicitly via ``exclude_non_charge_attempts``.
"""

from __future__ import annotations

from typing import Any

#: Status stamped on a `payment_attempts` row recording a pay link that could
#: not be created. Deliberately NOT "failed" — see module docstring.
CHECKOUT_MINT_FAILED_STATUS = "checkout_mint_failed"

#: Every attempt status that is not a charge outcome.
NON_CHARGE_ATTEMPT_STATUSES: tuple[str, ...] = (CHECKOUT_MINT_FAILED_STATUS,)


def exclude_non_charge_attempts(query: dict[str, Any]) -> dict[str, Any]:
    """Return ``query`` narrowed to charge-outcome attempt rows only.

    Use this in every read that answers "what happened to this invoice's
    payment?" — a pay-link mint failure is an operator signal, not an outcome
    of trying to take money.
    """
    return {**query, "status": {"$nin": list(NON_CHARGE_ATTEMPT_STATUSES)}}
