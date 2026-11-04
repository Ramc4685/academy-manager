"""ChargeRoute — which Stripe account a parent charge settles on.

The one routing rule every charge path shares (checkout, autopay setup,
invoice pay links, balance checkout, off-session autopay) and every
"can parents pay right now?" read model reports:

1. The HOUSE academy (the academy that owns the platform Stripe account,
   BLNO) charges on the platform account. It never uses a connected account.
2. Any other academy charges through its own connected account, but only once
   that account is ready for charges (``ConnectedAccount.is_ready_for_charges``)
   AND Stripe, not the platform, collects its fees and carries its losses
   (``ConnectedAccount.supports_direct_charges``).
3. Otherwise the charge is refused: ``no_account`` when the academy never
   onboarded online payments, ``account_not_ready`` when an account exists but
   cannot take charges yet, ``account_platform_liable`` when the account is (or
   may be — unknown fails closed) an express account where the platform pays
   Stripe's fees and carries losses. A direct charge on such an account would
   make the platform liable for money it never held; the owner reconnects
   Stripe, which creates a direct-charge account.

Pure domain. The application layer (``application/charge_route.py``) does the
repository reads and calls :func:`decide_charge_route`.
"""

from __future__ import annotations

from typing import Any, Literal

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
    # Refused: the account's liability model is not Stripe-collected fees and
    # Stripe-carried losses (legacy express accounts, or unknown).
    "account_platform_liable",
    # The connected-account store is not wired (test/dev compositions only).
    # Callers keep their historical handling of that wiring state.
    "unconfigured",
]


#: Owner-facing reason for each refused route (billing health, logs).
REFUSAL_MESSAGES: dict[str, str] = {
    "no_account": "No Stripe account is connected, so parents cannot pay online.",
    "account_not_ready": (
        "The connected Stripe account cannot take charges yet; finish Stripe onboarding."
    ),
    "account_platform_liable": (
        "Payments are paused until you reconnect Stripe: this account is not set up "
        "for direct charges (Stripe must collect its fees and carry its losses)."
    ),
}


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
        return self.kind in ("no_account", "account_not_ready", "account_platform_liable")

    @property
    def refusal_message(self) -> str | None:
        """Why this route refuses charges, in owner-facing words; None if not refused."""
        return REFUSAL_MESSAGES.get(self.kind) if self.refused else None

    @property
    def connected_account_id(self) -> str | None:
        """The connected account a charge routes to, or None on the platform."""
        return self.stripe_account_id if self.kind == "connected" else None

    def on_account_kwargs(self) -> dict[str, Any]:
        """Gateway kwargs that put one Stripe call on this route's account.

        ``{"stripe_account": <acct>}`` on a ``connected`` route (a DIRECT
        charge: the object is created on / read from the academy's own
        account); empty on every other route, so a platform (house academy)
        call passes exactly the kwargs it always did.
        """
        account = self.connected_account_id
        return {"stripe_account": account} if account else {}

    def idempotency_key(self, key: str) -> str:
        """Scope a Stripe idempotency key to this route's account.

        A connected route appends the account id, so a key minted for one
        account never collides with, or replays, a request on another. Every
        other route returns ``key`` unchanged: house keys stay byte-identical.
        """
        account = self.connected_account_id
        return f"{key}:acct:{account}" if account else key

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
    if not account.supports_direct_charges():
        return ChargeRoute(kind="account_platform_liable")
    return ChargeRoute.connected(
        account.stripe_account_id, application_fee_bps=max(0, int(application_fee_bps))
    )
