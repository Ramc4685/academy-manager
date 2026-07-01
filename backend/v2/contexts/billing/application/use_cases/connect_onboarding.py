"""Start / refresh an academy's Stripe Connect onboarding (Slice I).

Creates the academy's Accounts v2 connected account on first run (persisting a
``ConnectedAccount`` aggregate), then always mints a fresh hosted onboarding
AccountLink. Idempotent: a second call reuses the existing connected account and
just refreshes the link.
"""

from __future__ import annotations

from dataclasses import dataclass

from backend.v2.contexts.billing.application.ports import (
    ConnectedAccountRepository,
    StripeGateway,
)
from backend.v2.contexts.billing.domain.connected_account import ConnectedAccount
from backend.v2.shared.tenancy import tenant_scope


@dataclass(frozen=True)
class ConnectOnboardingResult:
    academy_id: str
    stripe_account_id: str
    onboarding_url: str
    status: str


class StartConnectOnboarding:
    def __init__(
        self,
        *,
        stripe: StripeGateway,
        connected_accounts: ConnectedAccountRepository,
        academy_id: str,
    ) -> None:
        self._stripe = stripe
        self._connected_accounts = connected_accounts
        self._academy_id = academy_id

    async def start(
        self,
        *,
        academy_id: str,
        refresh_url: str,
        return_url: str,
        display_name: str | None = None,
        contact_email: str | None = None,
    ) -> dict[str, str]:
        if academy_id != self._academy_id:
            raise ValueError("academy_id mismatch for connect onboarding")

        with tenant_scope(academy_id):
            existing = await self._connected_accounts.get_for_academy()
            if existing is None:
                stripe_account_id = await self._stripe.create_connected_account(
                    academy_id=academy_id,
                    display_name=display_name,
                    contact_email=contact_email,
                )
                account = ConnectedAccount.new(
                    academy_id=academy_id,
                    stripe_account_id=stripe_account_id,
                )
                await self._connected_accounts.upsert(account)
            else:
                account = existing

            onboarding_url = await self._stripe.create_account_onboarding_link(
                stripe_account_id=account.stripe_account_id,
                refresh_url=refresh_url,
                return_url=return_url,
            )

        return {
            "academy_id": academy_id,
            "stripe_account_id": account.stripe_account_id,
            "onboarding_url": onboarding_url,
            "status": account.status,
        }
