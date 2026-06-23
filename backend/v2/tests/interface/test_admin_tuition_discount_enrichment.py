"""Admin student detail enrichment with tuition discount badges (issue #244)."""

from __future__ import annotations

from datetime import date

import pytest

from backend.v2.contexts.billing.domain.tuition_discount import TuitionDiscount
from backend.v2.interfaces.admin.directory_routes import _attach_tuition_discounts


class _FakeDiscounts:
    def __init__(self, policies: dict[str, TuitionDiscount]) -> None:
        self._policies = policies

    async def active_by_enrollments(self, ids: list[str]) -> dict[str, TuitionDiscount]:
        return {k: v for k, v in self._policies.items() if k in ids}


class _FakeUseCases:
    def __init__(self, discounts) -> None:
        self.tuition_discounts = discounts


@pytest.mark.asyncio
async def test_enrichment_attaches_badge_for_discounted_session() -> None:
    policy = TuitionDiscount(
        discount_id="d1",
        enrollment_id="e1",
        student_id="s1",
        category="sibling",
        kind="percent",
        percent_bps=1000,
        effective_start=date(2026, 6, 1),
    )
    data = {
        "enrolled_sessions": [
            {"enrollment_id": "e1", "amount_cents": 10000},
            {"enrollment_id": "e2", "amount_cents": 8000},
        ]
    }

    await _attach_tuition_discounts(data, _FakeUseCases(_FakeDiscounts({"e1": policy})))

    discounted = data["enrolled_sessions"][0]["discount"]
    assert discounted["label"] == "Sibling discount"
    assert discounted["gross_cents"] == 10000
    assert discounted["discount_cents"] == 1000
    assert discounted["net_cents"] == 9000
    # session without a policy is untouched
    assert data["enrolled_sessions"][1].get("discount") is None


@pytest.mark.asyncio
async def test_enrichment_noop_without_repo() -> None:
    data = {"enrolled_sessions": [{"enrollment_id": "e1", "amount_cents": 10000}]}
    await _attach_tuition_discounts(data, _FakeUseCases(None))
    assert data["enrolled_sessions"][0].get("discount") is None
