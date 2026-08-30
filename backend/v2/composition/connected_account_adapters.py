"""Cross-context adapters bridging billing's ConnectedAccount records into
identity's Stripe gateway settings use cases.

These live in the composition layer, not in either context, per the
cross-context-import boundary rule — same pattern as ``_ConnectAccountResolver``
in ``composition/parent.py``.
"""

from __future__ import annotations

from backend.v2.contexts.billing.infrastructure.mongo_connected_account_repo import (
    MongoConnectedAccountRepository,
)
from backend.v2.shared.tenancy import tenant_scope


class ConnectedAccountGatewayReader:
    """Bridges billing's ConnectedAccountRepository into identity's gateway
    settings use case (Slice I follow-up). Lives in the composition root, not
    in either context, per the cross-context-import boundary rule — same
    pattern as ``_ConnectAccountResolver`` in ``composition/parent.py``.
    """

    def __init__(self, repo: MongoConnectedAccountRepository) -> None:
        self._repo = repo

    async def get_status_for_academy(self, academy_id: str) -> tuple[bool, str | None]:
        with tenant_scope(academy_id):
            account = await self._repo.get_for_academy()
        if account is None:
            return False, None
        return account.is_ready_for_charges(), account.stripe_account_id


class ConnectedAccountGatewayDisabler:
    """Marks an academy's Accounts-v2 ``ConnectedAccount`` disabled on disconnect.

    Companion to ``ConnectedAccountGatewayReader``: without this, disconnecting
    only clears the legacy ``academy.stripe_account_id`` field while the
    ConnectedAccount record — the real "connected"/charge-eligibility source
    of truth — stays active.
    """

    def __init__(self, repo: MongoConnectedAccountRepository) -> None:
        self._repo = repo

    async def disable_for_academy(self, academy_id: str) -> None:
        with tenant_scope(academy_id):
            account = await self._repo.get_for_academy()
            if account is None:
                return
            await self._repo.update_status(
                stripe_account_id=account.stripe_account_id,
                status="disabled",
                charges_enabled=False,
                payouts_enabled=False,
            )
