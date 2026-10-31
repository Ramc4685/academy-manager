"""ConnectedAccount — per-academy Stripe Connect merchant identity (Slice I).

Each academy (other than the house academy) is its own merchant-of-record and
is charged with DIRECT charges on its connected account (``Stripe-Account``).
Stripe collects processing fees from, and carries losses for, the account; the
academy gets the full Stripe Dashboard. See docs/runbooks/stripe-direct-charges.md.
Accounts created before direct charges were destination-charge (express,
platform-liable) accounts. Readiness accepts both, but a direct charge is only
ever routed to an account whose persisted liability model says Stripe collects
its fees AND carries its losses (``supports_direct_charges``); anything else,
including a legacy row with no recorded model, is refused (fail closed).

Pure domain model. No infra imports. The account is created via the Accounts v2
API (``POST /v2/core/accounts``) with ``configuration`` and
``defaults.responsibilities`` — the legacy ``type: express/custom/standard`` /
v1 ``controller`` model is never used.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

ConnectedAccountStatus = Literal["pending", "active", "restricted", "disabled"]

# The v1 Account capability key (Accounts v2
# ``configuration.merchant.capabilities.card_payments``) for card charges.
CARD_PAYMENTS_CAPABILITY = "card_payments"

#: The collector value meaning Stripe (not the platform) collects the account's
#: processing fees / carries its losses. Direct charges require it for both.
STRIPE_COLLECTOR = "stripe"

#: The liability-model fields persisted on the aggregate.
LIABILITY_FIELDS: tuple[str, ...] = ("fees_collector", "losses_collector", "dashboard")


class ConnectedAccount(BaseModel):
    """Academy-scoped Stripe Connect account aggregate."""

    model_config = ConfigDict(frozen=True)

    academy_id: str
    stripe_account_id: str
    status: ConnectedAccountStatus = "pending"
    capabilities: dict[str, str] = Field(default_factory=dict)
    charges_enabled: bool = False
    payouts_enabled: bool = False
    # Set when the academy owner disconnects Stripe. A disconnect is local
    # (the Stripe account lives on), so Stripe keeps sending ``account.updated``
    # events for it; while this is set those events must not re-activate the
    # account. Only an explicit reconnect (``reconnected``) clears it.
    disconnected_at: datetime | None = None
    # The account's liability model as Stripe reported it (Accounts v2
    # ``defaults.responsibilities`` / v1 ``controller``). ``None`` = unknown:
    # rows written before these fields existed, which were all express,
    # platform-liable accounts. Unknown never counts as Stripe-liable.
    fees_collector: str | None = None
    losses_collector: str | None = None
    dashboard: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @classmethod
    def new(
        cls,
        *,
        academy_id: str,
        stripe_account_id: str,
        now: datetime | None = None,
        fees_collector: str | None = None,
        losses_collector: str | None = None,
        dashboard: str | None = None,
    ) -> ConnectedAccount:
        """A freshly created connected account: pending onboarding, no capabilities.

        The liability model is whatever Stripe reported for the new account;
        left unset it stays unknown and the account never takes direct charges.
        """
        ts = now or datetime.now(UTC)
        return cls(
            academy_id=academy_id,
            stripe_account_id=stripe_account_id,
            status="pending",
            capabilities={},
            charges_enabled=False,
            payouts_enabled=False,
            fees_collector=fees_collector,
            losses_collector=losses_collector,
            dashboard=dashboard,
            created_at=ts,
            updated_at=ts,
        )

    def supports_direct_charges(self) -> bool:
        """True only when Stripe collects the fees AND carries the losses.

        A direct charge settles on this account; if the platform were the fee
        or loss collector it would pay Stripe's fees and be liable for refunds
        and disputes on money it never held. Unknown fails closed.
        """
        return self.fees_collector == STRIPE_COLLECTOR and self.losses_collector == STRIPE_COLLECTOR

    def with_liability(self, liability: dict[str, str]) -> ConnectedAccount:
        """A copy with the liability fields Stripe reported; absent keys keep
        their current value (a snapshot that omits them says nothing)."""
        update = {k: v for k, v in liability.items() if k in LIABILITY_FIELDS and v}
        return self.model_copy(update=update) if update else self

    @property
    def is_disconnected(self) -> bool:
        return self.disconnected_at is not None

    def is_ready_for_charges(self) -> bool:
        """Only route fund flow once Stripe has enabled charges on the account.

        Direct charges settle on the connected account itself, so readiness is
        the merchant ``card_payments`` capability plus ``charges_enabled``. The
        recipient ``transfers`` / ``stripe_transfers`` capability (destination
        charges only) is never required, so accounts created either way work.

        A ``card_payments`` entry that is present but not ``active`` blocks
        charges. An absent entry falls back to ``charges_enabled``: rows written
        before capabilities were tracked, or last written by a ``capability.*``
        event for a different capability, carry no ``card_payments`` key.
        """
        if self.status != "active" or not self.charges_enabled or self.is_disconnected:
            return False
        card_payments = self.capabilities.get(CARD_PAYMENTS_CAPABILITY)
        return card_payments is None or card_payments == "active"

    def reconnected(
        self,
        *,
        stripe_account: dict[str, Any] | None = None,
        now: datetime | None = None,
    ) -> ConnectedAccount:
        """Return a copy for an explicit owner reconnect.

        Clears the disconnect marker and resets status to ``pending`` with no
        charge/payout flags. When ``stripe_account`` (a fresh Stripe Account
        snapshot) is given, the status is re-derived from it instead, so a
        reconnect of an already-onboarded account does not wait on a webhook.
        """
        status: ConnectedAccountStatus = "pending"
        capabilities: dict[str, str] = {}
        charges_enabled = False
        payouts_enabled = False
        if stripe_account is not None:
            charges_enabled = bool(stripe_account.get("charges_enabled"))
            payouts_enabled = bool(stripe_account.get("payouts_enabled"))
            raw_capabilities = stripe_account.get("capabilities") or {}
            if isinstance(raw_capabilities, dict):
                capabilities = {str(k): str(v) for k, v in raw_capabilities.items()}
            status = status_from_stripe_flags(
                charges_enabled=charges_enabled,
                disabled_reason=_disabled_reason(stripe_account),
            )
        reset = self.model_copy(
            update={
                "status": status,
                "capabilities": capabilities,
                "charges_enabled": charges_enabled,
                "payouts_enabled": payouts_enabled,
                "disconnected_at": None,
                "updated_at": now or datetime.now(UTC),
            }
        )
        return reset.with_liability(liability_from_stripe_account(stripe_account))

    def with_status(
        self,
        *,
        status: ConnectedAccountStatus,
        capabilities: dict[str, str] | None = None,
        charges_enabled: bool | None = None,
        payouts_enabled: bool | None = None,
        now: datetime | None = None,
    ) -> ConnectedAccount:
        """Return a copy with onboarding status / capabilities advanced.

        Identity (``academy_id``/``stripe_account_id``) and ``created_at`` are
        preserved; ``updated_at`` advances.
        """
        return self.model_copy(
            update={
                "status": status,
                "capabilities": (
                    dict(capabilities) if capabilities is not None else self.capabilities
                ),
                "charges_enabled": (
                    charges_enabled if charges_enabled is not None else self.charges_enabled
                ),
                "payouts_enabled": (
                    payouts_enabled if payouts_enabled is not None else self.payouts_enabled
                ),
                "updated_at": now or datetime.now(UTC),
            }
        )


def status_from_stripe_flags(
    *, charges_enabled: bool, disabled_reason: str | None
) -> ConnectedAccountStatus:
    """Map Stripe's account flags onto our status (same rule as the webhook)."""
    if disabled_reason:
        return "disabled"
    return "active" if charges_enabled else "restricted"


def liability_from_stripe_account(stripe_account: dict[str, Any] | None) -> dict[str, str]:
    """The liability model a Stripe account snapshot reports, or ``{}``.

    Reads both shapes the platform sees:

    * Accounts v2 (the create response): ``defaults.responsibilities``
      ``fees_collector`` / ``losses_collector`` and a top-level ``dashboard``.
    * v1 Account (``account.updated`` payloads, ``Account.retrieve``):
      ``controller.fees.payer`` (``account`` = the account pays, i.e. Stripe
      collects -> ``stripe``; any ``application*`` value is kept as-is),
      ``controller.losses.payments`` and ``controller.stripe_dashboard.type``.

    Only keys the snapshot actually carries are returned, so a caller merging
    the result never erases a known value with "not reported".
    """
    if not isinstance(stripe_account, dict):
        return {}
    out: dict[str, str] = {}
    defaults = stripe_account.get("defaults")
    responsibilities = defaults.get("responsibilities") if isinstance(defaults, dict) else None
    if isinstance(responsibilities, dict):
        for key in ("fees_collector", "losses_collector"):
            value = responsibilities.get(key)
            if value:
                out[key] = str(value)
    dashboard = stripe_account.get("dashboard")
    if isinstance(dashboard, str) and dashboard:
        out["dashboard"] = dashboard
    controller = stripe_account.get("controller")
    if isinstance(controller, dict):
        fees = controller.get("fees")
        payer = fees.get("payer") if isinstance(fees, dict) else None
        if payer and "fees_collector" not in out:
            out["fees_collector"] = STRIPE_COLLECTOR if payer == "account" else str(payer)
        losses = controller.get("losses")
        loss_payer = losses.get("payments") if isinstance(losses, dict) else None
        if loss_payer and "losses_collector" not in out:
            out["losses_collector"] = str(loss_payer)
        stripe_dashboard = controller.get("stripe_dashboard")
        dash_type = stripe_dashboard.get("type") if isinstance(stripe_dashboard, dict) else None
        if dash_type and "dashboard" not in out:
            out["dashboard"] = str(dash_type)
    return out


def _disabled_reason(stripe_account: dict[str, Any]) -> str | None:
    # A v1 Account carries it under ``requirements``; accept a top-level value
    # too, matching what the Connect webhook handler reads.
    requirements = stripe_account.get("requirements")
    nested = requirements.get("disabled_reason") if isinstance(requirements, dict) else None
    reason = stripe_account.get("disabled_reason") or nested
    return str(reason) if reason else None
