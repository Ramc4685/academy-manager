"""Mongo storage for scheduled billing reconciliation run summaries."""

from __future__ import annotations

from typing import Any

from backend.v2.shared.tenancy import TenantScopedRepository


class MongoBillingReconciliationRunRepository(TenantScopedRepository):
    collection_name = "billing_reconciliation_runs"

    async def record_run(self, **kwargs: Any) -> None:
        academy_id = str(kwargs.get("academy_id") or "")
        run_id = str(kwargs.get("run_id") or "")
        if not academy_id or not run_id:
            raise ValueError("reconciliation run requires academy_id and run_id")
        await self.collection.update_one(
            {"academy_id": academy_id, "run_id": run_id},
            {"$set": kwargs},
            upsert=True,
        )

    async def list_runs(self, academy_id: str, *, limit: int = 50) -> list[dict[str, Any]]:
        """Return this academy's most recent reconciliation runs, newest first."""
        cursor = (
            self.collection.find({"academy_id": academy_id})
            .sort("started_at", -1)
            .limit(limit)
        )
        return [{k: v for k, v in doc.items() if k != "_id"} async for doc in cursor]
