"""ConnectedAccount — per-academy Stripe Connect merchant identity (Slice I).

Each academy is its own merchant-of-record. Autopay fund flow routes through
its connected Stripe account via destination charges (``on_behalf_of`` +
``transfer_data.destination``); the platform initially accepts liability.

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
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @classmethod
    def new(
        cls,
        *,
        academy_id: str,
        stripe_account_id: str,
        now: datetime | None = None,
    ) -> ConnectedAccount:
        """A freshly created connected account: pending onboarding, no capabilities."""
        ts = now or datetime.now(UTC)
        return cls(
            academy_id=academy_id,
            stripe_account_id=stripe_account_id,
            status="pending",
            capabilities={},
            charges_enabled=False,
            payouts_enabled=False,
            created_at=ts,
            updated_at=ts,
        )

    @property
    def is_disconnected(self) -> bool:
        return self.disconnected_at is not None

    def is_ready_for_charges(self) -> bool:
        """Only route fund flow once Stripe has enabled charges on the account."""
        return self.status == "active" and self.charges_enabled and not self.is_disconnected

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
        return self.model_copy(
            update={
                "status": status,
                "capabilities": capabilities,
                "charges_enabled": charges_enabled,
                "payouts_enabled": payouts_enabled,
                "disconnected_at": None,
                "updated_at": now or datetime.now(UTC),
            }
        )

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


def _disabled_reason(stripe_account: dict[str, Any]) -> str | None:
    # A v1 Account carries it under ``requirements``; accept a top-level value
    # too, matching what the Connect webhook handler reads.
    requirements = stripe_account.get("requirements")
    nested = requirements.get("disabled_reason") if isinstance(requirements, dict) else None
    reason = stripe_account.get("disabled_reason") or nested
    return str(reason) if reason else None
