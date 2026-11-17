"""The billing fields of an ``enrollments`` row that "Not billed" writes.

Only ``billing_type`` and its ``not_billed_*`` companions; the enrollment
lifecycle stays with the enrollment context. Tenant-scoped like every repo.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from backend.v2.shared.tenancy import TenantScopedRepository


class MongoEnrollmentNotBilledStore(TenantScopedRepository):
    collection_name = "enrollments"

    async def get(self, enrollment_id: str) -> Mapping[str, Any] | None:
        doc: Mapping[str, Any] | None = await self._find_one(
            {"enrollment_id": enrollment_id, "is_deleted": {"$ne": True}}
        )
        return doc

    async def mark_not_billed(
        self,
        enrollment_id: str,
        *,
        billing_type: str,
        reason: str,
        note: str | None,
        previous_billing_type: str | None,
        actor_id: str,
        at: datetime,
    ) -> None:
        fields: dict[str, Any] = {
            "billing_type": billing_type,
            "not_billed_reason": reason,
            "not_billed_note": note,
            "not_billed_by": actor_id,
            "not_billed_at": at,
            "updated_at": at,
        }
        if previous_billing_type is not None:
            fields["billing_type_before_not_billed"] = previous_billing_type
        await self._update_one({"enrollment_id": enrollment_id}, {"$set": fields})

    async def start_billing(
        self,
        enrollment_id: str,
        *,
        billing_type: str,
        skip_period: str,
        actor_id: str,
        at: datetime,
    ) -> None:
        await self._update_one(
            {"enrollment_id": enrollment_id},
            {
                "$set": {
                    "billing_type": billing_type,
                    "billing_started_by": actor_id,
                    "billing_started_at": at,
                    "updated_at": at,
                },
                "$unset": {
                    "not_billed_reason": "",
                    "not_billed_note": "",
                    "not_billed_by": "",
                    "not_billed_at": "",
                    "billing_type_before_not_billed": "",
                },
                # The month it starts in stays unbilled; the next run invoices.
                "$addToSet": {"skip_periods": skip_period},
            },
        )
