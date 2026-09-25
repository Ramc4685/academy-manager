"""Tenant-scoped ConnectedAccount storage (Slice I).

Collection ``academy_connected_accounts``: one document per academy holding
its Stripe Connect merchant identity + onboarding status/capabilities.
"""

from __future__ import annotations

from datetime import UTC, datetime

from backend.v2.contexts.billing.domain.connected_account import (
    ConnectedAccount,
    ConnectedAccountStatus,
)
from backend.v2.shared.tenancy import TenantScopedRepository, current_academy_id


class MongoConnectedAccountRepository(TenantScopedRepository):
    collection_name = "academy_connected_accounts"

    async def get_for_academy(self) -> ConnectedAccount | None:
        """Return this academy's connected account, or None if not onboarded."""
        doc = await self._find_one()
        return self._to_domain(doc)

    async def get_by_stripe_account_id(self, stripe_account_id: str) -> ConnectedAccount | None:
        """Resolve a connected account by its Stripe id, scoped to this tenant.

        Tenant-scoped: an academy can only resolve its OWN connected account id,
        so a Connect webhook for another academy's account never leaks through.
        """
        doc = await self._find_one({"stripe_account_id": stripe_account_id})
        return self._to_domain(doc)

    async def academy_id_for_account(self, stripe_account_id: str) -> str | None:
        account = await self.get_by_stripe_account_id(stripe_account_id)
        return account.academy_id if account else None

    async def upsert(self, account: ConnectedAccount) -> None:
        payload = account.model_dump(mode="python")
        payload.pop("academy_id", None)
        await self._update_one({}, {"$set": payload}, upsert=True)

    async def update_status(
        self,
        *,
        stripe_account_id: str,
        status: ConnectedAccountStatus,
        capabilities: dict[str, str] | None = None,
        charges_enabled: bool | None = None,
        payouts_enabled: bool | None = None,
        skip_if_disconnected: bool = False,
    ) -> bool:
        """Apply a status change; returns False when no row was updated.

        ``skip_if_disconnected`` makes the write conditional on the row not
        being owner-disconnected, in the same atomic update, so a Stripe webhook
        racing a disconnect can never re-activate it.
        """
        update: dict[str, object] = {
            "status": status,
            "updated_at": datetime.now(UTC),
        }
        if capabilities is not None:
            update["capabilities"] = dict(capabilities)
        if charges_enabled is not None:
            update["charges_enabled"] = charges_enabled
        if payouts_enabled is not None:
            update["payouts_enabled"] = payouts_enabled
        filter_: dict[str, object] = {"stripe_account_id": stripe_account_id}
        if skip_if_disconnected:
            # Matches a missing field too, so rows written before the marker
            # existed stay webhook-updatable.
            filter_["disconnected_at"] = None
        result = await self._update_one(filter_, {"$set": update})
        return bool(result.matched_count)

    async def mark_disconnected(self, *, stripe_account_id: str) -> None:
        """Owner disconnect: disable the account and stamp the sticky marker."""
        now = datetime.now(UTC)
        await self._update_one(
            {"stripe_account_id": stripe_account_id},
            {
                "$set": {
                    "status": "disabled",
                    "charges_enabled": False,
                    "payouts_enabled": False,
                    "disconnected_at": now,
                    "updated_at": now,
                }
            },
        )

    @staticmethod
    def _to_domain(doc: dict | None) -> ConnectedAccount | None:
        if not doc:
            return None
        doc = dict(doc)
        doc.pop("_id", None)
        doc.setdefault("academy_id", current_academy_id())
        return ConnectedAccount.model_validate(doc)
