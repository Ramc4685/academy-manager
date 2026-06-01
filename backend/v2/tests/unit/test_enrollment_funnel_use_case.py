"""Unit tests for GetEnrollmentFunnel use case.

All tests use a simple stub ``ApplicationFunnelReader`` — no Mongo
required.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from backend.v2.contexts.finance.application.use_cases.enrollment_funnel import (
    EnrollmentFunnelResult,
    GetEnrollmentFunnel,
)


class StubFunnelReader:
    """Stub implementation of ApplicationFunnelReader for unit tests."""

    def __init__(self, counts: dict[str, int]) -> None:
        self._counts = counts

    async def get_funnel_counts(self, academy_id: str, period: str | None) -> dict[str, int]:
        return dict(self._counts)


def _use_case(counts: dict[str, int]) -> GetEnrollmentFunnel:
    return GetEnrollmentFunnel(
        application_reader=StubFunnelReader(counts),
        academy_id="test-academy",
    )


@pytest.mark.asyncio
async def test_conversion_rate_calculated_correctly():
    """conversion_rate = confirmed / total, rounded to 4 decimal places."""
    uc = _use_case(
        {
            "DRAFT": 3,  # leads
            "APPROVED": 1,  # confirmed
            "ABANDONED": 1,  # dropped
        }
    )
    result = await uc.execute()

    # total = 3 + 1 + 1 = 5; confirmed = 1 → 1/5 = 0.2000
    assert result.total_applications == 5
    assert result.confirmed == 1
    assert result.conversion_rate == Decimal("0.2000")


@pytest.mark.asyncio
async def test_conversion_rate_zero_when_no_applications():
    """With no applications at all, conversion_rate must be 0, not ZeroDivisionError."""
    uc = _use_case({})
    result = await uc.execute()

    assert result.total_applications == 0
    assert result.conversion_rate == Decimal("0")
    assert isinstance(result, EnrollmentFunnelResult)


@pytest.mark.asyncio
async def test_statuses_bucketed_correctly():
    """Each onboarding status lands in the right funnel bucket."""
    uc = _use_case(
        {
            # leads
            "DRAFT": 2,
            "CHECKOUT_PENDING": 1,
            # applied
            "CHECKOUT_EXPIRED": 1,
            "PENDING_APPROVAL": 2,
            # assessed
            "WAITLISTED": 3,
            # confirmed
            "APPROVED": 4,
            # dropped
            "DECLINED": 1,
            "ABANDONED": 2,
            "REFUNDED": 1,
        }
    )
    result = await uc.execute()

    assert result.leads == 3  # DRAFT(2) + CHECKOUT_PENDING(1)
    assert result.applied == 3  # CHECKOUT_EXPIRED(1) + PENDING_APPROVAL(2)
    assert result.assessed == 3  # WAITLISTED(3)
    assert result.confirmed == 4  # APPROVED(4)
    assert result.dropped == 4  # DECLINED(1) + ABANDONED(2) + REFUNDED(1)
    assert result.total_applications == 17
    # conversion_rate = 4/17 ≈ 0.2353
    assert result.conversion_rate == (Decimal(4) / Decimal(17)).quantize(Decimal("0.0001"))


@pytest.mark.asyncio
async def test_period_is_forwarded_to_result():
    """The period argument is echoed back in the result DTO."""
    uc = _use_case({"APPROVED": 1})
    result = await uc.execute(period="2026-05")

    assert result.period == "2026-05"


@pytest.mark.asyncio
async def test_period_none_forwarded():
    """A None period is also preserved in the result."""
    uc = _use_case({})
    result = await uc.execute(period=None)

    assert result.period is None
