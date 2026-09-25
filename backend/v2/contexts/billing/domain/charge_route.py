"""ChargeRoute — which Stripe account a parent charge settles on.

The one routing rule every charge path shares (checkout, autopay setup,
invoice pay links, balance checkout, off-session autopay) and every
"can parents pay right now?" read model reports:

1. The HOUSE academy (the academy that owns the platform Stripe account,
   BLNO) charges on the platform account. It never uses a connected account.
2. Any other academy charges through its own connected account, but only once
   that account is ready for charges (``ConnectedAccount.is_ready_for_charges``).
3. Otherwise the charge is refused: ``no_account`` when the academy never
   onboarded online payments, ``account_not_ready`` when an account exists but
   cannot take charges yet.

Pure domain. The application layer (``application/charge_route.py``) does the
repository reads and calls :func:`decide_charge_route`.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from backend.v2.contexts.billing.domain.connected_account import ConnectedAccount
from backend.v2.contexts.billing.domain.fees import application_fee_cents

ChargeRouteKind = Literal[
    # Charge on the platform account (the house academy).
    "platform",
    # Charge through the academy's charge-ready connected account.
    "connected",
    # Refused: the academy has no connected account at all.
    "no_account",
    # Refused: a connected account exists but is not ready for charges.
    "account_not_ready",
    # The connected-account store is not wired (test/dev compositions only).
    # Callers keep their historical handling of that wiring state.
    "unconfigured",
]


class ChargeRoute(BaseModel):
    """Where one charge settles, and the academy's platform fee for it."""

    model_config = ConfigDict(frozen=True)

    kind: ChargeRouteKind
    # The academy's connected Stripe account id; set only for ``connected``.
    stripe_account_id: str | None = None
    # The academy's platform application fee in basis points; only ever
    # applied on a ``connected`` route.
    application_fee_bps: int = 0

    @classmethod
    def platform(cls) -> ChargeRoute:
        return cls(kind="platform")

    @classmethod
    def connected(cls, stripe_account_id: str, *, application_fee_bps: int = 0) -> ChargeRoute:
        if not stripe_account_id:
            raise ValueError("a connected charge route needs a stripe account id")
        return cls(
            kind="connected",
            stripe_account_id=stripe_account_id,
            application_fee_bps=application_fee_bps,
        )

    @property
    def is_platform(self) -> bool:
        return self.kind == "platform"

    @property
    def is_connected(self) -> bool:
        return self.kind == "connected"

    @property
    def payments_possible(self) -> bool:
        """True when a charge on this route can be created at all."""
        return self.kind in ("platform", "connected")

    @property
    def refused(self) -> bool:
        """True when the academy must not be charged (no ready account)."""
        return self.kind in ("no_account", "account_not_ready")

    @property
    def connected_account_id(self) -> str | None:
        """The connected account a charge routes to, or None on the platform."""
        return self.stripe_account_id if self.kind == "connected" else None

    def application_fee_cents(self, amount_cents: int) -> int:
        """The platform fee for one charge on this route, in cents.

        Zero on every route but ``connected`` — a platform charge already
        settles entirely to the platform.
        """
        if self.kind != "connected" or amount_cents <= 0:
            return 0
        return application_fee_cents(amount_cents, self.application_fee_bps)


def decide_charge_route(
    *,
    is_house_academy: bool,
    account: ConnectedAccount | None,
    application_fee_bps: int = 0,
) -> ChargeRoute:
    """Apply the routing rule. See the module docstring."""
    if is_house_academy:
        return ChargeRoute.platform()
    if account is None:
        return ChargeRoute(kind="no_account")
    if not account.is_ready_for_charges():
        return ChargeRoute(kind="account_not_ready")
    return ChargeRoute.connected(
        account.stripe_account_id, application_fee_bps=max(0, int(application_fee_bps))
    )
