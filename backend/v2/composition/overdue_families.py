"""Academy-wide overdue family counts for the admin dashboard, students page and
the Reports aging card.

The Payments bucket view is scoped to one billing period, so a family owing
last month and nothing yet due this month fell out of it (L2 risk review B2).
This read covers every period: one indexed scan of owing invoices
(``academy_invoice_status_due_date``, migration 0156), then ``$in`` lookups of
their dunning states and autopay status.
Bucket rules mirror :mod:`collections_buckets`: a failed autopay attempt
outranks past due and counts whatever the due date, and an invoice covered by
active autopay is not past due unless its charge is parked on a problem only an
operator can fix.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from backend.v2.contexts.billing.application.autopay_eligibility import (
    AUTOPAY_ACTIVE_STATUS,
    CHARGEABLE_INVOICE_STATUSES,
)
from backend.v2.shared.tenancy import current_academy_id
from backend.v2.shared.time.academy_timezone import (
    academy_timezone_lookup,
    resolve_reporting_timezone,
)

log = logging.getLogger(__name__)

# shortcut: counts stop at this many invoices per scan (logged when hit); page
# by due_date if an academy ever carries more open overdue invoices than this.
_MAX_INVOICES = 5000

# Same rule as collections_buckets ``_has_failed_attempt`` (private there);
# keep the two in step until that one is made public.
_FAILED_LADDER_STATUSES = ("active", "processing")
_DUNNED_STATUS = "dunned"

# Park reasons where the charge never reached the card and only an operator can
# unblock it. Parking keeps the ladder ``active`` with no attempt counted
# (domain/dunning.py ``park``), so without this an autopay family whose charge
# is parked would read as covered forever. Mirrors process_dunning_retries.
_BLOCKED_PARK_REASONS = frozenset(
    {"charge_technical_failure", "connected_account_not_ready", "stripe_not_configured"}
)


def _failed(state: dict[str, Any]) -> bool:
    status = state.get("status")
    return status == _DUNNED_STATUS or (
        status in _FAILED_LADDER_STATUSES and int(state.get("attempt_count") or 0) >= 1
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
        zone = ZoneInfo(await resolve_reporting_timezone(self._academy_timezone, academy_id))
        today = self._clock().astimezone(zone).date()
        cutoff = datetime(today.year, today.month, today.day, tzinfo=UTC)
        # Every owing invoice, any due date: a failed attempt counts before the
        # due date passes (Payments' failed_autopay bucket).
        owing: list[dict[str, Any]] = (
            await self._db["invoices"]
            .find(
                {
                    "academy_id": academy_id,
                    "status": {"$in": sorted(CHARGEABLE_INVOICE_STATUSES)},
                    "balance_due_cents": {"$gt": 0},
                    "is_deleted": {"$ne": True},
                },
                {
                    "_id": 0,
                    "invoice_id": 1,
                    "enrollment_id": 1,
                    "parent_id": 1,
                    "parent_user_id": 1,
                    "due_date": 1,
                },
            )
            .sort([("due_date", 1), ("invoice_id", 1)])
            .to_list(_MAX_INVOICES)
        )
        if len(owing) >= _MAX_INVOICES:
            log.warning("overdue families: invoice scan hit the %d cap", _MAX_INVOICES)
        # Bounded by the owing ids (uniq_dunning_state_invoice, migration 0143).
        dunning = {
            str(d["invoice_id"]): d
            async for d in self._db["dunning_states"].find(
                {
                    "academy_id": academy_id,
                    "invoice_id": {"$in": sorted(str(i["invoice_id"]) for i in owing)},
                },
                {
                    "_id": 0,
                    "invoice_id": 1,
                    "status": 1,
                    "attempt_count": 1,
                    "suppression_reason": 1,
                },
            )
        }
        past_due = [i for i in owing if _naive_utc(i.get("due_date")) < cutoff]
        enrollment_ids = sorted(
            {str(i["enrollment_id"]) for i in past_due if i.get("enrollment_id")}
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
        failed: set[str] = set()
        uncovered: set[str] = set()
        for inv in owing:
            parent = str(inv.get("parent_id") or inv.get("parent_user_id") or "")
            if not parent:
                continue
            state = dunning.get(str(inv["invoice_id"])) or {}
            if _failed(state):
                failed.add(parent)
            elif _naive_utc(inv.get("due_date")) < cutoff and (
                str(inv.get("enrollment_id") or "") not in autopay_active
                or state.get("suppression_reason") in _BLOCKED_PARK_REASONS
            ):
                # shortcut: active autopay with no saved card or an unready
                # Stripe account still reads as covered until the first dunning
                # tick parks the charge (the Payments page flags it at once).
                uncovered.add(parent)
        return {"past_due": len(uncovered - failed), "needs_action": len(uncovered | failed)}


def _naive_utc(value: Any) -> datetime:
    """Mongo returns naive UTC datetimes; a missing due date never counts as past."""
    if not isinstance(value, datetime):
        return datetime.max.replace(tzinfo=UTC)
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def compose_overdue_families(db: Any) -> OverdueFamiliesReader:
    return OverdueFamiliesReader(db, academy_timezone=academy_timezone_lookup(db))
