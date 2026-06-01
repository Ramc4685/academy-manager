"""GetEnrollmentFunnel use case — Phase 2 analytics.

Reads raw ``ApplicationStatus`` counts from the onboarding store via an
injected port and maps them to the five-stage funnel used by the admin
dashboard: leads → applied → assessed → confirmed → dropped.

The mapping uses the ``onboarding_applications`` status vocabulary:

    DRAFT, CHECKOUT_PENDING
        → leads  (top of funnel; expressed interest but not yet applied)

    CHECKOUT_EXPIRED, PENDING_APPROVAL
        → applied  (payment flow started or awaiting admin review)

    WAITLISTED
        → assessed  (reviewed, not yet placed)

    APPROVED
        → confirmed  (full enrollment)

    DECLINED, REFUNDED, CAPACITY_FAILED_REFUNDING,
    CAPACITY_FAILED_REFUND_FAILED, ABANDONED
        → dropped  (will not convert)
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, Field

from backend.v2.contexts.finance.application.ports import ApplicationFunnelReader

# ---------------------------------------------------------------------------
# Status bucket mappings (using onboarding's SCREAMING_SNAKE vocabulary)
# ---------------------------------------------------------------------------

_LEADS = frozenset({"DRAFT", "CHECKOUT_PENDING"})
_APPLIED = frozenset({"CHECKOUT_EXPIRED", "PENDING_APPROVAL"})
_ASSESSED = frozenset({"WAITLISTED"})
_CONFIRMED = frozenset({"APPROVED"})
_DROPPED = frozenset(
    {
        "DECLINED",
        "REFUNDED",
        "CAPACITY_FAILED_REFUNDING",
        "CAPACITY_FAILED_REFUND_FAILED",
        "ABANDONED",
    }
)


# ---------------------------------------------------------------------------
# Result DTO
# ---------------------------------------------------------------------------


class EnrollmentFunnelResult(BaseModel):
    model_config = {"frozen": True}

    leads: int
    applied: int
    assessed: int
    confirmed: int
    dropped: int
    total_applications: int
    conversion_rate: Decimal = Field(
        description="confirmed / total_applications (denominator includes all statuses including dropped)"
    )
    period: str | None


# ---------------------------------------------------------------------------
# Use case
# ---------------------------------------------------------------------------


class GetEnrollmentFunnel:
    """Return a five-stage enrollment funnel for the given academy.

    Args:
        application_reader: Port that queries the onboarding store.
        academy_id: Scopes the query to a single academy.
    """

    def __init__(
        self,
        *,
        application_reader: ApplicationFunnelReader,
        academy_id: str,
    ) -> None:
        self._reader = application_reader
        self._academy_id = academy_id

    async def execute(self, period: str | None = None) -> EnrollmentFunnelResult:
        counts: dict[str, int] = await self._reader.get_funnel_counts(self._academy_id, period)

        leads = sum(counts.get(s, 0) for s in _LEADS)
        applied = sum(counts.get(s, 0) for s in _APPLIED)
        assessed = sum(counts.get(s, 0) for s in _ASSESSED)
        confirmed = sum(counts.get(s, 0) for s in _CONFIRMED)
        dropped = sum(counts.get(s, 0) for s in _DROPPED)

        total = leads + applied + assessed + confirmed + dropped

        if total == 0:
            conversion_rate = Decimal("0")
        else:
            conversion_rate = (Decimal(confirmed) / Decimal(total)).quantize(Decimal("0.0001"))

        return EnrollmentFunnelResult(
            leads=leads,
            applied=applied,
            assessed=assessed,
            confirmed=confirmed,
            dropped=dropped,
            total_applications=total,
            conversion_rate=conversion_rate,
            period=period,
        )
