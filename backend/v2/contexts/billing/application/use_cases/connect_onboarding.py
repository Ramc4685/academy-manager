"""Start / refresh an academy's Stripe Connect onboarding (Slice I).

Creates the academy's Accounts v2 connected account on first run (persisting a
``ConnectedAccount`` aggregate), then always mints a fresh hosted onboarding
AccountLink. Idempotent: a second call reuses the existing connected account and
just refreshes the link.

Reconnect: when the existing account was disconnected by the owner (or is
disabled), starting onboarding again is the explicit reconnect. It clears the
disconnect marker, resets the status, and resyncs it from Stripe so an account
that is still charge-ready is usable again without waiting on a webhook.

Liability: direct charges need an account where Stripe collects the fees and
carries the losses. The model Stripe reports is persisted on create and on
every resync. An existing account whose model is not (known to be) that is
resynced from Stripe; if Stripe then reports the platform as fee or loss
collector (a pre-direct-charges express account, whose responsibilities
cannot be changed), a NEW direct-charge account replaces it. This is what
"reconnect Stripe" in the charge route's refusal does. When Stripe does not
report the model, the account is kept and stays refused (fail closed).
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from backend.v2.contexts.billing.application.ports import (
    ConnectedAccountRepository,
    StripeGateway,
)
from backend.v2.contexts.billing.domain.connected_account import (
    ConnectedAccount,
    liability_from_stripe_account,
)
from backend.v2.contexts.billing.domain.errors import (
    AcademyMismatchError,
    ConnectOnboardingFailed,
    HouseAcademyUsesPlatformAccount,
)
from backend.v2.shared.security.redirect import validate_redirect_url
from backend.v2.shared.tenancy import tenant_scope

log = logging.getLogger(__name__)


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
        allowed_redirect_origins: Iterable[str] | Callable[[], Iterable[str]],
        academy_id: str | None = None,
        house_academy_id: str | None = None,
    ) -> None:
        self._stripe = stripe
        self._connected_accounts = connected_accounts
        # A callable is evaluated per call so the allowlist can include the
        # REQUEST's resolved tenant origins (dynamically onboarded academies
        # are not in the static env-var list). A plain iterable is materialized
        # once, as before, for the static/test case.
        self._allowed_redirect_origins: tuple[str, ...] | Callable[[], Iterable[str]] = (
            allowed_redirect_origins
            if callable(allowed_redirect_origins)
            else tuple(allowed_redirect_origins)
        )
        self._academy_id = academy_id
        # The house academy charges on the platform account; it never onboards
        # a connected account (see infrastructure/house_academy.py).
        self._house_academy_id = house_academy_id

    def _current_allowed_origins(self) -> tuple[str, ...]:
        source = self._allowed_redirect_origins
        return tuple(source()) if callable(source) else source

    async def start(
        self,
        *,
        academy_id: str,
        refresh_url: str,
        return_url: str,
        display_name: str | None = None,
        contact_email: str | None = None,
    ) -> dict[str, str]:
        if self._academy_id is not None and academy_id != self._academy_id:
            raise AcademyMismatchError("academy_id mismatch for connect onboarding")
        if self._house_academy_id is not None and academy_id == self._house_academy_id:
            raise HouseAcademyUsesPlatformAccount(
                "This academy collects payments on the CourtMastr platform Stripe "
                "account, so it does not connect a separate Stripe account."
            )

        # Same allowlist as parent checkout redirects: these URLs become browser
        # redirects via Stripe's hosted onboarding, so an unvalidated value is an
        # open-redirect vector (raises InvalidRedirectUrl on a bad origin).
        allowed_origins = self._current_allowed_origins()
        for url in (refresh_url, return_url):
            validate_redirect_url(url, allowed_origins=allowed_origins)

        with tenant_scope(academy_id):
            existing = await self._connected_accounts.get_for_academy()
            if existing is None:
                account = await self._create_account(
                    academy_id=academy_id,
                    display_name=display_name,
                    contact_email=contact_email,
                    idempotency_key=f"connect-account:{academy_id}",
                )
            elif existing.is_disconnected or existing.status == "disabled":
                account = await self._reconnect(existing)
            elif not existing.supports_direct_charges():
                account = await self._resync(existing)
            else:
                account = existing

            if not account.supports_direct_charges() and _platform_liable(account):
                # Stripe says the platform collects fees or carries losses on
                # this account; it can never take direct charges. Replace it.
                previous = account.stripe_account_id
                account = await self._create_account(
                    academy_id=academy_id,
                    display_name=display_name,
                    contact_email=contact_email,
                    idempotency_key=f"connect-account:{academy_id}:direct:{previous}",
                )
                log.warning(
                    "connect_account_replaced_platform_liable academy=%s old=%s new=%s",
                    academy_id,
                    previous,
                    account.stripe_account_id,
                )

            try:
                onboarding_url = await self._stripe.create_account_onboarding_link(
                    stripe_account_id=account.stripe_account_id,
                    refresh_url=refresh_url,
                    return_url=return_url,
                )
            except ValueError as exc:
                raise ConnectOnboardingFailed(
                    "Stripe Connect onboarding is temporarily unavailable."
                ) from exc

        return {
            "academy_id": academy_id,
            "stripe_account_id": account.stripe_account_id,
            "onboarding_url": onboarding_url,
            "status": account.status,
        }

    async def _create_account(
        self,
        *,
        academy_id: str,
        display_name: str | None,
        contact_email: str | None,
        idempotency_key: str,
    ) -> ConnectedAccount:
        try:
            created = await self._stripe.create_connected_account(
                academy_id=academy_id,
                display_name=display_name,
                contact_email=contact_email,
                idempotency_key=idempotency_key,
            )
        except ValueError as exc:
            raise ConnectOnboardingFailed(
                "Stripe Connect onboarding is temporarily unavailable."
            ) from exc
        # Persist what Stripe RECORDED, not what was requested.
        account = ConnectedAccount.new(
            academy_id=academy_id,
            stripe_account_id=str(created["id"]),
        ).with_liability(liability_from_stripe_account(created))
        await self._connected_accounts.upsert(account)
        return account

    async def _resync(self, existing: ConnectedAccount) -> ConnectedAccount:
        """Refresh an active account's status and liability model from Stripe.

        A failed read keeps the row as it is: its liability stays unknown, so
        the charge route keeps refusing it (fail closed).
        """
        try:
            snapshot = await self._stripe.retrieve_connected_account(existing.stripe_account_id)
        except Exception:
            log.warning(
                "connect_liability_resync_failed account=%s",
                existing.stripe_account_id,
                exc_info=True,
            )
            return existing
        account = existing.reconnected(stripe_account=snapshot)
        await self._connected_accounts.upsert(account)
        return account

    async def _reconnect(self, existing: ConnectedAccount) -> ConnectedAccount:
        try:
            snapshot = await self._stripe.retrieve_connected_account(existing.stripe_account_id)
        except Exception:  # a failed resync must not block reconnect
            # Fail safe: reset to pending (not charge-ready); the next
            # account.updated webhook, no longer blocked, brings it current.
            log.warning(
                "connect_reconnect_resync_failed account=%s",
                existing.stripe_account_id,
                exc_info=True,
            )
            snapshot = None
        account = existing.reconnected(stripe_account=snapshot)
        await self._connected_accounts.upsert(account)
        log.info(
            "connect_account_reconnected account=%s status=%s resynced=%s",
            account.stripe_account_id,
            account.status,
            snapshot is not None,
        )
        return account


def _platform_liable(account: ConnectedAccount) -> bool:
    """True when Stripe positively reported the platform as fee or loss
    collector. Unknown is not "platform liable" here: it is never replaced on
    a guess (the route still refuses it)."""
    return any(
        value is not None and value != "stripe"
        for value in (account.fees_collector, account.losses_collector)
    )
