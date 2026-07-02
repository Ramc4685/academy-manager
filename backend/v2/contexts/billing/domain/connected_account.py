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
from typing import Literal

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

    def is_ready_for_charges(self) -> bool:
        """Only route fund flow once Stripe has enabled charges on the account."""
        return self.status == "active" and self.charges_enabled

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
