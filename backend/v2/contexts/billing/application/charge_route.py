"""Resolve the current academy's ChargeRoute (house platform / connected / refused).

Every charge path calls :func:`resolve_charge_route` instead of re-deriving
"connected account ready? else platform fallback?" on its own. The routing
rule itself lives in ``domain/charge_route.py``.

Reads happen at call time through tenant-scoped repositories, so the route is
always the CURRENT request's academy, never a boot-time one.

Failure posture (unchanged from the per-site code this replaced):

* A billing-settings read failure means we cannot prove the academy is the
  house academy, so it is treated as NOT the house academy (fail closed), and
  the platform fee falls back to 0 (the academy keeps the whole charge) —
  logged, never blocking a payment through a ready connected account.
* A connected-account read failure propagates: the caller's charge fails.
"""

from __future__ import annotations

import logging

from backend.v2.contexts.billing.application.ports import (
    BillingSettingsRepository,
    ConnectedAccountRepository,
)
from backend.v2.contexts.billing.domain.charge_route import ChargeRoute, decide_charge_route

log = logging.getLogger(__name__)

__all__ = ["ChargeRoute", "resolve_charge_route"]


async def resolve_charge_route(
    *,
    connected_accounts: ConnectedAccountRepository | None,
    settings: BillingSettingsRepository | None,
    context: str,
) -> ChargeRoute:
    """The current academy's charge route. ``context`` only labels log lines."""
    if connected_accounts is None:
        return ChargeRoute(kind="unconfigured")

    is_house = False
    fee_bps = 0
    if settings is not None:
        try:
            current = await settings.get()
        except Exception as exc:
            log.warning(
                "%s: billing settings lookup failed — treating academy as non-house "
                "(fail closed) and charging no platform fee err=%s",
                context,
                exc,
            )
        else:
            # Derived on read from HOUSE_ACADEMY_ID by the settings repository
            # (infrastructure/house_academy.py): true only for the house academy.
            is_house = bool(getattr(current, "allow_platform_charge_fallback", False))
            fee_bps = int(getattr(current, "application_fee_bps", 0) or 0)

    account = None if is_house else await connected_accounts.get_for_academy()
    route = decide_charge_route(
        is_house_academy=is_house, account=account, application_fee_bps=fee_bps
    )
    if route.is_platform:
        log.info("%s: house academy — charging on the PLATFORM Stripe account", context)
    elif route.refused:
        log.warning("%s: no charge-ready connected account (route=%s)", context, route.kind)
    return route
