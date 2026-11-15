"""Academy-wide overdue family counts for the admin dashboard and students page.

The Payments bucket view is scoped to one billing period, so a family owing
last month and nothing yet due this month fell out of it (L2 risk review B2).
This read covers every period: one indexed invoice scan
(``academy_invoice_status_due_date``, migration 0156) plus two ``$in``
lookups. Bucket rules mirror :mod:`collections_buckets`: a failed autopay
attempt outranks past due, and an invoice covered by active autopay is not
past due.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from backend.v2.contexts.billing.application.autopay_eligibility import (
    AUTOPAY_ACTIVE_STATUS,
    CHARGEABLE_INVOICE_STATUSES,
)
from backend.v2.shared.tenancy import current_academy_id
from backend.v2.shared.time.academy_timezone import academy_timezone_lookup

# shortcut: counts stop at this many overdue invoices; page by due_date if an
# academy ever carries more open overdue invoices than this.
_MAX_INVOICES = 5000
_FAILED_LADDER_STATUSES = {"active", "processing"}


def _failed(dunning: dict[str, Any] | None) -> bool:
    if not dunning:
        return False
    status = dunning.get("status")
    return status == "dunned" or (
        status in _FAILED_LADDER_STATUSES and int(dunning.get("attempt_count") or 0) >= 1
    )


class OverdueFamiliesReader:
    def __init__(
        self,
        db: Any,
        *,
        academy_timezone: Callable[[str], Awaitable[str | None]],
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._db = db
        self._academy_timezone = academy_timezone
        self._clock = clock

    async def counts(self) -> dict[str, int]:
        """``past_due``: owing past the due date without autopay cover (no failed
        attempt). ``needs_action``: those plus families whose autopay failed."""
        academy_id = current_academy_id()
        zone = ZoneInfo(await self._academy_timezone(academy_id) or "UTC")
        today = self._clock().astimezone(zone).date()
        cutoff = datetime(today.year, today.month, today.day, tzinfo=UTC)
        invoices = (
            await self._db["invoices"]
            .find(
                {
                    "academy_id": academy_id,
                    "status": {"$in": sorted(CHARGEABLE_INVOICE_STATUSES)},
                    "due_date": {"$lt": cutoff},
                    "balance_due_cents": {"$gt": 0},
                    "is_deleted": {"$ne": True},
                },
                {
                    "_id": 0,
                    "invoice_id": 1,
                    "enrollment_id": 1,
                    "parent_id": 1,
                    "parent_user_id": 1,
                },
            )
            .limit(_MAX_INVOICES)
            .to_list(_MAX_INVOICES)
        )
        enrollment_ids = sorted(
            {str(i["enrollment_id"]) for i in invoices if i.get("enrollment_id")}
        )
        autopay_active = {
            str(d["enrollment_id"])
            async for d in self._db["student_billing_enrollments"].find(
                {
                    "academy_id": academy_id,
                    "enrollment_id": {"$in": enrollment_ids},
                    "autopay_enrollment_status": AUTOPAY_ACTIVE_STATUS,
                },
                {"_id": 0, "enrollment_id": 1},
            )
        }
        dunning = {
            str(d["invoice_id"]): d
            async for d in self._db["dunning_states"].find(
                {
                    "academy_id": academy_id,
                    "invoice_id": {"$in": sorted(str(i["invoice_id"]) for i in invoices)},
                },
                {"_id": 0, "invoice_id": 1, "status": 1, "attempt_count": 1},
            )
        }
        failed: set[str] = set()
        uncovered: set[str] = set()
        for inv in invoices:
            parent = str(inv.get("parent_id") or inv.get("parent_user_id") or "")
            if not parent:
                continue
            if _failed(dunning.get(str(inv["invoice_id"]))):
                failed.add(parent)
            elif str(inv.get("enrollment_id") or "") not in autopay_active:
                # shortcut: active autopay with no saved card or an unready
                # Stripe account counts as covered here; its charge fails into
                # dunning and the family then counts as failed autopay.
                uncovered.add(parent)
        return {"past_due": len(uncovered - failed), "needs_action": len(uncovered | failed)}


def compose_overdue_families(db: Any) -> OverdueFamiliesReader:
    return OverdueFamiliesReader(db, academy_timezone=academy_timezone_lookup(db))
